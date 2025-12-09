{ config, pkgs, lib, theme, ... }:

{
  programs.git = {
    enable = true;
    ignores = [ ".DS_Store" ".tags*" ".claude/settings.local.json" ];
    settings = {
      user = {
        name = "Karl Hepler";
        email = "karl.hepler@gmail.com";
      };
      core.editor = "vim";
      diff.tool = "vimdiff";
      merge.tool = "vimdiff";
      difftool.prompt = false;
      push.default = "current";
      init.defaultBranch = "main";
      pull.rebase = false;
      alias = {
        who = "blame -w -C -C -C";
        difft = "-c diff.external=difft diff";
        logt = "-c diff.external=difft log -p --ext-diff";
        showt = "-c diff.external=difft show --ext-diff";
      };
    };
  };
}
