{ config, pkgs, lib, theme, unstable, ... }:

{
  programs.neovide = {
    enable = true;
    package = unstable.neovide;
    settings = {
      fork = false;
      frame = "full";
      font = {
        normal = [theme.font.family];
        size = theme.font.sizeFloat;
      };
    };
  };
}
