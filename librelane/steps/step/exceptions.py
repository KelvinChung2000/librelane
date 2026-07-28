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

from typing import (
    TypeVar,
)


VT = TypeVar("VT")


class StepError(RuntimeError):
    """
    A ``RuntimeError`` that occurs when a Step fails to finish execution
    properly.
    """

    def __init__(self, *args, underlying_error: Exception | None = None, **kwargs):
        self.underlying_error = underlying_error
        super().__init__(*args, **kwargs)


class DeferredStepError(StepError):
    """
    A variant of :class:`StepError` where parent Flows are encouraged to continue
    execution of subsequent steps regardless and then finally flag the Error
    at the very end.
    """

    pass


class StepException(StepError):
    """
    A variant of :class:`StepError` for unexpected failures or failures due
    to misconfiguration, such as:

    * Invalid inputs
    * Mis-use of class interfaces of the :class:`Step`
    * Other unexpected failures
    """

    pass


class StepSignalled(StepException):
    pass


class StepNotFound(NameError):
    def __init__(self, *args: object, id: str | None = None) -> None:
        super().__init__(*args)
        self.id = id
