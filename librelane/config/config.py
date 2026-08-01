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
from loguru import logger

import os
import json
import yaml
import dataclasses
from glob import glob
from textwrap import dedent
from functools import lru_cache
from dataclasses import dataclass
from typing import (
    Any,
    ClassVar,
    Literal,
    Union,
    Optional,
)
from collections.abc import Mapping, Sequence
from types import MappingProxyType

from librelane.config.legacy import Variable, MissingRequiredVariable
from librelane.config.diagnostics import Diagnostic, DiagnosticSet, Severity
from librelane.config.loading import (
    ConfigSource,
    OpenLaneYAMLLoader,
    layer_mappings,
    read_source,
)
from librelane.config.removals import removed_variables
from librelane.config.flow import (
    pdk_variables,
    scl_variables,
    pad_variables,
    flow_common_variables,
)
from librelane.config.pdk_compat import migrate_old_config
from librelane.config.preprocessor import preprocess_dict, Keys as SpecialKeys
from librelane.config.validation import translate_deprecated_names, validate_mapping
from librelane.__version__ import __version__
from librelane.common import (
    GenericDict,
    GenericImmutableDict,
    TclUtils,
    AnyPath,
    is_string_like,
)

AnyConfig = Union[AnyPath, Mapping[str, Any]]
AnyConfigs = Union[AnyConfig, Sequence[AnyConfig]]


# Moved to config.loading.sources, which is where read_source needs it and
# which this module already imports. Aliased because it is referenced by name
# throughout this file.
_OpenLaneYAMLLoader = OpenLaneYAMLLoader


class UnknownExtensionError(ValueError):
    """
    When a passed configuration file has an unrecognized extension, i.e.,
    not .json, .yml/.yaml or .tcl.
    """

    def __init__(self, config: AnyPath) -> None:
        self.config = str(config)
        _, ext = os.path.splitext(config)
        super().__init__(
            f"Unsupported configuration file extension '{ext}' for '{config}'."
        )


class PassedDirectoryError(ValueError):
    """
    When a passed configuration file is in fact a directory.
    """

    def __init__(self, config: AnyPath) -> None:
        self.config = str(config)
        super().__init__(
            "Passing design directories as arguments is unsupported in LibreLane: please pass the configuration file(s) directly."
        )


def _validate_config_file(config: AnyPath) -> Literal["json", "tcl", "yaml"]:
    config = str(config)
    if config.endswith(".tcl"):
        return "tcl"
    elif config.endswith(".json"):
        return "json"
    elif config.endswith(".yml") or config.endswith(".yaml"):
        return "yaml"
    elif os.path.isdir(config):
        raise PassedDirectoryError(config)
    else:
        raise UnknownExtensionError(config)


def _follow_renames(
    provenance: dict[str, str],
    translated_from: Mapping[str, str],
) -> None:
    """
    Moves a renamed key's origin onto the name it was renamed to, in place.

    Parameters
    ----------
    provenance : dict[str, str]
        The map to update.
    translated_from : Mapping[str, str]
        Each current name mapped to the name whose value it took.

    A rename moves the value, so the origin has to move with it: the value under
    the current name is there *because* some layer wrote the old one. Leaving
    the origin behind does not merely lose it. Whatever wrote the current name
    earlier -- typically the PDK, which supplies a value for every PDK variable
    -- is left claiming a value the design overrode, and naming a real layer
    that did not supply the value is harder to disbelieve than naming none.

    A name no layer wrote has no origin to move, and none is invented for it.
    """
    for current, previous in translated_from.items():
        if previous in provenance:
            provenance[current] = provenance[previous]


def _written_by(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    name: str,
) -> dict[str, str]:
    """
    Parameters
    ----------
    before : Mapping[str, Any]
        The environment a configuration file was evaluated against.
    after : Mapping[str, Any]
        The environment it produced.
    name : str
        What to attribute the keys it wrote to.

    Returns
    -------
    dict[str, str]
        Every key the file introduced or changed, mapped to ``name``. A key it
        left alone is not its, so it is left to whichever layer did write it.
    """
    return {
        key: name
        for key, value in after.items()
        if key not in before or before[key] != value
    }


class InvalidConfig(ValueError):
    """
    An error raised when a configuration under resolution is invalid.

    Parameters
    ----------
    config : str
        A human-readable name for the particular configuration file
        causing this exception, i.e. whether it's a PDK configuration file or a
        user configuration file.
    warnings : list[str]
        A list of warnings generated during the loading of this
        configuration file.
    errors : list[str]
        A list of errors generated during the loading of this
        configuration file.
    args
        Further arguments to be passed onto the constructor of
        :class:`ValueError`.
    message : str | None
        An optional override for the Exception message.
    kwargs
        Further keyword arguments to be passed onto the constructor of
        :class:`ValueError`.
    """

    def __init__(
        self,
        config: str,
        warnings: list[str],
        errors: list[str],
        message: str | None = None,
        *args,
        **kwargs,
    ) -> None:
        self.config = config
        self.warnings = warnings
        self.errors = errors
        if message is None:
            message = "The following errors were encountered: \n"
            for error in self.errors:
                message += f"\t* {error}\n"
            message = message.strip()
        super().__init__(message, *args, **kwargs)


@dataclass
class Meta:
    """
    Constitutes metadata for a configuration object.
    """

    version: int = 1
    flow: None | str = None
    step: None | str = None
    librelane_version: None | str = __version__

    @classmethod
    def from_dict(Self, meta_dict: dict):
        meta_dict_copy = meta_dict.copy()
        if "openlane_version" in meta_dict_copy:
            meta_dict_copy["librelane_version"] = meta_dict_copy["openlane_version"]
            del meta_dict_copy["openlane_version"]
        return Self(**meta_dict_copy)

    def copy(self) -> "Meta":
        return dataclasses.replace(self)


#: The source name given to a value handed straight to a ``Config``
#: constructor through the Python API -- :meth:`Config.copy`,
#: :meth:`Config.interactive` or :meth:`Config.with_increment` -- rather than
#: written by a configuration file, a PDK, a flow document or the command line.
#: Named rather than left out of the map, because absence is how ``default`` is
#: spelled and a value somebody passed in is not a default.
_API_OVERRIDE = "<override>"


class Config(GenericImmutableDict[str, Any]):
    """
    A map from LibreLane configuration variable keys to their values.

    It is recommended that you use :meth:`load` to create new, validated
    configurations from dictionaries or files.

    Parameters
    ----------
    meta : Meta | None
        The :class:`Meta` object for this configuration. If ``None`` is
        passed, the default Meta object will be assigned.
    diagnostics : DiagnosticSet | None
        The warnings and errors raised while this configuration was
        assembled.
    provenance : Mapping[str, str] | None
        The source that last wrote each key. See :attr:`provenance`.
    final
        Whether the configuration is final (i.e. has been
        pre-assembled for an entire flow) or may be incremented per-step.

        Final configurations may not be adjusted or incremented.
    """

    current_interactive: ClassVar[Optional["Config"]] = None
    meta: Meta

    def __init__(
        self,
        *args,
        meta: Meta | None = None,
        diagnostics: DiagnosticSet | None = None,
        provenance: Mapping[str, str] | None = None,
        **kwargs,
    ):
        if meta is None:
            meta = Meta(version=1)

        self.meta = meta
        self.diagnostics = diagnostics or DiagnosticSet()
        self.__provenance: Mapping[str, str] = MappingProxyType(dict(provenance or {}))

        super().__init__(*args, **kwargs)

    @property
    def provenance(self) -> Mapping[str, str]:
        """
        Returns
        -------
        Mapping[str, str]
            The name of the source that last wrote each key. A design
            configuration file is named by its path, and the layers that have
            no path are named ``<mapping>``, ``<pdk>``, ``<scl>``, ``<pad>``,
            ``<flow document>``, ``<flow document: {job id}>``,
            ``<command line>`` and ``<override>``, that last one for a value
            handed straight to a constructor through the Python API.

            Keys no source wrote are absent, which is what makes their origin
            ``default``.
        """
        return self.__provenance

    def copy(self, **overrides) -> "Config":
        """
        Produces a *shallow* copy of the configuration object.

        Parameters
        ----------
        overrides
            A series of configuration overrides as key-value pairs.
            These values are NOT validated and you should not be overriding these
            haphazardly.
        """
        return Config(
            self,
            meta=self.meta,
            diagnostics=self.diagnostics,
            # An overridden key's old source did not write the value this copy
            # carries, so keeping its name would attribute one layer's value to
            # another.
            provenance={
                **self.provenance,
                **{key: _API_OVERRIDE for key in overrides},
            },
            overrides=overrides,
        )

    def to_raw_dict(self, include_meta: bool = True) -> dict[str, Any]:
        """
        Parameters
        ----------
        include_meta : bool
            Whether to include the "meta" object or not

        Returns
        -------
        dict[str, Any]
            A raw dictionary representation including the ``meta`` object.
        """
        final = super().to_raw_dict()
        if include_meta:
            final["meta"] = self.meta
        return final

    def dumps(self, include_meta: bool = True, **kwargs) -> str:
        """
        Parameters
        ----------
        include_meta : bool
            Whether to include the ``meta`` object in the
            serialized string.
        kwargs
            Passed to ``json.dumps``.

        Returns
        -------
        str
            A JSON string representing the the GenericDict object.
        """
        if "indent" not in kwargs:
            kwargs["indent"] = 4
        return json.dumps(
            self.to_raw_dict(include_meta), cls=self.get_encoder(), **kwargs
        )

    def copy_filtered(
        self,
        config_vars: Sequence[Variable],
        include_flow_variables: bool = True,
    ) -> "Config":
        """
        Creates a new copy of the configuration object, but only with the
        configuration variables defined by the parameter.

        Parameters
        ----------
        config_vars : Sequence[Variable]
            A list of configuration variables to include in
            the filtered copy.
        include_flow_variables : bool
            Whether to include the common flow
            variables in the copy or not.

            This parameter is deprecated as of LibreLane 2.0.0b5 and should be
            set to ``False`` by callers.

        Returns
        -------
        Config
            The new copy
        """
        variables: set[str] = set([variable.name for variable in config_vars])
        if include_flow_variables:
            variables = variables.union(
                set([variable.name for variable in flow_common_variables])
            )

        return Config(
            {variable: self[variable] for variable in variables},
            meta=dataclasses.replace(self.meta),
            diagnostics=self.diagnostics,
            provenance={
                variable: source
                for variable, source in self.provenance.items()
                if variable in variables
            },
        )

    def with_increment(
        self,
        config_vars: Sequence[Variable],
        other_inputs: Mapping[str, Any],
        config_quiet: bool = False,
    ) -> "Config":
        """
        Creates a new ``Config`` object by copying all values
        from the original in addition to any new variables (and removing
        any variables not in `config_vars`).

        Furthermore, inputs can be provided incrementally by passing the object
        ``other_inputs``, which will also use these as overrides to the
        values in the base ``Config`` object.

        All values, including those in the base ``Config`` object and in
        ``other_inputs``, will be re-validated.

        Parameters
        ----------
        config_vars : Sequence[Variable]
            A list of configuration variables to include and
            validate.
        other_inputs : Mapping[str, Any]
            A mapping of other inputs.

        Returns
        -------
        Config
            The new ``Config`` object
        """
        incremental_pdk_vars = [variable for variable in config_vars if variable.pdk]

        mutable, _, _, _, pdk_provenance = self.__get_pdk_config(
            self["PDK"],
            self["STD_CELL_LIBRARY"],
            self.get("PAD_CELL_LIBRARY", None),
            self["PDK_ROOT"],
            incremental_pdk_vars,
        )

        mutable.update(self)
        mutable.update(other_inputs)

        processed, design_warnings, design_errors, renames = (
            Config.__process_variable_list(
                mutable,
                config_vars,
                removed_variables,
                on_unknown_key=None,
            )
        )

        if len(design_errors) != 0:
            raise InvalidConfig(
                "incremental configuration", design_warnings, design_errors
            )

        diagnostics = DiagnosticSet(self.diagnostics)
        if not config_quiet:
            diagnostics.extend(
                Diagnostic(Severity.WARNING, "incremental", warning)
                for warning in design_warnings
            )
        # In the order the three mappings are layered above: the incremental
        # PDK variables first, then everything this configuration already
        # carried, then the step's own inputs.
        provenance = {
            **pdk_provenance,
            **self.provenance,
            **{key: _API_OVERRIDE for key in other_inputs},
        }
        # 'other_inputs' may name a variable by one of its deprecated names,
        # in which case its value outranks the one this configuration already
        # carries under the current name and its origin has to follow it.
        _follow_renames(provenance, renames)
        return Config(
            processed,
            meta=self.meta.copy(),
            diagnostics=diagnostics,
            provenance=provenance,
        )

    @classmethod
    def get_meta(
        Self,
        config_in: AnyConfig,
        flow_override: str | None = None,
    ) -> Meta:
        """
        Returns the Meta object of a configuration dictionary or file.

        Parameters
        ----------
        config_in : AnyConfig
            A configuration object or file.

        Returns
        -------
        Meta
            Either a Meta object, or if the file is invalid, None.
        """
        default_meta_version = 2

        if is_string_like(config_in):
            config_in = str(config_in)
            validated_type = _validate_config_file(config_in)
            if validated_type == "tcl":
                default_meta_version = 1
                return Meta(version=default_meta_version)
            elif validated_type == "json":
                default_meta_version = 1
                config_in = json.load(open(config_in, encoding="utf8"))
            elif validated_type == "yaml":
                config_in = yaml.load(
                    open(config_in, encoding="utf8"),
                    Loader=_OpenLaneYAMLLoader,
                )

        assert not isinstance(config_in, str)
        assert not isinstance(config_in, os.PathLike)

        meta = Meta(version=default_meta_version)
        if meta_raw := config_in.get("meta"):
            meta = Meta.from_dict(meta_raw)

        if flow_override is not None:
            meta.flow = flow_override

        return meta

    @classmethod
    def interactive(
        Self,
        DESIGN_NAME: str,
        PDK: str,
        STD_CELL_LIBRARY: str | None = None,
        PAD_CELL_LIBRARY: str | None = None,
        PDK_ROOT: str | None = None,
        **kwargs,
    ) -> "Config":
        """
        This constructs a partial configuration object that may be incrementally
        adjusted per-step, and activates LibreLane's **interactive mode**.

        The interactive mode is overall less rigid than the pure mode, adding various
        references to global objects to make the REPL or Notebook experience more
        pleasant, however, it is not as resilient as the pure mode and should not
        be used in production code.

        Parameters
        ----------
        DESIGN_NAME : str
            The name of the design to be used.
        PDK : str
            The name of the PDK.
        STD_CELL_LIBRARY : str | None
            The name of the standard cell library.
        PAD_CELL_LIBRARY : str | None
            The name of the pad cell library.

            If not specified, the PDK's default SCL will be used.
        PDK_ROOT : str | None
            Required if Volare is not installed.

            If Volare is installed, this value can be used to optionally override
            Volare's default.
        kwargs
            Any overrides to PDK values and/or common flow default variables
            can be passed as keyword arguments to this function.

            Useful examples are CLOCK_PORT, CLOCK_PERIOD, et cetera, which while
            not bound to a specific :class:`Step`, affects most Steps' behavior.
        """
        PDK_ROOT = Self.__resolve_pdk_root(PDK_ROOT)

        raw, _, _, _, pdk_provenance = Self.__get_pdk_config(
            PDK,
            STD_CELL_LIBRARY,
            PAD_CELL_LIBRARY,
            PDK_ROOT,
            pdk_variables + scl_variables + pad_variables,
        )

        kwargs["DESIGN_NAME"] = DESIGN_NAME
        kwargs["DESIGN_DIR"] = kwargs.get("DESIGN_DIR", ".")

        raw.update(kwargs)

        processed, design_warnings, design_errors, renames = (
            Config.__process_variable_list(
                raw,
                flow_common_variables,
                removed_variables,
                on_unknown_key="error",
            )
        )

        if len(design_errors) != 0:
            raise InvalidConfig("default configuration", design_warnings, design_errors)

        if len(design_warnings) > 0:
            logger.info(
                "Loading the default configuration has generated the following warnings:"
            )
        for warning in design_warnings:
            logger.warning(warning)

        provenance = {
            **pdk_provenance,
            **{key: _API_OVERRIDE for key in kwargs},
        }
        # A keyword argument may name a variable by one of its deprecated
        # names, in which case it, and not the PDK's value under the current
        # name, is what 'compile' took.
        _follow_renames(provenance, renames)
        Config.current_interactive = Config(
            processed,
            provenance=provenance,
        )

        return Config.current_interactive

    @classmethod
    def load(
        Self,
        config_in: AnyConfigs,
        flow_config_vars: Sequence[Variable],
        *,
        flow_values: Mapping[str, Any] | None = None,
        job_values: tuple[str, Mapping[str, Any]] | None = None,
        config_override_strings: Sequence[str] | None = None,
        pdk: str | None = None,
        pdk_root: str | None = None,
        scl: str | None = None,
        pad: str | None = None,
        design_dir: str | None = None,
        _load_pdk_configs: bool = True,
    ) -> tuple["Config", str]:
        """
        Creates a new Config object based on a Tcl file, a JSON file, or a
        dictionary.

        The returned config object is locked and cannot be modified.

        Parameters
        ----------
        config_in : AnyConfigs
            Either a file path to a JSON file or a Python
            Mapping object (such as ``dict``) representing an unprocessed
            LibreLane configuration object.

            Tcl files are also supported, but are deprecated and will be removed
            in the future.
        flow_values : Mapping[str, Any] | None
            Values a flow supplies for configuration variables, from the
            top-level ``with`` block of a workflow document. They layer *under*
            the design configuration and *over* the PDK and the SCL, so a
            design always wins and a document always beats a PDK default.
        job_values : tuple[str, Mapping[str, Any]] | None
            A job id and the values that job's own ``with`` block supplies.
            Layered over ``flow_values``, so a job overrides the document and
            anything the job is silent about still comes from the document.

            The two are separate sources rather than one merged mapping
            because each key is attributed to whichever of them wrote it: a
            document-level value that reached this job unchanged must not be
            reported, in diagnostics or by ``--explain``, as something the job
            asked for. The id and the values are one argument because the
            attribution *is* the id, and two arguments could name a different
            job than they carried.
        config_override_strings : Sequence[str] | None
            A list of "overrides" in the form of
            NAME=VALUE strings. These are primarily for running LibreLane from
            the command-line and strictly speaking should not be used in the API.
        design_dir : str | None
            The design directory for said configuration(s).

            If not explicitly provided, the design directory will be the
            directory holding the last file in the list.

            If no files are provided, this argument is required.
        pdk : str | None
            A process design kit to use. Required unless specified via the
            "PDK" key in a configuration object.
        pdk_root : str | None
            Required if Volare is not installed.

            If Volare is installed, this value can be used to optionally override
            Volare's default.
        scl : str | None
            A standard cell library to use. If not specified, the PDK's
            default standard cell library will be used instead.
        pad : str | None
            A pad cell library to use. If not specified, the PDK's
            pad standard cell library will be used instead (if it exists).

        Returns
        -------
        tuple[Config, str]
            A tuple containing a Config object and the design directory.
        """
        if isinstance(config_in, Mapping):
            config_in = [config_in]
        elif is_string_like(config_in):
            config_in = [str(config_in)]

        assert not isinstance(config_in, str)
        assert not isinstance(config_in, os.PathLike)

        if len(config_in) == 0:
            raise ValueError("The value for config_in must not be empty.")

        file_design_dir = None
        configs_validated: list[AnyConfig] = []
        for config in config_in:
            if isinstance(config, Mapping):
                configs_validated.append(config)
            # Path
            else:
                config = str(config)
                _validate_config_file(config)
                config_abspath = os.path.abspath(config)
                file_design_dir = os.path.dirname(config_abspath)
                configs_validated.append(config_abspath)

        design_dir = design_dir or file_design_dir
        if design_dir is None:
            raise ValueError(
                "The design_dir argument is required when configuration dictionaries are used."
            )

        sources: list[ConfigSource] = []
        if flow_values is not None:
            # First, so that every design source layered after it wins. Not
            # folded into configs_validated: that loop also computes 'meta' and
            # 'file_design_dir', and a document is neither a design directory
            # nor a source of meta.
            sources.append(
                ConfigSource(dict(flow_values), "<flow document>", "mapping")
            )
        if job_values is not None:
            job_id, values = job_values
            sources.append(
                ConfigSource(dict(values), f"<flow document: {job_id}>", "mapping")
            )
        meta = Meta()
        for config_validated in configs_validated:
            try:
                meta = Self.get_meta(config_validated)
            except TypeError as e:
                identifier = "configuration dict"
                if is_string_like(config_validated):
                    identifier = os.path.relpath(str(config_validated))
                raise InvalidConfig(identifier, [], [f"'meta' object is invalid: {e}"])

            mapping = None
            source_name = "<mapping>"
            source_kind = "mapping"
            if isinstance(config_validated, Mapping):
                mapping = config_validated
            elif isinstance(config_validated, str):
                validated_type = _validate_config_file(config_validated)
                source_name = config_validated
                source_kind = validated_type
                if validated_type == "tcl":
                    mapping = Self.__mapping_from_tcl(
                        config_validated,
                        design_dir,
                        pdk_root=pdk_root,
                        pdk=pdk,
                        scl=scl,
                        pad=pad,
                    )
                else:
                    source = read_source(
                        config_validated,
                        yaml_loader=_OpenLaneYAMLLoader,
                    )
                    mapping = source.mapping

            assert mapping is not None, "Invalid validated config"
            sources.append(
                ConfigSource(
                    mapping,
                    source_name,
                    source_kind,  # type: ignore
                )
            )

        layered = layer_mappings(sources)
        mutable = GenericDict(layered.mapping)
        provenance = dict(layered.provenance)
        config_override_strings = config_override_strings or []
        permissive_keys = {
            key for source in sources if source.kind == "tcl" for key in source.mapping
        }
        for string in config_override_strings:
            key, value = string.split("=", 1)
            mutable[key] = value
            provenance[key] = "<command line>"
            permissive_keys.add(key)

        config_obj = Self.__load_dict(
            mutable,
            design_dir,
            flow_config_vars=flow_config_vars,
            pdk_root=pdk_root,
            pdk=pdk,
            scl=scl,
            pad=pad,
            meta=meta,
            permissive_typing=meta.version < 2,
            permissive_keys=frozenset(permissive_keys),
            provenance=provenance,
            _load_pdk_configs=_load_pdk_configs,
        )

        return (config_obj, design_dir)

    ## For Jupyter
    def _repr_markdown_(self) -> str:  # pragma: no cover
        title = (
            "Interactive Configuration"
            if self == Config.current_interactive
            else "Configuration"
        )
        values_title = (
            "Initial Values" if self == Config.current_interactive else "Values"
        )
        return dedent(
            f"""
                ### {title}
                #### {values_title}

                <br />

                ```yaml
                %s
                ```
                """
        ) % yaml.safe_dump(json.loads(self.dumps()))

    ## Private Methods
    @classmethod
    def __load_dict(
        Self,
        mapping_in: Mapping[str, Any],
        design_dir: str,
        flow_config_vars: Sequence[Variable],
        *,
        meta: Meta,
        pdk_root: str | None = None,
        pdk: str | None = None,
        scl: str | None = None,
        pad: str | None = None,
        full_pdk_warnings: bool = False,
        permissive_typing: bool = False,
        permissive_keys: frozenset[str] = frozenset(),
        provenance: Mapping[str, str] | None = None,
        _load_pdk_configs: bool = True,
    ) -> "Config":
        raw = dict(mapping_in)

        if "meta" in raw:
            del raw["meta"]

        flow_pdk_vars = []
        for variable in flow_config_vars:
            if variable.pdk:
                flow_pdk_vars.append(variable)

        mutable = GenericDict(
            preprocess_dict(
                raw,
                only_extract_process_info=True,
                design_dir=design_dir,
            )
        )

        pdk = mutable.get(SpecialKeys.pdk) or pdk
        scl = mutable.get(SpecialKeys.scl) or scl
        pad = mutable.get(SpecialKeys.pad) or pad
        pdkpath = ""

        mutable["PDK_ROOT"] = pdk_root

        if _load_pdk_configs:
            pdk_root = Self.__resolve_pdk_root(pdk_root)
            if pdk is None:
                raise ValueError(
                    "The pdk argument is required as the configuration object lacks a 'PDK' key."
                )

            mutable, pdkpath, scl, pad, pdk_provenance = Self.__get_pdk_config(
                pdk=pdk,
                scl=scl,
                pad=pad,
                pdk_root=pdk_root,
                full_pdk_warnings=full_pdk_warnings,
                flow_pdk_vars=flow_pdk_vars,
            )
            # Under the caller's map, because 'mutable.update(design_values)'
            # below layers the design over the PDK and the attribution has to
            # follow the value. A key only the PDK wrote keeps '<pdk>'.
            provenance = {**pdk_provenance, **(provenance or {})}
        else:
            if pdk_root is not None:
                pdkpath = os.path.join(pdk_root, mutable["PDK"])

        design_values, deprecations, design_renames = translate_deprecated_names(
            preprocess_dict(
                raw,
                pdk=pdk,
                pdkpath=pdkpath,
                scl=mutable[SpecialKeys.scl],
                pad=mutable.get(SpecialKeys.pad, None),
                design_dir=design_dir,
            ),
            list(flow_config_vars),
        )
        mutable.update(design_values)
        # Before validate_mapping rather than after, so a diagnostic about a
        # renamed key names the layer that actually wrote it too.
        provenance = dict(provenance or {})
        _follow_renames(provenance, design_renames)

        processed, diagnostics, merged_renames = validate_mapping(
            mutable,
            list(flow_config_vars),
            permissive=permissive_typing,
            permissive_keys=permissive_keys,
            on_unknown_key="warn" if permissive_typing else "error",
            provenance=provenance,
            removed=removed_variables,
        )
        diagnostics.extend(deprecations)
        # validate_mapping runs two more migrations of its own, on the merged
        # mapping and so out of reach of the call above: the deprecated names a
        # layer other than the design wrote, and DIODE_INSERTION_STRATEGY, which
        # becomes three keys.
        _follow_renames(provenance, merged_renames)
        # Every key of the resolved configuration and no others. A key the
        # migrations consumed is gone from 'processed' and an entry for it here
        # would describe nothing the caller can look up. This runs after the
        # renames are followed, so it can no longer drop the origin of a value
        # that survived under another name.
        provenance = {
            key: origin for key, origin in provenance.items() if key in processed
        }

        if diagnostics.errors():
            raise InvalidConfig(
                "design configuration file",
                diagnostics.rendered_warnings(),
                diagnostics.rendered_errors(),
            )

        return Config(
            processed, meta=meta, diagnostics=diagnostics, provenance=provenance
        )

    @classmethod
    def __mapping_from_tcl(
        Self,
        config: AnyPath,
        design_dir: str,
        *,
        pdk_root: str | None = None,
        pdk: str | None = None,
        scl: str | None = None,
        pad: str | None = None,
    ) -> Mapping[str, Any]:
        config_str = open(config, encoding="utf8").read()

        logger.warning(
            "Support for .tcl configuration files is deprecated. Please migrate to a .json file at your earliest convenience."
        )

        pdk_root = Self.__resolve_pdk_root(pdk_root)

        tcl_vars_in = GenericDict(
            {
                SpecialKeys.pdk_root: pdk_root,
                SpecialKeys.pdk: pdk,
            }
        )
        tcl_vars_in[SpecialKeys.scl] = ""
        tcl_vars_in[SpecialKeys.pad] = ""
        tcl_vars_in[SpecialKeys.design_dir] = design_dir
        tcl_config = GenericDict(TclUtils._eval_env(tcl_vars_in, config_str))

        process_info = preprocess_dict(
            tcl_config,
            only_extract_process_info=True,
            design_dir=design_dir,
        )

        pdk = process_info.get(SpecialKeys.pdk) or pdk

        if pdk is None:
            raise ValueError(
                "The pdk argument is required as the configuration object lacks a 'PDK' key."
            )

        _, _, scl, pad, _ = Self.__get_pdk_config(
            pdk=pdk,
            scl=scl,
            pad=pad,
            pdk_root=pdk_root,
            full_pdk_warnings=False,
        )

        tcl_vars_in[SpecialKeys.pdk] = pdk
        tcl_vars_in[SpecialKeys.scl] = scl
        tcl_vars_in[SpecialKeys.pad] = pad
        tcl_vars_in[SpecialKeys.design_dir] = design_dir

        tcl_mapping = GenericDict(TclUtils._eval_env(tcl_vars_in, config_str))

        return tcl_mapping

    @classmethod
    def __resolve_pdk_root(
        Self,
        pdk_root: str | None,
    ) -> str:
        if pdk_root is None:
            try:
                import ciel

                pdk_root = ciel.get_ciel_home(pdk_root)
            except ImportError:
                raise ValueError(
                    "The pdk_root argument is required as Ciel is not installed."
                )

        return os.path.abspath(pdk_root)

    @staticmethod
    @lru_cache(1, True)
    def __get_pdk_raw(
        pdk_root: str, pdk: str, scl: str | None, pad: str | None
    ) -> tuple[GenericImmutableDict[str, Any], str, str, str | None, dict[str, str]]:
        """
        Returns
        -------
        tuple[GenericImmutableDict[str, Any], str, str, str | None, dict[str, str]]
            The merged PDK environment, the PDK path, the SCL, the pad cell
            library, and a map from each key of the environment to the layer
            that last wrote it.

            Every key of the returned environment has an entry. The map is keyed
            by the names the *migrated* environment uses, which are the names the
            configuration ends up with, and not by the names the ``.tcl`` files
            wrote -- see the comment on the comparison below.

        The origin map is memoized along with everything else here, so callers
        read it and never mutate it.
        """
        pdk_config: GenericDict[str, Any] = GenericDict(
            {
                SpecialKeys.pdk_root: pdk_root,
                SpecialKeys.pdk: pdk,
            }
        )

        if scl is not None:
            pdk_config[SpecialKeys.scl] = scl

            # HACK: Prevent loading default SCL cfg vars for old openlane PDK
            # configs
            # For more info: https://github.com/librelane/librelane/issues/932
            pdk_config["STD_CELL_LIBRARY_OPT"] = scl

        if pad is not None:
            pdk_config[SpecialKeys.pad] = pad

        pdkpath = os.path.join(pdk_root, pdk)
        if not os.path.exists(pdkpath):
            matches = sorted(glob(f"{pdkpath}*"))
            errors = [f"The PDK {pdk} was not found."]
            warnings = []
            for match in matches:
                basename = os.path.basename(match)
                warnings.append(f"A similarly-named PDK was found: {basename}")
            raise InvalidConfig("PDK configuration", warnings, errors)

        pdk_config_path = os.path.join(pdkpath, "libs.tech", "librelane", "config.tcl")
        if not os.path.exists(pdk_config_path):
            pdk_config_path_alt = os.path.join(
                pdkpath, "libs.tech", "openlane", "config.tcl"
            )
            if not os.path.exists(pdk_config_path_alt):
                raise InvalidConfig(
                    "PDk configuration",
                    [],
                    [
                        f"Neither '{pdk_config_path}' nor '{pdk_config_path_alt} were found.'"
                    ],
                )
            pdk_config_path = pdk_config_path_alt

        pdk_env = TclUtils._eval_env(
            pdk_config,
            open(pdk_config_path, encoding="utf8").read(),
        )

        scl = pdk_env.get("STD_CELL_LIBRARY", None)
        assert scl is not None, (
            "Fatal error: STD_CELL_LIBRARY default value not set by PDK."
        )

        scl_config_path = os.path.join(
            pdkpath, "libs.tech", "librelane", scl, "config.tcl"
        )
        if not os.path.exists(scl_config_path):
            scl_config_path_alt = os.path.join(
                pdkpath, "libs.tech", "openlane", scl, "config.tcl"
            )
            if not os.path.exists(scl_config_path_alt):
                raise InvalidConfig(
                    "PDK configuration",
                    [],
                    [
                        f"Neither '{scl_config_path}' nor '{scl_config_path_alt} were found.'"
                    ],
                )
            scl_config_path = scl_config_path_alt

        # Every layer is attributed in migrated form, never raw. migrate_old_config
        # renames TECH_LEF to TECH_LEFS, SYNTH_TIEHI_PORT to SYNTH_TIEHI_CELL and
        # four more besides, and synthesises CELL_VERILOG_MODELS and its siblings
        # out of the PDK tree, so a key recorded under the name a '.tcl' file used
        # describes nothing that reaches the configuration. Attributing the raw
        # names and dropping the ones that did not survive left TECH_LEFS with no
        # entry at all, which reads as 'default' -- and every openlane-era PDK
        # reaches that rename, which is why the migration exists.
        #
        # Comparing migrated environments credits a renamed key to the layer whose
        # file supplied its input, which is the question being asked. The
        # alternative, flooring whatever is left to '<pdk>', would be wrong for
        # SYNTH_TIEHI_CELL: sky130A writes SYNTH_TIEHI_PORT in the standard cell
        # library's file, not the PDK's.
        #
        # migrate_old_config is idempotent -- every branch of it is guarded on the
        # old name still being present, or on the new one being absent -- so
        # migrating a layer that a later one migrates again is safe, which the pad
        # branch below already relied on.
        migrated_pdk_env = migrate_old_config(pdk_env)

        # Every key the process selection and the PDK's own file put in scope.
        # The seed keys -- PDK, PDK_ROOT and, when it was named rather than
        # defaulted, STD_CELL_LIBRARY -- are attributed to the PDK layer too,
        # because '<pdk>' names the layer and not the file.
        origins: dict[str, str] = dict.fromkeys(migrated_pdk_env, "<pdk>")

        # Evaluated against the raw environment, not the migrated one: the SCL's
        # file is written against the names the PDK's file used, and handing it
        # renamed keys would change what it reads.
        scl_env = TclUtils._eval_env(
            pdk_env,
            open(scl_config_path, encoding="utf8").read(),
        )
        full_env = migrate_old_config(scl_env)
        origins.update(_written_by(migrated_pdk_env, full_env, "<scl>"))

        pad = pdk_env.get("PAD_CELL_LIBRARY", None)

        if pad is not None:
            pad_config_path = os.path.join(
                pdkpath, "libs.tech", "librelane", pad, "config.tcl"
            )
            if not os.path.exists(pad_config_path):
                raise InvalidConfig(
                    "PDK configuration",
                    [],
                    [f"'{pad_config_path}' was not found.'"],
                )

            pad_env = TclUtils._eval_env(
                full_env,
                open(pad_config_path, encoding="utf8").read(),
            )
            migrated_pad_env = migrate_old_config(pad_env)
            origins.update(_written_by(full_env, migrated_pad_env, "<pad>"))
            full_env = migrated_pad_env

        # Both sides of every comparison above are migrated, so this drops only a
        # key some later layer genuinely deleted -- the gf180mcu removals -- and
        # never one that was merely renamed.
        origins = {key: origin for key, origin in origins.items() if key in full_env}

        return GenericImmutableDict(full_env), pdkpath, scl, pad, origins

    @staticmethod
    def __get_pdk_config(
        pdk: str,
        scl: str | None,
        pad: str | None,
        pdk_root: str,
        flow_pdk_vars: list[Variable] | None = None,
        full_pdk_warnings: bool | None = False,
    ) -> tuple[GenericDict[str, Any], str, str, str | None, dict[str, str]]:
        """
        Returns
        -------
        tuple[GenericDict[str, Any], str, str, str | None, dict[str, str]]
            A tuple of the PDK configuration, the PDK path, the SCL, the PAD,
            and a map from each variable this layer supplied a value for to
            ``<pdk>``, ``<scl>`` or ``<pad>``.

            The PDK is merged separately from the layered design sources, so
            without that map a PDK-supplied value has no attribution at all and
            a caller asking where it came from is told ``default`` -- a wrong
            answer rather than a missing one. A variable no configuration file
            here wrote is absent, which is how ``default`` is spelled.

            ``PDK`` and ``STD_CELL_LIBRARY`` are attributed ``<pdk>`` even when
            the caller named them, because a PDK's ``config.tcl`` emits both
            and the caller's choice reaches this layer as an argument rather
            than as a source that could outrank it. Correcting that needs a
            name for a layer LibreLane does not have today -- the ``pdk``,
            ``scl`` and ``pad`` arguments -- and this method cannot tell one
            passed by ``--scl`` from one passed by an API caller.
        """

        frozen, pdkpath, scl, pad, origins = Config.__get_pdk_raw(
            pdk_root, pdk, scl, pad
        )
        if flow_pdk_vars is None or len(flow_pdk_vars) == 0:
            return (GenericDict(), pdkpath, scl, pad, {})

        raw: GenericDict[str, Any] = GenericDict(frozen)  # microwave
        processed, pdk_warnings, pdk_errors, pdk_renames = (
            Config.__process_variable_list(
                raw,
                flow_pdk_vars,
                on_unknown_key=None,
                permissive_typing=True,
            )
        )

        if len(pdk_errors) != 0:
            raise InvalidConfig("PDK configuration files", pdk_warnings, pdk_errors)

        if len(pdk_warnings) > 0:
            if full_pdk_warnings:
                logger.info(
                    "Loading the PDK configuration files has generated the following warnings:"
                )
                for warning in pdk_warnings:
                    logger.warning(warning)

        processed["PDK_ROOT"] = pdk_root
        processed["PDK"] = pdk

        # A second rename pass, entirely separate from the one
        # '__get_pdk_raw' attributes across: 'compile' checks each variable's
        # deprecated names before its current one and emits under the current
        # one, so 'origins' -- keyed by the names the '.tcl' files wrote --
        # describes forty-two of sky130A's keys under names 'processed' does
        # not have. Following the renames before the filter below is what keeps
        # CELL_LEFS, MAGIC_TECH, WELLTAP_CELL and the whole PDN_* family from
        # reading as declared defaults for values plainly inside the PDK tree.
        #
        # It also moves an origin that was not merely missing but wrong: where
        # the SCL's file writes the deprecated name and the PDK's the current
        # one, 'compile' takes the SCL's value while the PDK's entry for the
        # current name survives, and the map names a layer that did not supply
        # the value.
        #
        # 'origins' is memoized inside '__get_pdk_raw', so it is copied rather
        # than written through.
        attributed = dict(origins)
        _follow_renames(attributed, pdk_renames)

        # Only the variables that survived compilation. A key of the raw
        # environment that no flow variable claims is dropped from 'processed',
        # so attributing it would name an origin for a value nothing carries.
        return (
            processed,
            pdkpath,
            scl,
            pad,
            {key: attributed[key] for key in processed if key in attributed},
        )

    def __process_variable_list(
        mutable: GenericDict[str, Any],
        variables: Sequence["Variable"],
        removed: Mapping[str, str] | None = None,
        *,
        on_unknown_key: Literal["error", "warn"] | None = "warn",
        permissive_typing: bool = False,
        missing_ok: bool = False,
    ) -> tuple[GenericDict[str, Any], list[str], list[str], dict[str, str]]:
        """
        Verifies a configuration object against a list of variables, returning
        an object with the variables normalized according to their types.

        Parameters
        ----------
        config
            The input, raw configuration object.
        variables : Sequence["Variable"]
            A sequence or some other iterable of variables.
        removed : Mapping[str, str] | None
            A dictionary of variables that may have existed at a point in
            time, but then have gotten removed. Useful to give feedback to the user.

        Returns
        -------
        tuple[GenericDict[str, Any], list[str], list[str], dict[str, str]]
            A tuple of:
            [0] A final, processed configuration.
            [1] A list of warnings.
            [2] A list of errors.
            [3] Each variable that took its value from one of its deprecated
                names, mapped to the name it took it from.

            If the third element is non-empty, the first object is invalid.

            The fourth element is reported for the same reason
            :func:`librelane.config.validation.translate_deprecated_names`
            reports its own: this is a rename, and a caller tracking where each
            value came from has to move the origin with the value.
            :meth:`Variable.compile` is the only place that knows both names --
            it prefers a deprecated name over the current one and emits under
            the current one, so no diff of the mapping across this call can
            recover the pairing.
        """
        if removed is None:
            removed = {}
        warnings: list[str] = []
        errors = []
        final: GenericDict[str, Any] = GenericDict()
        translated_from: dict[str, str] = {}

        # Special Deprecation Behaviors
        if (
            mutable.get("DIODE_INSERTION_STRATEGY") is not None
        ):  # Can't use := because 0 is a valid value
            dis = mutable["DIODE_INSERTION_STRATEGY"]
            del mutable["DIODE_INSERTION_STRATEGY"]
            try:
                dis = int(dis)
            except ValueError:
                pass
            if not isinstance(dis, int) or dis in [1, 2, 5] or dis > 6:
                errors.append(
                    f"DIODE_INSERTION_STRATEGY '{dis}' is not available in LibreLane 2.0 or higher. See 'Migrating DIODE_INSERTION_STRATEGY' in the docs for more info."
                )
            else:
                warnings.append(
                    "The DIODE_INSERTION_STRATEGY variable has been deprecated. See 'Migrating DIODE_INSERTION_STRATEGY' in the docs for more info."
                )

                mutable["GRT_REPAIR_ANTENNAS"] = False
                mutable["RUN_HEURISTIC_DIODE_INSERTION"] = False
                mutable["DIODE_ON_PORTS"] = "none"
                if dis in [3, 6]:
                    mutable["GRT_REPAIR_ANTENNAS"] = True
                if dis in [4, 6]:
                    mutable["RUN_HEURISTIC_DIODE_INSERTION"] = True
                    mutable["DIODE_ON_PORTS"] = "in"

        for variable in variables:
            try:
                key, value_processed = variable.compile(
                    mutable_config=mutable,
                    warning_list_ref=warnings,
                    values_so_far=final,
                    permissive_typing=permissive_typing,
                )
                if key is not None:
                    del mutable[key]
                    if key != variable.name:
                        translated_from[variable.name] = key
                final[variable.name] = value_processed
            except MissingRequiredVariable as e:
                if not missing_ok:
                    errors.append(str(e))
            except ValueError as e:
                errors.append(str(e))
            if variable.name in mutable:
                del mutable[variable.name]

        for key in sorted(mutable.keys()):
            assert isinstance(key, str)

            if key in vars(SpecialKeys).values():
                continue
            if key in removed:
                warnings.append(f"'{key}' has been removed: {removed[key]}")
            elif (
                "_OPT" not in key
                and not key.startswith("//")
                and not key.startswith("#")
            ):
                if on_unknown_key == "error":
                    if key in Variable.known_variable_names:
                        warnings.append(
                            f"Key '{key}' provided is unused by the current flow."
                        )
                    else:
                        errors.append(f"Unknown key '{key}' provided.")
                elif on_unknown_key == "warn":
                    if key in Variable.known_variable_names:
                        warnings.append(
                            f"Key '{key}' provided is unused by the current flow."
                        )
                    else:
                        warnings.append(f"An unknown key '{key}' was provided.")

        return (final, warnings, errors, translated_from)
