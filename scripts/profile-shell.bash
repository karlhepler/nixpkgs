#!/usr/bin/env bash

# Profile shell startup time with detailed timing

echo "=== Shell Startup Profiling ==="
echo "Starting profiling at: $(date +%s.%N)"
echo ""

# Test 1: Basic zsh startup without config
echo "1. Testing basic zsh (no config):"
time zsh -c 'exit' 2>&1
echo ""

# Test 2: Zsh with full config
echo "2. Testing zsh with full config:"
time zsh -i -c 'exit' 2>&1
echo ""

# Test 3: Profile individual components
echo "3. Profiling individual components..."
echo ""

# Create a temporary profiling script
cat > /tmp/zsh-profile.zsh << 'EOF'
#!/usr/bin/env zsh
zmodload zsh/zprof

# Source the actual zsh config
if [[ -f ~/.zshrc ]]; then
    source ~/.zshrc
fi

# Print profiling results
zprof
EOF

echo "Running zsh with profiling enabled:"
zsh /tmp/zsh-profile.zsh 2>&1 | head -50
echo ""

# Test 4: Test without tmux auto-start
echo "4. Testing without tmux auto-start:"
TMUX=1 time zsh -i -c 'exit' 2>&1
echo ""

# Test 5: Component-by-component timing
echo "5. Component timing analysis:"
echo ""

# Create test script for individual components
cat > /tmp/component-test.zsh << 'EOF'
#!/usr/bin/env zsh

start_time=$(($(date +%s%N)/1000000))
last_time=$start_time

function time_mark() {
    local current_time=$(($(date +%s%N)/1000000))
    local delta=$((current_time - last_time))
    local total=$((current_time - start_time))
    printf "%-40s: %5dms (total: %5dms)\n" "$1" "$delta" "$total"
    last_time=$current_time
}

time_mark "Start"

# Test PATH setup
nix_path='/nix/var/nix/profiles/default/bin'
nix_profile_path="$HOME/.nix-profile/bin"
go_bin_path="$GOPATH/bin"
export PATH="$go_bin_path:$nix_profile_path:$nix_path:$PATH"
time_mark "PATH setup"

# Test zoxide
if command -v zoxide >/dev/null 2>&1; then
    eval "$(zoxide init --cmd cd zsh)"
    time_mark "zoxide init"
fi

# Test fzf-tab
if [[ -f "${HOME}/.nix-profile/share/fzf-tab/fzf-tab.plugin.zsh" ]]; then
    source "${HOME}/.nix-profile/share/fzf-tab/fzf-tab.plugin.zsh"
    time_mark "fzf-tab"
fi

# Test starship
if command -v starship >/dev/null 2>&1; then
    eval "$(starship init zsh)"
    time_mark "starship init"
fi

# Test direnv
if command -v direnv >/dev/null 2>&1; then
    eval "$(direnv hook zsh)"
    time_mark "direnv hook"
fi

# Test fzf
if [[ -f "${HOME}/.fzf.zsh" ]]; then
    source "${HOME}/.fzf.zsh"
    time_mark "fzf integration"
fi

# Test syntax highlighting
if [[ -f "${HOME}/.nix-profile/share/zsh-syntax-highlighting/zsh-syntax-highlighting.zsh" ]]; then
    source "${HOME}/.nix-profile/share/zsh-syntax-highlighting/zsh-syntax-highlighting.zsh"
    time_mark "syntax highlighting"
fi

# Test autosuggestions
if [[ -f "${HOME}/.nix-profile/share/zsh-autosuggestions/zsh-autosuggestions.zsh" ]]; then
    source "${HOME}/.nix-profile/share/zsh-autosuggestions/zsh-autosuggestions.zsh"
    time_mark "autosuggestions"
fi

time_mark "Complete"
EOF

TMUX=1 zsh /tmp/component-test.zsh
echo ""

# Clean up
rm -f /tmp/zsh-profile.zsh /tmp/component-test.zsh

echo "=== Profiling Complete ==="
echo "Finished at: $(date +%s.%N)"