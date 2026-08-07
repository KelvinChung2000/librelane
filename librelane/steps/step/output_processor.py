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


class OutputProcessor(ABC, Generic[VT]):
    """
    An abstract base class that processes terminal output from
    :meth:`librelane.steps.Step.run_subprocess`
    and append a resultant key/value pair to its returned dictionary.

    Parameters
    ----------
    step : Step
        The step object instantiating this output processor
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
        silent: bool,
    ) -> None:
        self.step = step
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
    Prints each line of subprocess output to the logger.

    Nothing else travels over stdout anymore: metrics arrive as JSON records
    in the ``_LLN_METRICS_JSONL`` sidecar file, read back by
    ``run_subprocess`` after exit, and reports are written by the
    subprocess itself into ``_LLN_REPORT_DIR``.
    """

    key = "generated_metrics"

    def process_line(self, line: str) -> bool:
        """
        Always returns ``True``, so ``DefaultOutputProcessor`` should always be
        at the end of your list.
        """
        if not self.silent:
            logger.log("SUBPROCESS", line.rstrip())
        return True

    def result(self) -> dict[str, Any]:
        """
        Always empty: it seeds the ``generated_metrics`` key of the
        ``run_subprocess`` result, which the sidecar reader then merges
        into.
        """
        return {}
