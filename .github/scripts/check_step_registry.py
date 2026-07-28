#!/usr/bin/env python3

import json
from pathlib import Path

import librelane.steps  # noqa: F401
from librelane.steps import Step

SNAPSHOT = (
    Path(__file__).resolve().parents[2] / "test" / "steps" / "registry_snapshot.json"
)


def main() -> int:
    expected = set(json.loads(SNAPSHOT.read_text()))
    current = {
        step_id for step_id in Step.factory.list() if not step_id.startswith("Test.")
    }
    missing = sorted(expected - current)
    added = sorted(current - expected)

    if missing or added:
        if missing:
            print(f"Missing registered steps: {missing}")
        if added:
            print(f"Unrecorded registered steps: {added}")
        return 1

    print(f"Step registry matches snapshot ({len(current)} entries).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
