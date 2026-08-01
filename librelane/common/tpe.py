# Copyright 2024 Efabless Corporation
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
from librelane.common.misc import _get_process_limit

import contextvars
from concurrent.futures import Future, ThreadPoolExecutor
from collections.abc import Callable
from typing import Any, ParamSpec, TypeVar

P = ParamSpec("P")
R = TypeVar("R")


class ContextPropagatingThreadPoolExecutor(ThreadPoolExecutor):
    """
    A ``ThreadPoolExecutor`` that runs submitted callables inside a copy of the
    submitting thread's :mod:`contextvars` context.

    Every new thread starts with an empty context, so without this the
    ``logger.contextualize`` binding that identifies the running step is lost
    the moment work is handed to a worker. That would leave records from
    fanned-out work -- one job per timing corner in ``OpenROAD.STAPrePNR``, one
    job per step in a flow -- with no step attribution.
    """

    def submit(  # type: ignore[override]
        self,
        fn: Callable[P, R],
        /,
        *args: Any,
        **kwargs: Any,
    ) -> Future[R]:
        context = contextvars.copy_context()
        return super().submit(context.run, fn, *args, **kwargs)  # type: ignore[arg-type]


TPE: ThreadPoolExecutor = ContextPropagatingThreadPoolExecutor(
    max_workers=_get_process_limit()
)


def set_tpe(tpe: ThreadPoolExecutor):
    """
    Allows replacing LibreLane's global ``ThreadPoolExecutor`` with a customized
    one.

    Parameters
    ----------
    tpe : ThreadPoolExecutor
        The replacement ThreadPoolExecutor
    """
    global TPE
    TPE = tpe


def get_tpe() -> ThreadPoolExecutor:
    """
    Returns
    -------
    ThreadPoolExecutor
        LibreLane's global ``ThreadPoolExecutor``, sized from ``-j``.

    Warning
    -------
    This pool runs whole *jobs* for
    :class:`librelane.flows.engine.Workflow`, so its workers are occupied for
    as long as a job takes. Code running inside a job -- which is to say, any
    step, and anything a step calls -- must not submit to it and wait on the
    result: with the pool full of jobs the submitted work can only start once
    a worker frees up, and the worker that would free up is the one blocked
    waiting. A step that fans out builds its own executor instead, as
    ``OpenROAD.STAPrePNR`` does. The same applies to
    ``Flow.start_step_async``, which submits here.
    """
    global TPE
    return TPE
