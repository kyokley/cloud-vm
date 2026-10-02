{
  pkgs,
  target,
  config,
  ...
}: {
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
  };

  nix.settings = {
    extra-substituters = [
      "https://horus.cachix.org"
    ];
    extra-trusted-public-keys = [
      "horus.cachix.org-1:YZ4tQYAoKH+zkKbD4aqFcMHgZxIM7Uo4dPEfwUrubT4="
    ];
  };
}
