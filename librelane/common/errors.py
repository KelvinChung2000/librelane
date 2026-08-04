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

These live in ``common`` rather than in ``flows`` because ``jobs.job``
derives from them (``JobResolutionError``, ``JobContractError``) while
``flows.flow`` imports ``librelane.steps``, and several step modules (e.g.
``steps.innovus``) import ``jobs.job`` directly. Defining them in
``flows.flow`` instead would make importing ``jobs.job`` initialize the
``flows`` package, which imports ``steps``, which imports ``jobs.job`` again
while it is still partway through its own module body. ``common`` sits below
both, so the dependency runs one way only.

They are re-exported from :mod:`librelane.engine` and
:mod:`librelane.engine.flow`, which remain their documented import sites.

:class:`FlowSpecError` is here for the same reason one level down:
:mod:`librelane.engine.spec_include` resolves a document's ``include`` list
*before* a :class:`librelane.engine.spec.FlowSpec` exists to be validated, so
``spec`` imports it rather than the other way round, and neither can own the
error both raise. It is re-exported from :mod:`librelane.engine.spec`, which
remains its documented import site.
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


class FlowSpecError(FlowError):
    """
    Raised when a workflow document is malformed. Every instance names the
    offending job or key and the legal alternatives, and is raised before a run
    directory is created.
    """

    pass
