# Contributing

## Development Environment

```console
$ uv sync --all-groups
```

That is the whole setup. Run tooling through uv:

```console
$ uv run pytest          # tests
$ make lint              # ruff + mypy
$ make docs              # build documentation
```

## Before Opening a Pull Request

- `make lint` passes
- `uv run pytest` passes
- New behavior has a test

Step implementation tests (`-m step_impl_test`) need the full EDA toolchain and
run only in the Nix-based CI jobs. You are not expected to run them locally.

## CI Conventions

No `run:` step under `.github/` may contain more than one call into a script or
a Nix target. Branching, parsing, and decision logic live in `.github/scripts/`,
never inline in YAML.

This keeps CI logic runnable locally: scripts detect whether they are running
under Actions and write to `$GITHUB_ENV` or the local process environment
accordingly. Logic inlined into YAML cannot be run locally and will drift from
what developers run.
