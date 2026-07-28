import json
from pathlib import Path

import librelane.steps  # noqa: F401
from librelane.steps import Step

SNAPSHOT = Path(__file__).parent / "registry_snapshot.json"


def test_step_registry_matches_snapshot():
    """Guard against a step silently vanishing during package refactors."""
    # Some tests intentionally register ephemeral Test.* steps without unregistering
    # them, so only compare the production namespace.
    current = sorted(
        step_id for step_id in Step.factory.list() if not step_id.startswith("Test.")
    )

    if not SNAPSHOT.exists():
        SNAPSHOT.write_text(json.dumps(current, indent=2) + "\n")
        raise AssertionError(
            f"Wrote initial snapshot with {len(current)} steps. Re-run to verify."
        )

    expected = json.loads(SNAPSHOT.read_text())
    missing = sorted(set(expected) - set(current))
    added = sorted(set(current) - set(expected))

    assert not missing, (
        f"{len(missing)} step(s) disappeared from the registry: {missing}. "
        "If intentional, update test/steps/registry_snapshot.json."
    )
    assert not added, (
        f"{len(added)} new step(s) registered: {added}. "
        "If intentional, update test/steps/registry_snapshot.json."
    )
