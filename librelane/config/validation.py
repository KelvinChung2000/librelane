# Copyright 2026 LibreLane Contributors
from typing import Any, Literal
from collections.abc import Mapping, Sequence

from pydantic import ValidationError

from librelane.config.diagnostics import Diagnostic, DiagnosticSet, Severity
from librelane.config.variable import Variable
from librelane.config.loading.sources import CoercionSyntax
from librelane.config.model import variables_to_model
from librelane.config.preprocessor import SPECIAL_KEYS


def _prepare_deprecated_names(
    raw: dict[str, Any],
    variables: Sequence[Variable],
    diagnostics: DiagnosticSet,
    outranks: bool = False,
) -> dict[str, str]:
    """
    Parameters
    ----------
    outranks : bool
        Whether a value written under a deprecated name beats one already
        present under the current name.

        ``False`` for a mapping whose layers have already been ranked: there,
        the current name holds whatever won, and letting a deprecated spelling
        override it would let a PDK's old name beat a design's new one.

        ``True`` for a mapping where they have not been -- the environment a
        PDK, its standard cell library and its pad library are evaluated into,
        which is merged by evaluation order and keeps no record of which file
        wrote what. There the deprecated name is the *later* layer's more often
        than not, because renaming a variable is exactly what the newer file
        has not done yet; sky130A's standard cell library writes
        ``SYNTH_TIEHI_PORT`` over a PDK that writes ``SYNTH_TIEHI_CELL``. It is
        also what a caller means by passing one as a keyword argument.

    Returns
    -------
    dict[str, str]
        Each name this wrote, mapped to the deprecated name whose value it
        took. Reported rather than left implicit because a caller tracking
        where each value came from has to move the origin with the value, and
        this is the only place that knows both names.
    """
    translated_from: dict[str, str] = {}
    for variable in variables:
        if variable.name in raw and not outranks:
            continue
        for deprecated in variable.deprecated_names:
            name = deprecated
            translate = None
            if not isinstance(deprecated, str):
                name, translate = deprecated
            if name not in raw:
                continue
            value = raw[name]
            if translate is not None and value is not None:
                value = translate(value)
            raw[variable.name] = value
            translated_from[variable.name] = name
            diagnostics.add(
                Diagnostic(
                    Severity.DEPRECATION,
                    "deprecated-name",
                    f"The configuration variable '{name}' is deprecated. "
                    f"Please check the docs for the usage on the replacement "
                    f"variable '{variable.name}'.",
                    variable=variable.name,
                    key_path=name,
                )
            )
            break
    return translated_from


def translate_deprecated_names(
    mapping: Mapping[str, Any],
    variables: Sequence[Variable],
) -> tuple[dict[str, Any], DiagnosticSet, dict[str, str]]:
    """Rewrite deprecated keys to their current names within a single layer.

    A PDK supplies a value for every PDK variable, so by the time the layers
    have been merged the current name is always present and a design that
    still uses a deprecated one would be quietly ignored. Translating a layer
    while it is still on its own keeps the design's value winning, whichever
    name it was written under.

    Returns
    -------
    tuple[dict[str, Any], DiagnosticSet, dict[str, str]]
        The translated mapping, the deprecation diagnostics, and each name
        written here mapped to the deprecated name its value came from.
    """
    translated = dict(mapping)
    diagnostics = DiagnosticSet()
    translated_from = _prepare_deprecated_names(translated, variables, diagnostics)
    return translated, diagnostics, translated_from


def _migrate_diode_strategy(
    raw: dict[str, Any],
    diagnostics: DiagnosticSet,
) -> dict[str, str]:
    """
    Returns
    -------
    dict[str, str]
        Each of the three keys this wrote, mapped to
        ``DIODE_INSERTION_STRATEGY``. One key becoming three is still a
        rename as far as attribution goes: all three owe their values to
        whichever layer set the one.
    """
    if raw.get("DIODE_INSERTION_STRATEGY") is None:
        return {}
    strategy = raw.pop("DIODE_INSERTION_STRATEGY")
    try:
        strategy = int(strategy)
    except (TypeError, ValueError):
        pass
    if not isinstance(strategy, int) or strategy in (1, 2, 5) or strategy > 6:
        diagnostics.add(
            Diagnostic(
                Severity.ERROR,
                "removed-variable",
                f"DIODE_INSERTION_STRATEGY '{strategy}' is not available in "
                "LibreLane 2.0 or higher. See 'Migrating "
                "DIODE_INSERTION_STRATEGY' in the docs for more info.",
                variable="DIODE_INSERTION_STRATEGY",
            )
        )
        return {}
    diagnostics.add(
        Diagnostic(
            Severity.DEPRECATION,
            "removed-variable",
            "The DIODE_INSERTION_STRATEGY variable has been deprecated. See "
            "'Migrating DIODE_INSERTION_STRATEGY' in the docs for more info.",
            variable="DIODE_INSERTION_STRATEGY",
        )
    )
    raw["GRT_REPAIR_ANTENNAS"] = strategy in (3, 6)
    raw["RUN_HEURISTIC_DIODE_INSERTION"] = strategy in (4, 6)
    raw["DIODE_ON_PORTS"] = "in" if strategy in (4, 6) else "none"
    return dict.fromkeys(
        ("GRT_REPAIR_ANTENNAS", "RUN_HEURISTIC_DIODE_INSERTION", "DIODE_ON_PORTS"),
        "DIODE_INSERTION_STRATEGY",
    )


def validate_mapping(
    mapping: Mapping[str, Any],
    variables: Sequence[Variable],
    *,
    permissive: bool = False,
    syntaxes: Mapping[str, CoercionSyntax] | None = None,
    on_unknown_key: Literal["error", "warn"] | None = "warn",
    provenance: Mapping[str, str] | None = None,
    removed: Mapping[str, str] | None = None,
    deprecated_outranks: bool = False,
) -> tuple[dict[str, Any], DiagnosticSet, dict[str, str]]:
    """Validate one flat mapping through a Pydantic union model.

    Parameters
    ----------
    deprecated_outranks : bool
        Whether a value written under a variable's deprecated name beats one
        already present under its current name. See
        :func:`_prepare_deprecated_names`.
    syntaxes : Mapping[str, CoercionSyntax] | None
        Each key mapped to the syntax the source that last wrote it writes its
        strings in, which is what decides how a string reaching a list- or
        dictionary-typed variable is read. A key absent from it was not written
        by a source at all -- the PDK's compiled values, an API caller's
        mapping -- and is taken to have arrived typed.

    Returns
    -------
    tuple[dict[str, Any], DiagnosticSet, dict[str, str]]
        The validated values, the diagnostics, and each key the two migrations
        below wrote mapped to the key whose value it came from. The third
        element is reported for the same reason
        :func:`translate_deprecated_names` reports it: these migrations run
        after the layers have been merged, so a caller tracking origins cannot
        see them happen and would leave a renamed value attributed to whatever
        wrote its old name -- or to whichever layer last wrote the new one.
    """
    raw = dict(mapping)
    removed = removed or {}
    #: Which source last wrote each key, for the ``source`` every diagnostic
    #: below locates itself by. Defaulted once here rather than at each of the
    #: three reads, which each re-evaluated ``provenance or {}``.
    origins = provenance or {}
    diagnostics = DiagnosticSet()
    translated_from = _migrate_diode_strategy(raw, diagnostics)
    translated_from.update(
        _prepare_deprecated_names(raw, variables, diagnostics, deprecated_outranks)
    )
    model_type = variables_to_model("FlowConfig", list(variables))

    try:
        model = model_type.model_validate(
            raw,
            context={
                "permissive": permissive,
                "syntaxes": syntaxes or {},
            },
            strict=not permissive,
        )
    except ValidationError as error:
        declared_by_name = {variable.name: variable for variable in variables}
        for detail in error.errors(include_url=False):
            location = ".".join(str(part) for part in detail["loc"])
            category = (
                "missing-required" if detail["type"] == "missing" else "type-error"
            )
            message = detail["msg"]
            top_level = location.split(".", 1)[0] if location else None
            if (
                detail["type"] in ("list_type", "tuple_type", "dict_type")
                and top_level
                and isinstance(raw.get(top_level), str)
            ):
                message = (
                    f"Refusing to automatically convert value for "
                    f"'{top_level}' under strict typing."
                )
            elif detail["type"] == "missing" and top_level:
                # Pydantic says "Field required", which names neither the
                # variable nor -- for a PDK variable, where it is the whole
                # answer -- who was supposed to have supplied it. This is the
                # wording the legacy compiler raised, kept because it is the
                # better one and because a PDK missing a variable a step needs
                # is the most common way for a flow to be told "no".
                declared = declared_by_name.get(top_level)
                if declared is not None and declared.pdk:
                    message = (
                        f"Required PDK variable '{top_level}' did not get a "
                        f"specified value. This PDK may be incompatible with "
                        f"your flow."
                    )
                else:
                    message = (
                        f"Required variable '{top_level}' did not get a "
                        f"specified value."
                    )
            diagnostics.add(
                Diagnostic(
                    Severity.ERROR,
                    category,
                    message,
                    variable=top_level,
                    source=origins.get(top_level) if top_level else None,
                    key_path=location or None,
                )
            )
        return {}, diagnostics, translated_from

    # Read the validated values rather than dumping them: model_dump flattens
    # dataclasses such as Macro back into plain mappings, and steps expect the
    # typed objects.
    final = {name: getattr(model, name) for name in type(model).model_fields}
    extras = model.model_extra or {}
    declared_names = {variable.name for variable in variables}
    deprecated_names = {
        item if isinstance(item, str) else item[0]
        for variable in variables
        for item in variable.deprecated_names
    }
    for key in sorted(extras):
        if key in deprecated_names or key in SPECIAL_KEYS:
            continue
        # Each branch decides only what it disagrees about -- how bad it is,
        # what to call it, and what to say -- and the one report below is built
        # from that. The three fields locating the key were spelled out per
        # branch before, which is two chances to attribute a diagnostic to the
        # wrong key and no reason to take either.
        if key in removed:
            severity = Severity.DEPRECATION
            category = "removed-variable"
            message = f"'{key}' has been removed: {removed[key]}"
        elif "_OPT" in key or key.startswith(("//", "#")):
            continue
        elif on_unknown_key is None:
            # Nothing at all, not even for a key that is a variable somewhere
            # else. A caller passing 'None' is validating one layer against a
            # deliberately partial variable list -- a step's own, a PDK's --
            # where every key belonging to some other reader is present and
            # expected, and reporting each of them says nothing.
            continue
        else:
            known = key in Variable.known_variable_names or key in declared_names
            category = "unused-key" if known else "unknown-key"
            if known:
                severity = Severity.WARNING
                message = f"Key '{key}' provided is unused by the current flow."
            elif on_unknown_key == "error":
                severity = Severity.ERROR
                message = f"Unknown key '{key}' provided."
            elif on_unknown_key == "warn":
                severity = Severity.WARNING
                message = f"An unknown key '{key}' was provided."
            else:
                continue
        diagnostics.add(
            Diagnostic(
                severity,
                category,
                message,
                variable=key,
                source=origins.get(key),
                key_path=key,
            )
        )

    # Legacy post-validation hooks remain supported during the P4 migration.
    for variable in variables:
        if variable.name not in final:
            continue
        try:
            hook_warnings: list[str] = []
            final[variable.name] = variable.validator(
                variable,
                final[variable.name],
                hook_warnings,
            )
            for warning in hook_warnings:
                diagnostics.add(
                    Diagnostic(
                        Severity.WARNING,
                        "custom-validator",
                        warning,
                        variable=variable.name,
                    )
                )
        except ValueError as error:
            diagnostics.add(
                Diagnostic(
                    Severity.ERROR,
                    "custom-validator",
                    str(error),
                    variable=variable.name,
                )
            )

    return (
        {key: final[key] for key in declared_names if key in final},
        diagnostics,
        translated_from,
    )
