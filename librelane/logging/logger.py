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
import os
import atexit
from contextlib import contextmanager
from typing import Any, ClassVar
from collections.abc import Iterator, Mapping

import rich.console
from loguru import logger as _logger

from librelane.logging.live import LiveLog, StepDisplay

#: The levels LibreLane adds to Loguru's built-in registry, which already
#: defines DEBUG=10, INFO=20, SUCCESS=25, WARNING=30, ERROR=40 and CRITICAL=50.
#: ``ALL`` exists so ``--log-level ALL`` resolves through the same lookup as
#: every other name rather than needing a special case.
_ADDED_LEVELS = {
    "ALL": 0,
    "SUBPROCESS": 12,
    "VERBOSE": 15,
}

console = rich.console.Console()
#: Repairs the cursor a progress bar or live display hid but never restored,
#: for instance because the flow died mid-render. It writes to stderr rather
#: than to ``console``: stdout carries data a caller may be parsing, and merely
#: importing LibreLane must not put a control code in front of it.
_control_console = rich.console.Console(stderr=True)
atexit.register(_control_console.show_cursor)
_log_level = _ADDED_LEVELS["SUBPROCESS"]
_terminal_sink_id: int | None = None

#: Buffers terminal-bound records per step so the batch is rendered once per
#: refresh tick rather than once per line. See :mod:`librelane.logging.live`.
live = LiveLog(console)
atexit.register(live.stop)


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


def _passes_threshold(record: Mapping[str, Any]) -> bool:
    """
    Applies the process-wide threshold that ``--log-level`` moves.

    Loguru has no such threshold: severity is per-sink, fixed by ``level=`` when
    the sink is added and immutable afterwards. Re-adding sinks on every change
    is not an option either, because the threshold governs sinks LibreLane does
    not own the ``add()`` arguments of -- a flow registers ``flow.log`` and the
    per-level logs itself. A filter reading a module-level variable is Loguru's
    own answer to a level that has to change at runtime.
    """
    return int(record["level"].no) >= _log_level


_LEVEL_STYLES = {
    "WARNING": "yellow",
    "SUCCESS": "green",
    "ERROR": "red",
    "CRITICAL": "bold red",
}


def _terminal_sink(message) -> None:
    """
    Hands a record to the per-step buffer and returns.

    This runs on whichever thread emitted the record -- for subprocess output
    that is the thread draining the tool's stdout pipe -- so it must not
    render. Rendering happens once per refresh tick in :meth:`LiveLog.drain`.
    """
    record = message.record
    level_name = record["level"].name
    if options.get_condensed_mode() and level_name == "SUBPROCESS":
        return

    step_id = record["extra"].get("step") or ""
    text = str(record["message"])

    if level_name == "SUBPROCESS":
        # Raw tool output: no markup, or a stray '[' would be eaten as a tag.
        live.submit(step_id, text, markup=False)
        return

    if options.get_condensed_mode():
        prefix = f"[{level_name[0]}]"
    else:
        prefix = f"[{record['time']:%X}] {level_name:<8}"

    live.submit(
        step_id,
        f"{prefix} {text}",
        style=_LEVEL_STYLES.get(level_name),
        markup=True,
    )


def initialize_logger() -> None:
    global _terminal_sink_id

    for name, number in _ADDED_LEVELS.items():
        try:
            _logger.level(name)
        except ValueError:
            _logger.level(name, no=number)

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


@contextmanager
def step_context(
    step_id: str,
    title: str | None = None,
    log_path: str | os.PathLike | None = None,
) -> Iterator[StepDisplay]:
    """
    Marks the calling thread as running ``step_id``.

    Every record emitted underneath -- including subprocess output, which never
    had an explicit binding -- is attributed to the step without the emitting
    code having to say so. Submitting work to a
    :class:`librelane.common.ContextPropagatingThreadPoolExecutor` carries the
    attribution into worker threads too.

    Parameters
    ----------
    step_id : str
        The step's ID, used to attribute records.
    title : str | None
        Human-readable name for the step's block header. Defaults to
        ``step_id``.
    log_path : str | os.PathLike | None
        Where to write this step's own log. Unlike the terminal,
        which is a live view, this file is the durable record for the step --
        greppable after the fact and tailable while a parallel run is in
        flight.
    """
    # step_log rides along in the context so an issue collected anywhere can be
    # traced back to the durable record without extra plumbing.
    with _logger.contextualize(
        step=step_id,
        step_log=os.fspath(log_path) if log_path is not None else None,
    ):
        display = live.register(step_id, title)
        sink_id: int | None = None
        if log_path is not None:
            sink_id = _logger.add(
                log_path,
                # VERBOSE and above: raw tool output is already written
                # verbatim to the subprocess's own log by run_subprocess.
                level="VERBOSE",
                filter=lambda record: record["extra"].get("step") == step_id,
                format="[{time:HH:mm:ss}] {level: <8} {message}",
                backtrace=False,
                diagnose=False,
            )
        try:
            yield display
        finally:
            if sink_id is not None:
                _logger.remove(sink_id)
            live.unregister(step_id)


def register_additional_sink(
    sink,
    *,
    level: str | int = 0,
    filter=None,
    format: str = "{message}",
    **kwargs,
) -> int:
    """
    Registers a native Loguru sink governed by LibreLane's threshold.

    ``level`` is Loguru's own per-sink minimum and still applies; this only adds
    the process-wide threshold on top, which a bare :func:`loguru.logger.add`
    cannot express because a sink's ``level`` is fixed once it is added.
    """

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


@contextmanager
def additional_sink(*args, **kwargs) -> Iterator[int]:
    """
    Registers a sink and guarantees its removal when the context exits.

    Loguru pairs :func:`loguru.logger.add` with :func:`loguru.logger.remove` but
    offers no context manager over the pair.
    """
    sink_id = register_additional_sink(*args, **kwargs)
    try:
        yield sink_id
    finally:
        _logger.remove(sink_id)


def set_log_level(lv: str | int) -> None:
    """
    Sets the minimum severity emitted by LibreLane sinks.

    Parameters
    ----------
    lv : str | int
        A level number, or the name of a level registered with Loguru --
        its built-ins plus the ones in :data:`_ADDED_LEVELS`.

    Raises
    ------
    ValueError
        If ``lv`` names a level Loguru does not know.
    """
    global _log_level

    if isinstance(lv, str):
        try:
            _log_level = _logger.level(lv.upper()).no
        except ValueError:
            raise ValueError(f"Unknown level: {lv}") from None
    else:
        _log_level = int(lv)


def reset_log_level() -> None:
    """Restores the default ``SUBPROCESS`` threshold."""
    set_log_level("SUBPROCESS")


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
