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
    ("OpenROAD.RMP", ("openroad", "restructure.tcl")),
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


def test_no_debug_residue_in_shipped_scripts():
    """`wtaf` was logged into every non-slang synthesis run."""
    import pathlib

    scripts = pathlib.Path(str(files("librelane").joinpath("scripts")))
    offenders = [
        str(path)
        for path in scripts.rglob("*.py")
        if "wtaf" in path.read_text(encoding="utf8", errors="replace")
    ]

    assert offenders == []


def test_the_extra_corner_tcl_file_contract_holds():
    """The variable reaches Tcl through TclStep.prepare_env under its own name;
    a second, underscore-prefixed copy was set and never read."""
    import pathlib

    from librelane.steps.openroad.base import OpenROADStep

    scripts = pathlib.Path(str(files("librelane").joinpath("scripts")))
    bodies = [
        path.read_text(encoding="utf8", errors="replace")
        for path in scripts.rglob("*.tcl")
    ]

    assert any("$::env(STA_EXTRA_CORNER_TCL_FILE)" in body for body in bodies)
    assert not any("$::env(_EXTRA_CORNER_TCL_FILE)" in body for body in bodies)
    assert "STA_EXTRA_CORNER_TCL_FILE" in OpenROADStep.Config.model_fields
