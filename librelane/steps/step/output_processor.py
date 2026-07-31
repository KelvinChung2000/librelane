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
import pathlib
from decimal import Decimal
from io import TextIOWrapper
from abc import abstractmethod, ABC
from typing import (
    Any,
    ClassVar,
    Generic,
    TYPE_CHECKING,
    TypeVar,
)


if TYPE_CHECKING:
    from librelane.steps.step.core import Step

VT = TypeVar("VT")


REPORT_START_LOCUS = "%OL_CREATE_REPORT"
REPORT_END_LOCUS = "%OL_END_REPORT"
METRIC_LOCUS = "%OL_METRIC"


class OutputProcessor(ABC, Generic[VT]):
    """
    An abstract base class that processes terminal output from
    :meth:`librelane.steps.Step.run_subprocess`
    and append a resultant key/value pair to its returned dictionary.

    Parameters
    ----------
    step : Step
        The step object instantiating this output processor
    report_dir : str | os.PathLike[str]
        The report directory for this instantiation of
        ``run_subprocess``.
    silent : bool
        Whether the ``run_subprocess`` was called with ``silent`` or
        not.

    Attributes
    ----------
    key : ClassVar[str]
        The fixed key to be added to the return value of
        ``run_subprocess``. Must be implemented by subclasses.
    """

    key: ClassVar[str] = NotImplemented

    def __init__(
        self,
        step: Step,
        report_dir: str | os.PathLike[str],
        silent: bool,
    ) -> None:
        self.step = step
        self.report_dir = pathlib.Path(report_dir)
        self.silent: bool = silent

    @abstractmethod
    def process_line(self, line: str) -> bool:
        """
        Fires when a line is received by
        :meth:`librelane.steps.Step.run_subprocess`. Subclasses may do any
        arbitrary processing here.

        Parameters
        ----------
        line : str
            The line emitted by the subprocess

        Returns
        -------
        bool
            ``True`` if the line is "consumed", i.e. other output
            processors are skipped. ``False`` if the line is to be passed on
            to later output processors.
        """
        pass

    @abstractmethod
    def result(self) -> VT:
        """
        Returns
        -------
        VT
            The result of all previous ``process_line`` calls.
        """
        pass


class DefaultOutputProcessor(OutputProcessor[dict[str, Any]]):
    """
    An output processor that makes a number of special functions accessible to
    subprocesses by simply printing keywords in the terminal, such as:

    * ``%OL_CREATE_REPORT <file>``\\: Starts redirecting all output from
      standard output to a report file inside the step directory, with the
      name <file>.
    * ``%OL_END_REPORT``: Stops redirection behavior.
    * ``%OL_METRIC <name> <value>``\\: Adds a string metric with the name <name>
      and the value <value> to this function's returned object.
    * ``%OL_METRIC_F <name> <value>``\\: Adds a floating-point metric with the
      name <name> and the value <value> to this function's returned object.
    * ``%OL_METRIC_I <name> <value>``\\: Adds an integer metric with the name
      <name> and the value <value> to this function's returned object.

    Otherwise, the line is simply printed to the logger.
    """

    key = "generated_metrics"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.generated_metrics: dict[str, Any] = {}
        self.current_rpt: TextIOWrapper | None = None

    def process_line(self, line: str) -> bool:
        """
        Always returns ``True``, so ``DefaultOutputProcessor`` should always be
        at the end of your list.
        """
        if self.step.step_dir is not None and line.startswith(REPORT_START_LOCUS):
            if self.current_rpt is not None:
                self.current_rpt.close()
            report_name = line[len(REPORT_START_LOCUS) + 1 :].strip()
            report_path = self.report_dir / report_name
            self.current_rpt = report_path.open("w")
        elif line.startswith(REPORT_END_LOCUS):
            if self.current_rpt is not None:
                self.current_rpt.close()
            self.current_rpt = None
        elif line.startswith(METRIC_LOCUS):
            command, name, value = line.split(" ", maxsplit=3)
            metric_type: type[str] | type[int] | type[Decimal] = str
            if command.endswith("_I"):
                metric_type = int
            elif command.endswith("_F"):
                metric_type = Decimal
            self.generated_metrics[name] = metric_type(value)
        elif self.current_rpt is not None:
            # No echo- the timing reports especially can be very large
            # and terminal emulators will slow the flow down.
            self.current_rpt.write(line)
        elif not self.silent:
            logger.log("SUBPROCESS", line.rstrip())
        return True

    def result(self) -> dict[str, Any]:
        """
        A dictionary of all generated metrics.
        """
        return self.generated_metrics
