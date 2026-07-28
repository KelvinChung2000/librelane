# Copyright 2026 LibreLane Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
from dataclasses import dataclass
from enum import Enum
from collections.abc import Iterable, Iterator


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    DEPRECATION = "deprecation"
    INFO = "info"


@dataclass(frozen=True)
class Diagnostic:
    severity: Severity
    category: str
    message: str
    variable: str | None = None
    source: str | None = None
    key_path: str | None = None


class DiagnosticSet:
    """An ordered collection of configuration diagnostics."""

    def __init__(self, diagnostics: Iterable[Diagnostic] = ()) -> None:
        self._diagnostics = list(diagnostics)

    def __iter__(self) -> Iterator[Diagnostic]:
        return iter(self._diagnostics)

    def __len__(self) -> int:
        return len(self._diagnostics)

    def add(self, diagnostic: Diagnostic) -> None:
        self._diagnostics.append(diagnostic)

    def extend(self, diagnostics: Iterable[Diagnostic]) -> None:
        self._diagnostics.extend(diagnostics)

    def errors(self) -> list[Diagnostic]:
        return [item for item in self if item.severity is Severity.ERROR]

    def warnings(self) -> list[Diagnostic]:
        return [
            item
            for item in self
            if item.severity in (Severity.WARNING, Severity.DEPRECATION)
        ]

    def filter(
        self,
        *,
        severity: Severity | None = None,
        category: str | None = None,
    ) -> "DiagnosticSet":
        return DiagnosticSet(
            item
            for item in self
            if (severity is None or item.severity is severity)
            and (category is None or item.category == category)
        )

    def render(self, diagnostic: Diagnostic) -> str:
        location = diagnostic.source
        if diagnostic.key_path:
            location = (
                f"{location}:{diagnostic.key_path}" if location else diagnostic.key_path
            )
        return f"{location}: {diagnostic.message}" if location else diagnostic.message

    def rendered_errors(self) -> list[str]:
        return [self.render(item) for item in self.errors()]

    def rendered_warnings(self) -> list[str]:
        return [self.render(item) for item in self.warnings()]
