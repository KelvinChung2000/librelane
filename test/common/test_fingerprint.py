import os

import pytest

from librelane.common import Fingerprinter

pytestmark = pytest.mark.all


def test_content_determines_the_identity_not_the_path(tmp_path):
    a = tmp_path / "a.v"
    b = tmp_path / "b.v"
    a.write_text("module top(); endmodule")
    b.write_text("module top(); endmodule")

    fingerprinter = Fingerprinter()

    assert fingerprinter.of_path(a) == fingerprinter.of_path(b)
    assert fingerprinter.of_path(a).startswith("file:")


def test_editing_a_file_changes_its_identity(tmp_path):
    target = tmp_path / "a.v"
    target.write_text("module top(); endmodule")
    before = Fingerprinter().of_path(target)

    target.write_text("module top(); wire w; endmodule")

    assert Fingerprinter().of_path(target) != before


def test_a_touch_that_preserves_content_preserves_the_identity(tmp_path):
    target = tmp_path / "a.v"
    target.write_text("module top(); endmodule")
    before = Fingerprinter().of_path(target)

    os.utime(target, (0, 0))

    assert Fingerprinter().of_path(target) == before


def test_a_file_is_read_once_per_fingerprinter(tmp_path, mocker):
    """
    The same PDK views appear in many steps' configurations. Re-reading a
    30MB liberty file once per step is the difference between a sub-second
    resume check and a multi-second one.
    """
    target = tmp_path / "a.lib"
    target.write_text("library(x) {}")
    fingerprinter = Fingerprinter()
    fingerprinter.of_path(target)

    spy = mocker.spy(fingerprinter, "_read_digest")
    for _ in range(5):
        fingerprinter.of_path(target)

    assert spy.call_count == 0


def test_a_changed_file_is_reread_despite_the_memo(tmp_path):
    target = tmp_path / "a.lib"
    target.write_text("library(x) {}")
    fingerprinter = Fingerprinter()
    before = fingerprinter.of_path(target)

    target.write_text("library(x) { cell(y) {} }")

    assert fingerprinter.of_path(target) != before


def test_a_directory_is_identified_without_being_read(tmp_path):
    """
    DESIGN_DIR and PDK_ROOT are Path-typed directories in every step's
    configuration. DESIGN_DIR contains runs/, so hashing its contents would
    make the key depend on the run in progress and never stabilise.
    """
    (tmp_path / "runs").mkdir()
    (tmp_path / "runs" / "junk").write_text("changes constantly")

    identity = Fingerprinter().of_path(tmp_path)
    (tmp_path / "runs" / "junk").write_text("changed again")

    assert identity == f"dir:{tmp_path}"
    assert Fingerprinter().of_path(tmp_path) == identity


def test_an_absent_path_gets_its_own_identity(tmp_path):
    missing = tmp_path / "nope.v"

    identity = Fingerprinter().of_path(missing)

    assert identity == f"absent:{missing}"


def test_an_absent_path_differs_from_the_same_path_once_created(tmp_path):
    target = tmp_path / "a.v"
    fingerprinter = Fingerprinter()
    absent = fingerprinter.of_path(target)

    target.write_text("module top(); endmodule")

    assert fingerprinter.of_path(target) != absent
