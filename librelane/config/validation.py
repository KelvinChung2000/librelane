# Copyright 2026 LibreLane Contributors
from typing import Any, Literal
from collections.abc import Mapping, Sequence

from pydantic import ValidationError

from librelane.config.diagnostics import Diagnostic, DiagnosticSet, Severity
from librelane.config.legacy import Variable
from librelane.config.loading.sources import CoercionSyntax
from librelane.config.model import variables_to_model


def _prepare_deprecated_names(
    raw: dict[str, Any],
    variables: Sequence[Variable],
    diagnostics: DiagnosticSet,
) -> dict[str, str]:
    """
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
        if variable.name in raw:
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
    permissive: bool,
    syntaxes: Mapping[str, CoercionSyntax] | None = None,
    on_unknown_key: Literal["error", "warn"] | None = "warn",
    provenance: Mapping[str, str] | None = None,
    removed: Mapping[str, str] | None = None,
) -> tuple[dict[str, Any], DiagnosticSet, dict[str, str]]:
    """Validate one flat mapping through a Pydantic union model.

    Parameters
    ----------
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
    diagnostics = DiagnosticSet()
    translated_from = _migrate_diode_strategy(raw, diagnostics)
    translated_from.update(_prepare_deprecated_names(raw, variables, diagnostics))
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
            diagnostics.add(
                Diagnostic(
                    Severity.ERROR,
                    category,
                    message,
                    variable=top_level,
                    source=(
                        (provenance or {}).get(top_level)
                        if top_level is not None
                        else None
                    ),
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
    # ``None`` means the caller wants no commentary on the key set at all --
    # the per-step increment revalidates a full flow configuration against
    # one step's variables, where "unused by the current flow" would fire
    # for nearly every key, every step.
    for key in sorted(extras) if on_unknown_key is not None else []:
        if key in deprecated_names or key in {
            "PDKPATH",
            "DESIGN_DIR",
            "PDK_ROOT",
            "PDK",
            "STD_CELL_LIBRARY",
            "PAD_CELL_LIBRARY",
        }:
            continue
        if key in removed:
            diagnostics.add(
                Diagnostic(
                    Severity.DEPRECATION,
                    "removed-variable",
                    f"'{key}' has been removed: {removed[key]}",
                    variable=key,
                    source=(provenance or {}).get(key),
                    key_path=key,
                )
            )
        elif "_OPT" not in key and not key.startswith(("//", "#")):
            known = key in Variable.known_variable_names or key in declared_names
            if known:
                message = f"Key '{key}' provided is unused by the current flow."
                severity = Severity.WARNING
            elif on_unknown_key == "error":
                message = f"Unknown key '{key}' provided."
                severity = Severity.ERROR
            elif on_unknown_key == "warn":
                message = f"An unknown key '{key}' was provided."
                severity = Severity.WARNING
            else:
                continue
            diagnostics.add(
                Diagnostic(
                    severity,
                    "unused-key" if known else "unknown-key",
                    message,
                    variable=key,
                    source=(provenance or {}).get(key),
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
