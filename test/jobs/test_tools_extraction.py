# Copyright 2026 LibreLane Contributors
import json

import pytest

pytestmark = pytest.mark.all


def _extract(*sources, overrides=None):
    from librelane.jobs.tools import extract_tools

    return extract_tools(list(sources), config_override_strings=overrides)


def test_absent_tools_yields_an_empty_mapping():
    assert _extract({"DESIGN_NAME": "a"}) == {}


def test_mapping_source_is_read():
    assert _extract({"TOOLS": {"synthesis": "genus"}}) == {"synthesis": "genus"}


def test_later_sources_win():
    result = _extract(
        {"TOOLS": {"synthesis": "yosys"}},
        {"TOOLS": {"synthesis": "genus"}},
    )
    assert result == {"synthesis": "genus"}


def test_override_strings_win_over_every_source():
    result = _extract(
        {"TOOLS": {"synthesis": "yosys"}},
        overrides=[f"TOOLS={json.dumps({'synthesis': 'genus'})}"],
    )
    assert result == {"synthesis": "genus"}


def test_unrelated_override_strings_are_ignored():
    result = _extract(
        {"TOOLS": {"synthesis": "yosys"}},
        overrides=["DESIGN_NAME=whatever"],
    )
    assert result == {"synthesis": "yosys"}


def test_list_values_are_preserved():
    assert _extract({"TOOLS": {"streamout": ["magic", "klayout"]}}) == {
        "streamout": ["magic", "klayout"]
    }


def test_non_mapping_tools_is_rejected():
    from librelane.jobs import JobResolutionError

    with pytest.raises(JobResolutionError, match="must be a mapping"):
        _extract({"TOOLS": "genus"})


def test_preprocessor_constructs_are_rejected():
    from librelane.jobs import JobResolutionError

    with pytest.raises(JobResolutionError, match="must be a literal"):
        _extract({"TOOLS": {"synthesis": "ref::$SYNTH_TOOL"}})


def test_preprocessor_constructs_are_rejected_inside_a_list():
    from librelane.jobs import JobResolutionError

    with pytest.raises(JobResolutionError, match="must be a literal"):
        _extract({"TOOLS": {"streamout": ["magic", "expr::$X"]}})


def test_non_string_provider_is_rejected():
    from librelane.jobs import JobResolutionError

    with pytest.raises(JobResolutionError, match="must be a string"):
        _extract({"TOOLS": {"synthesis": 3}})


def test_malformed_override_json_is_rejected():
    from librelane.jobs import JobResolutionError

    with pytest.raises(JobResolutionError, match="not valid JSON"):
        _extract({}, overrides=["TOOLS={not json}"])


def test_yaml_source_is_read(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("TOOLS:\n  synthesis: genus\n", encoding="utf8")

    assert _extract(path) == {"synthesis": "genus"}


def test_tcl_source_contributes_nothing(tmp_path):
    """
    Evaluating Tcl needs process information that is not resolved this early,
    so a .tcl source is reported as unconsulted rather than read and empty.
    """
    path = tmp_path / "config.tcl"
    path.write_text("set ::env(TOOLS) whatever\n", encoding="utf8")

    assert _extract(path) == {}
