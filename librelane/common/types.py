# Copyright 2023 Efabless Corporation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import os
import sys
import pathlib
import tempfile
from math import isfinite
from decimal import Decimal
from weakref import finalize
from collections import UserString
from typing import Any, Union, ClassVar


def is_string(obj: Any) -> bool:
    return isinstance(obj, str) or isinstance(obj, UserString)


def is_string_like(obj: Any) -> bool:
    """
    Whether a value names a single piece of text, path objects included.

    :func:`is_string` asks what a value *is*. A number of call sites instead
    ask whether a value can be *read as* one string rather than walked as a
    sequence, and a path answers yes to that however it is implemented. Those
    sites answered it with :func:`is_string`, which works only while the path
    type happens to subclass ``UserString``.

    Callers that need a real ``str`` afterwards must still call ``str()``; this
    only classifies.
    """
    return is_string(obj) or isinstance(obj, os.PathLike)


Number = Union[int, float, Decimal]


def is_number(obj: Any) -> bool:
    return isinstance(obj, int) or isinstance(obj, float) or isinstance(obj, Decimal)


def is_real_number(obj: Any) -> bool:
    return is_number(obj) and isfinite(obj)


class Path(UserString, os.PathLike):
    """
    A Path type for LibreLane configuration variables.

    Basically just a string.
    """

    # This path will pass the validate() call, but will
    # fail to open. It should be used for deprecated variable
    # translation only.
    _dummy_path: ClassVar[str] = "__librelane_dummy_path"

    @classmethod
    def __get_pydantic_core_schema__(cls, source, handler):
        """
        Teach Pydantic LibreLane's scalar/glob path semantics.

        Deliberately built *around* a ``str_schema`` rather than as one opaque
        validator. A plain validator function tells Pydantic nothing about what
        comes out, so it cannot describe the field and
        :meth:`pydantic.BaseModel.model_json_schema` raises
        ``PydanticInvalidForJsonSchema`` — which it did for 40 of LibreLane's
        configuration variables, every one of them path-typed. Collapsing a
        glob and coercing to ``str`` on the way *in*, then constructing the
        path on the way *out*, leaves the core type visible, so the schema is
        derived rather than hand-written.
        """
        from pydantic_core import core_schema
        from librelane.config.preprocessor import GlobMatch

        def collapse(value):
            """Glob to single path, then to the ``str`` the inner schema wants."""
            if isinstance(value, GlobMatch):
                if len(value) == 1:
                    value = value[0]
                elif len(value) == 0:
                    value = value.literal
                else:
                    raise ValueError(
                        f"expected one path, glob matched {len(value)}: "
                        + ", ".join(value)
                    )
            # Covers str, os.PathLike and this class itself, so the inner
            # str_schema never has to accept anything but a real str.
            return str(value)

        def construct(value: str):
            result = cls(value)
            result.validate("Path provided for configuration variable is invalid")
            return result

        return core_schema.no_info_after_validator_function(
            construct,
            core_schema.no_info_before_validator_function(
                collapse,
                core_schema.str_schema(),
            ),
            serialization=core_schema.plain_serializer_function_ser_schema(
                str,
                when_used="json",
            ),
        )

    def __fspath__(self) -> str:
        return str(self)

    def __repr__(self) -> str:
        return f"{self.__class__.__qualname__}('{self}')"

    def exists(self) -> bool:
        """
        A convenience method calling :meth:`os.path.exists`
        """
        return os.path.exists(self)

    def validate(self, message_on_err: str = ""):
        """
        Raises an error if the path does not exist.
        """
        # str() rather than a bare ``==``: the sentinel is a plain str, and
        # comparing a path object to one only works while the path type happens
        # to be string-like. ``toolbox.py:301`` already spells it this way.
        if not self.exists() and str(self) != Path._dummy_path:
            raise ValueError(f"{message_on_err}: '{self}' does not exist")

    def startswith(
        self,
        prefix: str | tuple[str, ...] | UserString | os.PathLike,
        start: int | None = 0,
        end: int | None = sys.maxsize,
    ) -> bool:
        if isinstance(prefix, UserString) or isinstance(prefix, os.PathLike):
            prefix = str(prefix)
        return super().startswith(prefix, start, end)

    def rel_if_child(
        self,
        start: str | os.PathLike = os.getcwd(),
        *,
        relative_prefix: str = "",
    ) -> "Path":
        """
        Returns this path relative to ``start`` if it is inside it, and
        absolute otherwise.

        Parentage is decided per path component, not by string prefix. A
        sibling directory that merely shares a name prefix -- ``/a/b-sibling``
        against ``/a/b`` -- is not a child, and previously came back as a
        ``../`` escape rather than as an absolute path.

        Parameters
        ----------
        start : str | os.PathLike
            The directory to relativize against.
        relative_prefix : str
            Prepended to the result when it is relative, e.g. ``"./"``.

        Returns
        -------
        Path
            The relative path, prefixed, or this path made absolute.
        """
        my_abspath = pathlib.Path(os.path.abspath(self))
        start_abspath = pathlib.Path(os.path.abspath(start))
        if my_abspath.is_relative_to(start_abspath):
            return Path(relative_prefix + str(my_abspath.relative_to(start_abspath)))
        return Path(my_abspath)

    def write_text(self, data: str, encoding=None, errors=None, newline=None):
        with open(
            self, "w", encoding=encoding, errors=errors, newline=newline
        ) as ofile:
            return ofile.write(data)

    def read_text(self, encoding=None, errors=None, newline=None):
        with open(
            self, "r", encoding=encoding, errors=errors, newline=newline
        ) as ifile:
            return ifile.read()


AnyPath = Union[str, os.PathLike]


class ScopedFile(os.PathLike):
    """
    Creates a temporary file that remains valid while this variable is in scope,
    and is deleted upon deconstruction.

    The object *holds* a path rather than being one: it implements
    ``os.PathLike``, so it can be handed to :func:`open`, to
    :mod:`subprocess`, or to anything else that accepts a path, and
    :attr:`path` is available when the path object itself is wanted.

    It used to subclass :class:`Path`, which was its only subclass.
    Composition is not a stylistic preference here: :class:`Path` is on its way
    to becoming :class:`pathlib.Path`, and subclassing that is not supported
    before Python 3.12 while this project supports 3.10.

    Parameters
    ----------
    contents
        The contents of the temporary file to create.

    Attributes
    ----------
    path : Path
        The path to the temporary file.
    """

    def __init__(self, *, contents: str = "") -> None:
        ntf = tempfile.NamedTemporaryFile(
            "w",
            delete=False,
            encoding="utf8",
        )
        ntf.write(contents)
        ntf.close()
        self.path = Path(ntf.name)
        self._cleanup = finalize(self, os.unlink, ntf.name)

    def __fspath__(self) -> str:
        return os.fspath(self.path)

    def __str__(self) -> str:
        return str(self.path)

    def __repr__(self) -> str:
        return f"{self.__class__.__qualname__}('{self.path}')"
