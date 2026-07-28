# Copyright 2026 LibreLane Contributors
from typing import Any
from collections.abc import Mapping

from .resolve import parse_directive, resolve_directive


class SymbolCycleError(ValueError):
    pass


def resolve_symbols(
    mapping: Mapping[str, Any],
    seeds: Mapping[str, Any],
) -> dict[str, Any]:
    """Resolve every scalar through a dependency graph, including forward refs."""

    nodes: dict[str, Any] = {}
    children: dict[str, list[tuple[str | int, str]]] = {}

    def collect(value: Any, path: str) -> None:
        nodes[path] = value
        if isinstance(value, Mapping):
            child_paths = []
            for key, item in value.items():
                child = f"{path}.{key}" if path else str(key)
                child_paths.append((key, child))
                collect(item, child)
            children[path] = child_paths
        elif isinstance(value, list):
            child_paths = []
            for index, item in enumerate(value):
                child = f"{path}[{index}]"
                child_paths.append((index, child))
                collect(item, child)
            children[path] = child_paths

    for key, value in mapping.items():
        collect(value, key)

    resolved: dict[str, Any] = {
        key: value for key, value in seeds.items() if key not in nodes
    }
    visiting: list[str] = []

    def resolve(path: str) -> Any:
        if path in resolved:
            return resolved[path]
        if path not in nodes:
            raise KeyError(path)
        if path in visiting:
            start = visiting.index(path)
            cycle = visiting[start:] + [path]
            raise SymbolCycleError(
                "Configuration reference cycle: " + " -> ".join(cycle)
            )

        visiting.append(path)
        value = nodes[path]
        if isinstance(value, Mapping):
            final: Any = {key: resolve(child) for key, child in children[path]}
        elif isinstance(value, list):
            final = [resolve(child) for _, child in children[path]]
        elif isinstance(value, str) and (directive := parse_directive(value)):
            final = resolve_directive(directive, resolve)
        else:
            final = value
        visiting.pop()
        resolved[path] = final
        return final

    return {key: resolve(key) for key in mapping}
