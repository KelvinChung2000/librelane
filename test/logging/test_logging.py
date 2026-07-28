import io

import pytest
from rich.console import Console


pytestmark = pytest.mark.all


def test_native_loguru_levels_and_context(caplog):
    from loguru import logger

    import librelane.logging as librelane_logging
    from librelane.logging import (
        get_log_level,
        reset_log_level,
        set_log_level,
    )

    assert not hasattr(librelane_logging, "info")
    assert not hasattr(librelane_logging, "warn")
    assert not hasattr(librelane_logging, "err")

    set_log_level("ALL")
    try:
        logger.debug("debug marker")
        logger.log("SUBPROCESS", "subprocess marker")
        logger.log("VERBOSE", "verbose marker")
        logger.bind(step="Test.Step", key="TEST-001").info("info marker")
        logger.success("success marker")
        logger.warning("warning marker")
        logger.error("error marker")
    finally:
        reset_log_level()

    assert get_log_level() == 12
    assert [record["level"].name for record in caplog.records] == [
        "DEBUG",
        "SUBPROCESS",
        "VERBOSE",
        "INFO",
        "SUCCESS",
        "WARNING",
        "ERROR",
    ]
    contextual = next(
        record for record in caplog.records if record["message"] == "info marker"
    )
    assert contextual["extra"]["step"] == "Test.Step"
    assert contextual["extra"]["key"] == "TEST-001"


def test_additional_handler_registration():
    from loguru import logger

    from librelane.logging import register_additional_sink

    records = []
    sink_id = register_additional_sink(
        lambda message: records.append(message.record.copy())
    )
    try:
        logger.bind(step="Test.Step").info("registered marker")
    finally:
        logger.remove(sink_id)
    logger.info("deregistered marker")

    assert [record["message"] for record in records] == ["registered marker"]
    assert records[0]["extra"]["step"] == "Test.Step"


def test_initialize_logger_preserves_additional_sinks():
    from loguru import logger

    from librelane.logging import additional_sink, initialize_logger

    records = []
    with additional_sink(lambda message: records.append(message.record["message"])):
        initialize_logger()
        logger.info("preserved marker")

    assert records == ["preserved marker"]


def test_temporary_log_level_restores_after_exception():
    from librelane.logging import (
        get_log_level,
        reset_log_level,
        set_log_level,
        temporary_log_level,
    )

    set_log_level("VERBOSE")

    def fail_with_temporary_level():
        with temporary_log_level("ERROR"):
            assert get_log_level() == 40
            raise RuntimeError("marker")

    try:
        with pytest.raises(RuntimeError, match="marker"):
            fail_with_temporary_level()
        assert get_log_level() == 15
    finally:
        reset_log_level()


def test_loguru_owns_the_level_registry():
    """
    LibreLane must not keep a second table of level names and numbers. Loguru
    already has one, and ``initialize_logger`` populates it with the two levels
    LibreLane adds.
    """
    from loguru import logger

    import librelane.logging as librelane_logging

    assert not hasattr(librelane_logging, "LogLevels")

    expected = {
        "ALL": 0,
        "DEBUG": 10,
        "SUBPROCESS": 12,
        "VERBOSE": 15,
        "INFO": 20,
        "SUCCESS": 25,
        "WARNING": 30,
        "ERROR": 40,
        "CRITICAL": 50,
    }
    assert {name: logger.level(name).no for name in expected} == expected


def test_set_log_level_resolves_names_through_loguru():
    from loguru import logger

    from librelane.logging import get_log_level, reset_log_level, set_log_level

    try:
        for name in ["ALL", "SUBPROCESS", "VERBOSE", "WARNING", "CRITICAL"]:
            set_log_level(name)
            assert get_log_level() == logger.level(name).no
        set_log_level("warning")
        assert get_log_level() == 30
        set_log_level(37)
        assert get_log_level() == 37
        with pytest.raises(ValueError, match="NOT_A_LEVEL"):
            set_log_level("NOT_A_LEVEL")
    finally:
        reset_log_level()


def test_threshold_gates_every_sink_not_only_the_terminal():
    """
    A Loguru sink's ``level=`` is fixed when it is added, and LibreLane does not
    own the ``add()`` arguments of every sink it must gate -- a flow registers
    ``flow.log`` and the per-level logs itself. So the threshold stays a filter
    shared by every sink rather than a per-sink ``level=``.
    """
    from loguru import logger

    from librelane.logging import additional_sink, reset_log_level, set_log_level

    def capture(store):
        return lambda message: store.append(message.record["level"].name)

    default_levels: list[str] = []
    with additional_sink(capture(default_levels)):
        logger.debug("below default threshold")
        logger.log("SUBPROCESS", "at default threshold")
    assert default_levels == ["SUBPROCESS"]

    raised_levels: list[str] = []
    set_log_level("ERROR")
    try:
        with additional_sink(capture(raised_levels)):
            logger.warning("below raised threshold")
            logger.error("at raised threshold")
    finally:
        reset_log_level()
    assert raised_levels == ["ERROR"]


def test_sink_helpers_do_not_alias_loguru_primitives():
    """
    ``register_additional_sink`` earns its place by folding the shared threshold
    into the caller's filter. A deregister helper would only be ``logger.remove``
    under another name, and level-name filtering is a caller-side predicate.
    """
    import librelane.logging as librelane_logging

    assert not hasattr(librelane_logging, "deregister_additional_sink")
    assert not hasattr(librelane_logging, "LevelFilter")


def test_additional_sink_removes_its_sink_on_exit():
    from loguru import logger

    from librelane.logging import additional_sink

    records: list[str] = []
    with additional_sink(lambda message: records.append(message.record["message"])):
        logger.info("inside")
    logger.info("outside")

    assert records == ["inside"]


def test_condensed_mode_suppresses_subprocess(monkeypatch):
    from loguru import logger

    from librelane.logging import logger as logger_module

    output = io.StringIO()
    console = Console(file=output, color_system=None, width=120)
    monkeypatch.setattr(logger_module, "console", console)
    # Subprocess output is buffered per step and rendered in batches, so the
    # assertion has to drain rather than read straight after emitting.
    monkeypatch.setattr(
        logger_module, "live", logger_module.LiveLog(console, autostart=False)
    )
    logger_module.initialize_logger()
    logger_module.options.set_condensed_mode(False)
    logger.log("SUBPROCESS", "visible subprocess marker")
    logger_module.live.drain()
    assert "visible subprocess marker" in output.getvalue()

    output.seek(0)
    output.truncate()
    logger_module.options.set_condensed_mode(True)
    logger.log("SUBPROCESS", "hidden subprocess marker")
    logger_module.live.drain()
    assert "hidden subprocess marker" not in output.getvalue()

    logger_module.options.set_condensed_mode(False)
    logger_module.initialize_logger()
