# SPDX-License-Identifier: MIT
# Copyright (c) 2025 LibreLane Contributors
# Copyright (c) 2023-2025 UmbraLogic Technologies LLC
{
  description = "open-source infrastructure for implementing chip design flows";

  inputs = {
    nix-eda.url = "github:fossi-foundation/nix-eda/7.0.0";
    ciel.url = "github:fossi-foundation/ciel/2.5.1";
    devshell.url = "github:numtide/devshell";
    flake-compat = {
      url = "github:NixOS/flake-compat";
      flake = false;
    };
    pyproject-nix.url = "github:pyproject-nix/pyproject.nix";
    uv2nix.url = "github:pyproject-nix/uv2nix";
    pyproject-build-systems.url = "github:pyproject-nix/build-system-pkgs";
  };

  inputs.ciel.inputs.nix-eda.follows = "nix-eda";
  inputs.devshell.inputs.nixpkgs.follows = "nix-eda/nixpkgs";
  inputs.pyproject-nix.inputs.nixpkgs.follows = "nix-eda/nixpkgs";
  inputs.uv2nix.inputs.nixpkgs.follows = "nix-eda/nixpkgs";
  inputs.uv2nix.inputs.pyproject-nix.follows = "pyproject-nix";
  inputs.pyproject-build-systems.inputs.nixpkgs.follows = "nix-eda/nixpkgs";
  inputs.pyproject-build-systems.inputs.pyproject-nix.follows = "pyproject-nix";
  inputs.pyproject-build-systems.inputs.uv2nix.follows = "uv2nix";

  outputs =
    {
      self,
      nix-eda,
      ciel,
      devshell,
      pyproject-nix,
      uv2nix,
      pyproject-build-systems,
      ...
    }:
    let
      nixpkgs = nix-eda.inputs.nixpkgs;
      lib = nixpkgs.lib;
    in
    {
      # Common
      overlays = {
        default = lib.composeManyExtensions [
          (ciel.overlays.default)
          (
            pkgs': pkgs:
            let
              callPackage = lib.callPackageWith pkgs';
            in
            {
              or-tools_9_14 = callPackage ./nix/or-tools_9_14.nix {
                inherit (pkgs'.darwin) DarwinTools;
              };
              colab-env = callPackage ./nix/colab-env.nix { };
              opensta = callPackage ./nix/opensta.nix { };
              openroad-abc = callPackage ./nix/openroad-abc.nix { };
              openroad = callPackage ./nix/openroad.nix { };
            }
          )
          (nix-eda.composePythonOverlay (
            pkgs': pkgs: pypkgs': pypkgs:
            let
              callPythonPackage = lib.callPackageWith (pkgs' // pypkgs');
              workspace = uv2nix.lib.workspace.loadWorkspace {
                workspaceRoot = ./.;
              };
              pythonBase = pkgs.callPackage pyproject-nix.build.packages {
                python = pkgs.python3;
              };
              # tkinter is how LibreLane gets a Tcl interpreter (see
              # librelane.common.TclUtils), but it is standard library shipped
              # with CPython, not a PyPI distribution -- so uv cannot resolve it
              # and it never appears in uv.lock. nixpkgs builds its python3
              # without tk and ships the module separately, so hand that
              # prebuilt module to the virtual environment builder.
              tkinterOverlay = _final: _prev: {
                tkinter = (pkgs.callPackage pyproject-nix.build.hacks { }).nixpkgsPrebuilt {
                  from = pkgs.python3.pkgs.tkinter;
                };
              };
              withTkinter = deps: deps // { tkinter = [ ]; };
              pythonSet = pythonBase.overrideScope (
                lib.composeManyExtensions [
                  pyproject-build-systems.overlays.wheel
                  (workspace.mkPyprojectOverlay {
                    sourcePreference = "wheel";
                  })
                  tkinterOverlay
                ]
              );
              librelaneEnv = pythonSet.mkVirtualEnv "librelane-python-env" (withTkinter workspace.deps.default);
              # Every dependency group in pyproject.toml, with LibreLane itself
              # installed as a pointer to the working tree at $REPO_ROOT rather
              # than a copy in the store. This is what the dev and docs shells
              # run, so edits take effect without rebuilding.
              editablePythonSet = pythonSet.overrideScope (
                lib.composeManyExtensions [
                  (workspace.mkEditablePyprojectOverlay {
                    root = "$REPO_ROOT";
                  })
                  # hatchling only reaches for `editables` when asked to build
                  # an editable wheel, so uv.lock never records it as one of
                  # LibreLane's build systems.
                  (final: prev: {
                    librelane = prev.librelane.overrideAttrs (previousAttrs: {
                      nativeBuildInputs =
                        previousAttrs.nativeBuildInputs ++ final.resolveBuildSystem { editables = [ ]; };
                    });
                  })
                ]
              );
              librelaneDevEnv = editablePythonSet.mkVirtualEnv "librelane-dev-env" (withTkinter {
                librelane = [
                  "lint"
                  "test"
                  "docs"
                ];
              });
              librelaneNotebookEnv = pythonSet.mkVirtualEnv "librelane-notebook-env" (withTkinter {
                librelane = [ "notebook" ];
              });
            in
            {
              libparse = callPythonPackage ./nix/libparse.nix { };

              sphinx-tippy = callPythonPackage ./nix/sphinx-tippy.nix { };
              sphinx-subfigure = callPythonPackage ./nix/sphinx-subfigure.nix { };
              py-mon = callPythonPackage ./nix/py-mon.nix { };

              # ---
              librelane = callPythonPackage ./default.nix {
                inherit librelaneEnv;
              };
              librelane-dev-env = pypkgs'.toPythonModule librelaneDevEnv;
              librelane-notebook-env = pypkgs'.toPythonModule librelaneNotebookEnv;
            }
          ))
          (
            pkgs': pkgs:
            let
              callPackage = lib.callPackageWith pkgs';
            in
            {
              librelane-shell = callPackage ./nix/create-shell.nix { };
            }
            // lib.optionalAttrs pkgs.stdenv.isLinux {
              librelane-docker = callPackage ./nix/docker.nix {
                createDockerImage = nix-eda.createDockerImage;
                librelane = pkgs'.python3.pkgs.librelane;
              };
            }
          )
        ];
      };

      # Formatters
      formatter = nix-eda.formatter;

      # Packages
      legacyPackages = nix-eda.forAllSystems (
        system:
        import nix-eda.inputs.nixpkgs {
          inherit system;
          overlays = [
            devshell.overlays.default
            nix-eda.overlays.default
            self.overlays.default
          ];
        }
      );

      packages = nix-eda.forAllSystems (
        system:
        let
          pkgs = self.legacyPackages."${system}";
        in
        {
          inherit (pkgs)
            colab-env
            opensta
            openroad-abc
            openroad
            ;
          inherit (pkgs.python3.pkgs) librelane;
          default = pkgs.python3.pkgs.librelane;
        }
        // lib.optionalAttrs pkgs.stdenv.isLinux {
          inherit (pkgs) librelane-docker;
        }
      );

      # Development Shells
      devShells = nix-eda.forAllSystems (
        system:
        let
          pkgs = self.legacyPackages."${system}";
          callPackage = lib.callPackageWith pkgs;
        in
        {
          # These devShells are rather unorthodox for Nix devShells in that they
          # include the package itself. For a proper devShell, try .#dev.
          default = pkgs.librelane-shell;
          notebook = pkgs.librelane-shell.override ({
            python-env = pkgs.python3.pkgs.librelane-notebook-env;
          });
          # The lint, test and docs tooling comes from pyproject.toml's
          # dependency groups by way of the development environment, so these
          # shells only add what is not a Python package.
          dev = pkgs.librelane-shell.override ({
            extra-packages = with pkgs; [
              alejandra
            ];
            python-env = pkgs.python3.pkgs.librelane-dev-env;
          });
          docs = pkgs.librelane-shell.override ({
            extra-packages = with pkgs; [
              alejandra
              imagemagick
              python3.pkgs.py-mon
            ];
            python-env = pkgs.python3.pkgs.librelane-dev-env;
          });
        }
      );
    };
}
