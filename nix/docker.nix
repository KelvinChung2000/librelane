# SPDX-License-Identifier: MIT
# Copyright (c) 2025 LibreLane Contributors
# Copyright (c) 2023-2024 UmbraLogic Technologies LLC
{
  createDockerImage,
  dockerTools,
  stdenv,
  pkgs,
  lib,
  librelane,
  git,
  zsh,
  silver-searcher,
  coreutils,
}:
let
  librelane-env-bin = "${librelane}/bin";
in
createDockerImage {
  inherit pkgs;
  inherit lib;
  name = "librelane";
  tag = "tmp-${stdenv.hostPlatform.system}";
  extraPkgs = with dockerTools; [
    git
    zsh
    silver-searcher

    librelane
  ];
  nixConf = {
    extra-experimental-features = "nix-command flakes repl-flake";
  };
  maxLayers = 2;
  channelURL = "https://nixos.org/channels/nixos-23.11";

  image-created = "now";
  image-extraCommands = ''
    mkdir -p ./etc
    mkdir -p ./tmp
    chmod 1777 ./tmp

    cat <<HEREDOC > ./etc/zshrc
    autoload -U compinit && compinit
    autoload -U promptinit && promptinit && prompt suse && setopt prompt_sp
    autoload -U colors && colors

    export PS1=$'%{\033[31m%}LibreLane Container (${librelane.version})%{\033[0m%}:%{\033[32m%}%~%{\033[0m%}%% ';
    HEREDOC
  '';
  image-config-cmd = [ "${zsh}/bin/zsh" ];
  image-config-extra-env = [
    "LANG=C.UTF-8"
    "LC_ALL=C.UTF-8"
    "LC_CTYPE=C.UTF-8"
    "EDITOR=nvim"
    # Where 'librelane --dockerized' mounts the host's copy of the package, so
    # that it takes precedence over the one baked into the image. LibreLane now
    # ships as a virtual environment, whose interpreter reads PYTHONPATH rather
    # than nixpkgs' NIX_PYTHONPATH.
    "PYTHONPATH=/host_librelane"
    "TMPDIR=/tmp"
  ];
  image-config-extra-path = [
    "${librelane-env-bin}"
    "${librelane.computed_PATH}"
  ];
}
