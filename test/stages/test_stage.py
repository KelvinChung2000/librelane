# Copyright 2026 LibreLane Contributors
import pytest

pytestmark = pytest.mark.all


def test_stage_registers_and_is_retrievable():
    from librelane.stages import Stage
    from librelane.state import DesignFormat

    stage = Stage(
        id="test_stage_alpha",
        full_name="Test Stage Alpha",
        default_provider="mock",
        requires=(DesignFormat.nl,),
        provides=(DesignFormat.def_,),
    ).register()

    assert Stage.factory.get("test_stage_alpha") is stage
    assert Stage.test_stage_alpha is stage
    assert "test_stage_alpha" in Stage.factory.list()


def test_unknown_stage_attribute_raises():
    from librelane.stages import Stage

    with pytest.raises(AttributeError):
        Stage.no_such_stage_exists


def test_duplicate_registration_raises():
    from librelane.stages import Stage, StageError
    from librelane.state import DesignFormat

    def make():
        return Stage(
            id="test_stage_duplicate",
            full_name="Test Stage Duplicate",
            default_provider="mock",
            requires=(DesignFormat.nl,),
            provides=(DesignFormat.nl,),
        )

    make().register()
    with pytest.raises(StageError, match="already registered"):
        make().register()


def test_optional_stage_may_have_no_default_provider():
    from librelane.stages import Stage
    from librelane.state import DesignFormat

    Stage(
        id="test_stage_optional",
        full_name="Test Stage Optional",
        default_provider=None,
        requires=(DesignFormat.def_,),
        provides=(DesignFormat.def_,),
        optional=True,
    ).register()


def test_non_optional_stage_without_default_provider_raises():
    from librelane.stages import Stage, StageError
    from librelane.state import DesignFormat

    with pytest.raises(StageError, match="marked optional"):
        Stage(
            id="test_stage_bad",
            full_name="Test Stage Bad",
            default_provider=None,
            requires=(DesignFormat.def_,),
            provides=(DesignFormat.def_,),
        ).register()
