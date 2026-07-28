# Copyright 2026 Efabless Corporation
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
Buffered, batched terminal output for concurrently running steps.

Rendering a line through Rich costs roughly 225µs while a progress bar holds
the live region, because the per-call overhead -- taking the ``Live`` lock,
clearing the region, redrawing it -- is paid once per line. That work used to
happen inline on the thread draining a subprocess's stdout pipe, so a tool
emitting faster than ~4,400 lines/second would fill the pipe and block on
write: logging throttled the tool.

Here the producer only appends to a per-step buffer, and the batch is rendered
once per refresh tick. Amortised over a batch the cost falls to ~11µs/line,
raising the sustainable rate to ~92,000 lines/second -- far above what any EDA
tool emits, so the buffer drains faster than it fills and nothing is ever
dropped.
"""

import threading
from collections.abc import Callable
from dataclasses import dataclass, field

import rich.console
from rich.text import Text


@dataclass
class StepDisplay:
    """The live state of one running step."""

    step_id: str
    #: Human-readable name for this step's block header.
    title: str = ""
    #: Records awaiting the next drain, as ``(style, markup, text)``.
    pending: list[tuple[str | None, bool, str]] = field(default_factory=list)
    #: The most recent line, shown by this step's progress row.
    last_line: str = ""

    def append(self, text: str, style: str | None, markup: bool) -> None:
        self.pending.append((style, markup, text))
        self.last_line = text

    def take(self) -> list[tuple[str | None, bool, str]]:
        pending = self.pending
        self.pending = []
        return pending


class LiveLog:
    """
    Buffers terminal-bound records per step and renders them in batches.

    Ordering is preserved within a step: styled and unstyled records share one
    buffer, so a warning can never overtake the tool output it followed. Across
    steps, each step's lines are emitted as a contiguous block rather than
    interleaved line-by-line, which keeps a parallel run readable.
    """

    def __init__(
        self,
        console: rich.console.Console,
        interval: float = 0.1,
        autostart: bool = True,
    ) -> None:
        """
        :param interval: Seconds between drains. Matches Rich's default refresh
            rate, so the terminal updates at the same cadence as the bar.
        :param autostart: Whether to start the pump on first use. Tests set this
            to ``False`` so drains happen only where they say they do.
        """
        self._console = console
        self._steps: dict[str, StepDisplay] = {}
        self._lock = threading.Lock()
        self._titles: dict[str, str] = {}
        #: Whose block was rendered last, so headers appear on change only.
        self._last_rendered: str | None = None
        self._interval = interval
        self._autostart = autostart
        self._pump: threading.Thread | None = None
        self._stopping = threading.Event()
        self._listeners: list[Callable[[], None]] = []

    def add_listener(self, listener: Callable[[], None]) -> None:
        """
        Registers a callback fired after each drain.

        The progress bar uses this to keep its rows in step with the running
        steps without any flow having to announce that it is fanning out.
        """
        with self._lock:
            if listener not in self._listeners:
                self._listeners.append(listener)

    def remove_listener(self, listener: Callable[[], None]) -> None:
        with self._lock:
            if listener in self._listeners:
                self._listeners.remove(listener)

    @property
    def pump_running(self) -> bool:
        return self._pump is not None

    def _ensure_pump(self) -> None:
        """
        Starts the drain thread on first use.

        Called with ``self._lock`` held. Started lazily rather than in
        ``__init__`` so merely importing LibreLane does not spawn a thread.
        """
        if self._pump is not None or not self._autostart or self._stopping.is_set():
            return
        self._pump = threading.Thread(
            target=self._run_pump,
            name="librelane-log-pump",
            daemon=True,
        )
        self._pump.start()

    def _run_pump(self) -> None:
        while not self._stopping.wait(self._interval):
            self.drain()

    def stop(self) -> None:
        """Stops the pump and flushes whatever is still buffered."""
        self._stopping.set()
        with self._lock:
            pump, self._pump = self._pump, None
        if pump is not None:
            pump.join(timeout=5.0)
        self.drain()

    def register(self, step_id: str, title: str | None = None) -> StepDisplay:
        with self._lock:
            display = StepDisplay(step_id, title or step_id)
            self._steps[step_id] = display
            self._titles[step_id] = display.title
            return display

    def unregister(self, step_id: str) -> None:
        """
        Flushes everything buffered, then drops the step.

        Draining all of it -- not just this step's share -- keeps blocks in the
        order they were produced. Flushing only the finishing step would push
        its block ahead of flow-level records that were queued earlier.
        """
        self.drain()
        with self._lock:
            display = self._steps.pop(step_id, None)
            batches = [(step_id, display.take())] if display is not None else []
        self._render(batches)

    def get(self, step_id: str) -> StepDisplay | None:
        with self._lock:
            return self._steps.get(step_id)

    def snapshot(self) -> list[StepDisplay]:
        """:returns: The currently live steps, for the progress bar to render."""
        with self._lock:
            return list(self._steps.values())

    def submit(
        self,
        step_id: str,
        text: str,
        style: str | None = None,
        markup: bool = False,
    ) -> None:
        """
        Buffers one record. This is the producer path and must stay cheap: it
        appends and returns, never blocking and never dropping.

        :param markup: Whether ``text`` carries Rich markup. LibreLane's own
            messages do; raw subprocess output must not, or a stray ``[`` in
            tool output would be eaten as a tag.
        """
        with self._lock:
            display = self._steps.get(step_id)
            if display is None:
                display = self._steps[step_id] = StepDisplay(step_id)
            display.append(text, style, markup)
            self._ensure_pump()

    def drain(self) -> None:
        """Renders every buffered record. Called once per refresh tick."""
        with self._lock:
            batches = [
                (step_id, display.take())
                for step_id, display in self._steps.items()
                if display.pending
            ]
            listeners = list(self._listeners)
        self._render(batches)
        for listener in listeners:
            listener()

    def _render(
        self, batches: list[tuple[str, list[tuple[str | None, bool, str]]]]
    ) -> None:
        for step_id, batch in batches:
            if not batch:
                continue
            self._emit_header(step_id)
            run: list[str] = []
            run_key: tuple[str | None, bool] = (None, False)
            for style, markup, text in batch:
                if (style, markup) != run_key and run:
                    self._flush_run(run, run_key)
                    run = []
                run_key = (style, markup)
                run.append(text)
            if run:
                self._flush_run(run, run_key)

    def _emit_header(self, step_id: str) -> None:
        """
        Heads a block with its step, but only when the step has changed. A
        serial run drains ten times a second and must not re-head every tick.
        """
        if step_id == self._last_rendered:
            return
        self._last_rendered = step_id
        if not step_id:
            # Flow-level records belong to no step.
            return
        # Text() rather than a bare str: a step id like "synthesis-AREA 0"
        # would otherwise be picked apart by Rich's highlighter.
        self._console.rule(Text(self._titles.get(step_id, step_id)))

    def _flush_run(self, run: list[str], key: tuple[str | None, bool]) -> None:
        # One print per run of like-rendered lines is what makes the cost
        # amortise; printing per line would reinstate the bottleneck.
        # highlight=False matters independently: Rich's regex highlighters cost
        # ~76µs/line on tool output that has nothing worth highlighting.
        style, markup = key
        self._console.print(
            "\n".join(run),
            style=style,
            markup=markup,
            highlight=False,
        )
