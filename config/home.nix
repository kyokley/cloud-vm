{
  inputs,
  pkgs,
  target,
  config,
  ...
}: let
  defaultContext = ''
    You are running in an exe.dev VM.

    https://exe.dev/docs/proxy.md has details about the exe.dev HTTPS proxy.

    Only use documented exe.dev features (see https://exe.dev/docs.md). Undocumented local endpoints are internal infrastructure—unstable and unsupported.
  '';
in {
  home.username = target.username;
  home.homeDirectory = target.homeDirectory;

  # Keep this stable after initial deployment; changing it does not migrate state.
  home.stateVersion = "26.05";

  home.packages = with pkgs; [
    git
    curl
    jq
    ripgrep
    tmux
    nix-search-cli
  ];

  programs = {
    home-manager.enable = true;
    bash.enable = true;
    nh = {
      enable = true;
      clean = {
        enable = true;
        dates = "weekly";
      };
      flake = "${config.home.homeDirectory}/dotfiles";
    };
    opencode = {
      enable = true;
      context = builtins.concatStringsSep "\n" [
        defaultContext
        (builtins.readFile "${inputs.caveman}/plugins/caveman/skills/caveman/SKILL.md")
      ];
      settings = {
        autoupdate = false;
        model = "opencode/big-pickle";
        small_model = "opencode/big-pickle";
      };
    };
  };

  nix = {
    package = pkgs.nix;
    settings = {
      extra-substituters = [
        "https://horus.cachix.org"
      ];
      extra-trusted-public-keys = [
        "horus.cachix.org-1:YZ4tQYAoKH+zkKbD4aqFcMHgZxIM7Uo4dPEfwUrubT4="
      ];
    };
  };
}
