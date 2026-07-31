# SPDX-License-Identifier: MIT
# Copyright (c) 2025 LibreLane Contributors
# Copyright (c) 2023-2025 UmbraLogic Technologies LLC
{
  lib,
  clangStdenv,
  makeWrapper,
  symlinkJoin,
  # Tools
  klayout-app,
  magic-vlsi,
  netgen,
  opensta,
  openroad,
  ruby,
  tcl,
  verilator,
  iverilog,
  yosys,
  yosys-sby,
  yosys-eqy,
  yosys-slang,
  yosys-ghdl,
  yosys-plugin-set ? [
    yosys-sby
    yosys-eqy
    yosys-slang
  ]
  ++ lib.optionals (lib.meta.availableOn clangStdenv.hostPlatform yosys-ghdl) [ yosys-ghdl ],
  extra-yosys-plugins ? [ ],
  # Python
  python,
  librelaneEnv,
  extra-python-interpreter-packages ? ps: [ ],
}:
let
  python-interpreter-packages =
    ps:
    [
      ps.click
      ps.pydantic
      ps.rich
      ps.pyyaml
    ]
    ++ (extra-python-interpreter-packages ps);
  yosys-with-plugins = yosys.withPlugins (yosys-plugin-set ++ extra-yosys-plugins);
  yosys-env =
    (yosys.withPythonPackages.override { target = yosys-with-plugins; })
      python-interpreter-packages;
  openroad-env = openroad.withPythonPackages python-interpreter-packages;
  includedTools = lib.map lib.getBin [
    opensta
    yosys-env
    openroad-env
    netgen
    magic-vlsi
    klayout-app
    iverilog
    verilator
    tcl
    ruby
  ];
  computed_PATH = lib.makeBinPath includedTools;
  version = (builtins.fromTOML (builtins.readFile ./pyproject.toml)).project.version;
in
symlinkJoin {
  pname = "librelane";
  inherit version;
  paths = [ librelaneEnv ];
  nativeBuildInputs = [ makeWrapper ];
  # LibreLane hands its own sys.path to the interpreters it shells out to (see
  # librelane.steps.klayout.base), so "python3" has to resolve to the one in
  # this environment rather than whichever happens to be on the user's PATH.
  postBuild = ''
    for program in "$out"/bin/librelane "$out"/bin/librelane.*; do
      if [ -e "$program" ]; then
        wrapProgram "$program" --prefix PATH : "$out/bin:${computed_PATH}"
      fi
    done
  '';

  passthru = {
    inherit includedTools computed_PATH librelaneEnv;
    pythonModule = python;
  };

  meta = {
    description = "Hardware design and implementation infrastructure library and ASIC flow";
    homepage = "https://librelane.org/";
    mainProgram = "librelane";
    license = lib.licenses.asl20;
    platforms = with lib.platforms; linux ++ darwin;
  };
}
