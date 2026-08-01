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
from __future__ import annotations

from loguru import logger

import os
import json
import psutil
import signal
import subprocess
import pathlib
from collections import deque
from contextlib import ExitStack
from typing import (
    Any,
    ClassVar,
    TYPE_CHECKING,
    TypeVar,
    cast,
)
from collections.abc import Callable, Sequence

from rich.markup import escape

from librelane.common import slugify, protected
from librelane.logging import console, options

from librelane.steps.step.exceptions import StepException
from librelane.steps.step.output_processor import OutputProcessor
from librelane.steps.step.process_stats import ProcessStatsThread

if TYPE_CHECKING:
    from librelane.steps.step.core import Step

VT = TypeVar("VT")


class SubprocessMixin:
    id: str
    step_dir: pathlib.Path
    output_processors: ClassVar[list[type[OutputProcessor]]]
    err: Callable[..., None]

    @protected
    def get_log_path(self) -> str:
        """
        Returns
        -------
        str
            the default value for :meth:`run_subprocess`'s "log_to"
            parameter.

            Override it to change the default log path.

        Named after the step's *class*, not the instance. A flow may give an
        instance a per-run id -- :class:`librelane.flows.engine.Workflow`
        names the job in it so two concurrent runs of one step class can be
        told apart in the logs -- and that name is already the directory this
        file sits in. Spelling it twice would rename every default subprocess
        log the moment a flow started disambiguating, which the documentation
        tells newcomers to open by name.
        """
        return os.fspath(pathlib.Path(self.step_dir) / f"{slugify(type(self).id)}.log")

    @protected
    def run_subprocess(
        self,
        cmd: Sequence[str | os.PathLike],
        log_to: str | os.PathLike | None = None,
        silent: bool = False,
        report_dir: str | os.PathLike | None = None,
        env: dict[str, Any] | None = None,
        *,
        check: bool = True,
        output_processing: Sequence[type[OutputProcessor]] | None = None,
        _popen_callable: Callable[..., psutil.Popen] = psutil.Popen,
        **kwargs,
    ) -> dict[str, Any]:
        """
        A helper function for :class:`Step` objects to run subprocesses.

        The output from the subprocess is processed line-by-line by instances
        of output processor classes.

        Parameters
        ----------
        cmd : Sequence[str | os.PathLike]
            A list of variables, representing a program and its arguments,
            similar to how you would use it in a shell.
        log_to : str | os.PathLike | None
            An optional override for the log path from
            :meth:`get_log_path`\\. Useful for if you run multiple subprocesses
            within one step.
        silent : bool
            If specified, the subprocess does not print anything to
            the terminal. Useful when running multiple processes simultaneously.
        report_dir : str | os.PathLike | None
            An optional override for where reports by output
            processors
        check : bool
            Whether to raise ``subprocess.CalledProcessError`` in
            the event of a non-zero exit code. Set to ``False`` if you'd like
            to do further processing on the output(s).
        output_processing : Sequence[type[OutputProcessor]] | None
            An override for the class's list of
            :class:`librelane.steps.OutputProcessor` classes.
        **kwargs
            Passed on to subprocess execution: useful if you want to
            redirect stdin, stdout, etc.

        Returns
        -------
        dict[str, Any]
            A dictionary of output processor results.

            These key/value pairs are included in all cases:
            * ``returncode``: Exit code for the subprocess
            * ``log_path``: The resolved log path for the subprocess

            The other key value pairs depend on the ``key`` class variables
            and :meth:`librelane.steps.OutputProcessor.result` methods of the
            output processors.

        Raises
        ------
        subprocess.CalledProcessError
            If the process has a non-zero
            exit, and ``check`` is True, this exception will be raised.
        """
        if report_dir is None:
            report_dir = self.step_dir
        report_dir = pathlib.Path(report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)

        log_path_value = log_to or self.get_log_path()
        log_path = pathlib.Path(log_path_value)
        cmd_str = [str(arg) for arg in cmd]

        with (pathlib.Path(self.step_dir) / "COMMANDS").open(
            "a+", encoding="utf8"
        ) as f:
            f.write(" ".join(cmd_str))
            f.write("\n")

        kwargs = kwargs.copy()
        if "stdout" not in kwargs:
            kwargs["stdout"] = subprocess.PIPE
        if "stderr" not in kwargs:
            kwargs["stderr"] = subprocess.STDOUT

        if env is None:
            env = os.environ.copy()

        # A subprocess writes to a pipe, not a terminal, so Rich inside it can
        # only fall back to its 80-column default and clamps every table it
        # prints -- the cell frequency and disconnected pin tables among them.
        # Only the parent knows the real width. ``console.width`` already
        # honours a COLUMNS the user exported, and ``setdefault`` leaves a
        # caller that set one explicitly alone.
        env = dict(env)
        env.setdefault("COLUMNS", str(console.width))

        for key, value in env.items():
            if not (
                isinstance(value, str)
                or isinstance(value, bytes)
                or isinstance(value, os.PathLike)
            ):
                raise StepException(
                    f"Environment variable for key '{key}' is of invalid type {type(value)}: {value}"
                )

        if output_processing is None:
            output_processing = self.output_processors
        output_processors = []
        for cls in output_processing:
            output_processors.append(cls(cast("Step", self), report_dir, silent))

        hyperlinks = (
            os.getenv(
                "_i_want_librelane_to_hyperlink_things_for_some_reason",
                None,
            )
            == "1"
        )
        link_start = ""
        link_end = ""
        if hyperlinks:
            link_start = f"[link=file://{log_path.resolve()}]"
            link_end = "[/link]"

        msg = f"Logging subprocess to [repr.filename]{link_start}'{os.path.relpath(log_path)}'{link_end}[/repr.filename]…"
        if options.get_condensed_mode():
            logger.info(msg)
        else:
            logger.log("VERBOSE", msg)

        with ExitStack() as owned_files:
            log_file = owned_files.enter_context(log_path.open("w", encoding="utf8"))
            if "stdin" not in kwargs:
                kwargs["stdin"] = owned_files.enter_context(
                    open(os.devnull, "r", encoding="utf8")
                )

            process = _popen_callable(
                cmd_str,
                encoding="utf8",
                env=env,
                **kwargs,
            )

            process_stats_thread = ProcessStatsThread(process)
            process_stats_thread.start()

            line_buffer: deque[str] = deque(maxlen=10)
            try:
                if process_stdout := process.stdout:
                    try:
                        for line in process_stdout:
                            log_file.write(line)
                            line_buffer.append(line)
                            for processor in output_processors:
                                if processor.process_line(line):
                                    break
                    except UnicodeDecodeError as e:
                        raise StepException(f"Subprocess emitted non-UTF-8 output: {e}")
            finally:
                # Whatever happened to the output, the monitor has to come back:
                # left running it keeps polling a process nobody is waiting on.
                process_stats_thread.stop()
                process_stats_thread.join()
            returncode = process.wait()

        json_stats = log_path.with_suffix(".process_stats.json")
        with json_stats.open("w", encoding="utf8") as f:
            json.dump(process_stats_thread.stats_as_dict(), f, indent=4)

        result: dict[str, Any] = {}
        result["returncode"] = returncode
        result["log_path"] = log_path_value

        for processor in output_processors:
            result[processor.key] = processor.result()

        if check and returncode != 0:
            if returncode > 0:
                logger.bind(step=self.id).error("Subprocess had a non-zero exit.")
                concatenated = ""
                for line in line_buffer:
                    concatenated += line
                if concatenated.strip() != "":
                    logger.bind(step=self.id).error(
                        f"Last {len(line_buffer)} line(s):\n" + escape(concatenated)
                    )
                logger.bind(step=self.id).error(
                    f"Full log file: {link_start}'{os.path.relpath(log_path)}'{link_end}"
                )
            raise subprocess.CalledProcessError(returncode, process.args)

        return result

    @protected
    def run_interactive_subprocess(
        self,
        cmd: Sequence[str | os.PathLike],
        env: dict[str, Any] | None = None,
    ) -> int:
        """
        A helper function for :class:`Step` objects that hand a tool's own
        prompt or window over to the user.

        Unlike :meth:`run_subprocess`, the subprocess inherits the terminal's
        standard input, output and error, so the user can interact with it. That
        also means its output is neither logged nor processed.

        Parameters
        ----------
        cmd : Sequence[str | os.PathLike]
            A list of variables, representing a program and its arguments,
            similar to how you would use it in a shell.
        env : dict[str, Any] | None
            The environment to run the command in.

        Returns
        -------
        int
            The exit code of the subprocess.
        """
        process = subprocess.Popen(
            [str(arg) for arg in cmd],
            env=env,
            cwd=self.step_dir,
        )
        try:
            return process.wait()
        except KeyboardInterrupt:
            process.send_signal(signal.SIGKILL)
            return process.wait()

    @protected
    def extract_env(self, kwargs) -> tuple[dict, dict[str, str]]:
        """
        An assisting function: Given a ``kwargs`` object, it does the following:

            * If the kwargs object has an "env" variable, it separates it into
                its own variable.
            * If the kwargs object has no "env" variable, a new "env" dictionary
                is created based on the current environment.

        Parameters
        ----------
        kwargs
            A Python keyword arguments object.

        Returns
        -------
        tuple[dict, dict[str, str]]
            A kwargs without an ``env`` object, and an isolated ``env`` object.
        """
        env = kwargs.get("env")
        if env is None:
            env = os.environ.copy()
        else:
            kwargs = kwargs.copy()
            del kwargs["env"]
        return (kwargs, env)
