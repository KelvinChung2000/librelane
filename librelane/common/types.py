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
import pathlib
import tempfile
from math import isfinite
from decimal import Decimal
from weakref import finalize
from collections import UserString
from typing import Annotated, Any, Union


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


AnyPath = Union[str, os.PathLike]

#: A path that passes :func:`validate_path` but will fail to open.
#:
#: For deprecated variable translation only: a translation has to produce
#: *some* value for a variable whose file does not exist yet, and this is the
#: agreed spelling of "deliberately not a real file".
DUMMY_PATH = "__librelane_dummy_path"


def validate_path(path: AnyPath, message_on_err: str = "") -> None:
    """
    Raises a :class:`ValueError` if ``path`` does not exist.

    A free function rather than a method because the path type is
    :class:`pathlib.Path`, which cannot be given extra methods before Python
    3.12 (see :data:`Path`).

    Parameters
    ----------
    path : str | os.PathLike
        The path to check.
    message_on_err : str
        Prefixed to the raised message to say what was being validated.
    """
    # str() rather than a bare ``==``: the sentinel is a plain str, and
    # comparing a path object to one only works while the path type happens to
    # be string-like.
    if not os.path.exists(path) and str(path) != DUMMY_PATH:
        raise ValueError(f"{message_on_err}: '{path}' does not exist")


def rel_if_child(
    path: AnyPath,
    start: AnyPath = os.getcwd(),
    *,
    relative_prefix: str = "",
) -> str:
    """
    Spells ``path`` relative to ``start`` if it is inside it, and absolute
    otherwise.

    Parentage is decided per path component, not by string prefix. A sibling
    directory that merely shares a name prefix -- ``/a/b-sibling`` against
    ``/a/b`` -- is not a child, and previously came back as a ``../`` escape
    rather than as an absolute path.

    Returns a ``str`` rather than a path object because ``relative_prefix`` is
    a property of the *spelling*: :class:`pathlib.Path` normalises a leading
    ``./`` away, so a path object cannot carry one.

    Parameters
    ----------
    path : str | os.PathLike
        The path to relativize.
    start : str | os.PathLike
        The directory to relativize against.
    relative_prefix : str
        Prepended to the result when it is relative, e.g. ``"./"``.

    Returns
    -------
    str
        The relative path, prefixed, or this path made absolute.
    """
    my_abspath = pathlib.Path(os.path.abspath(path))
    start_abspath = pathlib.Path(os.path.abspath(start))
    if my_abspath.is_relative_to(start_abspath):
        return relative_prefix + str(my_abspath.relative_to(start_abspath))
    return str(my_abspath)


Number = Union[int, float, Decimal]


def is_number(obj: Any) -> bool:
    return isinstance(obj, int) or isinstance(obj, float) or isinstance(obj, Decimal)


def is_real_number(obj: Any) -> bool:
    return is_number(obj) and isfinite(obj)


class _PathAnnotation:
    """
    LibreLane's configuration semantics for a :class:`pathlib.Path` field.

    Metadata on an :data:`Annotated <typing.Annotated>` alias rather than a
    subclass of :class:`pathlib.Path`, because that class cannot be subclassed
    before Python 3.12 and this project supports 3.10.
    """

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
            # Covers str, os.PathLike and pathlib.Path itself, so the inner
            # str_schema never has to accept anything but a real str.
            return str(value)

        def construct(value: str):
            # Validated as the text the user wrote, before pathlib normalises
            # it: os.path.exists("") is False, but pathlib.Path("") is ".",
            # which exists.
            validate_path(value, "Path provided for configuration variable is invalid")
            return pathlib.Path(value)

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


#: The type of a LibreLane configuration variable naming a file or directory.
#:
#: :class:`pathlib.Path` carrying LibreLane's configuration semantics: a glob
#: that matched exactly one file collapses to it, and the result is checked for
#: existence. Values of this type are ordinary :class:`pathlib.Path` objects.
#:
#: It is an :data:`Annotated <typing.Annotated>` alias, which makes it an
#: annotation and nothing else. ``isinstance(x, Path)`` raises ``TypeError``;
#: ``Path(x)`` happens to work, because the alias forwards ``__call__`` to
#: :class:`pathlib.Path`, but it validates nothing and reads as if it did.
#: Spell both ``pathlib.Path``.
Path = Annotated[pathlib.Path, _PathAnnotation]


def unwrap_annotated(annotation: Any) -> Any:
    """
    Strips :data:`Annotated <typing.Annotated>` metadata from an annotation.

    Configuration types are inspected at runtime -- to decide that a variable
    is path-typed, for instance -- and :data:`Path` is an ``Annotated`` alias,
    so a bare ``is pathlib.Path`` test would miss it. Pydantic strips the
    metadata off *top-level* field annotations but leaves it in place inside
    ``list[...]`` and ``Optional[...]``, so both spellings genuinely occur and
    every such test has to normalise first.
    """
    while hasattr(annotation, "__metadata__"):
        annotation = annotation.__origin__
    return annotation


def is_path_annotation(annotation: Any) -> bool:
    """
    Whether a configuration annotation denotes a single path.

    Asks about :class:`os.PathLike` rather than comparing against
    :class:`pathlib.Path` by identity. Annotations are captured when a module
    is imported, and anything that replaces ``pathlib.Path`` afterwards --
    ``pyfakefs`` does exactly that, and the configuration tests run under it --
    leaves an identity test answering *no* for a genuine path variable, which
    silently skips the existence check.
    """
    return isinstance(annotation := unwrap_annotated(annotation), type) and issubclass(
        annotation, os.PathLike
    )


class ScopedFile(os.PathLike):
    """
    Creates a temporary file that remains valid while this variable is in scope,
    and is deleted upon deconstruction.

    The object *holds* a path rather than being one: it implements
    ``os.PathLike``, so it can be handed to :func:`open`, to
    :mod:`subprocess`, or to anything else that accepts a path, and
    :attr:`path` is available when the path object itself is wanted.

    It used to subclass the old LibreLane ``Path``, which was its only
    subclass. Composition is not a stylistic preference here: that type is now
    :class:`pathlib.Path`, and subclassing it is not supported before Python
    3.12 while this project supports 3.10.

    Parameters
    ----------
    contents
        The contents of the temporary file to create.

    Attributes
    ----------
    path : pathlib.Path
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
        self.path = pathlib.Path(ntf.name)
        self._cleanup = finalize(self, os.unlink, ntf.name)

    def __fspath__(self) -> str:
        return os.fspath(self.path)

    def __str__(self) -> str:
        return str(self.path)

    def __repr__(self) -> str:
        return f"{self.__class__.__qualname__}('{self.path}')"
