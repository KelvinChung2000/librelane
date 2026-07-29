# Copyright 2023 Efabless Corporation
# Copyright 2026 LibreLane Contributors
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
The flow-level exception hierarchy.

These live in ``common`` rather than in ``flows`` because ``stages`` derives
from them while ``flows`` depends on ``stages``. Defining them in
``flows.flow`` and importing them from ``stages`` initializes the ``flows``
package, which imports ``flows.staged``, which imports ``stages`` again while
it is still partway through its own module body. ``common`` sits below both, so
the dependency runs one way only.

They are re-exported from :mod:`librelane.flows` and
:mod:`librelane.flows.flow`, which remain their documented import sites.
"""


class FlowError(RuntimeError):
    """
    A ``RuntimeError`` that occurs when a Flow, or one of its underlying Steps,
    fails to finish execution properly.
    """

    pass


class FlowException(FlowError):
    """
    A variant of :class:`FlowError` for unexpected failures or failures due
    to misconfiguration, such as:

    * A :class:`StepException` raised by an underlying Step
    * Invalid inputs
    * Mis-use of class interfaces of the :class:`Flow`
    * Other unexpected failures
    """

    pass
