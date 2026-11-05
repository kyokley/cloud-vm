{
  pkgs,
  target,
  ...
}:
{
  imports = [
    ./shell
    ./opencode
  ];

  home = {
    username = target.username;
    homeDirectory = target.homeDirectory;

    # Keep this stable after initial deployment; changing it does not migrate state.
    stateVersion = "26.05";

    packages = with pkgs; [
      git
      jujutsu
      curl
      jq
      ripgrep
      tmux
      nix-search-cli
    ];
  };

  programs = {
    tmux = {
      enable = true;
      prefix = "C-a";
      shortcut = "a";
    };
    home-manager.enable = true;
    nh = {
      enable = true;
      clean = {
        enable = true;
        dates = "weekly";
      };
      flake = "github:kyokley/cloud-vm";
    };
  };

  nix = {
    package = pkgs.nix;
    settings = {
      trusted-users = [
        "root"
        target.username
      ];
    };
  };
}
