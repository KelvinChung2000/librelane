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
"""The :class:`Job` dataclass, its factory, and the shared contract constants."""

import builtins
from dataclasses import dataclass, field
from typing import ClassVar

from librelane.common.errors import FlowError
from librelane.state import DesignFormat


class JobDefinitionError(RuntimeError):
    """
    Raised when a job or a job registration is itself malformed. This is a
    programming error in a provider package and surfaces at import time.
    """


class JobResolutionError(FlowError):
    """
    Raised when a configuration cannot be resolved to a concrete step list:
    an unknown provider, an inconsistent span selection, a missing PDK
    variable, or an unsatisfiable view dependency.
    """


class JobContractError(FlowError):
    """
    Raised at runtime when a job completes without having produced every
    view or metric it declared.
    """


class JobMetaclass(type):
    def __getattr__(Self, key: str):
        job = Self.factory.get(key)
        if job is not None:
            return job
        raise AttributeError("Unknown Job attribute", key, Self)


@dataclass(frozen=True)
class Job(metaclass=JobMetaclass):
    """
    A named phase of a flow. A job is the unit of tool substitution and of
    independent gating. It never executes anything: a provider registration
    binds it to a sequence of concrete steps.

    Parameters
    ----------
    id : str
        A lowercase alphanumeric/underscore identifier, for example
        ``detailed_routing``. This is what appears in the ``TOOLS``
        configuration key, and what ``--target``, ``--invalidate`` and
        ``--skip`` name on the command line. ``--reproducible`` is the one that
        addresses a concrete step rather than a job.

        A workflow document gives each job its own id, which is not always the
        id of the template it uses: ``classic.yaml`` runs the ``streamout``
        template under ``magic_streamout`` and ``klayout_streamout``, and it is
        the document's names that all four options take.
    full_name : str
        A human-readable name.
    default_provider : str | None
        The provider a document's bare ``uses`` selects, and the one a
        ``uses: job/provider`` or a ``TOOLS`` entry overrides. Exactly one,
        because one job runs one tool: a phase a flow wants to run under two
        tools is two jobs in the document, as ``classic.yaml`` does for
        ``streamout`` and ``drc``.

        ``None`` is for a phase the taxonomy names but no provider package
        implements yet. A document cannot declare such a job at all -- a bare
        ``uses`` has no default to take and a named one matches no
        registration -- and load-time validation says so by name.
    requires : tuple[DesignFormat, ...]
        The neutral views the job consumes at its boundary.
        A provider may additionally consume its own native views, declared on
        the registration.
    provides : tuple[DesignFormat, ...]
        The neutral views every provider of this job must have
        produced by the time the job completes. Enforced at runtime.
    metrics : tuple[str, ...]
        The metric names every provider of this job must have
        produced by the time it completes. Enforced at runtime.
    """

    id: str
    full_name: str
    default_provider: str | None
    requires: tuple[DesignFormat, ...]
    provides: tuple[DesignFormat, ...]
    metrics: tuple[str, ...] = field(default=())

    def __hash__(self):
        return hash(self.id)

    def __str__(self) -> str:
        return self.id

    def register(self) -> "Job":
        """
        Adds this job to the registry. Raises :class:`JobDefinitionError` if a
        job with the same id is already registered.
        """
        self.__class__.factory.register(self)
        return self

    class JobFactory(object):
        """
        A factory singleton for Jobs, allowing them to be registered and
        then retrieved by a string id.
        """

        _registry: ClassVar[dict[str, "Job"]] = {}

        @classmethod
        def register(Self, job: "Job") -> "Job":
            if job.id in Self._registry:
                raise JobDefinitionError(f"Job '{job.id}' is already registered.")
            Self._registry[job.id] = job
            return job

        @classmethod
        def get(Self, id: str) -> "Job | None":
            return Self._registry.get(id)

        @classmethod
        def list(Self) -> builtins.list[str]:
            return list(Self._registry.keys())

    factory: ClassVar = JobFactory


#: The view contract shared by every in-place place-and-route transform: a
#: job that takes a placed-or-routed design and returns one, changing the
#: layout but not the set of views. Declared once and reused rather than
#: restated on each of the fifteen jobs that share it.
PNR_IN_PLACE_REQUIRES: tuple[DesignFormat, ...] = (
    DesignFormat.def_,
    DesignFormat.nl,
    DesignFormat.sdc,
)

PNR_IN_PLACE_PROVIDES: tuple[DesignFormat, ...] = (
    DesignFormat.def_,
    DesignFormat.nl,
    DesignFormat.sdc,
)
