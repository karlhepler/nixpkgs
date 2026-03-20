#!/usr/bin/env bash
set -eou pipefail

# Reload Home Manager session variables into the current shell
# - Sources the Home Manager session vars without restarting the shell
# - Useful after running 'hms' to apply environment changes

show_help() {
  echo "reload-env - Reload Home Manager session variables into current shell"
  echo
  echo "USAGE:"
  echo "  reload-env    Reload environment variables from Home Manager"
  echo
  echo "DESCRIPTION:"
  echo "  Sources ~/.nix-profile/etc/profile.d/hm-session-vars.sh to reload"
  echo "  Home Manager environment variables in the current shell session"
  echo "  without needing to restart the terminal or shell."
  echo
  echo "WHEN TO USE:"
  echo "  After running 'hms' to apply Home Manager configuration changes,"
  echo "  use this to reload the environment in your current shell window."
  echo
  echo "EXAMPLES:"
  echo "  # Run hms and reload environment in same shell session"
  echo "  hms && reload-env"
}

# Parse arguments
if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  show_help
  exit 0
fi

# Source the Home Manager session variables
# shellcheck disable=SC1091,SC1090
source ~/.nix-profile/etc/profile.d/hm-session-vars.sh
