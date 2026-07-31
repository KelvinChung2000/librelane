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
    from librelane.common import Path

    child = tmp_path / "a" / "b.txt"

    result = Path(str(child)).rel_if_child(str(tmp_path), relative_prefix="./")

    assert str(result) == "./a/b.txt"


def test_rel_if_child_leaves_a_path_outside_the_tree_absolute(tmp_path):
    from librelane.common import Path

    outside = tmp_path.parent / "elsewhere" / "c.txt"

    result = Path(str(outside)).rel_if_child(str(tmp_path), relative_prefix="./")

    assert str(result) == str(outside)


def test_rel_if_child_does_not_treat_a_name_prefix_sibling_as_a_child(tmp_path):
    """Parentage is per path component, not per character.

    ``/a/b-sibling`` starts with the string ``/a/b`` but is not inside it. The
    old str.startswith test called it a child and returned a ``../`` escape,
    which is not a path relative to ``start`` at all.
    """
    from librelane.common import Path

    base = tmp_path / "b"
    sibling = tmp_path / "b-sibling" / "d.txt"

    result = Path(str(sibling)).rel_if_child(str(base), relative_prefix="./")

    assert ".." not in str(result)
    assert str(result) == str(sibling)


def test_rel_if_child_handles_the_path_being_the_start_itself(tmp_path):
    from librelane.common import Path

    result = Path(str(tmp_path)).rel_if_child(str(tmp_path), relative_prefix="./")

    assert str(result) == "./."


def test_the_dummy_path_is_exempt_from_the_existence_check():
    """The sentinel is a plain str, so the exemption must not depend on the
    path type comparing equal to one."""
    from librelane.common import Path

    Path(Path._dummy_path).validate("should not raise")


def test_a_genuinely_missing_path_still_fails_validation(tmp_path):
    import pytest

    from librelane.common import Path

    with pytest.raises(ValueError, match="does not exist"):
        Path(str(tmp_path / "nope")).validate("bad")


def test_is_string_like_covers_every_path_representation(tmp_path):
    """The config gates ask "can this be read as one string?", not "is this a
    str?". A path answers yes however it is implemented."""
    import pathlib

    from librelane.common import Path, is_string, is_string_like

    a_path = tmp_path / "x"

    assert is_string_like("plain") is True
    assert is_string_like(Path(str(a_path))) is True
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

    from librelane.common import Path, ScopedFile

    scoped = ScopedFile(contents="hello")

    assert isinstance(scoped, os.PathLike)
    assert open(scoped).read() == "hello"
    assert os.path.exists(scoped)
    assert str(scoped) == str(scoped.path)
    assert isinstance(scoped.path, Path)


def test_scoped_file_is_no_longer_a_path_subclass():
    """Path is on its way to becoming pathlib.Path, which cannot be subclassed
    before 3.12 while this project supports 3.10. ScopedFile was the only
    subclass."""
    from librelane.common import Path, ScopedFile

    assert not issubclass(ScopedFile, Path)
    assert Path.__subclasses__() == []


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
