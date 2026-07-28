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
import atexit
from contextlib import contextmanager
from enum import IntEnum
from typing import Any, ClassVar
from collections.abc import Iterable, Iterator, Mapping

import rich.console
from loguru import logger as _logger


class LogLevels(IntEnum):
    ALL = 0
    DEBUG = 10
    SUBPROCESS = 12
    VERBOSE = 15
    INFO = 20
    SUCCESS = 25
    WARNING = 30
    ERROR = 40
    CRITICAL = 50


console = rich.console.Console()
atexit.register(console.show_cursor)
_log_level = int(LogLevels.SUBPROCESS)
_terminal_sink_id: int | None = None


class options:
    _condensed_mode: ClassVar[bool] = False
    _show_progress_bar: ClassVar[bool] = True

    @classmethod
    def get_condensed_mode(Self) -> bool:
        return Self._condensed_mode

    @classmethod
    def set_condensed_mode(Self, condensed: bool):
        Self._condensed_mode = condensed

    @classmethod
    def get_show_progress_bar(Self) -> bool:
        return Self._show_progress_bar

    @classmethod
    def set_show_progress_bar(Self, show: bool):
        Self._show_progress_bar = show


class LevelFilter:
    """Filters native Loguru records by level name."""

    def __init__(self, levels: Iterable[str], invert: bool = False) -> None:
        if isinstance(levels, str):
            levels = [levels]
        self.levels = set(levels)
        self.invert = invert

    def __call__(self, record: Mapping[str, Any]) -> bool:
        level = record["level"]
        level_name = getattr(level, "name", str(level))
        if options.get_condensed_mode() and level_name == "SUBPROCESS":
            return False
        matched = level_name in self.levels
        return not matched if self.invert else matched


def _passes_threshold(record: Mapping[str, Any]) -> bool:
    return int(record["level"].no) >= _log_level


def _terminal_sink(message) -> None:
    record = message.record
    level_name = record["level"].name
    if options.get_condensed_mode() and level_name == "SUBPROCESS":
        return

    text = str(record["message"])
    if level_name == "SUBPROCESS":
        console.print(text, markup=False)
        return

    if options.get_condensed_mode():
        prefix = f"[{level_name[0]}]"
    else:
        prefix = f"[{record['time']:%X}] {level_name:<8}"

    style = None
    if level_name == "WARNING":
        style = "yellow"
    elif level_name == "SUCCESS":
        style = "green"
    elif level_name in {"ERROR", "CRITICAL"}:
        style = "bold red" if level_name == "CRITICAL" else "red"
    console.print(f"{prefix} {text}", style=style, markup=True)


def initialize_logger() -> None:
    global _terminal_sink_id

    for name, number in [
        ("SUBPROCESS", LogLevels.SUBPROCESS),
        ("VERBOSE", LogLevels.VERBOSE),
    ]:
        try:
            _logger.level(name)
        except ValueError:
            _logger.level(name, no=int(number))

    if _terminal_sink_id is None:
        _logger.remove()
    else:
        try:
            _logger.remove(_terminal_sink_id)
        except ValueError:
            pass

    _terminal_sink_id = _logger.add(
        _terminal_sink,
        level=0,
        filter=_passes_threshold,
        format="{message}",
        backtrace=False,
        diagnose=False,
    )


initialize_logger()


def register_additional_sink(
    sink,
    *,
    level: str | int = 0,
    filter=None,
    format: str = "{message}",
    **kwargs,
) -> int:
    """Registers a native Loguru sink governed by LibreLane's threshold."""

    def combined_filter(record):
        if not _passes_threshold(record):
            return False
        if filter is None:
            return True
        return filter(record)

    return _logger.add(
        sink,
        level=level,
        filter=combined_filter,
        format=format,
        backtrace=False,
        diagnose=False,
        **kwargs,
    )


def deregister_additional_sink(sink_id: int) -> None:
    """Removes a native Loguru sink by its registration ID."""
    _logger.remove(sink_id)


@contextmanager
def additional_sink(*args, **kwargs) -> Iterator[int]:
    """Registers a sink and guarantees its removal when the context exits."""
    sink_id = register_additional_sink(*args, **kwargs)
    try:
        yield sink_id
    finally:
        deregister_additional_sink(sink_id)


def set_log_level(lv: str | int) -> None:
    """Sets the minimum severity emitted by LibreLane sinks."""
    global _log_level

    if isinstance(lv, str):
        try:
            _log_level = int(LogLevels[lv.upper()])
        except KeyError:
            raise ValueError(f"Unknown level: {lv}") from None
    else:
        _log_level = int(lv)


def reset_log_level() -> None:
    """Restores the default ``SUBPROCESS`` threshold."""
    set_log_level(LogLevels.SUBPROCESS)


def get_log_level() -> int:
    """Returns LibreLane's numeric minimum severity."""
    return _log_level


@contextmanager
def temporary_log_level(level: str | int) -> Iterator[None]:
    """Temporarily changes the LibreLane threshold."""
    previous = get_log_level()
    set_log_level(level)
    try:
        yield
    finally:
        set_log_level(previous)


if __name__ == "__main__":
    set_log_level("ALL")
    _logger.debug("Debug")
    _logger.log("VERBOSE", "Verbose")
    _logger.log("SUBPROCESS", "Subprocess")
    console.rule("Rule")
    _logger.info("Info")
    _logger.success("Success")
    _logger.warning("Warn")
    _logger.error("Err")
