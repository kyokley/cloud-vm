{ pkgs, target, ... }:
{
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
  ];

  programs.home-manager.enable = true;
  programs.bash.enable = true;
}
