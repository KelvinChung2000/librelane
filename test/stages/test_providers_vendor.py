# Copyright 2026 LibreLane Contributors
import subprocess
import sys
import textwrap

import pytest

pytestmark = pytest.mark.all


def test_vendor_registration_is_opt_in_via_subprocess():
    """
    StageRegistry and Step.factory are process-wide singletons, so importing
    librelane.stages.providers_vendor in this process would register the
    sixteen commercial providers for the rest of the pytest session, and a
    later test asserting their absence would then fail depending on test
    order under pytest-randomly. Both the "before" and "after" halves of this
    check therefore run inside one throwaway subprocess, which is discarded
    once it exits.
    """
    script = textwrap.dedent(
        """
        import librelane.stages
        from librelane.stages import StageRegistry
        from librelane.flows.flow import Flow

        before = set(StageRegistry.providers("synthesis"))
        assert before == {"yosys", "yosys_vhdl"}, before
        assert not ({"dc", "fc", "genus"} & before), before

        before_help = Flow.factory.get("Classic").get_help_md()
        assert "`dc`" not in before_help, "vendor provider leaked before opt-in"

        import librelane.stages.providers_vendor  # noqa: F401  (the opt-in)

        after = set(StageRegistry.providers("synthesis"))
        assert {"dc", "fc", "genus"} <= after, after

        after_help = Flow.factory.get("Classic").get_help_md()
        assert "`dc`" in after_help, "vendor provider did not appear after opt-in"

        print("OK")
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"subprocess check failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "OK" in result.stdout


def test_stages_package_does_not_import_the_vendor_aggregator():
    """
    librelane/stages/__init__.py must never import providers_vendor: doing so
    would make every commercial provider ambient on ordinary import of
    librelane.stages, defeating the opt-in boundary the previous test pins.
    """
    import librelane.stages as stages_pkg

    assert not hasattr(stages_pkg, "providers_vendor")


def test_every_vendor_module_exports_registrations_for_real_stages():
    """
    Harmless to run in-process: this only reads each module's REGISTRATIONS
    data and checks stage ids against Stage.factory, without ever calling
    StageRegistry.register. A typo in a stage id here would otherwise only
    surface the first time someone actually opts in.
    """
    from librelane.stages import Stage
    from librelane.steps import (
        calibre,
        conformal,
        dc,
        fc,
        fm,
        genus,
        icc2,
        icv,
        innovus,
        pegasus,
        pt,
        quantus,
        starrc,
        tempus,
        vc_spyglass,
        voltus,
    )

    modules = (
        calibre,
        conformal,
        dc,
        fc,
        fm,
        genus,
        icc2,
        icv,
        innovus,
        pegasus,
        pt,
        quantus,
        starrc,
        tempus,
        vc_spyglass,
        voltus,
    )
    known_stages = set(Stage.factory.list())

    for module in modules:
        registrations = module.REGISTRATIONS
        assert registrations, f"{module.__name__}.REGISTRATIONS is empty"
        for entry in registrations:
            for stage_id in entry["stages"]:
                assert stage_id in known_stages, (
                    f"{module.__name__}: registration for provider "
                    f"'{entry['provider']}' names unknown stage '{stage_id}'"
                )
