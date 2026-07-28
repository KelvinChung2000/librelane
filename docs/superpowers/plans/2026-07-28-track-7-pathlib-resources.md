# Track 7: pathlib and Package Resources Implementation Plan

**Goal:** Replace stringly `os.path` path ownership with `pathlib.Path`, and
source packaged scripts/data through `importlib.resources` rather than
installation-layout assumptions.

**Architecture:** Use `importlib.resources.files("librelane")` directly at
resource consumers rather than maintaining a project wrapper. Then migrate
paths by domain (CLI/config boundaries, flow/run directories, step execution,
state/toolbox) while accepting `os.PathLike` at public inputs. Convert to
strings only at subprocess/environment/JSON boundaries.

## Verified Baseline

- About 520 `os.path`, `Path(...)`, `__file__`, and resource-related occurrences.
- `get_script_dir()` feeds external Python, Tcl, Magic, Netgen, OpenROAD, and
  KLayout processes, so resources often require a real filesystem path.
- `pdk_hashes.yaml`, examples, and 100+ scripts are packaged in the wheel.
- `librelane.common.Path` subclasses `UserString`; it is also a configuration
  type with validation, glob, serialization, and deprecated-value semantics.

### Task 1: Use native package resources

- Use `importlib.resources.files("librelane")` directly for read-only
  traversals and installed script paths.
- Remove `librelane/resources.py` and its project-specific accessors.
- Copy directory `Traversable` objects recursively where a concrete ejected
  tree is needed.
- Characterize source-tree, built-wheel, and Nix resource access.

### Task 2: Remove hard-coded resource roots

- Replace `get_pdk_hash()` file construction with resource `read_text`.
- Replace smoke-test/example discovery with resource traversal.
- Replace `get_script_dir()` call sites with specific resource accessors.
- Replace package-root `__file__` derivation with a managed `package_path()`
  accessor, including the development container mount.
- Use installed distribution metadata for the package version instead of
  locating `pyproject.toml` relative to `__file__`.
- Preserve the `SCRIPTS_DIR` environment contract as a concrete path.
- Deprecate `get_librelane_root()` and `get_script_dir()` once no internal
  callers remain.

### Task 3: Define path boundary rules

- Public file inputs accept `str | os.PathLike[str]`.
- Internally owned filesystem locations become `pathlib.Path`.
- Environment variables, command arguments, JSON/YAML state, and user-facing
  config values convert with `os.fspath()`/`str()` at the boundary.
- No `str(path) + suffix`; use `/`, `with_name`, `with_suffix`, `relative_to`,
  `resolve`, `read_text`, `write_text`, `mkdir`, and `unlink`.

### Task 4: Migrate domains incrementally

- Common utilities and CLI/resource paths.
- Flow/design/run directories and log paths.
- `Step` core, reporting, and subprocess execution.
- Toolbox/state/config filesystem operations.
- Tool-specific step packages, one package per commit.

### Task 5: Replace the configuration `Path` type separately

- Add golden coercion/serialization tests for every `Variable` using
  `librelane.common.Path`.
- Decide between a `pathlib.Path` alias plus validators or a compatibility
  wrapper; do not subclass concrete `Path` in a way that breaks Python 3.10.
- Preserve `_dummy_path`, glob unwrapping, JSON encoding, equality, and
  deprecated-name translations.
- Remove the `UserString` implementation only after golden parity.

### Task 6: Validate every installation form

- Full tests, lint/mypy, registry check.
- `uv build` without deleting `dist`.
- Install the wheel into an isolated environment and execute resource tests
  outside the checkout.
- `nix build .#librelane` and run the same checks from `result`.
