# Copyright 2026 LibreLane Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
``include``: what one document takes from another, and what it refuses to.

The documents here are written as YAML text rather than as mappings, unlike
most of ``test_spec.py``: an include is a path resolved against the file that
wrote it, so a case that never writes a file cannot exercise one.
"""

import json
import os
import textwrap
from pathlib import Path

import pytest

from librelane.engine.spec_include import common_directory
from librelane.engine.spec import FlowSpec, FlowSpecError, load_flow_spec
from librelane.engine.spec_include import (
    _FLOW_KEYS,
    COMMON_PREFIX,
    INCLUDE_KEY,
    common_library,
)

pytestmark = pytest.mark.all


def _write(directory: Path, name: str, text: str) -> str:
    path = directory / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text), encoding="utf8")
    return str(path)


#: A one-job document, as the thing an include is added to.
_ROOT = """
name: Root
jobs:
  synthesis:
    steps: [Yosys.Synthesis]
"""


def test_the_key_list_is_the_model_s_own():
    """
    ``spec_include`` cannot import ``FlowSpec`` -- ``spec`` imports it, to
    resolve a document before it can build one -- so its list of legal
    top-level keys is written out. This is what keeps the copy honest.
    """
    aliased = {field.alias or name for name, field in FlowSpec.model_fields.items()} | {
        INCLUDE_KEY
    }

    assert set(_FLOW_KEYS) == aliased


def test_an_include_contributes_every_section_a_document_has(tmp_path):
    _write(
        tmp_path,
        "shared.yaml",
        """
        config:
          - name: RUN_CTS
            type: bool
            default: true
            description: Enables clock tree synthesis.
        with:
          CLOCK_PERIOD: 10
        resources:
          seats: 2
        final: cts
        jobs:
          cts:
            needs: [synthesis]
            steps: [OpenROAD.CTS]
            if: RUN_CTS
            resources: [seats]
        """,
    )
    document = _write(tmp_path, "flow.yaml", _ROOT + "\ninclude: [./shared.yaml]\n")

    spec = load_flow_spec(document)

    assert spec.name == "Root"
    assert sorted(spec.jobs) == ["cts", "synthesis"]
    assert [variable.name for variable in spec.config] == ["RUN_CTS"]
    assert spec.values == {"CLOCK_PERIOD": 10}
    assert spec.resources == {"seats": 2}
    assert spec.final == "cts"


def test_a_document_overrides_a_job_it_includes(tmp_path):
    """
    Whole, not key by key: a reader who sees ``uses`` in an override should not
    have to open another file to find the ``if`` that survived underneath it.
    """
    _write(
        tmp_path,
        "shared.yaml",
        """
        config:
          - name: RUN_CTS
            type: bool
            default: true
            description: Enables clock tree synthesis.
        jobs:
          cts:
            needs: [synthesis]
            steps: [OpenROAD.CTS]
            if: RUN_CTS
        """,
    )
    document = _write(
        tmp_path,
        "flow.yaml",
        """
        name: Root
        include: [./shared.yaml]
        jobs:
          synthesis:
            steps: [Yosys.Synthesis]
          cts:
            needs: [synthesis]
            uses: cts
        """,
    )

    spec = load_flow_spec(document)

    assert spec.jobs["cts"].uses == "cts"
    assert spec.jobs["cts"].steps is None
    assert spec.jobs["cts"].condition is None


def test_a_document_overrides_a_variable_where_its_include_declares_it(tmp_path):
    """
    In place, so that overriding one default does not move the variable to the
    end of a list the include otherwise orders.
    """
    _write(
        tmp_path,
        "shared.yaml",
        """
        config:
          - name: A
            type: bool
            default: true
            description: The first.
          - name: B
            type: bool
            default: true
            description: The second.
        """,
    )
    document = _write(
        tmp_path,
        "flow.yaml",
        _ROOT
        + """
include: [./shared.yaml]
config:
  - name: B
    type: bool
    default: false
    description: Overridden.
  - name: C
    type: bool
    default: true
    description: Added.
""",
    )

    spec = load_flow_spec(document)

    assert [variable.name for variable in spec.config] == ["A", "B", "C"]
    assert [variable.default for variable in spec.config] == [True, False, True]
    assert spec.config[1].description == "Overridden."


def test_an_include_s_own_name_and_description_are_ignored(tmp_path):
    """
    A flow is registered and selected under one name. A fragment may still
    carry one, which is what lets an editor validate it as a document.
    """
    _write(
        tmp_path,
        "shared.yaml",
        """
        name: NotTheFlow
        description: Not the flow's description either.
        jobs:
          cts:
            needs: [synthesis]
            steps: [OpenROAD.CTS]
        """,
    )
    document = _write(
        tmp_path,
        "flow.yaml",
        """
name: Root
description: The flow's own.
include: [./shared.yaml]
jobs:
  synthesis:
    steps: [Yosys.Synthesis]
""",
    )

    spec = load_flow_spec(document)

    assert spec.name == "Root"
    assert spec.description == "The flow's own."


def test_a_document_being_loaded_still_needs_a_name(tmp_path):
    """
    The requirement the JSON Schema drops, and the loader keeps: a file with no
    name is a legal include and not a flow.
    """
    document = _write(
        tmp_path,
        "flow.yaml",
        """
jobs:
  synthesis:
    steps: [Yosys.Synthesis]
""",
    )

    with pytest.raises(FlowSpecError) as exc_info:
        load_flow_spec(document)

    assert "name" in str(exc_info.value)


def test_a_document_may_declare_no_jobs_of_its_own(tmp_path):
    _write(
        tmp_path,
        "shared.yaml",
        """
        jobs:
          synthesis:
            steps: [Yosys.Synthesis]
        """,
    )
    document = _write(tmp_path, "flow.yaml", "name: Root\ninclude: [./shared.yaml]\n")

    assert list(load_flow_spec(document).jobs) == ["synthesis"]


def test_an_include_may_itself_include(tmp_path):
    _write(
        tmp_path,
        "variables.yaml",
        """
        config:
          - name: RUN_CTS
            type: bool
            default: true
            description: Enables clock tree synthesis.
        """,
    )
    _write(
        tmp_path,
        "jobs.yaml",
        """
        include: [./variables.yaml]
        jobs:
          cts:
            needs: [synthesis]
            steps: [OpenROAD.CTS]
            if: RUN_CTS
        """,
    )
    document = _write(tmp_path, "flow.yaml", _ROOT + "\ninclude: [./jobs.yaml]\n")

    spec = load_flow_spec(document)

    assert sorted(spec.jobs) == ["cts", "synthesis"]
    assert [variable.name for variable in spec.config] == ["RUN_CTS"]


def test_a_file_reached_twice_is_merged_once(tmp_path):
    """
    The diamond. Two includes both reaching one file is not two declarations of
    what that file declares, so it is not the conflict below.
    """
    _write(
        tmp_path,
        "variables.yaml",
        """
        config:
          - name: RUN_CTS
            type: bool
            default: true
            description: Enables clock tree synthesis.
        """,
    )
    _write(tmp_path, "jobs.yaml", "include: [./variables.yaml]\n")
    document = _write(
        tmp_path,
        "flow.yaml",
        _ROOT + "\ninclude: [./jobs.yaml, ./variables.yaml]\n",
    )

    assert [variable.name for variable in load_flow_spec(document).config] == [
        "RUN_CTS"
    ]


@pytest.mark.parametrize(
    "order", ["./overrides.yaml, ./plain.yaml", "./plain.yaml, ./overrides.yaml"]
)
def test_an_arm_of_a_diamond_that_overrides_the_shared_file_collides(tmp_path, order):
    """
    Both arms reach ``shared.yaml``; one of them replaces what it declares. The
    document then has two values for one key and no rule for which wins, and
    which arm was written first is not that rule.
    """
    _write(tmp_path, "shared.yaml", "with:\n  CLOCK_PERIOD: 10\n")
    _write(
        tmp_path,
        "overrides.yaml",
        "include: [./shared.yaml]\nwith:\n  CLOCK_PERIOD: 20\n",
    )
    _write(tmp_path, "plain.yaml", "include: [./shared.yaml]\n")
    document = _write(tmp_path, "flow.yaml", _ROOT + f"\ninclude: [{order}]\n")

    with pytest.raises(FlowSpecError) as exc_info:
        load_flow_spec(document)

    assert "a value for 'CLOCK_PERIOD'" in str(exc_info.value)


#: The four sections two includes can collide in, each as the text the two
#: files declare and the words the message is expected to reach for.
_CLASHES = {
    "a job": (
        "jobs:\n  cts:\n    steps: [OpenROAD.CTS]\n",
        "job 'cts'",
    ),
    "a variable": (
        "config:\n  - name: A\n    type: bool\n    default: true\n"
        "    description: A.\n",
        "configuration variable 'A'",
    ),
    "a value": (
        "with:\n  CLOCK_PERIOD: 10\n",
        "a value for 'CLOCK_PERIOD'",
    ),
    "a resource pool": (
        "resources:\n  seats: 2\n",
        "resource pool 'seats'",
    ),
    "a final job": (
        "final: synthesis\n",
        "'final'",
    ),
}


@pytest.mark.parametrize(
    ("declaration", "described"), _CLASHES.values(), ids=list(_CLASHES)
)
def test_two_includes_may_not_declare_the_same_thing(tmp_path, declaration, described):
    _write(tmp_path, "one.yaml", declaration)
    _write(tmp_path, "two.yaml", declaration)
    document = _write(
        tmp_path, "flow.yaml", _ROOT + "\ninclude: [./one.yaml, ./two.yaml]\n"
    )

    with pytest.raises(FlowSpecError) as exc_info:
        load_flow_spec(document)

    message = str(exc_info.value)
    assert described in message
    assert "one.yaml" in message
    assert "two.yaml" in message


def test_the_including_document_settles_what_two_includes_disagree_on(tmp_path):
    """
    The way out the conflict names: nothing orders two includes, and the
    document that names them both does.
    """
    _write(tmp_path, "one.yaml", "with:\n  CLOCK_PERIOD: 10\n")
    _write(tmp_path, "two.yaml", "with:\n  CLOCK_PERIOD: 20\n")
    document = _write(
        tmp_path,
        "flow.yaml",
        _ROOT + "\ninclude: [./one.yaml, ./two.yaml]\nwith:\n  CLOCK_PERIOD: 30\n",
    )

    with pytest.raises(FlowSpecError):
        load_flow_spec(document)


def test_an_include_cycle_is_refused_with_the_path_that_closes_it(tmp_path):
    _write(tmp_path, "a.yaml", _ROOT + "\ninclude: [./b.yaml]\n")
    _write(tmp_path, "b.yaml", "include: [./a.yaml]\n")

    with pytest.raises(FlowSpecError) as exc_info:
        load_flow_spec(str(tmp_path / "a.yaml"))

    message = str(exc_info.value)
    assert "cycle" in message
    assert f"a.yaml -> {tmp_path}/b.yaml -> {tmp_path}/a.yaml" in message


def test_a_document_may_not_include_itself(tmp_path):
    document = _write(tmp_path, "flow.yaml", _ROOT + "\ninclude: [./flow.yaml]\n")

    with pytest.raises(FlowSpecError, match="cycle"):
        load_flow_spec(document)


def test_a_relative_include_resolves_against_the_document_not_the_caller(
    tmp_path, monkeypatch
):
    """
    A document and the files it reuses travel together; where it is run from is
    not their business.
    """
    _write(
        tmp_path,
        "flows/shared.yaml",
        "jobs:\n  cts:\n    needs: [synthesis]\n    steps: [OpenROAD.CTS]\n",
    )
    document = _write(
        tmp_path, "flows/flow.yaml", _ROOT + "\ninclude: [./shared.yaml]\n"
    )
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    assert sorted(load_flow_spec(document).jobs) == ["cts", "synthesis"]


def test_an_include_may_be_an_absolute_path(tmp_path):
    shared = _write(
        tmp_path,
        "shared.yaml",
        "jobs:\n  cts:\n    needs: [synthesis]\n    steps: [OpenROAD.CTS]\n",
    )
    document = _write(tmp_path, "flow.yaml", _ROOT + f"\ninclude: ['{shared}']\n")

    assert sorted(load_flow_spec(document).jobs) == ["cts", "synthesis"]


def test_a_document_loaded_from_a_mapping_has_no_relative_paths(tmp_path):
    with pytest.raises(FlowSpecError) as exc_info:
        load_flow_spec(
            {
                "name": "Root",
                "include": ["./shared.yaml"],
                "jobs": {"synthesis": {"steps": ["Yosys.Synthesis"]}},
            }
        )

    assert "no directory to resolve it against" in str(exc_info.value)


def test_a_document_loaded_from_a_mapping_may_include_an_absolute_path(tmp_path):
    shared = _write(
        tmp_path,
        "shared.yaml",
        "jobs:\n  cts:\n    needs: [synthesis]\n    steps: [OpenROAD.CTS]\n",
    )

    spec = load_flow_spec(
        {
            "name": "Root",
            "include": [shared],
            "jobs": {"synthesis": {"steps": ["Yosys.Synthesis"]}},
        }
    )

    assert sorted(spec.jobs) == ["cts", "synthesis"]


def test_the_common_library_is_what_the_package_holds():
    """
    Read off the installation rather than written out, so the list an error
    message and the schema both quote is the library this LibreLane ships.
    """
    assert common_library() == sorted(
        path.name
        for path in common_directory().iterdir()
        if path.name.endswith((".yaml", ".yml", ".json"))
    )


def test_the_common_directive_names_a_file_librelane_ships(tmp_path):
    """
    The library has no path a document can write: LibreLane lives wherever it
    was installed. ``common::`` is answered by the installation instead.
    """
    document = _write(
        tmp_path,
        "flow.yaml",
        _ROOT + f"\ninclude: [{COMMON_PREFIX}classic_config.yaml]\n",
    )

    spec = load_flow_spec(document)

    assert "RUN_CTS" in [variable.name for variable in spec.config]


def test_the_common_directive_needs_no_directory_to_resolve_against(tmp_path):
    """
    The one form a document loaded from a mapping can still write, where a
    relative path has nothing to be relative to.
    """
    spec = load_flow_spec(
        {
            "name": "Root",
            "include": [f"{COMMON_PREFIX}classic_config.yaml"],
            "jobs": {"synthesis": {"steps": ["Yosys.Synthesis"]}},
        }
    )

    assert "RUN_CTS" in [variable.name for variable in spec.config]


def test_a_common_entry_the_library_does_not_have_lists_what_it_does(tmp_path):
    document = _write(
        tmp_path, "flow.yaml", _ROOT + f"\ninclude: [{COMMON_PREFIX}nope.yaml]\n"
    )

    with pytest.raises(FlowSpecError) as exc_info:
        load_flow_spec(document)

    message = str(exc_info.value)
    assert "nope.yaml" in message
    assert "classic_config.yaml" in message


@pytest.mark.parametrize(
    "entry",
    ["", "../classic.yaml", "nested/classic_config.yaml"],
    ids=["nothing", "a way out", "a subdirectory"],
)
def test_a_common_entry_names_one_file_and_not_a_path(tmp_path, entry):
    """
    The library is one flat directory. A separator in the name would be a
    document reaching somewhere the directive does not go, and is refused
    rather than followed.
    """
    document = _write(
        tmp_path, "flow.yaml", _ROOT + f"\ninclude: ['{COMMON_PREFIX}{entry}']\n"
    )

    with pytest.raises(FlowSpecError, match="flat directory"):
        load_flow_spec(document)


def test_the_common_library_and_a_path_to_it_are_one_file(tmp_path):
    """
    Reached both ways at once. The merge keys on the real path, so the
    directive is a way of naming the file and not a second copy of it.
    """
    library = str(common_directory().joinpath("classic_config.yaml"))
    document = _write(
        tmp_path,
        "flow.yaml",
        _ROOT + f"\ninclude: [{COMMON_PREFIX}classic_config.yaml, '{library}']\n",
    )

    names = [variable.name for variable in load_flow_spec(document).config]

    assert len(names) == len(set(names))


def test_an_include_may_be_json(tmp_path):
    _write(
        tmp_path,
        "shared.json",
        json.dumps({"jobs": {"cts": {"needs": ["synthesis"], "uses": "cts"}}}),
    )
    document = _write(tmp_path, "flow.yaml", _ROOT + "\ninclude: [./shared.json]\n")

    assert sorted(load_flow_spec(document).jobs) == ["cts", "synthesis"]


def test_a_missing_include_names_the_document_that_wrote_it(tmp_path):
    _write(tmp_path, "a.yaml", _ROOT + "\ninclude: [./b.yaml]\n")
    _write(tmp_path, "b.yaml", "include: [./nowhere.yaml]\n")

    with pytest.raises(FlowSpecError) as exc_info:
        load_flow_spec(str(tmp_path / "a.yaml"))

    message = str(exc_info.value)
    assert "b.yaml" in message
    assert "./nowhere.yaml" in message


def test_a_file_that_is_not_a_document_is_refused(tmp_path):
    _write(tmp_path, "values.tcl", "set A 1\n")
    document = _write(tmp_path, "flow.yaml", _ROOT + "\ninclude: [./values.tcl]\n")

    with pytest.raises(FlowSpecError) as exc_info:
        load_flow_spec(document)

    assert "values.tcl" in str(exc_info.value)


def test_an_empty_include_is_refused(tmp_path):
    _write(tmp_path, "shared.yaml", "")
    document = _write(tmp_path, "flow.yaml", _ROOT + "\ninclude: [./shared.yaml]\n")

    with pytest.raises(FlowSpecError) as exc_info:
        load_flow_spec(document)

    assert "shared.yaml" in str(exc_info.value)
    assert "not a mapping" in str(exc_info.value)


def test_an_unknown_key_names_the_file_that_wrote_it(tmp_path):
    _write(tmp_path, "shared.yaml", "jobz:\n  cts:\n    uses: cts\n")
    document = _write(tmp_path, "flow.yaml", _ROOT + "\ninclude: [./shared.yaml]\n")

    with pytest.raises(FlowSpecError) as exc_info:
        load_flow_spec(document)

    message = str(exc_info.value)
    assert "shared.yaml" in message
    assert "jobz" in message


def test_a_document_error_names_the_files_merged_into_it(tmp_path):
    """
    A key merged out of an include is not written in the document being
    loaded, so the message says which files it could be in.
    """
    _write(tmp_path, "shared.yaml", "jobs:\n  cts:\n    nonsense: 1\n")
    document = _write(tmp_path, "flow.yaml", _ROOT + "\ninclude: [./shared.yaml]\n")

    with pytest.raises(FlowSpecError) as exc_info:
        load_flow_spec(document)

    message = str(exc_info.value)
    assert "flow.yaml" in message
    assert "shared.yaml" in message


def test_a_document_that_includes_nothing_is_named_alone(tmp_path):
    document = _write(tmp_path, "flow.yaml", "name: Root\njobs:\n  cts:\n    x: 1\n")

    with pytest.raises(FlowSpecError) as exc_info:
        load_flow_spec(document)

    assert "including" not in str(exc_info.value)


#: The shapes an ``include`` itself may not have.
_MALFORMED = {
    "a bare path": "include: ./shared.yaml\n",
    "a mapping": "include:\n  shared: ./shared.yaml\n",
    "an entry that is not a path": "include: [2]\n",
    "the same document twice": "include: [./shared.yaml, ./shared.yaml]\n",
}


@pytest.mark.parametrize("declaration", _MALFORMED.values(), ids=list(_MALFORMED))
def test_a_malformed_include_is_refused(tmp_path, declaration):
    _write(tmp_path, "shared.yaml", "with:\n  CLOCK_PERIOD: 10\n")
    document = _write(tmp_path, "flow.yaml", _ROOT + "\n" + declaration)

    with pytest.raises(FlowSpecError, match="include"):
        load_flow_spec(document)


def test_an_include_that_reached_the_model_is_an_unloaded_document():
    """
    ``FlowSpec`` is the merged document, so a model asked to validate one that
    still declares an ``include`` is one nothing has read the includes of.
    """
    with pytest.raises(FlowSpecError) as exc_info:
        FlowSpec.model_validate(
            {
                "name": "Root",
                "include": ["./shared.yaml"],
                "jobs": {"synthesis": {"steps": ["Yosys.Synthesis"]}},
            }
        )

    assert "load_flow_spec" in str(exc_info.value)


def test_a_symlinked_include_is_the_file_it_points_at(tmp_path):
    """
    Reached twice down two names, and still one file: the merge keys on the
    real path, so a symlink is not a second declaration of what it points at.
    """
    _write(tmp_path, "shared.yaml", "with:\n  CLOCK_PERIOD: 10\n")
    os.symlink(tmp_path / "shared.yaml", tmp_path / "alias.yaml")
    document = _write(
        tmp_path, "flow.yaml", _ROOT + "\ninclude: [./shared.yaml, ./alias.yaml]\n"
    )

    assert load_flow_spec(document).values == {"CLOCK_PERIOD": 10}
