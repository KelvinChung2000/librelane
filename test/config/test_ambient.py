# Copyright 2026 LibreLane Contributors
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
"""
The two tiers of :mod:`librelane.config.ambient`, and the property that makes
the scoped one necessary: a run resolves more than one configuration and runs
them at the same time.
"""

import threading

import pytest

from librelane.config import config

pytestmark = pytest.mark.all

mock_variables = pytest.mock_variables


def _config(**overrides):
    from librelane.config import Config

    resolved, _ = Config.load(
        {
            "DESIGN_NAME": "whatever",
            "VERILOG_FILES": "dir::src/*.v",
            **overrides,
        },
        config.flow_common_variables,
        design_dir="/cwd",
        pdk="dummy",
        scl="dummy_scl",
        pdk_root="/pdk",
    )
    return resolved


def _scope(**overrides):
    from librelane.config import build_scope

    return build_scope(_config(**overrides), lambda: config.flow_common_variables)


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables()
def test_nothing_is_current_by_default():
    from librelane.config import NoCurrentConfig, current_config, get_current_config

    assert get_current_config() is None
    with pytest.raises(NoCurrentConfig, match="No configuration is current"):
        current_config()


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables()
def test_the_singleton_is_readable_from_anywhere():
    from librelane.config import current_config, current_raw_config, set_current_config

    scope = _scope(DESIGN_NAME="published")
    set_current_config(scope)

    assert current_config().DESIGN_NAME == "published"
    assert current_raw_config()["DESIGN_NAME"] == "published"


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables()
def test_setting_the_singleton_returns_the_previous_one():
    from librelane.config import set_current_config

    first = _scope()
    second = _scope()

    assert set_current_config(first) is None
    assert set_current_config(second) is first
    assert set_current_config(None) is second


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables()
def test_a_scope_outranks_the_singleton_and_leaves_it_intact():
    from librelane.config import current_config, set_current_config, use_config

    set_current_config(_scope(DESIGN_NAME="flow"))

    with use_config(_scope(DESIGN_NAME="job")):
        assert current_config().DESIGN_NAME == "job"

    assert current_config().DESIGN_NAME == "flow"


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables()
def test_scopes_nest():
    from librelane.config import current_config, use_config

    with use_config(_scope(DESIGN_NAME="outer")):
        with use_config(_scope(DESIGN_NAME="inner")):
            assert current_config().DESIGN_NAME == "inner"
        assert current_config().DESIGN_NAME == "outer"


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables()
def test_a_scope_is_restored_when_the_block_raises():
    from librelane.config import get_current_config, use_config

    with pytest.raises(ValueError, match="deliberate"):
        with use_config(_scope()):
            raise ValueError("deliberate")

    assert get_current_config() is None


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables()
def test_concurrent_scopes_do_not_see_each_other():
    """
    The property the whole two-tier design exists for. A sweep runs several
    passes at once, each with its own resolved configuration, on the shared
    pool; one slot would let the last writer decide what all of them read.
    """
    from librelane.common.tpe import ContextPropagatingThreadPoolExecutor
    from librelane.config import current_config, set_current_config, use_config

    set_current_config(_scope(DESIGN_NAME="flow"))
    names = [f"pass_{index}" for index in range(8)]
    scopes = {name: _scope(DESIGN_NAME=name) for name in names}
    # Built here and not on the worker: validating a configuration reads the
    # filesystem, and pyfakefs does not survive another thread doing that while
    # it is active. What is under test is which scope a worker finds, not when
    # its model is built.
    for scope in scopes.values():
        scope.typed
    # Every worker has entered its scope before any of them reads one, so a
    # slot shared between them would be read after it had been overwritten.
    entered = threading.Barrier(len(names))

    def read(name: str) -> str:
        with use_config(scopes[name]):
            entered.wait(timeout=10)
            return current_config().DESIGN_NAME

    with ContextPropagatingThreadPoolExecutor(max_workers=len(names)) as pool:
        observed = list(pool.map(read, names))

    assert observed == names
    assert current_config().DESIGN_NAME == "flow"


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables()
def test_a_scope_reaches_work_submitted_from_inside_it():
    """
    A step fans out onto the pool -- ``OpenROAD.STAPrePNR`` runs a job per
    timing corner -- and the work it submits has to read the configuration the
    step is running under, not the one the process happens to hold.
    """
    from librelane.common.tpe import ContextPropagatingThreadPoolExecutor
    from librelane.config import current_config, set_current_config, use_config

    outer = _scope(DESIGN_NAME="flow")
    inner = _scope(DESIGN_NAME="job")
    # As above: built on this thread, so no worker touches the fake filesystem.
    outer.typed
    inner.typed
    set_current_config(outer)

    with ContextPropagatingThreadPoolExecutor(max_workers=2) as pool:
        with use_config(inner):
            inside = pool.submit(lambda: current_config().DESIGN_NAME).result(
                timeout=10
            )
        outside = pool.submit(lambda: current_config().DESIGN_NAME).result(timeout=10)

    assert inside == "job"
    assert outside == "flow"


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables()
def test_a_scope_builds_its_model_once_and_only_when_read():
    """
    Generating the model is the expensive half, and a flow that is only asked
    to explain itself never needs it.
    """
    from librelane.config import build_scope

    built = 0

    def model():
        nonlocal built
        built += 1
        from librelane.config.ambient import scope_model

        return scope_model(config.flow_common_variables)

    scope = build_scope(_config(), model_type=model)
    assert built == 0

    first = scope.typed
    second = scope.typed
    assert built == 1
    assert first is second


@pytest.mark.usefixtures("_mock_conf_fs")
@mock_variables()
def test_build_scope_needs_something_to_validate_against():
    from librelane.config import build_scope

    with pytest.raises(TypeError, match="'variables' or 'model_type'"):
        build_scope(_config())
