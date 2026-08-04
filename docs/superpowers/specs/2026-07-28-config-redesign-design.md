# Config Module Redesign

**Status:** Design approved, ready for planning
**Date:** 2026-07-28
**Tracks:** Supersedes the gated Pydantic item in Track 5 of the
[modernization roadmap](../plans/2026-07-28-modernization-roadmap.md)
**Upstream:** Implements [librelane/librelane#911](https://github.com/librelane/librelane/issues/911)

## Problem

The configuration module has two structural faults.

**Parsing is hand-rolled.** `Variable.__process` (`librelane/config/variable.py:517-793`)
is a 276-line recursive validator that re-implements optionality, unions,
dataclasses, enums, literals, defaults, and scalar coercion. `preprocessor.py`
dispatches a string micro-language by `str.startswith()` plus one regular
expression, and walks nested dictionaries by hand. Only `expr::` has been moved
onto a real parser.

**The system is stringy.** `Config` is a `GenericImmutableDict[str, Any]`. The
469 `Variable(...)` declarations carry real Python type objects, but that type
information is discarded the moment a step reads a value. All 314
`self.config["KEY"]` subscripts and 15 `self.config.get(...)` calls in
`librelane/` return `Any`. Neither mypy nor an editor can catch a misspelled
key, a wrong-typed comparison, or an invalid `Literal`.

Upstream agrees. Issue #911, filed by the maintainer, states that "everything
about the `Config` class is a bit too complex" and names the `dir::` hack
specifically.

## Goals

1. Replace hand-rolled validation with Pydantic, keeping every LibreLane-specific
   semantic that Pydantic does not provide natively.
2. Give steps statically-typed configuration access.
3. Replace the hand-rolled preprocessor with one Lark grammar plus explicit
   resolution passes.
4. Fix the upstream issues that this rework makes cheap, and design hooks for
   the ones it makes possible.

## Scope

In scope, as a single project:

| Part | Content |
| --- | --- |
| P1 | Typed core. Type vocabulary, `BaseConfigModel`, `variable()`, `Variable` shim. |
| P2 | Preprocessor. Lark grammar, resolver registry, overlays, symbol graph. |
| P3 | Load pipeline. Sources, layering, PDK loading, validation, diagnostics. |

Out of scope, each getting its own spec later:

| Part | Content |
| --- | --- |
| P4 | Step migration. 469 declarations to model fields, 329 accesses to attributes. |
| P5 | Documentation and JSON Schema generation from model fields. |

## Constraints

These are hard and non-negotiable.

- **The user configuration file format does not change.** JSON, YAML and Tcl
  files with flat `UPPER_SNAKE_CASE` keys and the
  `dir::`/`pdk_dir::`/`ref::`/`refg::`/`expr::`/`pdk::`/`scl::` language must
  keep working exactly as they do today. Designs in the wild must not break.
- **PDK ingestion does not change.** PDKs ship
  `libs.tech/librelane/config.tcl` evaluated through a Tcl interpreter. That
  path stays, including the `libs.tech/openlane/` fallback and
  `migrate_old_config`.
- **The flat variable namespace stays.** It is required by both of the above.

These get a deprecation path rather than a break.

- The `Config` public Python API and the exported `Variable` class.
- The 329 `self.config["KEY"]` and `self.config.get(...)` access sites.

Inherited from the modernization roadmap:

- Apache-2.0 compatible dependencies only. Pydantic is MIT, so it qualifies.
- Python floor is `>=3.13`, raised from `>=3.10` after this spec was written.
  No `from __future__ import annotations`.
- Any `pyproject.toml` dependency change requires a matching `default.nix`
  change in the same commit.

## Upstream issues

Fixed by construction.

| Issue | Resolution |
| --- | --- |
| #911 Rearchitecting the config module | The project itself. |
| #993 Union coercion under lax typing | Pydantic smart-union. Verified: `Union[int, bool, str]` given `"true"` yields `"true"`, not `1`. This is exactly the "most specific type, with `str` as fallback" behavior the issue asks for. |
| #712 Multiple globs into a `list[Path]` | Glob resolution moves out of the preprocessor into the type layer, which is the fix the issue itself proposes. Retires the `Variable.__flatten_list` hack. |

Committed as part of this spec.

| Issue | Resolution |
| --- | --- |
| #779, #410 Config warnings never reach the flow log | `Config.load` stops logging eagerly and attaches diagnostics to the returned object. `Flow.start` replays them after its sinks exist. |
| #401 Warning severity levels | `Diagnostic.severity` and `Diagnostic.category`. |
| #827 `STD_CELL_LIBRARY` honored only in the first config file | Process info is resolved from the merged mapping of all sources before the PDK is loaded. |

Enabled but explicitly deferred: #754 (unsafe variables), #600 (portable
states), #641 (PDK default documentation), #996 (unit clarity), #318 (consistent
naming), #599 (`Path` and `pathlib` unification, Track 7), #697 (do not assume a
PDK), #813 and #999 (making individual variables optional), #769 (STA corner
override, needs its own reproduction).

## Architecture

The current `variable.py` is three unrelated concerns in one file. Splitting it
is a prerequisite, not a side effect. It also resolves the name clash that would
otherwise exist between a `variable` module and a `variable()` function bound at
package level.

```
librelane/config/
  diagnostics.py      Diagnostic, Severity, DiagnosticSet
  types.py            Path and enum core schemas, shape coercion,
                      Orientation, Instance, Macro
  model.py            BaseConfigModel, variable()
  legacy.py           DEPRECATED. Variable, MissingRequiredVariable,
                      repr_type, table rendering, and the old __process
                      implementation retained for the verification gate.
  preprocessor/
    grammar.lark      the whole string language, in one place
    ast.py            parsed node types
    resolve.py        Transformer per directive
    overlay.py        pdk:: and scl:: conditional merge
    graph.py          topological symbol resolution
  loading/
    sources.py        JSON, YAML and Tcl readers, producing raw mapping
                      plus provenance
    pdk.py            PDK, SCL and PAD discovery, Tcl evaluation, migration
    layering.py       multi-source merge and process-info resolution
    loader.py         Config.load orchestration
  config.py           Config and Meta
  pdk_compat.py       unchanged
  removals.py         unchanged
```

`variable.py` ceases to exist. It is referenced by module path in only three
internal files and two of our own tests. The API Stability Policy scopes the API
to documented functions, classes, methods and properties, and `Variable` remains
reachable at its documented location `librelane.config.Variable`.

## P1. Typed core

### The central insight

`Variable.__process` is long because it recurses through the entire type tree.
Almost none of that work is LibreLane-specific. Exactly three things are.

1. **Structural Tcl coercion.** A string becomes a list, a flat string or list
   becomes a dictionary. This needs only the *container* shape, not the full
   type tree.
2. **Path glob semantics.** A single-element glob match unwraps to a scalar, and
   multiple globs feeding a `list[Path]` flatten.
3. **Enum lookup by name.** Pydantic looks up by value.

Item 1 becomes one `model_validator(mode="before")` on the base model. Items 2
and 3 live in the types themselves through `__get_pydantic_core_schema__`, so
declaration sites stay plain. A step author writes `list[Path]`, never a special
alias. When #599 replaces `common.Path` with `pathlib.Path`, exactly one method
changes.

### Shape coercion

The complete replacement for the container-handling portion of `__process`.
Verified working against Pydantic 2.13.4.

```python
def _shape(value, ann, split_strings: bool):
    """Structural coercion only. No scalar validation, enums, unions or defaults."""
    ann = _unwrap_optional(ann)
    origin, args = get_origin(ann), get_args(ann)
    if origin in (list, tuple):
        if split_strings and isinstance(value, str):
            value = value.split(",") if "," in value else TclUtils.split(value)
            if value and value[-1] == "":
                value.pop()                       # trailing separator
        if isinstance(value, (list, tuple)):
            if args and args[0] is Path:          # issue #712, always applied
                value = [i for x in value for i in (x if isinstance(x, list) else [x])]
            return [_shape(v, args[0], split_strings) for v in value] if args else value
    elif origin is dict:
        if split_strings and isinstance(value, str):
            value = TclUtils.split(value)
        if split_strings and isinstance(value, list):
            if len(value) % 2:
                raise ValueError(f"uneven Tcl dictionary ({len(value)} components)")
            value = dict(zip(value[::2], value[1::2]))
        if isinstance(value, dict) and args:
            return {k: _shape(v, args[1], split_strings) for k, v in value.items()}
    return value
```

It recurses because nested shapes genuinely occur. `dict[str, list[Path]]` from
a Tcl PDK configuration arrives as `{"nom_tt*": "/l/a.lib /l/b.lib"}`, so the
value needs splitting one level down.

The two behaviors compose through the `split_strings` flag rather than through
two separate passes. Tcl string splitting happens only for permissive keys. Glob
flattening happens on every key, because a `GlobMatch` can reach a `list[Path]`
field regardless of typing strictness, so `_shape` is called for every field and
only the string-splitting branches are gated.

```python
class BaseConfigModel(BaseModel):
    @model_validator(mode="before")
    @classmethod
    def _coerce_shapes(cls, data, info: ValidationInfo):
        if not isinstance(data, dict):
            return data
        ctx = info.context or {}
        permissive = bool(ctx.get("permissive"))
        permissive_keys = ctx.get("permissive_keys", frozenset())
        out = {}
        for key, value in data.items():
            field = cls.model_fields.get(key)
            if field is None or value is None:
                out[key] = value                  # extras handled in P3
                continue
            out[key] = _shape(
                value,
                field.annotation,
                split_strings=permissive or key in permissive_keys,
            )
        return out
```

`permissive_keys` exists so command-line `--override KEY=VALUE` values, which
are always strings, can be coerced without downgrading the entire configuration
to lax typing. Today a single `--override` forces `permissive_typing=True` across
the whole config, silently defeating `meta.version: 2` strictness.

### Types carrying their own semantics

```python
class Path(UserString):
    @classmethod
    def __get_pydantic_core_schema__(cls, source, handler):
        def validate(v):
            if isinstance(v, GlobMatch):
                if len(v) == 1:
                    return cls(v[0])
                if len(v) == 0:
                    return cls(v.literal)         # today's unglobbed fallback
                raise ValueError(f"expected one path, glob matched {len(v)}")
            return cls(str(v))
        return core_schema.no_info_plain_validator_function(
            validate,
            serialization=core_schema.plain_serializer_function_ser_schema(
                str, when_used="json"
            ),
        )
```

Enums that look up by name inherit a `ByNameEnum` base providing the same hook.
`Orientation`'s OpenAccess aliases (`R0` for `N`, `MY` for `FN`) continue to work
because Python resolves them at class definition time.

### Declaring configuration

```python
from librelane.config import variable

class Floorplan(OpenROADStep):
    class Config(OpenROADStep.Config):
        FP_TRACKS_INFO: Path = variable(
            description="Tracks info file.", pdk=True
        )
        FP_SIZING: Literal["absolute", "relative"] = variable(
            "relative", description="Whether sizing is absolute or relative."
        )
        FP_CORE_UTIL: Decimal = variable(
            50, description="Core utilization percentage.", units="%"
        )
        TRISTATE_CELLS: list[str] | None = variable(
            None,
            description="Cell names or wildcards of tri-state buffers.",
            pdk=True,
            deprecated_names=[("TRISTATE_CELL_PREFIX", _prefix_to_wildcard)],
        )

    def run(self):
        path = self.config.FP_TRACKS_INFO       # typed as Path, statically
```

`variable()` is a thin wrapper over `pydantic.Field`. It maps `units`, `pdk` and
`unsafe` into `json_schema_extra`, where they survive into a generated JSON
Schema, and maps `deprecated_names` into either `AliasChoices` for plain renames
or a callable-alias validator for transforming renames such as
`_prefix_to_wildcard`. All three mechanisms are verified working.

The lowercase `variable()` function and the deprecated uppercase `Variable`
class coexist the way factory functions and classes conventionally do in Python.

### Two-layer validation

The flat namespace is required by the hard constraints, so it stays. Validation
happens at two levels.

- **Flow level.** A union model synthesized with `create_model` from every
  step's `Config` plus the universal flow variables. This is what `Config`
  wraps, what produces `resolved.json`, and what is hashed for caching.
- **Step level.** `Step.start` validates the flat mapping into that step's own
  `Config` model. Typed attribute access is per-step. Serialization and hashing
  stay flat.

This mirrors what `copy_filtered` and `with_increment` already do, so caching
and `resolved.json` semantics are unchanged.

## P2. Preprocessor

### Grammar

One grammar covers the entire string micro-language, with the existing `expr::`
arithmetic rules folded in rather than living separately.

```lark
?directive : expr_d | refg_d | ref_d | dir_d | pdk_dir_d
expr_d    : "expr::"     sum
ref_d     : "ref::"      interp
refg_d    : "refg::"     interp
dir_d     : "dir::"      PATH_REST
pdk_dir_d : "pdk_dir::"  PATH_REST
interp    : VARREF PATH_REST?
VARREF    : /\$[A-Za-z_][A-Za-z0-9_.\[\]]*/
```

`dir_d` and `pdk_dir_d` desugar at the AST level into `refg::$DESIGN_DIR/...` and
`refg::$PDKPATH/...`, preserving current behavior.

A string with no recognized prefix is never parsed. A cheap prefix check runs
first, then the string passes through unchanged. An unrecognized `foo::bar`
passes through **silently**. It must not warn, because Tcl namespaces and
SystemVerilog scope resolution (`pkg::type`) legitimately contain `::` and a
"did you mean" diagnostic would fire on valid configuration values.

### Glob resolution moves to the type layer

`refg::` yields a `GlobMatch` marker rather than a bare list. The declared type
resolves the ambiguity.

| Field type | Behavior |
| --- | --- |
| `Path` | One match uses that path. Zero matches use the unglobbed literal, matching today. More than one match is an error naming the matches. |
| `list[Path]` | Every `GlobMatch` is flattened. Resolves #712. |

This is what retires the hack #911 names directly, that `dir::` "technically
returns a list of Paths but we allow it to return only one path". The ambiguity
stops being a special case and becomes a consequence of the declared type.

`GlobMatch` exists only in the intermediate mapping between preprocessing and
validation, so serialization is unaffected.

### Symbol resolution becomes a graph

Today resolution follows document order, so `ref::$LATER_KEY` fails. `graph.py`
builds a dependency graph from each directive's referenced symbols and resolves
topologically. Forward references work. Cycles produce a diagnostic naming the
cycle rather than a confusing `KeyError`. Nested dotted symbol paths such as
`MACROS.foo.gds` are preserved.

Enabling forward references only makes previously-failing configurations work,
so it is not a break.

### Overlays

`pdk::PATTERN` and `scl::PATTERN` merging becomes its own pass in `overlay.py`,
running before symbol resolution rather than being interleaved into the
recursive walk. Order sensitivity, where later overlays win, `fnmatch` semantics,
and nesting are all preserved.

## P3. Load pipeline

`Config.load` currently loops over configuration files, preprocessing and
validating each in turn, and sets `_load_pdk_configs = False` after the first.
That flag is the root cause of #827: a later file's `STD_CELL_LIBRARY` can never
re-resolve the PDK. The fix is to stop looping and run ordered stages once.

```
1  Read        each source to a raw mapping plus provenance (file, key path)
2  Layer       merge all sources in order, last wins.
                 CLI --override forms the top layer
3  Process     extract PDK, STD_CELL_LIBRARY and PAD_CELL_LIBRARY from the
                 MERGED mapping                                    <- #827 fix
4  PDK         eval config.tcl, then scl config.tcl, then pad config.tcl,
                 then migrate_old_config
5  Preprocess  overlays, then symbol-graph resolution with PDK, PDKPATH,
                 STD_CELL_LIBRARY, PAD_CELL_LIBRARY and DESIGN_DIR seeded
6  Merge       PDK values as base, user values on top
7  Validate    one pass against the flow union model
8  Report      diagnostics, raising InvalidConfig if any ERROR is present
```

Three consequences worth stating explicitly.

**Tcl sources keep their two-pass wart.** A `.tcl` configuration must be
evaluated to discover `PDK`, but needs `STD_CELL_LIBRARY` in order to evaluate
fully, so `sources.py`'s Tcl reader still evaluates twice. This is inherent to
the PDK ingestion constraint and cannot be removed here.

**Command-line overrides no longer trigger a second validation pass.** Today
they are applied after everything else and the whole configuration is
re-validated with `permissive_typing=True`. The `permissive_keys` context
described in P1 replaces that.

**PDK values set on non-PDK variables become a diagnostic.** Today they are
silently ignored, with the docstring promising future warnings. They now emit a
`DEPRECATION` diagnostic, suppressed unless `full_pdk_warnings` is set, so old
PDKs do not generate noise by default.

### Unknown keys

The union model uses `extra="allow"` and `model_extra` is post-processed with
the existing rules, rather than using `extra="forbid"`. This preserves the
`_OPT`, `//` and `#` exemptions, the `removed_variables` explanatory messages,
and the distinction between an unknown key and a key that is a known variable
but unused by the current flow. A bare `extra="forbid"` would flatten all of
that into one unhelpful error.

## Diagnostics

```python
class Severity(Enum):
    ERROR = "error"
    WARNING = "warning"
    DEPRECATION = "deprecation"
    INFO = "info"

@dataclass(frozen=True)
class Diagnostic:
    severity: Severity
    category: str            # unknown-key, deprecated-name, removed-variable,
                             # type-error, missing-required, pdk-override, ...
    message: str
    variable: str | None = None
    source: str | None = None       # originating configuration file
    key_path: str | None = None     # for example MACROS.foo.gds[0]
```

`DiagnosticSet` is an ordered collection exposing `errors()`, `warnings()`,
filtering, and a renderer for the command line.

The fix for #779 and #410 is not to log harder, it is to stop logging eagerly.
`Config.load` attaches a `DiagnosticSet` to the returned object as
`config.diagnostics` instead of emitting into a logger that has no flow sinks
yet.

`Flow.start` opens its sinks inside an `ExitStack` at
`librelane/flows/flow.py:647-668`, well after configuration has been loaded.
Three sinks matter here.

| Line | Sink |
| --- | --- |
| 648-653 | `_StepWarningSink`, the aggregator behind the end-of-flow warning summary |
| 654-661 | `warning.log` and `error.log`, built as `f"{level.lower()}.log"` |
| 662-668 | `flow.log` |

The drain point is immediately after the stack has entered all three, and before
`resolved.json` is written at line 670. Replaying `config.diagnostics` there
routes configuration warnings into the end-of-flow summary, `warning.log` and
`flow.log` for the first time, which is precisely what #779 and #410 ask for.
This is additive, so `Config.load`'s signature is unchanged.

`severity` and `category` supply #401's mechanism without anyone hand-classifying
warnings. `InvalidConfig` retains `.warnings` and `.errors` as `list[str]`
properties for compatibility.

## Deprecation surface

`Config` largely survives. `load`, `interactive`, `get_meta`, `dumps`,
`to_raw_dict`, `copy_filtered` and `with_increment` all keep working. Two things
are actually deprecated.

**`Variable` becomes a shim over model fields.** `legacy.py` keeps the class and
provides bridges in both directions.

```python
variables_to_model(name, vars, base) -> type[BaseConfigModel]   # via create_model
model_to_variables(model)            -> list[Variable]
```

That symmetry makes P4 incremental and order-independent. A step declares either
`Config` or `config_vars`, and `Step.__init_subclass__` derives whichever is
missing. Documentation generation, `get_all_config_variables` and third-party
introspection keep seeing `config_vars` regardless of which side a given step is
on. `checker.py`'s dynamic `__init_subclass__` construction is served by
`create_model`, which is verified working.

**`self.config["KEY"]` becomes `self.config.KEY`.** `BaseConfigModel` carries a
`Mapping` facade providing `__getitem__`, `__contains__`, `__iter__`, `__len__`,
`keys`, `values`, `items` and `get`, so `tclstep.py:149`'s `self.config.keys()`
loop and `toolbox.filter_views(self.config, ...)` keep working untouched.

**Deprecation warnings stay off during migration.** Both deprecations are gated
behind one module-level flag, defaulting to off until P4 completes. Otherwise
every intermediate release emits roughly a hundred step classes' worth of
`DeprecationWarning` at import time and breaks anyone running `-W error`. The
flag flips in P5, once nothing in-tree triggers it.

## Verification

The modernization roadmap gates the Pydantic swap on a golden-output comparison
of old against new across every declared `Variable`, not sampled test cases.
That gate is part of this project.

**Harvest.** Collect every `Variable` reachable from the `Step.factory` registry
plus the universal flow variables. Assert the count against a committed
baseline, applying the same anti-silent-shrinkage principle as Track 3's
registry-equality check.

**Corpus, per variable.** The declared default. Real values obtained by
evaluating the sky130A, gf180mcu and ihp-sg13g2 `config.tcl` files. Every value
appearing under that key anywhere in `test/` and the bundled examples. A
per-type-shape adversarial set covering the empty string, `"null"`, `0`, `"0"`,
`"true"`, a one-element list and a nested list.

**Compare.** Run old `Variable.compile` against new model validation for each
`(value, permissive)` pair and compare the tuple
`(result, result_type, exception_class, normalized_message)`.

**Verdict.** Every difference must be identical or on an explicit allowlist
naming an issue number. The expected allowlist has exactly four entries: #993,
#712, #827, and the `ref::` layering change described below. Anything else fails
the gate. This is why the old implementation moves to `legacy.py` rather than
being deleted.

**End to end.** Run `Config.load` over every configuration file in the
repository and the examples, and diff `resolved.json` old against new.

Alongside the gate, ordinary tests cover the grammar at the parse-to-AST level,
each resolver, overlay merging, the symbol graph including cycles and forward
references, and shape coercion in table-driven form. The existing 1,880 lines of
configuration tests must pass unchanged wherever behavior is unchanged. Any
re-baselined test carries a comment naming the issue that justifies the change.

## Breaking changes

Each requires a `Changelog.md` entry and a dedicated test.

1. **`ref::` across multiple configuration files.** With a single global symbol
   graph, a `ref::` in file one that points at a key overridden in file two now
   resolves to file two's value. Today it resolves to file one's value, because
   file one is fully preprocessed before file two is read. This is unavoidable
   if #827 is to be fixed, and it matches what the issue reporter expects, but
   it is a real break.
2. **Union coercion under lax typing** changes as described in #993.
3. **Multiple globs into a `list[Path]`** now succeed rather than crashing, per
   #712.
4. **`librelane.config.variable` as a module path** no longer exists. `Variable`
   remains at `librelane.config.Variable`.
5. **Error message wording changes.** The verification gate normalizes messages,
   so it checks that the information survives rather than the exact prose.

## Risks

- **Pydantic is a new runtime dependency.** `default.nix` must gain it in the
  same commit as `pyproject.toml`, per the roadmap's global constraint.
- **Union-model construction cost.** Roughly 500 fields synthesized through
  `create_model` per flow. Pydantic model construction is not free. This needs
  measuring and caching, not assuming.
- **Two implementations coexist** until the gate passes and P4 completes. This
  is deliberate, since the gate requires the old code to be executable, but it
  is a maintenance cost for the duration.

## Verified assumptions

Established by direct execution against Pydantic 2.13.4 on 2026-07-28, not by
inference.

| Assumption | Result |
| --- | --- |
| Smart union resolves #993 | `Union[int, bool, str]` given `"true"` returns `"true"`; given `1` returns `1` |
| Validation context drives permissive coercion | `model_validate(..., context={"permissive": True})` splits `"a,b,c"`; strict mode rejects |
| `AliasChoices` handles plain deprecated names | `TRISTATE_CELL_PREFIX` populates `TRISTATE_CELLS` |
| `create_model` serves `checker.py` | Dynamic subclass gains fields correctly |
| `json_schema_extra` survives into JSON Schema | `pdk` and `units` present in generated schema |
| `__get_pydantic_core_schema__` works on a `UserString` subclass | Glob unwrap and JSON serialization both correct |
| Enum lookup by name via the same hook | `"R0"` resolves to `Orientation.N` |
| Shape coercion handles every Tcl case | Under 30 lines cover list, tuple, dict, nested `dict[str, list[Path]]`, and #712 |
| Glob flattening survives strict mode | With `split_strings=False`, `list[Path]` still flattens while `"a,b"` is rejected as `list_type` |
| Per-key permissiveness works | `context={"permissive_keys": {"STA_CORNERS"}}` coerces only that key; other keys still reject strings |
| `Flow.start` has a viable diagnostic drain point | `ExitStack` enters `_StepWarningSink`, `warning.log`, `error.log` and `flow.log` at `flows/flow.py:647-668`, all after config load |
| Pydantic is not currently a dependency | Absent from the environment; `lark`, `click` and `yamlcore` present |

## Open questions

None blocking. Two to settle during planning.

1. Whether the flow union model should be cached across `Config.load` calls
   within a process, which depends on the measured construction cost.
2. Whether `Step.__init_subclass__` should derive `config_vars` eagerly for every
   step or lazily on first access, which depends on the same measurement.
