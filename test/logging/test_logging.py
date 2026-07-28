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

    from librelane.logging import (
        deregister_additional_sink,
        register_additional_sink,
    )

    records = []
    sink_id = register_additional_sink(
        lambda message: records.append(message.record.copy())
    )
    try:
        logger.bind(step="Test.Step").info("registered marker")
    finally:
        deregister_additional_sink(sink_id)
    logger.info("deregistered marker")

    assert [record["message"] for record in records] == ["registered marker"]
    assert records[0]["extra"]["step"] == "Test.Step"


def test_initialize_logger_preserves_additional_sinks():
    from loguru import logger

    from librelane.logging import (
        deregister_additional_sink,
        initialize_logger,
        register_additional_sink,
    )

    records = []
    sink_id = register_additional_sink(
        lambda message: records.append(message.record["message"])
    )
    try:
        initialize_logger()
        logger.info("preserved marker")
    finally:
        deregister_additional_sink(sink_id)

    assert records == ["preserved marker"]


def test_temporary_log_level_restores_after_exception():
    from librelane.logging import (
        LogLevels,
        get_log_level,
        set_log_level,
        temporary_log_level,
    )

    set_log_level(LogLevels.VERBOSE)

    def fail_with_temporary_level():
        with temporary_log_level(LogLevels.ERROR):
            assert get_log_level() == LogLevels.ERROR
            raise RuntimeError("marker")

    try:
        with pytest.raises(RuntimeError, match="marker"):
            fail_with_temporary_level()
        assert get_log_level() == LogLevels.VERBOSE
    finally:
        set_log_level(LogLevels.SUBPROCESS)


def test_condensed_mode_suppresses_subprocess(monkeypatch):
    from loguru import logger

    from librelane.logging import logger as logger_module

    output = io.StringIO()
    monkeypatch.setattr(
        logger_module,
        "console",
        Console(file=output, color_system=None, width=120),
    )
    logger_module.initialize_logger()
    logger_module.options.set_condensed_mode(False)
    logger.log("SUBPROCESS", "visible subprocess marker")
    assert "visible subprocess marker" in output.getvalue()

    output.seek(0)
    output.truncate()
    logger_module.options.set_condensed_mode(True)
    logger.log("SUBPROCESS", "hidden subprocess marker")
    assert "hidden subprocess marker" not in output.getvalue()

    logger_module.options.set_condensed_mode(False)
    logger_module.initialize_logger()
