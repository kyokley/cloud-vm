{
  ...
}:
{
  programs = {
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
  };
}
