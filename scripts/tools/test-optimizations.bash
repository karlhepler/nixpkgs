#!/usr/bin/env bash

echo "=== Testing Shell Optimizations ==="
echo ""

# Test 1: Simulate optimized shell startup
echo "1. Testing with optimizations (simulated):"
cat > /tmp/test-optimized.zsh << 'EOF'
#!/usr/bin/env zsh

# Fast compinit
autoload -Uz compinit
compinit -C -d ~/.zcompdump

# Simulate lazy loading (no actual loading)
__zoxide_hook() { : ; }
__fzf_tab_init() { : ; }
autoload -Uz add-zsh-hook
add-zsh-hook precmd __zoxide_hook
add-zsh-hook preexec __fzf_tab_init

# Simulate direnv hook load from file
_direnv_hook() { : ; }
typeset -ag precmd_functions
precmd_functions=(_direnv_hook $precmd_functions)

# Key bindings
bindkey -M viins 'jk' vi-cmd-mode
bindkey -M viins '^A' beginning-of-line
bindkey -M viins '^E' end-of-line

# Exit immediately (no tmux)
exit 0
EOF

TMUX=1 time zsh /tmp/test-optimized.zsh 2>&1
echo ""

# Test 2: Current shell startup for comparison
echo "2. Current shell startup time:"
TMUX=1 time zsh -i -c 'exit' 2>&1
echo ""

# Cleanup
rm -f /tmp/test-optimized.zsh

echo "=== Test Complete ==="