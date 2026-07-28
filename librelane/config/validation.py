# Copyright 2026 LibreLane Contributors
from typing import Any, Literal
from collections.abc import Mapping, Sequence

from pydantic import ValidationError

from .diagnostics import Diagnostic, DiagnosticSet, Severity
from .legacy import Variable
from .model import variables_to_model


def _prepare_deprecated_names(
    raw: dict[str, Any],
    variables: Sequence[Variable],
    diagnostics: DiagnosticSet,
) -> None:
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


def translate_deprecated_names(
    mapping: Mapping[str, Any],
    variables: Sequence[Variable],
) -> tuple[dict[str, Any], DiagnosticSet]:
    """Rewrite deprecated keys to their current names within a single layer.

    A PDK supplies a value for every PDK variable, so by the time the layers
    have been merged the current name is always present and a design that
    still uses a deprecated one would be quietly ignored. Translating a layer
    while it is still on its own keeps the design's value winning, whichever
    name it was written under.
    """
    translated = dict(mapping)
    diagnostics = DiagnosticSet()
    _prepare_deprecated_names(translated, variables, diagnostics)
    return translated, diagnostics


def _migrate_diode_strategy(
    raw: dict[str, Any],
    diagnostics: DiagnosticSet,
) -> None:
    if raw.get("DIODE_INSERTION_STRATEGY") is None:
        return
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
        return
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


def validate_mapping(
    mapping: Mapping[str, Any],
    variables: Sequence[Variable],
    *,
    permissive: bool,
    permissive_keys: frozenset[str] = frozenset(),
    on_unknown_key: Literal["error", "warn"] | None = "warn",
    provenance: Mapping[str, str] | None = None,
    removed: Mapping[str, str] | None = None,
) -> tuple[dict[str, Any], DiagnosticSet]:
    """Validate one flat mapping through a Pydantic union model."""
    raw = dict(mapping)
    removed = removed or {}
    diagnostics = DiagnosticSet()
    _migrate_diode_strategy(raw, diagnostics)
    _prepare_deprecated_names(raw, variables, diagnostics)
    model_type = variables_to_model("FlowConfig", list(variables))

    try:
        model = model_type.model_validate(
            raw,
            context={
                "permissive": permissive,
                "permissive_keys": permissive_keys,
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
        return {}, diagnostics

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

    return {key: final[key] for key in declared_names if key in final}, diagnostics
