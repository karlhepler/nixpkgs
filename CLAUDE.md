# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with this Nix Home Manager repository.

## Repository Overview

This repository contains Nix Home Manager configuration for managing development environments using the Nix package manager with flakes. It creates reproducible and declarative system configurations including shell setups (zsh), text editors (Neovim), terminal emulators, git configuration, and developer tools.

## Quick Commands

- `hms`: Apply Home Manager changes (use `--expunge` for complete environment refresh)
- `hme`: Edit the `home.nix` file (main configuration)
- `hmo`: Edit the `overconfig.nix` file (machine-specific customizations)
- `hm`: Change directory to Nix Packages configuration directory (`~/.config/nixpkgs`)

## Nix Development Commands

- `nix run nixpkgs#nix-prefetch-github -- owner repo --rev main`: Get hash for GitHub packages
- `nix flake update`: Update flake dependencies
- `nix flake metadata`: Show flake metadata
- `nix search nixpkgs <package>`: Search for available packages

## Configuration Structure

- `flake.nix`: Defines inputs and outputs for the Nix flake
  - **nixpkgs**: Stable channel (25.11)
  - **nixpkgs-unstable**: Unstable channel for bleeding-edge packages (available as `unstable` in home.nix)
  - **home-manager**: Release 25.11
  - **nix-index-database**: Fast command-not-found alternative
- `home.nix`: Main configuration file defining packages, programs, and configuration
- `overconfig.nix`: Machine-specific customizations (gitignored after sync)
- `claude-global.md`: Global Claude Code configuration and development preferences
- `.claude/`: Directory for Claude Code settings (gitignored)
- `neovim/`: Neovim configuration files
  - `vimrc`: Traditional Vim settings
  - `lspconfig.lua`: LSP (Language Server Protocol) configuration
- `scripts/`: Custom shell scripts and automation tools

## Making Changes

1. Modify appropriate files in `~/.config/nixpkgs/`
2. Run `hms` command which automatically:
   - Creates backup of `overconfig.nix` to `~/.backup/.config/nixpkgs/`
   - Makes git track `overconfig.nix` temporarily
   - Runs `home-manager switch` to apply configuration
   - Makes git ignore `overconfig.nix` changes again
   - Prompts to restart tmux server (requires explicit `y`/`Y` confirmation)

## Home Manager Activation Process

When running `hms`, these activation hooks run automatically:
1. **gitIgnoreOverconfigChanges**: Makes git ignore overconfig.nix changes
2. **claudeSettings**: Symlinks Claude Code settings with configured hooks
3. **claudeGlobal**: Copies global Claude settings
4. **precompileZshCompletions**: Compiles zsh completions for faster shell startup
5. **generateDirenvHook**: Creates static direnv hook for performance

Note: Application management is handled natively by home-manager 25.11+. Apps are automatically available in ~/Applications/Home Manager Apps for Spotlight/Alfred indexing.

## Shell Applications (Custom Commands)

### Git Workflow
- `commit`: Enhanced git commit with automatic staging
- `pull`: Smart git pull with automatic upstream tracking
- `push`: Smart git push with automatic upstream setting
- `save`: Combines commit and push operations
- `git-branches`: Interactive branch selector with preview
- `git-kill`: Reset current branch to clean state
- `git-trunk`: Switch to and update main/master branch
- `git-sync`: Merge latest trunk changes into current branch
- `git-resume`: Checkout most recently used branch
- `git-tmp`: Create/switch to temporary branch (karlhepler/tmp)
- `workout`: Git worktree management tool (auto-evaluates cd commands)

### Claude Code Integration
- `claude-notification-hook`: Handles Claude Code notifications
- `claude-complete-hook`: Handles Claude Code completion events
- `claude-csharp-format-hook`: Auto-formats C# files after Edit/Write operations

## Custom Scripts

- `scripts/quicket.bash`: Create Jira tickets
- `scripts/quickpr.bash`: Create pull requests integrated with Jira
- `scripts/claude-notification-hook.bash`: Claude Code notification handler
- `scripts/claude-complete-hook.bash`: Claude Code completion handler
- `scripts/test-optimizations.bash`: Shell optimization testing
- `scripts/profile-shell.bash`: Shell performance profiling

## Important Git Handling

**overconfig.nix File Management:**
- Designed for per-machine customizations and secrets
- Made "invisible" to git using `git update-index --assume-unchanged`
- The `hms` command handles visibility automatically:
  1. Makes file visible: `git update-index --no-assume-unchanged overconfig.nix`
  2. Runs home-manager switch
  3. Makes file invisible again: `git update-index --assume-unchanged overconfig.nix`
- **Automatic backups**: Created at `~/.backup/.config/nixpkgs/overconfig.YYYYMMDD-HHMMSS.nix`
- Symlink `overconfig.latest.nix` points to most recent backup

## Editors and Terminal

- **Primary Editor**: Neovim (vim/vi aliases enabled)
- **GUI Editor**: Neovide (unstable channel)
- **Terminal**: Alacritty (configured with Tokyo Night Storm theme)
- **Font**: SauceCodePro Nerd Font Mono, size 20
- **Color Scheme**: Tokyo Night Storm (consistent across tmux, Alacritty, Neovim)

## Neovim Plugin Architecture

Key integrations:
- **LSP**: Configured for TypeScript, Bash, C#, Nix, Go, Python, Haskell
- **claude-tmux-neovim**: Special plugin for Claude Code integration (keybindings for sending selections)
- **FZF Integration**: `<C-p>` for file search, `<C-b>` for LSP symbols
- **Copilot**: GitHub Copilot enabled
- **Treesitter**: Parsers for bash, C#, gdscript, go, helm, lua, markdown, nix, python, rust, starlark, typescript, yaml

## Claude Code Configuration

This repository includes integrated Claude Code settings:
- Global preferences defined in `claude-global.md`
- Notification and completion hooks configured in `home.nix`
- Settings managed through `.claude/` directory (gitignored)

## GitHub Package Updates

For packages using `rev = "main"` with fixed hash:

1. Get latest hash: `nix run nixpkgs#nix-prefetch-github -- owner repo --rev main`
2. Update hash in `home.nix`
3. Apply changes: `hms`

## Performance Optimizations

This config includes several shell performance optimizations:
- Precompiled zsh completions (`.zcompdump.zwc`)
- Static direnv hook generation
- Async zsh autosuggestions
- Fast compinit without security checks (`compinit -C`)

## Critical Requirements

1. **Repository Location**: MUST be installed at `~/.config/nixpkgs` - other locations will cause errors
2. **Use hms Command**: Always use `hms` for syncing to ensure proper git handling of `overconfig.nix`
3. **Backup Synchronization**: Sync `~/.backup` folder with cloud storage for machine-specific configuration safety
4. **Shell Applications**: All custom commands are defined in `home.nix` under the `shellapps` section

## Automation Safety

Claude Code must never use the `--expunge` flag with `hms`.

## Communication Best Practices

### Structured Response Format

Use XML tags to structure complex responses for clarity:

```xml
<analysis>
  <current_state>Description of what exists now</current_state>
  <goal>What we're trying to achieve</goal>
  <approach>Chosen strategy with rationale</approach>
</analysis>

<implementation>
  <step number="1">
    <action>What will be done</action>
    <file>Specific file path</file>
    <rationale>Why this approach</rationale>
  </step>
</implementation>
```

### Investigation Protocol

When debugging or researching issues:

1. **Think Step-by-Step**: Articulate reasoning at each stage
2. **Search Exhaustively**: Look for multiple potential causes, not just the first issue found
3. **Verify Assumptions**: Check actual behavior before proposing solutions
4. **Reflect After Tool Use**: Analyze results and determine next steps explicitly

Example investigation structure:
```xml
<investigation>
  <hypothesis>What I think might be wrong</hypothesis>
  <verification_steps>
    - Check A
    - Examine B
    - Test C
  </verification_steps>
  <findings>What was discovered</findings>
  <additional_checks>Continue searching for other issues</additional_checks>
</investigation>
```

## Working Examples

### ✅ Correct Scope Discipline

**User Request**: "Fix the bug where the login button doesn't disable during API calls"

**Good Response**:
```xml
<analysis>
  <scope>Modify login button to disable state during authentication API call only</scope>
  <files_affected>
    - src/components/LoginButton.tsx (add disabled state logic)
  </files_affected>
  <boundary>Will NOT modify error handling, validation, or other button behaviors</boundary>
</analysis>
```

Then implement only the disabled state change.

**Why This Works**: Single, focused change addressing exact request

---

**User Request**: "The tests are failing"

**Good Response**:
```xml
<investigation>
  <step_1>Run test suite to see all failures</step_1>
  <step_2>Examine first failure in detail</step_2>
  <step_3>Check for related failures (cascading effects)</step_3>
  <step_4>Search for additional unrelated failures</step_4>
  <reasoning>Software issues often have multiple causes - investigating thoroughly before proposing fixes</reasoning>
</investigation>
```

**Why This Works**: Systematic approach looking for all issues, not just the first one

### ❌ Scope Violations to Avoid

**User Request**: "Fix the bug where the login button doesn't disable during API calls"

**Poor Response**: "I'll fix the button disabling issue. While I'm here, I also notice the error handling could be improved, the button styling is inconsistent, and we should add loading spinner animation..."

**Why This Fails**: Adding unrequested improvements violates single-task principle

---

**User Request**: "The tests are failing"

**Poor Response**: "I found the issue - there's a typo in line 45. Let me fix that."

**Why This Fails**: Stops at first issue without checking for other problems

### Check-In Template

For complex or multi-file changes, always check in first:

```xml
<check_in>
  <task>Update authentication flow to support OAuth</task>
  <why>Current password-only auth doesn't meet security requirements</why>
  <approach>
    Integrate oauth2 library (considering passport vs. next-auth)
    Chose next-auth because it's already used in the codebase
  </approach>
  <changes>
    - src/auth/config.ts: Add OAuth provider configuration
    - src/pages/api/auth/[...nextauth].ts: Create NextAuth route handler
    - src/components/LoginButton.tsx: Update to use NextAuth signIn
  </changes>
  <scope_confirmation>
    Changes limited to OAuth integration only
    NOT modifying existing password auth
    NOT updating user profile pages
    NOT changing session management
  </scope_confirmation>
  <ready>Shall I proceed with these specific changes?</ready>
</check_in>
```

## Reasoning and Reflection Prompts

Apply these thinking patterns to ensure thorough work:

### Before Starting
- "What exactly is being asked for?"
- "What are the boundaries of this change?"
- "What alternatives exist?"

### During Implementation
- "Does this change affect other parts of the system?"
- "Am I staying within the defined scope?"
- "What could go wrong with this approach?"

### After Tool Use
- "What did this tool call reveal?"
- "Are there additional issues to investigate?"
- "Does this finding change my approach?"

### Before Completing
- "Have I addressed the full request?"
- "Did I introduce any unintended changes?"
- "Are there related issues I should mention separately?"

## Success Criteria

You'll know you're on track when:

1. **Scope is Crystal Clear**: Can state the deliverable in one sentence
2. **Changes are Minimal**: Modifying only what's necessary
3. **Communication is Transparent**: User understands approach before execution
4. **Investigation is Complete**: Found multiple issues or confirmed single cause
5. **Boundaries are Explicit**: Clear about what's NOT being changed