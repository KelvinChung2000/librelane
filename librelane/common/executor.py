# Copyright 2025 LibreLane Contributors
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
Global ProcessPoolExecutor for async step execution and log processing.

This module provides a singleton ProcessPoolExecutor that replaces the previous
ThreadPoolExecutor-based approach. Using a single ProcessPoolExecutor for both
step execution and log processing eliminates the nested executor deadlock that
occurred when running 45+ concurrent jobs on a 32-core system.
"""

import os
import atexit
from concurrent.futures import ProcessPoolExecutor
from typing import Optional


def _get_worker_count() -> int:
    """
    Get worker count with oversubscription for I/O-bound workloads.

    Default: 1.5x CPU count to allow more concurrent I/O-bound jobs
    (e.g., 48 workers on 32-core system allows 45+ jobs without queuing).

    Override with _OPENLANE_MAX_CORES environment variable.

    :returns: Number of worker processes for the ProcessPoolExecutor
    """
    cpu_count = os.cpu_count() or 1
    default = int(cpu_count * 1.5)
    return int(os.getenv("_OPENLANE_MAX_CORES", default))


# Global singleton ProcessPoolExecutor
_executor: Optional[ProcessPoolExecutor] = None


def get_executor() -> ProcessPoolExecutor:
    """
    Get or create the global ProcessPoolExecutor.

    This executor is used for:
    - Async step execution (flow.start_step_async)
    - Log processing (step._run_subprocess_unix)

    Using a single executor for both operations avoids the nested executor
    deadlock that occurred with separate ThreadPoolExecutor and ProcessPoolExecutor.

    :returns: The global ProcessPoolExecutor instance
    """
    global _executor
    if _executor is None:
        _executor = ProcessPoolExecutor(max_workers=_get_worker_count())
        # Register cleanup at exit
        atexit.register(shutdown_executor)
    return _executor


def shutdown_executor(wait: bool = True) -> None:
    """
    Shutdown the global executor.

    Called automatically at program exit via atexit handler.
    Can also be called manually for testing or cleanup.

    :param wait: If True, wait for all pending jobs to complete
    """
    global _executor
    if _executor is not None:
        _executor.shutdown(wait=wait)
        _executor = None


# Compatibility shim for code that uses the old get_tpe() name
def get_tpe() -> ProcessPoolExecutor:
    """
    Deprecated: Use get_executor() instead.

    Provided for backward compatibility with code that uses the old
    ThreadPoolExecutor-based API.

    :returns: The global ProcessPoolExecutor instance
    """
    import warnings

    warnings.warn(
        "get_tpe() is deprecated and will be removed in a future version. "
        "Use get_executor() instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return get_executor()
