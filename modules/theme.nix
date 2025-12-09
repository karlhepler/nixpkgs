{ lib, ... }:

{
  # Tokyo Night Storm Theme
  # Single source of truth for colors and fonts across all applications
  # Reference: https://github.com/zatchheems/tokyo-night-alacritty-theme

  theme = {
    name = "Tokyo Night Storm";
    variant = "storm";

    colors = {
      primary = {
        background = "#24283b";
        foreground = "#a9b1d6";
      };
      normal = {
        black = "#32344a";
        red = "#f7768e";
        green = "#9ece6a";
        yellow = "#e0af68";
        blue = "#7aa2f7";
        magenta = "#ad8ee6";
        cyan = "#449dab";
        white = "#9699a8";
      };
      bright = {
        black = "#444b6a";
        red = "#ff7a93";
        green = "#b9f27c";
        yellow = "#ff9e64";
        blue = "#7da6ff";
        magenta = "#bb9af7";
        cyan = "#0db9d7";
        white = "#acb0d0";
      };
    };

    font = {
      family = "SauceCodePro Nerd Font Mono";
      size = 20;
      sizeFloat = 20.0;  # For applications that need float
    };
  };
}
