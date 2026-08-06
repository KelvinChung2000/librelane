# Typed configuration access

LibreLane configuration is authored and read through typed pydantic models,
not string-keyed dictionaries. This document records the invariant, what still
speaks strings, and the plan for retiring the remainder.

## The invariant

A configuration variable is *declared* once, as a field on a `Config` model:

```python
class MyStep(Step):
    class Config(Step.Config):
        MY_VARIABLE: Optional[int] = variable(
            None, description="…",
        )
```

and *read* as an attribute — `self.config.MY_VARIABLE` — which mypy checks
against the declaration. The same holds for flows: `Flow.__init__` constructs
the resolved configuration into a model over every variable
`get_all_config_variables()` reports, so flow code reads
`self.config.DESIGN_NAME`. `Toolbox`'s view/timing helpers type their
`config` parameter as the `ViewsConfig` protocol, which any step's or flow's
model satisfies structurally.

Do not add new `config["X"]` or `config.get("X")` reads for a name written
out in source. `Netgen.LVS` carried a read of `SPICE_MODELS` — a variable
nothing declared — for years, always returning `None`, because a string
lookup cannot fail to typecheck.

String-keyed access remains correct in exactly two situations:

* **The key is data, not a name in source** — e.g. the engine reading
  `self.config[capacity]` where `capacity` arrived from a document.
* **A raw-source boundary** — places that touch configuration *before*
  validation or *outside* the Python process: the loader itself, the `TOOLS`
  pre-pass (which reads sources before any model exists), `pdk_compat` (which
  migrates OpenLane-1 PDK dictionaries), run artifacts re-read from JSON
  (`librelane open`), and the env/JSON handoff to Tcl and tool-side Python
  scripts.

## What still speaks strings, and the plan

1. **The loader** (`config/config.py`) resolves sources against
   `Variable` lists (`config/legacy.py`), which are themselves derived from
   the models via `model_to_variables`, and steps/flows then re-validate the
   result back into models. The end-state is to invert this: compose one
   model per flow (the `extend_model`/`variables_to_model` machinery already
   exists, and `BaseConfigModel._coerce_shapes` already understands per-key
   coercion syntaxes and deprecated names), validate each layered source
   against it once, and keep per-key provenance — which `BaseConfigModel`
   now carries — as the loader records it today. `Variable` then survives
   only as the documentation/JSON-schema bridge until docs generation reads
   model fields directly, after which `legacy.py` can go. This is a large,
   self-contained refactor of ~1,600 lines and should be its own change
   series, not a rider on anything else.

2. **Tool-side scripts** (`scripts/pyosys/synthesize.py`,
   `scripts/odbpy/*`) receive configuration as JSON or environment variables
   in interpreters that do not ship pydantic. If their string reads become a
   problem in practice, the stdlib answer is a frozen `dataclass` view
   constructed from the JSON, which gives the scripts mypy-checked attribute
   access without new dependencies — at the cost of merge friction with the
   scripts' upstream ancestry. Not currently planned.

3. **Deliberate exceptions in steps**: `OpenSTAStep` reads
   `self.config.get("EXTRA_SPEFS")` because the variable is declared only on
   `MultiCornerSTA`, a subclass — the base class read is optional by design.
