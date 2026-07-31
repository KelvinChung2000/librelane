from importlib.resources import files
from pathlib import Path

import pytest

import librelane.steps  # noqa: F401
from librelane.steps import Step


# One representative step per external tool that consumes a packaged script.
# Paths are relative to ``librelane/scripts``.
SCRIPT_STEPS = [
    ("OpenROAD.Floorplan", ("openroad", "floorplan.tcl")),
    ("OpenROAD.CheckMacroInstances", ("openroad", "sta", "check_macro_instances.tcl")),
    ("OpenROAD.OpenSTAConsole", ("openroad", "sta", "console.tcl")),
    ("Odb.ApplyDEFTemplate", ("odbpy", "apply_def_template.py")),
    ("Odb.SetPowerConnections", ("odbpy", "power_utils.py")),
    ("Magic.WriteLEF", ("magic", "lef.tcl")),
    ("Magic.DRC", ("magic", "drc.tcl")),
    ("Yosys.Synthesis", ("pyosys", "synthesize.py")),
    ("Yosys.JsonHeader", ("pyosys", "json_header.py")),
]


@pytest.mark.parametrize(("step_id", "relative_script"), SCRIPT_STEPS)
def test_step_script_paths_are_real_files(
    step_id: str, relative_script: tuple[str, ...]
):
    """
    ``get_script_path`` is stringified into the argv of an external process, so
    it must name a file that actually exists on the filesystem.
    """
    step_class = Step.factory.get(step_id)
    assert step_class is not None, f"{step_id} is not a registered step"

    # These implementations return a constant, so a bare instance suffices;
    # building a real one would require a complete configuration.
    step = object.__new__(step_class)
    script_path = Path(str(step.get_script_path()))

    assert script_path.is_file(), f"{step_id}: {script_path} is not a file"
    assert script_path == Path(
        str(files("librelane").joinpath("scripts", *relative_script))
    )
