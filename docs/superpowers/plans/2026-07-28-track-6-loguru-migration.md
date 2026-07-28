# Track 6: Loguru Migration Implementation Plan

**Goal:** Make Loguru both the logging engine and the application-facing API,
while preserving terminal modes, test capture, and per-flow log artifacts.

**Architecture:** Keep `librelane.logging` only for initialization, thresholds,
sink registration, terminal options, and the shared Rich console. Application
code imports `loguru.logger` directly, uses native level methods, and binds
`step`/`key` context with `logger.bind()`.

## Verified Surface

- Seven effective thresholds: `ALL`, `DEBUG`, `SUBPROCESS`, `VERBOSE`, `INFO`,
  `WARNING`, `ERROR`, `CRITICAL`.
- Application code previously imported facade functions across the repo.
- `Flow.start()` registers three file handlers and a warning aggregation
  handler dynamically.
- Step logging binds `step`; OpenROAD alerts also bind `key`.
- Existing tests depend on pytest `caplog`, so a stdlib-compatible capture sink
  is a migration requirement.

### Task 1: Characterize the facade

- Add focused tests for every level, threshold changes, reset, condensed
  subprocess suppression, bound `step`/`key`, success/warning/error formatting,
  additional handler registration, and deregistration.
- Add a small flow test asserting exact existence and level partitioning of
  `flow.log`, `warning.log`, and `error.log`.
- Commit tests before the backend change.

### Task 2: Add and configure Loguru

- Add `loguru>=0.7,<1` to `pyproject.toml`; refresh `uv.lock`.
- Remove Loguru’s default sink and register `SUBPROCESS` and `VERBOSE`.
- Implement normal and condensed terminal sinks with Loguru filters.
- Translate facade `extra`, `stacklevel`, and exception arguments to
  `bind()`/`opt()`.
- Keep `rule()` backed by the shared Rich console.

### Task 3: Replace dynamic stdlib handlers

- Replace handler registration with sink registration returning/storing Loguru
  sink IDs.
- Implement warning aggregation as a callable sink over Loguru records.
- Register per-flow file paths directly as Loguru sinks with level filters.
- Preserve the existing public registration functions for downstream callers;
  accept a stdlib `logging.Handler` during the compatibility window because
  Loguru supports it as a sink.

### Task 4: Migrate callers to native Loguru

- Add a stdlib forwarding sink for pytest/root-handler capture without using
  stdlib logging as the primary engine.
- Keep `LogLevels`, `LevelFilter`, settings, and sink registration in
  `librelane.logging`; remove the logging-call facade exports.
- Replace application calls with `logger.debug()`, `logger.info()`,
  `logger.success()`, `logger.warning()`, and `logger.error()`.
- Use `logger.log("VERBOSE", ...)` and `logger.log("SUBPROCESS", ...)` for the
  custom levels.
- Replace Step warning/error wrappers with bound native loggers.
- Run all tests, lint/mypy, registry check, `uv build`, and
  `nix build .#librelane`.

### Task 5: Commit boundaries

- Characterization tests.
- Dependency/backend and capture bridge.
- Flow sink conversion and removal of obsolete formatter/handler classes.
- Native caller migration and facade removal.

## Completion

Complete. All application code now uses native Loguru calls. The logging
package contains only initialization, settings, sink/filter compatibility, and
the shared Rich console. Native wheel and Nix installations were validated.
