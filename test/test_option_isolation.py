"""
Guards the suite against process-global CLI options leaking between tests.

``apply_runtime_options`` (:mod:`librelane.cli.runtime`) mutates four things that
outlive the call: the two flags on :class:`librelane.logging.options`, the
module-level log-level threshold, and the global thread pool. Nothing in the CLI
restores them, which is correct for a process that exits afterwards and wrong for
a test session that keeps going.

``test/cli/test_entry_points.py`` invokes the CLI with ``--log-level ERROR
--condensed``, so without a restoring fixture every later test in the session saw
``show_progress_bar=False``. That silently disabled the Rich bar and made
``test/engine/test_progress_bar.py`` assert against an empty console.

Both tests below are deliberately identical: each asserts the state is pristine
and then dirties all four. Whichever pytest happens to run second fails if the
first one's mutations were not undone, so the guard does not depend on collection
order and survives ``pytest-randomly``.
"""

import pytest

from librelane.common import get_tpe, set_tpe
from librelane.common.tpe import ContextPropagatingThreadPoolExecutor
from librelane.logging import get_log_level, options, set_log_level

pytestmark = pytest.mark.all

#: Captured at import, before any test has had a chance to mutate it.
_PRISTINE_LOG_LEVEL = get_log_level()

#: Every thread pool this module has observed at the start of a test.
_POOLS_SEEN: list[int] = []


def _assert_pristine_then_dirty():
    assert options.get_show_progress_bar() is True
    assert options.get_condensed_mode() is False
    assert get_log_level() == _PRISTINE_LOG_LEVEL

    _POOLS_SEEN.append(id(get_tpe()))
    assert len(set(_POOLS_SEEN)) == 1, "the global thread pool was not restored"

    options.set_show_progress_bar(False)
    options.set_condensed_mode(True)
    set_log_level("ERROR")
    set_tpe(ContextPropagatingThreadPoolExecutor(max_workers=1))


def test_runtime_options_do_not_leak_between_tests():
    _assert_pristine_then_dirty()


def test_runtime_options_do_not_leak_between_tests_either():
    _assert_pristine_then_dirty()
