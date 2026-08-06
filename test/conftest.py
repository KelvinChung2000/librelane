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
import contextlib
import os
import tempfile
from unittest import mock
from decimal import Decimal
from typing import Any, Literal, NamedTuple, Optional
from collections.abc import Iterable, Callable, Iterator

import pytest
from loguru import logger
from pyfakefs.fake_filesystem_unittest import Patcher
from _pytest.fixtures import SubRequest

from librelane.config import Variable, Macro
from librelane.common import Path, GenericDict


class LoguruCapture:
    def __init__(self):
        self.records = []

    def __call__(self, message):
        self.records.append(message.record.copy())

    @property
    def text(self) -> str:
        return "\n".join(str(record["message"]) for record in self.records)

    def clear(self) -> None:
        self.records.clear()


@pytest.fixture
def caplog():
    from librelane.logging import additional_sink

    capture = LoguruCapture()
    with additional_sink(capture):
        yield capture


def pytest_assertrepr_compare(op, left, right):
    if isinstance(left, GenericDict) and isinstance(right, GenericDict) and op == "==":
        return_value = ["comparing GenericDict-derived objects"]
        left_d = left.to_raw_dict()
        right_d = right.to_raw_dict()

        for key in set(left_d.keys()).union(right_d.keys()):
            if left_d.get(key) != right_d.get(key):
                return_value.append(
                    f"  * mismatched values for '{key}': {repr(left_d.get(key))} vs. {repr(right_d.get(key))}"
                )
        return return_value


class MockConfTree(NamedTuple):
    """
    Where a built mock configuration tree lives.

    Attributes
    ----------
    cwd : str
        The design directory, the tree's ``src`` and ``spef`` inputs.
    pdk_root : str
        The PDK root, holding the ``dummy`` and ``dummy2`` PDKs.
    """

    cwd: str
    pdk_root: str


def mock_conf_tree(tree: MockConfTree) -> dict[str, str]:
    """
    The one definition of the mock design and PDK tree the tests resolve
    configurations against.

    Both :func:`_mock_conf_fs`, which builds it inside pyfakefs, and
    :func:`mock_conf_dir`, which builds it on a real temporary filesystem,
    consume this, so the two cannot drift apart.

    Parameters
    ----------
    tree : MockConfTree
        The absolute roots to build the tree at. The PDKs' ``config.tcl``
        files name their own views by absolute path, so the root cannot be
        left implicit.

    Returns
    -------
    dict[str, str]
        A mapping of absolute file path to that file's contents. Every
        directory in the tree holds at least one file, so the directories are
        implied by the keys and are not listed separately.
    """
    cwd = tree.cwd
    pdk_root = tree.pdk_root
    files = {
        f"{cwd}/src/a.v": "",
        f"{cwd}/src/b.v": "",
        f"{cwd}/spef/b.spef": "",
        f"{pdk_root}/dummy/libs.tech/librelane/config.tcl": f"""
            if {{ ![info exists ::env(STD_CELL_LIBRARY)] }} {{
                set ::env(STD_CELL_LIBRARY) "dummy_scl"
            }}
            set ::env(TECH_LEF) "{pdk_root}/dummy/libs.ref/techlef/dummy_scl/dummy_tech_lef.tlef"
            set ::env(LIB_SYNTH) "sky130_fd_sc_hd__tt_025C_1v80.lib"
            set ::env(KLAYOUT_TECH) "{pdk_root}/dummy/libs.tech/klayout/dummy.lyt"
            set ::env(KLAYOUT_PROPERTIES) "{pdk_root}/dummy/libs.tech/klayout/dummy.lyp"
            set ::env(KLAYOUT_DEF_LAYER_MAP) "{pdk_root}/dummy/libs.tech/klayout/dummy.map"
            set ::env(FP_TRACKS_INFO) "{pdk_root}/dummy/libs.tech/librelane/dummy_scl/tracks.info"
            set ::env(GRT_LAYER_ADJUSTMENTS) "0.3 0.3"
            set ::env(DPL_CELL_PADDING) "0"
            set ::env(GPL_CELL_PADDING) "0"
            """,
        f"{pdk_root}/dummy2/libs.tech/librelane/config.tcl": f"""
            if {{ ![info exists ::env(STD_CELL_LIBRARY)] }} {{
                set ::env(STD_CELL_LIBRARY) "dummy2_scl"
            }}
            set ::env(TECH_LEF) "{pdk_root}/dummy2/libs.ref/techlef/dummy2_scl/dummy_tech_lef.tlef"
            set ::env(LIB_SYNTH) "sky130_fd_sc_hd__tt_025C_1v80.lib"
            """,
        f"{pdk_root}/dummy/libs.ref/techlef/dummy_scl/dummy_tech_lef.tlef": "",
        f"{pdk_root}/dummy2/libs.ref/techlef/dummy2_scl/dummy_tech_lef.tlef": "",
        f"{pdk_root}/dummy/libs.tech/librelane/dummy_scl/config.tcl": "",
        # The four PDK variables the OpenROAD floorplan and global placement
        # steps require and have no default for. Declared here for the same
        # reason the KLayout views below are: a document that runs those steps
        # cannot resolve its configuration at all without them, so a test of
        # anything else about such a flow would fail in the loader.
        f"{pdk_root}/dummy/libs.tech/librelane/dummy_scl/tracks.info": "",
        f"{pdk_root}/dummy2/libs.tech/librelane/dummy2_scl/config.tcl": "",
    }
    # Enough of a KLayout view for the KLayout steps to resolve their required
    # PDK variables; the tool itself is stubbed out in tests.
    for klayout_view in ("dummy.lyt", "dummy.lyp", "dummy.map"):
        files[f"{pdk_root}/dummy/libs.tech/klayout/{klayout_view}"] = ""
    return files


@pytest.fixture
def _mock_conf_fs():
    """
    Builds the mock configuration tree inside pyfakefs and chdirs into its
    design directory.

    The default for tests that resolve a configuration. Tests that run flow
    jobs concurrently must use :func:`mock_conf_dir` instead: pyfakefs is
    single-threaded by design, and its process-global "answer this call from
    the real disk" switch leaks the real filesystem into whichever other
    thread is mid-call.
    """
    with Patcher() as patcher:
        for path, contents in mock_conf_tree(
            MockConfTree(cwd="/cwd", pdk_root="/pdk")
        ).items():
            patcher.fs.create_file(path, contents=contents)

        os.chdir("/cwd")
        yield


@contextlib.contextmanager
def _build_mock_conf_tree(root: str) -> Iterator[MockConfTree]:
    """
    Writes the mock configuration tree under ``root`` on the real filesystem
    and chdirs into its design directory.

    Parameters
    ----------
    root : str
        An existing directory to build ``cwd`` and ``pdk`` under.

    Yields
    ------
    MockConfTree
        Where the two roots ended up.
    """
    tree = MockConfTree(
        cwd=os.path.join(root, "cwd"),
        pdk_root=os.path.join(root, "pdk"),
    )
    for path, contents in mock_conf_tree(tree).items():
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf8") as f:
            f.write(contents)
    with chdir(tree.cwd):
        yield tree


@pytest.fixture
def mock_conf_dir(request: SubRequest) -> Iterator[MockConfTree]:
    """
    The real-filesystem counterpart of :func:`_mock_conf_fs`.

    Same tree, same working directory, built under a temporary directory that
    is removed on teardown unless ``--keep-tmp`` was passed. For the tests
    that run flow jobs concurrently, where pyfakefs cannot be used at all.

    Yields
    ------
    MockConfTree
        The tree's two roots, so that a test's design and PDK arguments can be
        derived from them rather than hard-coded.
    """
    if not request.config.option.keep_tmp:
        with tempfile.TemporaryDirectory(prefix="librelane_test_") as dir:
            with _build_mock_conf_tree(dir) as tree:
                yield tree
    else:
        dir = tempfile.mkdtemp(prefix="librelane_test_")
        with _build_mock_conf_tree(dir) as tree:
            logger.info(f"\nTMP: {dir}")
            yield tree
            logger.info(f"\nTMP: {dir}")


class chdir(object):
    def __init__(self, path):
        self.path = path
        self.previous = None

    def __enter__(self):
        self.previous = os.getcwd()
        os.chdir(self.path)

    def __exit__(self, exc_type, exc_value, traceback):
        os.chdir(self.previous)
        if exc_type is not None:
            raise exc_value


@pytest.fixture
def _chdir_tmp(request: SubRequest):
    if not request.config.option.keep_tmp:
        with tempfile.TemporaryDirectory(prefix="librelane_test_") as dir, chdir(dir):
            yield
    else:
        dir = tempfile.mkdtemp(prefix="librelane_test_")
        with chdir(dir):
            logger.info(f"\nTMP: {dir}")
            yield
            logger.info(f"\nTMP: {dir}")


MOCK_PDK_VARS = [
    Variable(
        "STD_CELL_LIBRARY",
        str,
        description="x",
        pdk=True,
    ),
    Variable(
        "EXAMPLE_PDK_VAR",
        Decimal,
        description="x",
        default=10.0,
        pdk=True,
        deprecated_names=["EXAMPLE_PDK_VAR_LEGACY"],
    ),
    Variable(
        "TECH_LEFS",
        dict[str, Path],
        description="x",
        pdk=True,
    ),
    Variable(
        "DEFAULT_CORNER",
        str,
        description="x",
        default="nom_tt_025C_1v80",
        pdk=True,
    ),
    Variable(
        "RANDOM_ARRAY",
        Optional[list[str]],
        description="x",
    ),
]
MOCK_FLOW_VARS = [
    Variable(
        "PDK_ROOT",
        str,
        description="x",
    ),
    Variable(
        "PDK",
        str,
        description="x",
    ),
    Variable(
        "DESIGN_DIR",
        Path,
        "The directory of the design. Does not need to be provided explicitly.",
    ),
    Variable(
        "DESIGN_NAME",
        str,
        description="x",
    ),
    Variable(
        "VERILOG_FILES",
        list[Path],
        description="x",
    ),
    Variable(
        "GRT_REPAIR_ANTENNAS",
        bool,
        description="x",
        default=True,
    ),
    Variable(
        "RUN_HEURISTIC_DIODE_INSERTION",
        bool,
        description="x",
        default=False,
    ),
    # Verbatim from Odb.DiodesOnPorts/Odb.PortDiodePlacement: the flow model
    # build calls get_all_config_variables even over a resolved Config, which
    # requires a name shared between the (mocked) universal list and a real
    # step to be declared identically.
    Variable(
        "DIODE_ON_PORTS",
        Literal["none", "in", "out", "both"],
        description="Always insert diodes on ports with the specified polarities.",
        default="none",
    ),
    Variable(
        "MACROS",
        Optional[dict[str, Macro]],
        description="x",
        default=None,
    ),
]
COMMON_FLOW_VARS = MOCK_PDK_VARS + MOCK_FLOW_VARS


def mock_variables(patch_in_objects: Iterable[Any] | None = None):
    from librelane.config import config

    if patch_in_objects is None:
        patch_in_objects = []
    patch_in_objects = patch_in_objects + [config]

    def decorator(f: Callable):
        for o in patch_in_objects:
            if hasattr(o, "flow_common_variables"):
                f = mock.patch.object(
                    o,
                    "flow_common_variables",
                    COMMON_FLOW_VARS,
                )(f)
            if hasattr(o, "removed_variables"):
                f = mock.patch.object(
                    o,
                    "removed_variables",
                    {"REMOVED_VARIABLE": "Variable sucked"},
                )(f)
            if hasattr(o, "universal_flow_config_variables"):
                f = mock.patch.object(
                    o,
                    "universal_flow_config_variables",
                    COMMON_FLOW_VARS,
                )(f)
            if hasattr(o, "all_variables"):
                f = mock.patch.object(
                    o,
                    "all_variables",
                    COMMON_FLOW_VARS,
                )(f)

        return f

    return decorator


@pytest.fixture
@mock_variables()
def mock_config():
    from librelane.config import Config

    mock_config, _ = Config.load(
        {
            "DESIGN_NAME": "whatever",
            "VERILOG_FILES": "dir::src/*.v",
        },
        COMMON_FLOW_VARS,
        design_dir="/cwd",
        pdk="dummy",
        scl="dummy_scl",
        pdk_root="/pdk",
    )
    return mock_config


class MockProgress(object):
    def __init__(self, *args, **kwargs):
        self.add_task_called_count = 0
        self.start_called_count = 0
        self.stop_called_count = 0
        self.update_called_count = 0
        self.total = 100
        self.completed = 0
        self.description = "Progress"

    def add_task(self, *args, **kwargs):
        self.add_task_called_count += 1
        # Per-step rows are keyed by the returned ID, so it has to be distinct.
        self.add_task_returned_count = getattr(self, "add_task_returned_count", 0) + 1
        return self.add_task_returned_count

    def remove_task(self, *args, **kwargs):
        self.remove_task_called_count = getattr(self, "remove_task_called_count", 0) + 1

    def refresh(self):
        self.refresh_called_count = getattr(self, "refresh_called_count", 0) + 1

    def start(self):
        self.start_called_count += 1

    def stop(self):
        self.stop_called_count += 1

    def update(
        self,
        _,
        description: str | None = None,
        total: int | None = None,
        completed: float | None = None,
    ):
        if total_stages := total:
            self.total = total_stages

        if completed_stages := completed:
            self.completed = completed_stages

        if current_task_description := description:
            self.description = current_task_description

        self.update_called_count += 1


@pytest.fixture(autouse=True)
def _mock_progress():
    from librelane.flows import flow

    with mock.patch.object(flow, "Progress", MockProgress):
        yield


@pytest.fixture(autouse=True)
def _restore_runtime_options():
    """
    Undoes the process-global options a CLI invocation applies.

    :func:`librelane.cli.runtime.apply_runtime_options` mutates the two flags on
    :class:`librelane.logging.options`, the log-level threshold and the global
    thread pool. Not restoring them is right for a process that exits afterwards
    and wrong for a test session, where the next test inherits them: a single
    ``--condensed`` invocation left ``show_progress_bar`` false for everything
    collected after it. See ``test/test_option_isolation.py``.
    """
    from librelane.common import get_tpe, set_tpe
    from librelane.logging import get_log_level, options, set_log_level

    condensed = options.get_condensed_mode()
    show_progress_bar = options.get_show_progress_bar()
    log_level = get_log_level()
    tpe = get_tpe()
    try:
        yield
    finally:
        options.set_condensed_mode(condensed)
        options.set_show_progress_bar(show_progress_bar)
        set_log_level(log_level)
        set_tpe(tpe)


@pytest.fixture(autouse=True)
def _quiesce_log_pump():
    """
    Keeps the shared :data:`librelane.logging.live` pump thread from rendering
    during tests.

    pyfakefs does not support other threads touching the filesystem while it is
    active, and a pump tick landing inside a faked filesystem corrupts that
    test's view of it. Tests that exercise the pump construct their own
    ``LiveLog`` instead.
    """
    from librelane.logging import logger as logger_module

    live = logger_module.live
    live.stop()
    live._stopping.clear()
    live._autostart = False
    yield
    live.drain()


def pytest_configure():
    pytest.COMMON_FLOW_VARS = COMMON_FLOW_VARS
    pytest.mock_variables = mock_variables


def pytest_addoption(parser):
    parser.addoption("--pdk-root", action="store", default=None)
    parser.addoption(
        "--keep-tmp", action="store_true", default=False
    )  # add --log-cli-level=INFO so that the tmp being kept is printed
    parser.addoption(
        "--create-reproducible-on-fail", action="store_true", default=False
    )
