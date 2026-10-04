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

  oh_my_opencode_slim = {
    autoUpdate = false;
    preset = "opencode-zen";
    presets = {
      opencode-free = {
        orchestrator = {model = "opencode/mimo-v2.5-free";};
        oracle = {
          model = "opencode/nemotron-3-ultra-free";
          variant = "max";
        };
        librarian = {model = "opencode/mimo-v2.5-free";};
        explorer = {model = "opencode/ling-3.0-flash-fin-free";};
        designer = {model = "opencode/muse-spark-1.2-contributor-free";};
        fixer = {
          model = "opencode/nemotron-3.5-lightning-free";
          variant = "high";
        };
        council = {model = "opencode/mimo-v2.5-free";};
      };
    };
  };
in {
  home = {
    username = target.username;
    homeDirectory = target.homeDirectory;

    # Keep this stable after initial deployment; changing it does not migrate state.
    stateVersion = "26.05";

    packages = with pkgs; [
      git
      curl
      jq
      ripgrep
      tmux
      nix-search-cli
    ];

    file = {
      ".config/opencode/oh-my-opencode-slim.json" = {
        text = builtins.toJSON oh_my_opencode_slim;
      };
    };
  };

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
        tmux.autoStartRemote = true;
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
    opencode = let
      bun2nix-lib = inputs.bun2nix.packages.${pkgs.stdenv.hostPlatform.system}.default;
      npm_deps = bun2nix-lib.mkDerivation {
        packageJson = ./package.json;
        src = ./.;

        bunDeps = bun2nix-lib.fetchBunDeps {
          bunNix = ./_bun.nix;
        };

        module = "package.json";
        dontUseBunBuild = true;
        dontRunLifecycleScripts = true;
        installPhase = ''
          runHook preInstall
          cp -R node_modules "$out"
          runHook postInstall
        '';
      };
    in {
      enable = true;
      context = builtins.concatStringsSep "\n" [
        defaultContext
        (builtins.readFile "${inputs.caveman}/plugins/caveman/skills/caveman/SKILL.md")
      ];
      settings = {
        autoupdate = false;
        model = "opencode/big-pickle";
        small_model = "opencode/big-pickle";
        plugin = [
          "${npm_deps}/oh-my-opencode-slim/dist/index.js"
          "opencode-skill-creator"
        ];
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

  xdg.configFile = {
    "opencode/opencode.json".force = true;
    "opencode/AGENTS.md".force = true;
  };
}
