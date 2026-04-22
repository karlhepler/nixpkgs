---
name: agent-browser
description: Browser automation via agent-browser CLI — screenshots, PDFs, clicks, form fills, navigation. Use when an agent needs to see or interact with web pages, rendered UI, or capture visual snapshots.
allowed-tools: Bash(agent-browser open*), Bash(agent-browser snapshot*), Bash(agent-browser get*), Bash(agent-browser skills*), Bash(agent-browser screenshot*), Bash(agent-browser pdf*), Bash(agent-browser click*), Bash(agent-browser fill*), Bash(agent-browser type*), Bash(agent-browser press*), Bash(agent-browser drag*), Bash(agent-browser upload*), Bash(agent-browser navigate*)
---

# agent-browser — Browser Automation

READ THIS ENTIRE FILE before running agent-browser commands.

## HARD RULES — absolute, non-negotiable, override anything taught in the upstream reference

1. **NEVER run `agent-browser install`.** Chrome is Nix-managed (`pkgs.google-chrome`), wired via `AGENT_BROWSER_EXECUTABLE_PATH`. Running `install` downloads Chrome outside Nix's control.
2. **NEVER run `agent-browser upgrade`.** The binary is SRI-pinned in `modules/agent-browser/version.nix`. Upgrading outside Nix breaks reproducibility. If a version bump is needed, ask the user.
3. **NEVER run `agent-browser eval`.** It executes arbitrary JavaScript in the browser's authenticated session context — credential/data exfiltration risk. Use `snapshot` + `get text` or `get html` for data extraction instead. The upstream reference recommends `eval` for complex extraction — IGNORE that guidance; it does not apply in this repo.
4. **NEVER `npm i -g agent-browser` or `npx agent-browser`.** The CLI is Nix-installed; `which agent-browser` resolves to a /nix/store/ path. Use the Nix binary only.
5. **NEVER Homebrew.** This is a Nix-managed system — see global CLAUDE.md.
6. **ALWAYS use `--session <name>`.** Isolates browser state across unrelated tasks. Example: `agent-browser --session my-task-42 open https://example.com`. Without `--session` you share auth/cookies with the user's regular browser — that's a leak.
7. **ALWAYS write screenshots/PDFs to `.scratchpad/`.** Example: `agent-browser --session X screenshot --output .scratchpad/<card-id>-shot.png`. Never to `/tmp/`, CWD, or anywhere agent-controlled outside `.scratchpad/`.

## Full reference (on demand)

Vercel ships a 2,235-line core skill covering the snapshot-and-ref workflow, element interaction, form handling, and auth. It is NOT injected into this context — fetch only when needed:

    agent-browser skills get core --full

Read the output inline. Do not write it to disk unless you are genuinely reusing it across many turns; it adds ~8k tokens to your context.

When consulting the upstream reference: the HARD RULES above override any pattern it teaches.

## Quick patterns

- **Capture a page:** `agent-browser --session X open <url> && agent-browser --session X screenshot --output .scratchpad/X.png`
- **Read page text:** `agent-browser --session X open <url> && agent-browser --session X snapshot && agent-browser --session X get text`
- **Form interaction:** `open` → `snapshot` → `click <ref>` / `fill <ref> <value>` → `snapshot` again

Full CLI: `agent-browser --help`. Deep reference: fetch command above.
