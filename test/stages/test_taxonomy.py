# Copyright 2026 LibreLane Contributors
import pytest

pytestmark = pytest.mark.all


def test_every_stage_in_order_is_registered():
    from librelane.stages import Stage
    from librelane.stages.taxonomy import STAGE_ORDER

    for stage_id in STAGE_ORDER:
        assert Stage.factory.get(stage_id) is not None, stage_id


def test_taxonomy_has_twenty_seven_stages():
    from librelane.stages.taxonomy import STAGE_ORDER

    assert len(STAGE_ORDER) == 27
    assert len(set(STAGE_ORDER)) == 27


def test_only_post_route_opt_is_unselected():
    from librelane.stages import Stage
    from librelane.stages.taxonomy import STAGE_ORDER

    unselected = [
        stage_id
        for stage_id in STAGE_ORDER
        if Stage.factory.get(stage_id).default_provider is None
    ]
    assert unselected == ["post_route_opt"]


def test_optional_stages_only_feed_other_optional_stages():
    """
    An optional stage may be skipped. If a *mandatory* later stage required
    something only that optional stage provides, the flow would be
    unconditionally broken whenever the gate were turned off, and no
    configuration could rescue it.

    An optional consumer is a different matter: the combination is legal as
    long as both gates agree, and the static view availability preflight
    rejects the disagreeing case by name before the run starts. `extraction`
    (RUN_SPEF_EXTRACTION) feeding `signoff_sta` (RUN_MCSTA) and `ir_drop`
    (RUN_IRDROP_REPORT) is exactly that case.
    """
    from librelane.stages import Stage
    from librelane.stages.taxonomy import STAGE_ORDER

    for index, stage_id in enumerate(STAGE_ORDER):
        stage = Stage.factory.get(stage_id)
        if not stage.optional:
            continue
        mandatory_later_requirements = set()
        for later_id in STAGE_ORDER[index + 1 :]:
            later = Stage.factory.get(later_id)
            if later.optional:
                continue
            mandatory_later_requirements.update(later.requires)
        exclusive = set(stage.provides) - {
            view
            for earlier_id in STAGE_ORDER[:index]
            for view in Stage.factory.get(earlier_id).provides
        }
        assert not (exclusive & mandatory_later_requirements), stage_id


def test_extraction_only_feeds_optional_consumers():
    """
    Pins the one case the invariant above deliberately permits, so that
    turning `signoff_sta` or `ir_drop` into a mandatory stage fails loudly
    here rather than at some user's runtime.
    """
    from librelane.stages import Stage
    from librelane.state import DesignFormat

    assert Stage.factory.get("extraction").optional
    assert DesignFormat.spef in Stage.factory.get("extraction").provides
    for consumer in ("signoff_sta", "ir_drop"):
        stage = Stage.factory.get(consumer)
        assert DesignFormat.spef in stage.requires, consumer
        assert stage.optional, consumer


def test_gating_variables_are_unique():
    from librelane.stages import Stage
    from librelane.stages.taxonomy import STAGE_ORDER

    gates = [
        Stage.factory.get(stage_id).gating_config_var
        for stage_id in STAGE_ORDER
        if Stage.factory.get(stage_id).gating_config_var is not None
    ]
    assert len(gates) == len(set(gates))
    assert len(gates) == 15


def test_multi_provider_stages():
    from librelane.stages import Stage
    from librelane.stages.taxonomy import STAGE_ORDER

    multi = [
        stage_id
        for stage_id in STAGE_ORDER
        if Stage.factory.get(stage_id).multi_provider
    ]
    assert multi == ["streamout", "drc"]
