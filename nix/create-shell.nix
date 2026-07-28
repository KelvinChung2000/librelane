# SPDX-License-Identifier: MIT
# Copyright (c) 2025 LibreLane Contributors
# Copyright (c) 2023-2024 UmbraLogic Technologies LLC
{
  lib,
  git,
  zsh,
  delta,
  gtkwave,
  coreutils,
  graphviz,
  iverilog,
  python3,
  devshell,
  extra-packages ? [ ],
  extra-env ? [ ],
  librelane-plugins ? ps: [ ],
  librelane-extra-python-interpreter-packages ? ps: [ ],
  librelane-extra-yosys-plugins ? [ ],
  # The Python environment placed on the shell's PATH. LibreLane is itself a
  # virtual environment, so by default the shell simply uses it. Pass
  # python3.pkgs.librelane-dev-env for a shell that runs the working tree.
  python-env ? null,
}:
let
  plugins-resolved = librelane-plugins python3.pkgs;
  plugin-included-tools = lib.lists.flatten (map (n: n.includedTools) plugins-resolved);
  plugin-yosys-plugins = lib.lists.flatten (map (n: n.addedYosysPlugins or [ ]) plugins-resolved);
  librelane' = python3.pkgs.librelane.override {
    extra-python-interpreter-packages = librelane-extra-python-interpreter-packages;
    extra-yosys-plugins = librelane-extra-yosys-plugins ++ plugin-yosys-plugins;
  };
  plugins-overridden = map (p: p.override { librelane = librelane'; }) plugins-resolved;
  plugins-propagatedBuildInputs = lib.lists.flatten (
    map (p: (lib.filter (d: d.pname != "librelane") p.propagatedBuildInputs)) plugins-resolved
  );
  librelane-env = if python-env == null then librelane' else python-env;
  # Plugins are built by nixpkgs, so they live outside the virtual environment
  # and reach it through the import path instead.
  plugin-sitepackages = map (p: "${p}/${python3.sitePackages}") (
    plugins-overridden ++ plugins-propagatedBuildInputs
  );
  prompt = ''\[\033[1;32m\][nix-shell:\w]\$\[\033[0m\] '';
  packages = [
    librelane-env

    # Conveniences
    git
    zsh
    delta
    gtkwave
    iverilog
    coreutils
    graphviz
  ]
  ++ extra-packages
  ++ librelane'.includedTools
  ++ plugin-included-tools;
in
devshell.mkShell {
  devshell.packages = packages;
  env = [
    # Editable installs resolve the working tree through this variable; see
    # mkEditablePyprojectOverlay in flake.nix.
    {
      name = "REPO_ROOT";
      eval = "$PRJ_ROOT";
    }
  ]
  ++ lib.optional (plugin-sitepackages != [ ]) {
    name = "PYTHONPATH";
    value = lib.concatStringsSep ":" plugin-sitepackages;
  }
  ++ extra-env;
  devshell.interactive.PS1 = {
    text = ''PS1="${prompt}"'';
  };
  motd = "";
}
