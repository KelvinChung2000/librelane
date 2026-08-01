# Writing and Using Plugins

LibreLane plugin modules are written in Python and can be added to `PYTHONPATH`
or installed to your Python `site-packages` (e.g. installed either inside
or outside a venv). LibreLane detects and imports all Python modules found that
have the prefix `librelane_plugin_`.

Plugins are useful to add support for more utilities other than those included
with LibreLane; either alternative open-source EDA utilities that are not part of
the built-in flows, or proprietary utilities that can never be a part of the
built-in parts.

```{note}
Plugins are not supported in LibreLane Docker containers.
```

## Registering new Flows and Steps

Plugins, much like LibreLane itself, may create and register steps and flows into
global registries, where the steps and flows can then be accessed
programmatically via their ID.

A step is a Python class, so you register it with the `@Step.factory.register()`
decorator. A flow is a YAML document, so you load it and hand the result to
`Flow.factory.register()`:

```python
from librelane.flows import Flow, load_flow_spec

Flow.factory.register(load_flow_spec("./my_flow.yaml"))
```

Registered flows and steps can be accessed in configuration files as shown in
{doc}`/usage/writing_custom_flows`, but they can also be accessed
programmatically as follows:

```python
MyCustomStep = Step.factory.get("ToolName.MyCustomStep")
MyCustomFlow = Flow.factory.get("MyCustomFlow")
```

`Step.factory.get` returns the step class; `Flow.factory.get` returns the
{class}`librelane.flows.spec.FlowSpec` the document parsed into, which
{class}`librelane.flows.engine.Workflow` runs.

For information on writing the flows and steps themselves, see
{doc}`/usage/writing_custom_flows` and {doc}`/usage/writing_custom_steps`.

## Including Tools

Naturally, one of the most important uses of plugins is the ability to write
steps for other tools. There are multiple ways to include these tools:

### Bring-your-own-tools

You may require users to bring their own tools by installing them on their own
and adding them to `PATH`, then running LibreLane with the plugin separately.

This is usually the only option for proprietary utilities.

You can still install the plugin itself with Nix while requiring the tool be
separate- see the section below.

### With Nix

```{note}
This section requires a strong understanding of the Nix programming language,
including the Flakes feature, to follow.
```

You may bundle either the plugin alone or the plugin and the tool using Nix.

LibreLane's overlay adds a package named `librelane-shell`. It builds a
[devshell](https://github.com/numtide/devshell), an executable script that drops
you into an environment with LibreLane, its dependencies, and optionally your
plugins, installed. Override it to add plugins:

```nix
pkgs.librelane-shell.override {
  librelane-plugins = ps: [ ps.librelane_plugin_example ];
}
```

`librelane-plugins` is a function of the Python package set, in the same style
as `python3.withPackages`, so the plugin has to be a member of `python3.pkgs` —
add it there with an overlay of your own.

The plugins themselves are regular Python Nix derivations, built with the
[`buildPythonPackage` function](https://github.com/NixOS/nixpkgs/blob/master/doc/languages-frameworks/python.section.md#buildpythonpackage-function-buildpythonpackage-function),
with two additions:

- A `librelane` argument, which the shell overrides so the plugin is built
  against the same LibreLane the shell ships.
- An `includedTools` attribute listing the plugin's tool dependencies, so they
  are also available to the user standalone in the environment. Add
  `addedYosysPlugins` too if the plugin needs Yosys plugins.

For example, a plugin that depends on the Python `numpy` library and
incorporates `bash` declares its dependencies as follows:

```nix
{ buildPythonPackage, librelane, numpy, bash, ... }:
buildPythonPackage {
  pname = "librelane_plugin_example";
  # …
  includedTools = [ bash ];
  propagatedBuildInputs = [ librelane numpy ];
}
```

Putting it together, a downstream flake that provides a shell with both
LibreLane and the plugin available looks like this:

```nix
{
  inputs.librelane.url = "github:librelane/librelane";

  outputs = { self, librelane, ... }: {
    overlays.default = final: prev: {
      python3 = prev.python3.override (old: {
        packageOverrides = final.lib.composeExtensions
          (old.packageOverrides or (_: _: { }))
          (pfinal: pprev: {
            librelane_plugin_example = pfinal.callPackage ./nix/plugin.nix { };
          });
      });
    };

    devShells = librelane.inputs.nix-eda.forAllSystems (system:
      let
        pkgs = import librelane.inputs.nix-eda.inputs.nixpkgs {
          inherit system;
          overlays = [
            librelane.inputs.devshell.overlays.default
            librelane.inputs.nix-eda.overlays.default
            librelane.overlays.default
            self.overlays.default
          ];
        };
      in
      {
        default = pkgs.librelane-shell.override {
          librelane-plugins = ps: [ ps.librelane_plugin_example ];
        };
      });
  };
}
```

```{note}
LibreLane ships as a virtual environment, which plugins are not built into.
The shell instead puts each plugin's `site-packages` on `PYTHONPATH`, which is
why plugins must be importable on their own rather than being installed
alongside LibreLane.
```
