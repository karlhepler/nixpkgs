---
name: learn
description: Interactive learning session to crystallize mistakes and improve Claude configuration. Use when user says "you screwed up", "that's wrong", "you made a mistake", "that was incorrect", "learn from this", "remember this for next time", "fix the skill", "fix the prompt", "update the agent", "update staff engineer", "improve burns", "fix smithers". Guides dialogue to identify which Claude artifact needs improvement (staff engineer prompt, team member skill, agent definition, burns/Ralph orchestrator, smithers, etc.), understand what went wrong, and what should happen, then launches new staff session to implement improvements.
version: 1.1
---

# Learn - Crystallize Mistakes and Improve Claude Configuration

**Purpose:** Turn mistakes into prompt improvements through interactive dialogue followed by handoff to a fresh staff session for implementation.

**Default target:** `modules/claude/global/output-styles/staff-engineer.md` (when context is ambiguous)

## When to Use

Activate this skill when the user signals a mistake was made or wants to improve a Claude artifact:
- "You screwed up"
- "That's wrong"
- "You made a mistake"
- "That was incorrect"
- "Learn from this"
- "Remember this for next time"
- "Why did you do X? You should have done Y"
- "Fix the prompt"
- "Fix the [skill/agent/burns/smithers/ralph]"
- "Update [team member name]'s skill"
- "Improve [Claude config artifact]"

**This is an exception skill.** It runs in the current conversation, NOT as a background sub-agent.

## How This Skill Works

**Two-phase process:**

### Phase 1: Interactive Dialogue (In Current Conversation)

Guide conversation to crystallize:
1. **What happened** - What did the staff engineer do?
2. **What went wrong** - Why was that a mistake?
3. **What should have happened** - What's the desired behavior?

**You already have full conversation context.** Surface what you think went wrong and confirm with the user. Iterate back and forth until both agree on a clear, structured description.

**Dialogue pattern (borrowed from project-planner):**
- Start by acknowledging the mistake: "I see the issue. Let me make sure I understand what went wrong."
- Present your understanding of what happened and why it was wrong
- Ask clarifying questions: "Is the issue that I should have X instead of Y?"
- Iterate until the user confirms: "Yes, that's exactly it."

**Output of Phase 1:** A structured summary containing:
- **What Happened:** Concrete description of the artifact's actions or behavior
- **Why It Was Wrong:** Clear explanation of the mistake
- **Desired Behavior:** Specific guidance on what should have happened instead
- **Target:** The artifact name and file path to update

### Phase 2: TMUX Handoff (New Staff Session)

Once the user confirms the crystallized context:

1. **Create new TMUX window** (see Step 2 below for the full pattern)
2. **Navigate to nixpkgs:** `cd ~/.config/nixpkgs`
3. **Launch staff:** Run `staff` command (NOT `claude` directly)
4. **Inject structured prompt** with the crystallized mistake context

## Your Task

$ARGUMENTS

## Hard Prerequisites

**Before anything else: verify required permissions are in the project's `permissions.allow`.**

Due to a known Claude Code bug ([GitHub #5140](https://github.com/anthropics/claude-code/issues/5140)), global `~/.claude/settings.json` permissions are **not** inherited by projects with their own `permissions.allow` -- project settings replace globals entirely. To verify: read `.claude/settings.json` or `.claude/settings.local.json` in the project root and confirm each required permission appears in the `permissions.allow` array.

**Required:**
- `Bash(tmux *)` -- needed to create TMUX windows for the handoff session
- `Write(.scratchpad/**)` -- needed to write the structured prompt file before TMUX launch (`.scratchpad/` is project-local, persists across sessions)

**If any are missing:** Stop immediately. Do not start work. Surface to the staff engineer:
> "Blocked: Required permissions (`Bash(tmux *)`, `Write(.scratchpad/**)`) are missing from `permissions.allow`. Add them before delegating learn."

## Phase 1: Interactive Dialogue

**You already have conversation context.** Use it to surface what went wrong.

### Step 0: Identify the Target Artifact

Before the dialogue, determine which Claude artifact needs improvement. Use conversation context and any explicit user direction.

**Known artifact types:**

| Artifact | File Path | Notes |
|----------|-----------|-------|
| Staff engineer prompt (default) | `modules/claude/global/output-styles/staff-engineer.md` | |
| Team member skill | `modules/claude/global/commands/<name>.md` | For skill-generated hats, also see hat template row below |
| Agent definition | `modules/claude/global/agents/<name>.md` | |
| Hat template (routing/wiring) | `modules/claude/global/hats/<name>.yml.tmpl` | Build-time only — never deployed to `~/.claude/`. Controls display name, routing description, trigger/published events, backpressure. Edit when changing how Ralph routes to this hat or its event wiring. Skill-generated hats have two edit surfaces: this file (routing) + the skill `.md` file (expertise). |
| Monty Burns hat | `modules/claude/global/hats/monty-burns.yml.tmpl` | Standalone special case — fully self-contained, no corresponding skill file. Its instructions live directly in the hat template. |
| Burns / Ralph orchestrator | `modules/claude/burns.py` | Launcher script only — hat behavior is in `monty-burns.yml.tmpl` above |
| Smithers | `~/.config/nixpkgs/modules/claude/smithers.py` | |
| Other Claude config | Identify from conversation context | |

**Decision logic:**
- User explicitly names an artifact (e.g., "fix the swe-backend skill") → use that artifact
- Mistake clearly involves a specific team member's behavior → use their skill file
- Mistake involves staff engineer coordination/orchestration behavior → use staff engineer prompt (default)
- Context is ambiguous → default to staff engineer prompt, confirm with user during dialogue

**If the target is ambiguous:** Surface your assumption early in Step 1 so the user can correct it.

### Step 1: Acknowledge and Surface

Start by acknowledging the mistake and presenting what you understand went wrong:

**Template:**
```
I see the issue. Let me make sure I understand what went wrong.

**What I did:** [Describe your actions from conversation history]

**Why it was wrong:** [Your hypothesis about the mistake]

**Target for improvement:** [Named artifact and file path — or "staff engineer prompt (default)" if ambiguous]

Is this accurate, or did I misunderstand the problem?
```

### Step 2: Iterate Until Clear

Ask clarifying questions until the user confirms:
- "Is the issue that I should have [X] instead of [Y]?"
- "So the desired behavior is [specific guidance]?"
- "Does this mean I should [action] in situations like [context]?"

**Keep iterating until the user says something like:**
- "Yes, that's exactly it."
- "Correct."
- "That's right."

### Step 3: Crystallize the Context

Once confirmed, structure the learnings:

**Structured Summary:**
```
## What Happened
[Concrete description of the artifact's actions or behavior]

## Why It Was Wrong
[Clear explanation of the mistake and its impact]

## Desired Behavior
[Specific guidance on what should happen instead]

## Target
[Artifact name and file path to update]
```

**Present this to the user and ask:** "I've crystallized the issue. Ready to launch a new staff session to implement the improvement?"

## Phase 2: TMUX Handoff

**Only proceed after user confirms (e.g., "yes", "go ahead", "do it").**

### Step 1: Build the Structured Prompt

Create a prompt for the new staff session that includes:

**Prompt Template:**
```
YOU ARE A FRESH STAFF SESSION LAUNCHED BY THE /learn SKILL

This is an IMPLEMENTATION SESSION. The diagnostic dialogue has ALREADY been completed in a previous conversation. DO NOT replay Phase 1 dialogue (no "I see the issue, let me make sure I understand..." or "Is this accurate?").

Your job: CLARIFY -> READ -> PROPOSE EDIT -> CONFIRM WITH USER -> IMPLEMENT.

## Context: What Went Wrong (Already Crystallized)

**What Happened:**
[Concrete description from Phase 1]

**Why It Was Wrong:**
[Explanation from Phase 1]

**Desired Behavior:**
[Specific guidance from Phase 1]

**Target:**
[Artifact name and file path from Phase 1]

## Your Task (Implementation Only)

Update `[TARGET FILE PATH]` to prevent this mistake in the future.

**Implementation Steps:**
1. **FIRST:** Present a brief summary of what you understand from the context above and ask: "Anything you'd like to adjust or add before I start?" (Wait for user response)
2. Read the current target file
3. Locate the relevant section (or determine if a new section is needed)
4. Propose specific changes (additions, clarifications, or new guidelines)
5. Confirm your proposed edit with the user
6. Implement the approved changes
7. Add to git and run `hms` to deploy the updated prompt

**Critical:**
- DO start with a lightweight clarification checkpoint (step 1 above) - context can drift between sessions
- DO NOT replay the full Phase 1 dialogue (no iterative "Is this accurate?" loops)
- AFTER user confirms or adjusts understanding, GO STRAIGHT TO: read file -> propose specific edit -> confirm -> implement

The goal is to make the artifact's behavior more reliable by encoding this lesson in the prompt.
```

### Step 2: Create TMUX Window and Launch Staff

**CRITICAL: Generate a topic-specific window name to avoid conflicts.**

Use the temp-file + atomic-window pattern (reliable TMUX window creation):

```bash
# Window name format: learn-<topic-in-kebab-case>
# Examples: learn-date-awareness, learn-tmux-naming, learn-source-code-access
# Generate name from the crystallized learning topic

# Step 1: Write prompt to scratchpad (filename matches window name for uniqueness)
cat > .scratchpad/learn-<topic>-prompt.txt << 'EOF'
YOUR_STRUCTURED_PROMPT_HERE
EOF

# Step 2: Launch atomically
tmux new-window -n learn-<topic> -c ~/.config/nixpkgs 'staff "$(cat .scratchpad/learn-<topic>-prompt.txt)"'

# Step 3: Clean up (one-shot consumed input)
rm .scratchpad/learn-<topic>-prompt.txt
```

**Important:**
- **Window name:** `learn-<topic>` where `<topic>` is derived from the learning subject in short kebab-case format
  - Examples: `learn-delegation-rules`, `learn-kanban-workflow`, `learn-code-access-prohibition`
- Working directory: `~/.config/nixpkgs` (set via `-c` flag — no `cd` prefix needed)
- Command: `staff` (guaranteed to exist - it's the alias that launches Claude Code with staff-engineer output style)
- Prompt written to `.scratchpad/learn-<topic>-prompt.txt` first (filename matches window name for uniqueness across concurrent sessions), then read atomically at window launch — NEVER inline long prompts in TMUX commands
- NEVER use `tmux send-keys` as a separate step — window creation and command must be atomic

### Step 3: Inform the User

After launching the TMUX window, tell the user:

**Template:**
```
Created a new staff session in TMUX window `learn-<topic>` to implement the improvement.

Switch to it with:
- `tmux select-window -t learn-<topic>`

The new staff engineer has been given the context about what went wrong and will propose specific improvements to the target file. You can review and approve the changes in that session.
```

**Replace `<topic>` with the actual topic-specific window name you generated** (e.g., `learn-delegation-rules`).

## Important Constraints

**Guaranteed dependencies (no defensive checks needed):**
- `tmux` command exists (Nix-managed)
- `staff` command exists (shellapp in this repo)
- `~/.config/nixpkgs` directory exists (this repo's location)

**Scope is any Claude configuration artifact:**
This skill improves any Claude config — staff engineer prompt (default), team member skills, agent definitions, burns/Ralph, smithers, or other Claude-related config files. The target is determined from conversation context in Phase 1.

**Exception skill behavior:**
- Runs in current conversation (uses Skill tool, NOT Task tool)
- Interactive dialogue before handoff
- User confirmation required before TMUX handoff

## Example Usage

**Example 1 — Default target (staff engineer prompt): user says:** "You screwed up. You should have delegated that to an engineer instead of trying to investigate yourself."

**Your response (Phase 1, Step 1):**
```
I see the issue. Let me make sure I understand what went wrong.

**What I did:** I used Grep to search the codebase for error handling patterns instead of delegating to an engineer.

**Why it was wrong:** The staff engineer's role is coordination, not investigation. I violated the "NO SOURCE CODE ACCESS" rule by attempting to examine the codebase myself.

Is this accurate, or did I misunderstand the problem?
```

**User:** "Yes, exactly. You should have created a card and delegated to swe-backend."

**Your response (Phase 1, Step 3):**
```
## What Happened
Staff engineer used Grep to search codebase for error handling patterns instead of delegating.

## Why It Was Wrong
Violated "NO SOURCE CODE ACCESS" rule. Staff engineer should coordinate via delegation, not investigate source code directly.

## Desired Behavior
When investigation is needed, create kanban card and delegate to appropriate engineer (e.g., swe-backend) via Task tool. Never use Read/Grep/Glob on source code.

## Target
`modules/claude/global/output-styles/staff-engineer.md`

I've crystallized the issue. Ready to launch a new staff session to implement the improvement?
```

**Non-default target example — user says:** "The swe-backend skill is giving wrong advice about APIs. It keeps suggesting REST when we've standardized on GraphQL."

**Your response (Phase 1, Step 1):**
```
I see the issue. Let me make sure I understand what went wrong.

**What I did:** The swe-backend skill recommended REST endpoints for the new data layer.

**Why it was wrong:** The project has standardized on GraphQL. Recommending REST contradicts that decision and sends engineers in the wrong direction.

**Target for improvement:** `modules/claude/global/commands/swe-backend.md` (team member skill)

Is this accurate, or did I misunderstand the problem?
```

**Your response (Phase 1, Step 3):**
```
## What Happened
swe-backend skill recommended REST endpoints for the new data layer.

## Why It Was Wrong
The project has standardized on GraphQL. Recommending REST contradicts that decision and sends engineers in the wrong direction.

## Desired Behavior
swe-backend should default to GraphQL for all new data layer work and only suggest REST when there is an explicit reason to deviate.

## Target
`modules/claude/global/commands/swe-backend.md`

I've crystallized the issue. Ready to launch a new staff session to implement the improvement?
```

**User:** "Yes, go ahead."

**Your response (Phase 2):** Phase 2 follows the same pattern shown in Example 1. The only differences are the target file (`modules/claude/global/commands/swe-backend.md`), the window name (`learn-graphql-standardization`), and the crystallized context above.

---

**Example 1 Phase 2 (shown in full for reference):**

**Your response (Phase 2):**
```bash
# Topic: source-code-access (derived from the mistake about using Grep inappropriately)

# Step 1: Write prompt to scratchpad (filename matches window name for uniqueness)
cat > .scratchpad/learn-source-code-access-prompt.txt << 'EOF'
YOU ARE A FRESH STAFF SESSION LAUNCHED BY THE /learn SKILL

This is an IMPLEMENTATION SESSION. The diagnostic dialogue has ALREADY been completed in a previous conversation. DO NOT replay Phase 1 dialogue (no "I see the issue, let me make sure I understand..." or "Is this accurate?").

Your job: CLARIFY -> READ -> PROPOSE EDIT -> CONFIRM WITH USER -> IMPLEMENT.

## Context: What Went Wrong (Already Crystallized)

**What Happened:**
Staff engineer used Grep to search codebase for error handling patterns instead of delegating.

**Why It Was Wrong:**
Violated "NO SOURCE CODE ACCESS" rule. Staff engineer should coordinate via delegation, not investigate source code directly.

**Desired Behavior:**
When investigation is needed, create kanban card and delegate to appropriate engineer (e.g., swe-backend) via Task tool. Never use Read/Grep/Glob on source code.

## Your Task (Implementation Only)

Update `modules/claude/global/output-styles/staff-engineer.md` to prevent this mistake in the future.

**Implementation Steps:**
1. **FIRST:** Present a brief summary of what you understand from the context above and ask: "Anything you'd like to adjust or add before I start?" (Wait for user response)
2. Read the current staff-engineer.md file
3. Locate the relevant section (likely "NO SOURCE CODE ACCESS" or "What You Do vs What You Do NOT Do")
4. Propose specific changes (strengthen prohibitions, add examples, or clarify edge cases)
5. Confirm your proposed edit with the user
6. Implement the approved changes
7. Add to git and run `hms` to deploy the updated prompt

**Critical:**
- DO start with a lightweight clarification checkpoint (step 1 above) - context can drift between sessions
- DO NOT replay the full Phase 1 dialogue (no iterative "Is this accurate?" loops)
- AFTER user confirms or adjusts understanding, GO STRAIGHT TO: read file -> propose specific edit -> confirm -> implement

The goal is to make the staff engineer's behavior more reliable by encoding this lesson in the prompt.
EOF

# Step 2: Launch atomically
tmux new-window -n learn-source-code-access -c ~/.config/nixpkgs 'staff "$(cat .scratchpad/learn-source-code-access-prompt.txt)"'

# Step 3: Clean up (one-shot consumed input)
rm .scratchpad/learn-source-code-access-prompt.txt
```

Then inform the user:
```
Created a new staff session in TMUX window `learn-source-code-access` to implement the improvement.

Switch to it with:
- `tmux select-window -t learn-source-code-access`

The new staff engineer will start with a brief clarification checkpoint (presenting what it understands and asking for adjustments), then propose specific improvements to the target file. You can review and approve the changes in that session.
```

## Success Criteria

- [ ] Identified correct target artifact in Step 0
- [ ] Mistake acknowledged and conversation context leveraged
- [ ] Interactive dialogue crystallized what happened, why it was wrong, and desired behavior
- [ ] User confirmed the crystallized context
- [ ] Structured prompt created with clear context and requirements
- [ ] TMUX window created and staff launched with prompt
- [ ] User informed about how to access the new session

## Notes

- **This skill does NOT implement the improvement itself** - it crystallizes the learning and hands off to a fresh staff session
- **Default to staff-engineer prompt when ambiguous** - if context doesn't clearly point to another artifact, assume staff engineer and surface that assumption early so the user can correct it
- **Accept any Claude artifact target** - team member skills, agent definitions, burns/Ralph, smithers, or any other Claude config in `modules/claude/`
- **User confirmation required** - don't launch TMUX session without explicit user approval
- **Leverage conversation history** - you already have context, use it to speed up dialogue
- **Keep dialogue focused** - iterate until clear, but don't over-complicate
