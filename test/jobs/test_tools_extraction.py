# Copyright 2026 LibreLane Contributors
import json

import pytest

pytestmark = pytest.mark.all


def _extract(*sources, overrides=None, **process):
    from librelane.jobs.tools import extract_tools

    return extract_tools(
        list(sources),
        config_override_strings=overrides,
        **process,
    )


@pytest.fixture
def two_pdks(tmp_path):
    """
    Two PDKs under one root, each defaulting to a standard cell library of its
    own.

    The default is what makes an ``scl::`` section testable at all: a section
    naming ``alpha_scl`` can only be matched by a pre-pass that fetched the
    PDK's own configuration, because nothing the design or the command line
    says names that library. The ``info exists`` guard is the shape every
    shipped PDK uses, so a caller that *does* name one still wins.

    Returns
    -------
    str
        The PDK root.
    """
    root = tmp_path / "pdk"
    for pdk, scl in (("alpha", "alpha_scl"), ("beta", "beta_scl")):
        librelane_dir = root / pdk / "libs.tech" / "librelane"
        (librelane_dir / scl).mkdir(parents=True)
        (librelane_dir / "config.tcl").write_text(
            "if { ![info exists ::env(STD_CELL_LIBRARY)] } {\n"
            f'    set ::env(STD_CELL_LIBRARY) "{scl}"\n'
            "}\n",
            encoding="utf8",
        )
        (librelane_dir / scl / "config.tcl").write_text("", encoding="utf8")
    return str(root)


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


def test_a_scoped_tools_under_the_matching_pdk_is_read(two_pdks, tmp_path):
    """
    The defect this file's ``pdk::`` cases exist for: the pre-pass used to read
    the sources as written, so a section's ``TOOLS`` was invisible to selection
    while the loader promoted it -- and the run then used one provider while
    ``--explain-variables`` reported another.
    """
    assert _extract(
        {
            "TOOLS": {"synthesis": "yosys"},
            "pdk::alpha": {"TOOLS": {"synthesis": "genus"}},
        },
        pdk="alpha",
        pdk_root=two_pdks,
        design_dir=str(tmp_path),
    ) == {"synthesis": "genus"}


def test_a_section_naming_another_pdk_is_dropped(two_pdks, tmp_path):
    assert _extract(
        {
            "TOOLS": {"synthesis": "yosys"},
            "pdk::beta": {"TOOLS": {"synthesis": "genus"}},
        },
        pdk="alpha",
        pdk_root=two_pdks,
        design_dir=str(tmp_path),
    ) == {"synthesis": "yosys"}


def test_an_scl_section_matches_the_library_the_pdk_defaults_to(two_pdks, tmp_path):
    """
    No argument and no source names ``alpha_scl``; the PDK's own configuration
    does. Matching this section is only possible for a pre-pass that fetches
    it, which is the half of the resolution that is not just reading keys.
    """
    assert _extract(
        {
            "TOOLS": {"synthesis": "yosys"},
            "scl::alpha_scl": {"TOOLS": {"synthesis": "genus"}},
        },
        pdk="alpha",
        pdk_root=two_pdks,
        design_dir=str(tmp_path),
    ) == {"synthesis": "genus"}


def test_a_pdk_key_in_a_source_outranks_the_pdk_argument(two_pdks, tmp_path):
    """
    ``Config.load`` reads ``PDK`` off the layered sources and falls back to the
    argument only where no source wrote one, so ``--pdk alpha`` alongside a
    configuration naming ``beta`` resolves to ``beta``. The pre-pass runs that
    same line rather than its own, so the two cannot rank them differently.
    """
    assert _extract(
        {
            "PDK": "beta",
            "TOOLS": {"synthesis": "yosys"},
            "pdk::beta": {"TOOLS": {"synthesis": "genus"}},
        },
        pdk="alpha",
        pdk_root=two_pdks,
        design_dir=str(tmp_path),
    ) == {"synthesis": "genus"}


def test_a_command_line_pdk_override_decides_which_section_matches(two_pdks, tmp_path):
    """
    ``--config-override`` is a layer of its own, above every file, so it
    outranks a ``PDK`` a configuration wrote -- and therefore decides which
    section is promoted. The pre-pass builds that layer exactly as the loader
    does.
    """
    assert _extract(
        {
            "PDK": "alpha",
            "TOOLS": {"synthesis": "yosys"},
            "pdk::beta": {"TOOLS": {"synthesis": "genus"}},
        },
        overrides=["PDK=beta"],
        pdk_root=two_pdks,
        design_dir=str(tmp_path),
    ) == {"synthesis": "genus"}


def test_a_command_line_tools_override_beats_a_scoped_section(two_pdks, tmp_path):
    assert _extract(
        {"pdk::alpha": {"TOOLS": {"synthesis": "genus"}}},
        overrides=[f"TOOLS={json.dumps({'synthesis': 'yosys'})}"],
        pdk="alpha",
        pdk_root=two_pdks,
        design_dir=str(tmp_path),
    ) == {"synthesis": "yosys"}


def test_a_section_that_cannot_reach_tools_is_not_resolved(tmp_path):
    """
    Scoping an ordinary variable per PDK is the common idiom, and ``TOOLS`` is
    the only key read here, so such a section is no reason to resolve a
    process. The unreadable PDK root is what shows none was: refusing to read
    ``TOOLS`` at all until a PDK is installed would be a new demand made by the
    pass that needs it least.
    """
    path = tmp_path / "other.yaml"
    path.write_text("PDK: beta\n", encoding="utf8")

    assert _extract(
        {
            "TOOLS": {"synthesis": "yosys"},
            "pdk::alpha": {"FP_CORE_UTIL": 40},
        },
        path,
        pdk="alpha",
        pdk_root="/nonexistent",
        design_dir=str(tmp_path),
    ) == {"synthesis": "yosys"}


def test_a_section_nested_two_deep_still_reaches_tools(two_pdks, tmp_path):
    """
    An ``scl::`` block inside a matching ``pdk::`` block promotes its keys two
    levels, into the top-level mapping, so it scopes ``TOOLS`` as directly as a
    top-level section does.
    """
    assert _extract(
        {
            "TOOLS": {"synthesis": "yosys"},
            "pdk::alpha": {"scl::alpha_scl": {"TOOLS": {"synthesis": "genus"}}},
        },
        pdk="alpha",
        pdk_root=two_pdks,
        design_dir=str(tmp_path),
    ) == {"synthesis": "genus"}


def test_a_tools_under_some_other_key_of_a_section_is_not_scoped_tools(tmp_path):
    """
    What a section promotes is its own keys. A ``TOOLS`` under a further key
    inside it lands under that key, never at the top level, so it is not a
    scoped selection and resolving a process would tell nobody anything.
    """
    assert _extract(
        {
            "TOOLS": {"synthesis": "yosys"},
            "pdk::alpha": {"SOME_MACRO": {"TOOLS": {"synthesis": "genus"}}},
        },
        pdk="alpha",
        pdk_root="/nonexistent",
        design_dir=str(tmp_path),
    ) == {"synthesis": "yosys"}


def test_a_section_with_no_pdk_named_raises_the_loaders_own_error(tmp_path):
    """
    The message is ``Config.load``'s, because it is raised by the same call the
    loader makes. A pre-pass with a refusal of its own would report the missing
    PDK in one wording here and another one line later.
    """
    with pytest.raises(ValueError, match="The pdk argument is required"):
        _extract(
            {"pdk::alpha": {"TOOLS": {"synthesis": "genus"}}},
            design_dir=str(tmp_path),
        )


def test_no_section_reads_tools_without_resolving_a_pdk():
    """
    Expanding a mapping that carries no section returns that mapping, so there
    is nothing a PDK could change about the answer -- and asking for one would
    make tool selection demand an installed PDK before the loader that needs it
    ever runs. The unreadable root is what shows none was consulted.
    """
    assert _extract(
        {"TOOLS": {"synthesis": "genus"}},
        pdk="nonexistent",
        pdk_root="/nonexistent",
    ) == {"synthesis": "genus"}


def test_the_selection_and_the_loader_agree_on_a_scoped_tools(two_pdks, tmp_path):
    """
    The consistency check that closes the loop. Both readings of one
    configuration are taken here and compared: what tool selection sees, and
    what the resolved configuration -- which is what ``--explain-variables``
    prints -- ends up holding.
    """

    from librelane.config import Config, Variable

    design = {
        "DESIGN_NAME": "x",
        "TOOLS": {"synthesis": "yosys"},
        "scl::alpha_scl": {"TOOLS": {"synthesis": "genus"}},
    }
    resolved, _ = Config.load(
        design,
        [
            Variable("DESIGN_NAME", str, description="x"),
            Variable("STD_CELL_LIBRARY", str, description="x", pdk=True),
            Variable("TOOLS", dict[str, str] | None, description="x"),
        ],
        design_dir=str(tmp_path),
        pdk="alpha",
        pdk_root=two_pdks,
    )
    selected = _extract(
        design,
        pdk="alpha",
        pdk_root=two_pdks,
        design_dir=str(tmp_path),
    )

    assert selected == {"synthesis": "genus"}
    assert resolved["TOOLS"] == selected


def test_a_tcl_source_is_not_a_configuration(tmp_path):
    """
    Design '.tcl' configurations are gone, so one reaching the pre-pass is an
    unreadable source rather than a source read as empty.
    """
    path = tmp_path / "config.tcl"
    path.write_text("set ::env(TOOLS) whatever\n", encoding="utf8")

    with pytest.raises(ValueError, match="Unsupported configuration source"):
        _extract(path)
