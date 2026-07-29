# Copyright 2026 LibreLane Contributors
import pytest


@pytest.fixture
def mock_steps():
    """
    Two trivial steps that pass views through and emit one metric each.
    Registered with the Step factory so they can be named by ID.
    """
    from librelane.state import DesignFormat
    from librelane.steps import Step

    @Step.factory.register()
    class MockPlace(Step):
        id = "Test.MockPlace"
        inputs = [DesignFormat.def_, DesignFormat.nl, DesignFormat.sdc]
        outputs = [DesignFormat.def_, DesignFormat.nl, DesignFormat.sdc]

        def run(self, state_in, **kwargs):
            return {}, {"mock__placed": 1}

    @Step.factory.register()
    class MockRoute(Step):
        id = "Test.MockRoute"
        inputs = [DesignFormat.def_, DesignFormat.nl, DesignFormat.sdc]
        outputs = [DesignFormat.def_, DesignFormat.nl, DesignFormat.sdc]

        def run(self, state_in, **kwargs):
            return {}, {"mock__routed": 1}

    return MockPlace, MockRoute
