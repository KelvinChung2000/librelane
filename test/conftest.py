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
import threading
from unittest import mock
from decimal import Decimal
from typing import Any, Literal, Optional
from collections.abc import Iterable, Callable, Iterator

import pytest
from loguru import logger
from pyfakefs import fake_os, fake_pathlib
from pyfakefs import fake_filesystem_unittest
from pyfakefs.fake_filesystem_unittest import Patcher
from _pytest.fixtures import SubRequest

from librelane.config import Variable, Macro
from librelane.common import Path, GenericDict


class _ThreadScopedUseOriginal:
    """
    pyfakefs's "answer this call from the real disk" switch, made per-thread.

    :func:`pyfakefs.fake_os.use_original_os` sets
    ``FakeOsModule.use_original``, a plain class attribute, so that pyfakefs's
    own ``linecache`` shim can read a source file that only exists on the real
    disk. Every faked ``open`` reaches that shim: ``fake_open`` asks
    ``helpers.is_called_from_skipped_module``, which calls
    ``traceback.extract_stack()``, which reads source through ``linecache``.

    The switch is process-wide and pyfakefs contains no threading code at all,
    so while one thread holds it every *other* thread's ``open`` and
    ``os.path.exists`` are answered by the real filesystem, where the fixtures'
    ``/pdk`` and ``/cwd`` do not exist. A single-threaded test never sees it. A
    test that runs two flow jobs at once fails with a PDK path that "does not
    exist", at whichever call lost the race.

    Whether the calling code is a module pyfakefs was told to skip is a fact
    about one call stack, so the switch is per-thread by nature. Both readers
    -- ``fake_os.handle_original_call`` and ``fake_path.handle_original_call``
    -- only ever test it for truthiness, so an object with a per-thread
    ``__bool__`` is a drop-in for the ``bool`` they read today.
    """

    def __init__(self) -> None:
        self._local = threading.local()

    def __bool__(self) -> bool:
        return getattr(self._local, "value", False)

    def set(self, value: bool) -> None:
        self._local.value = value


@contextlib.contextmanager
def _thread_scoped_use_original_os() -> Iterator[None]:
    """Replaces :func:`pyfakefs.fake_os.use_original_os`, holding the switch
    for the calling thread only."""
    switch = fake_os.FakeOsModule.use_original
    if not isinstance(switch, _ThreadScopedUseOriginal):
        # An explicit raise rather than an assert: under `python -O` the assert
        # would be stripped and the next line would fail with an AttributeError
        # on a bool, which says nothing about what went wrong.
        raise RuntimeError(
            "pyfakefs's use_original switch is a "
            f"{type(switch).__name__}, not the thread-scoped one the "
            "_pyfakefs_switch_is_thread_scoped fixture installs. Something "
            "replaced it, and faked calls will leak to the real filesystem "
            "across threads."
        )
    switch.set(True)
    try:
        yield
    finally:
        switch.set(False)


@pytest.fixture(scope="session", autouse=True)
def _pyfakefs_switch_is_thread_scoped():
    """
    Installs :class:`_ThreadScopedUseOriginal` for the session.

    Both names have to be replaced together: the switch, and every module-level
    reference to the context manager that sets it. ``fake_filesystem_unittest``
    holds one for the ``linecache`` shim and ``fake_pathlib`` holds one for its
    real-path methods, and each resolves it as a module global at call time, so
    rebinding the global is enough to reach both. The original
    ``use_original_os`` would assign a bare ``True`` over the switch object and
    undo the whole thing, so leaving any reference behind is not an option.
    """
    original_switch = fake_os.FakeOsModule.use_original
    originals = {
        module: module.use_original_os
        for module in (fake_os, fake_filesystem_unittest, fake_pathlib)
    }
    fake_os.FakeOsModule.use_original = _ThreadScopedUseOriginal()
    for module in originals:
        module.use_original_os = _thread_scoped_use_original_os
    yield
    for module, original in originals.items():
        module.use_original_os = original
    fake_os.FakeOsModule.use_original = original_switch


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


@pytest.fixture
def _mock_conf_fs():
    with Patcher() as patcher:
        patcher.fs.create_dir("/cwd/src")
        patcher.fs.create_file("/cwd/src/a.v")
        patcher.fs.create_file("/cwd/src/b.v")
        patcher.fs.create_dir("/cwd/spef")
        patcher.fs.create_file("/cwd/spef/b.spef")
        patcher.fs.create_file(
            "/pdk/dummy/libs.tech/librelane/config.tcl",
            contents="""
            if { ![info exists ::env(STD_CELL_LIBRARY)] } {
                set ::env(STD_CELL_LIBRARY) "dummy_scl"
            }
            set ::env(TECH_LEF) "/pdk/dummy/libs.ref/techlef/dummy_scl/dummy_tech_lef.tlef"
            set ::env(LIB_SYNTH) "sky130_fd_sc_hd__tt_025C_1v80.lib"
            set ::env(KLAYOUT_TECH) "/pdk/dummy/libs.tech/klayout/dummy.lyt"
            set ::env(KLAYOUT_PROPERTIES) "/pdk/dummy/libs.tech/klayout/dummy.lyp"
            set ::env(KLAYOUT_DEF_LAYER_MAP) "/pdk/dummy/libs.tech/klayout/dummy.map"
            """,
        )
        # Enough of a KLayout view for the KLayout steps to resolve their
        # required PDK variables; the tool itself is stubbed out in tests.
        for klayout_view in ("dummy.lyt", "dummy.lyp", "dummy.map"):
            patcher.fs.create_file(f"/pdk/dummy/libs.tech/klayout/{klayout_view}")
        patcher.fs.create_file(
            "/pdk/dummy2/libs.tech/librelane/config.tcl",
            contents="""
            if { ![info exists ::env(STD_CELL_LIBRARY)] } {
                set ::env(STD_CELL_LIBRARY) "dummy2_scl"
            }
            set ::env(TECH_LEF) "/pdk/dummy2/libs.ref/techlef/dummy2_scl/dummy_tech_lef.tlef"
            set ::env(LIB_SYNTH) "sky130_fd_sc_hd__tt_025C_1v80.lib"
            """,
        )
        patcher.fs.create_file(
            "/pdk/dummy/libs.ref/techlef/dummy_scl/dummy_tech_lef.tlef",
        )
        patcher.fs.create_file(
            "/pdk/dummy2/libs.ref/techlef/dummy2_scl/dummy_tech_lef.tlef",
        )
        patcher.fs.create_file(
            "/pdk/dummy/libs.tech/librelane/dummy_scl/config.tcl",
            contents="",
        )
        patcher.fs.create_file(
            "/pdk/dummy2/libs.tech/librelane/dummy2_scl/config.tcl",
            contents="",
        )

        os.chdir("/cwd")
        yield


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
    Variable(
        "DIODE_ON_PORTS",
        Literal["none", "in"],
        description="x",
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
