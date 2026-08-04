# Copyright 2024 Efabless Corporation
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
from math import inf
from decimal import Decimal

import pytest
import pathlib

pytestmark = pytest.mark.all


def test_is_number():
    from librelane.common import is_number

    assert is_number(int(10)) is True, "integer was not a number"
    assert is_number(float(-inf)) is True, "infinite float was not a number"
    assert is_number(Decimal("1e10")) is True, "decimal was not a number"
    assert is_number("10") is False, "string was a number"


def test_is_real_number():
    from librelane.common import is_real_number

    assert is_real_number(10) is True, "integer was not real number"
    assert is_real_number(inf) is False, "infinity was real number"
    assert is_real_number(Decimal("-Infinity")) is False, (
        "decimal infinity was real number"
    )


def test_rel_if_child_relativizes_a_real_child(tmp_path):
    from librelane.common import rel_if_child

    child = tmp_path / "a" / "b.txt"

    result = rel_if_child(child, tmp_path, relative_prefix="./")

    assert str(result) == "./a/b.txt"


def test_rel_if_child_leaves_a_path_outside_the_tree_absolute(tmp_path):
    from librelane.common import rel_if_child

    outside = tmp_path.parent / "elsewhere" / "c.txt"

    result = rel_if_child(outside, tmp_path, relative_prefix="./")

    assert str(result) == str(outside)


def test_rel_if_child_does_not_treat_a_name_prefix_sibling_as_a_child(tmp_path):
    """Parentage is per path component, not per character.

    ``/a/b-sibling`` starts with the string ``/a/b`` but is not inside it. The
    old str.startswith test called it a child and returned a ``../`` escape,
    which is not a path relative to ``start`` at all.
    """
    from librelane.common import rel_if_child

    base = tmp_path / "b"
    sibling = tmp_path / "b-sibling" / "d.txt"

    result = rel_if_child(sibling, base, relative_prefix="./")

    assert ".." not in str(result)
    assert str(result) == str(sibling)


def test_rel_if_child_handles_the_path_being_the_start_itself(tmp_path):
    from librelane.common import rel_if_child

    result = rel_if_child(tmp_path, tmp_path, relative_prefix="./")

    assert str(result) == "./."


def test_the_dummy_path_is_exempt_from_the_existence_check():
    """The sentinel is a plain str, so the exemption must not depend on the
    path type comparing equal to one."""
    from librelane.common import DUMMY_PATH, validate_path

    validate_path(DUMMY_PATH, "should not raise")


def test_a_genuinely_missing_path_still_fails_validation(tmp_path):
    import pytest

    from librelane.common import validate_path

    with pytest.raises(ValueError, match="does not exist"):
        validate_path(tmp_path / "nope", "bad")


def test_is_string_like_covers_every_path_representation(tmp_path):
    """The config gates ask "can this be read as one string?", not "is this a
    str?". A path answers yes however it is implemented."""
    from librelane.common import is_string, is_string_like

    a_path = tmp_path / "x"

    assert is_string_like("plain") is True
    assert is_string_like(str(a_path)) is True
    assert is_string_like(pathlib.Path(a_path)) is True

    # Still says no to the things those gates must reject.
    assert is_string_like(["a", "b"]) is False
    assert is_string_like({"a": 1}) is False
    assert is_string_like(3) is False

    # And it is strictly wider than is_string, which is the whole point.
    assert is_string(pathlib.Path(a_path)) is False


def test_scoped_file_is_usable_as_a_path():
    """It composes a path rather than being one, so os.PathLike is what keeps
    it usable everywhere it was usable before."""
    import os

    from librelane.common import ScopedFile

    scoped = ScopedFile(contents="hello")

    assert isinstance(scoped, os.PathLike)
    assert open(scoped).read() == "hello"
    assert os.path.exists(scoped)
    assert str(scoped) == str(scoped.path)
    assert isinstance(scoped.path, pathlib.Path)


def test_no_librelane_type_subclasses_pathlib_path():
    """Nothing in the tree subclasses pathlib.Path. ScopedFile was the last
    thing that did.

    This began as a language constraint: subclassing needs ``_flavour``, which
    is private before 3.12, and the floor was 3.10. The floor is 3.13 now, so
    a subclass would work -- which is exactly why this is still asserted. The
    shipped design has ``common.Path`` as an ``Annotated`` alias and
    ``ScopedFile`` composing a path, and roughly two dozen
    ``isinstance(..., Path)`` sites are written to that shape. Reintroducing a
    subclass is now a design change rather than an error the interpreter
    catches, and it should be made deliberately instead of by someone reaching
    for the obvious ``class Path(pathlib.Path)``."""
    import librelane
    from librelane.common import ScopedFile

    assert not issubclass(ScopedFile, pathlib.Path)

    offenders = [
        subclass
        for subclass in pathlib.Path.__subclasses__()
        if subclass.__module__.startswith(librelane.__name__)
    ]
    assert offenders == []


def test_path_is_an_annotated_alias_that_rejects_isinstance():
    """The pydantic behaviour lives in Annotated metadata, which is what the
    3.10 floor forced when this landed and what the design kept after the
    floor moved to 3.13.

    The alias forwards ``__call__`` to pathlib.Path, so ``Path(x)`` quietly
    still builds the right object -- but ``isinstance(x, Path)`` raises. That
    asymmetry is why the isinstance sites are the ones that had to be found,
    and it is worth pinning: if a future typing release made the alias
    isinstance-able, a missed site would start silently answering the wrong
    question."""
    import typing

    from librelane.common import Path

    assert typing.get_args(Path)[0] is pathlib.Path
    with pytest.raises(TypeError, match="cannot be used with class and instance"):
        isinstance(pathlib.Path("x"), Path)  # type: ignore[arg-type]


def test_a_path_variable_validates_and_produces_a_pathlib_path(tmp_path):
    from pydantic import TypeAdapter

    from librelane.common import Path

    a_file = tmp_path / "real.v"
    a_file.write_text("")

    result = TypeAdapter(Path).validate_python(str(a_file))

    assert type(result) is type(pathlib.Path())
    assert result == a_file

    with pytest.raises(Exception, match="does not exist"):
        TypeAdapter(Path).validate_python(str(tmp_path / "absent.v"))


def test_scoped_file_deletes_itself_when_it_goes_out_of_scope():
    import gc
    import os

    from librelane.common import ScopedFile

    scoped = ScopedFile(contents="hello")
    name = os.fspath(scoped)
    assert os.path.exists(name)

    del scoped
    gc.collect()

    assert not os.path.exists(name)
