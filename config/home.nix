{
  inputs,
  pkgs,
  target,
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
    tmux = {
      enable = true;
      prefix = "C-a";
      shortcut = "a";
    };
    home-manager.enable = true;
    bash.enable = false;
    zsh = {
      enable = true;
      prezto = {
        enable = true;
        caseSensitive = false;
        syntaxHighlighting.highlighters = [
          "main"
          "brackets"
          "pattern"
          "line"
          "cursor"
          "root"
        ];
        prompt = {
          theme = "powerlevel10k";
          showReturnVal = true;
        };
        pmodules = [
          "environment"
          "terminal"
          "editor"
          "history"
          "spectrum"
          "utility"
          "completion" # completion module can lead to slow terminal start times
          "syntax-highlighting"
          "history-substring-search"
          "ssh"
          "tmux"
          "git"
          "autosuggestions"
          "prompt"
        ];
        utility.safeOps = false;
        # ssh.identities = [
        #   "id_ed25519"
        # ];
        extraConfig = builtins.concatStringsSep "\n" [
          (builtins.readFile ./powerlevel10k_config.zsh)
        ];
      };
    };
    nh = {
      enable = true;
      clean = {
        enable = true;
        dates = "weekly";
      };
      flake = "github:kyokley/cloud-vm";
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
      trusted-users = [
        "root"
        target.username
      ];
    };
  };
}
