---
name: learn
description: Interactive learning session to crystallize mistakes and improve staff-engineer prompt. Use when user says "you screwed up", "that's wrong", "you made a mistake", "that was incorrect", "learn from this", "remember this for next time". Guides dialogue to understand what happened, what went wrong, and what should happen, then launches new staff session to implement improvements.
version: 1.0
keep-coding-instructions: true
---

# Learn - Crystallize Mistakes and Improve Staff Engineer Prompt

**Purpose:** Turn staff engineer mistakes into prompt improvements through interactive dialogue followed by handoff to a fresh staff session for implementation.

**Target file:** `modules/claude/global/output-styles/staff-engineer.md`

## When to Use

Activate this skill when the user signals a mistake was made:
- "You screwed up"
- "That's wrong"
- "You made a mistake"
- "That was incorrect"
- "Learn from this"
- "Remember this for next time"
- "Why did you do X? You should have done Y"

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
- **What Happened:** Concrete description of staff engineer's actions
- **Why It Was Wrong:** Clear explanation of the mistake
- **Desired Behavior:** Specific guidance on what should have happened instead
- **Scope:** Always improvements to the target file

### Phase 2: TMUX Handoff (New Staff Session)

Once the user confirms the crystallized context:

1. **Create new TMUX window** (see Step 2 below for the full pattern)
2. **Navigate to nixpkgs:** `cd ~/.config/nixpkgs`
3. **Launch staff:** Run `staff` command (NOT `claude` directly)
4. **Inject structured prompt** with the crystallized mistake context

## Your Task

$ARGUMENTS

## Phase 1: Interactive Dialogue

**You already have conversation context.** Use it to surface what went wrong.

### Step 1: Acknowledge and Surface

Start by acknowledging the mistake and presenting what you understand went wrong:

**Template:**
```
I see the issue. Let me make sure I understand what went wrong.

**What I did:** [Describe your actions from conversation history]

**Why it was wrong:** [Your hypothesis about the mistake]

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
[Concrete description of staff engineer's actions]

## Why It Was Wrong
[Clear explanation of the mistake and its impact]

## Desired Behavior
[Specific guidance on what should happen instead]

## Scope
Improvements to the target file
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

## Your Task (Implementation Only)

Update `modules/claude/global/output-styles/staff-engineer.md` to prevent this mistake in the future.

**Implementation Steps:**
1. **FIRST:** Present a brief summary of what you understand from the context above and ask: "Anything you'd like to adjust or add before I start?" (Wait for user response)
2. Read the current staff-engineer.md file
3. Locate the relevant section (or determine if a new section is needed)
4. Propose specific changes (additions, clarifications, or new guidelines)
5. Confirm your proposed edit with the user
6. Implement the approved changes
7. Add to git and run `hms` to deploy the updated prompt

**Critical:**
- DO start with a lightweight clarification checkpoint (step 1 above) - context can drift between sessions
- DO NOT replay the full Phase 1 dialogue (no iterative "Is this accurate?" loops)
- AFTER user confirms or adjusts understanding, GO STRAIGHT TO: read file -> propose specific edit -> confirm -> implement

The goal is to make the staff engineer's behavior more reliable by encoding this lesson in the prompt.
```

### Step 2: Create TMUX Window and Launch Staff

**CRITICAL: Generate a topic-specific window name to avoid conflicts.**

Use the temp-file + atomic-window pattern (reliable TMUX window creation):

```bash
# Window name format: learn-<topic-in-kebab-case>
# Examples: learn-date-awareness, learn-tmux-naming, learn-source-code-access
# Generate name from the crystallized learning topic

# Step 1: Write prompt to temp file
cat > /tmp/learn-prompt.txt << 'EOF'
YOUR_STRUCTURED_PROMPT_HERE
EOF

# Step 2: Launch atomically
tmux new-window -n learn-<topic> -c ~/.config/nixpkgs 'staff "$(cat /tmp/learn-prompt.txt)"'
```

**Important:**
- **Window name:** `learn-<topic>` where `<topic>` is derived from the learning subject in short kebab-case format
  - Examples: `learn-delegation-rules`, `learn-kanban-workflow`, `learn-code-access-prohibition`
- Working directory: `~/.config/nixpkgs` (set via `-c` flag — no `cd` prefix needed)
- Command: `staff` (guaranteed to exist - it's the alias that launches Claude Code with staff-engineer output style)
- Prompt written to `/tmp/learn-prompt.txt` first, then read atomically at window launch — NEVER inline long prompts in TMUX commands
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

**Scope is always the staff-engineer prompt:**
This skill is specifically for improving the target file. The mistake crystallization should focus on staff engineer behavior, not other skills or agents.

**Exception skill behavior:**
- Runs in current conversation (uses Skill tool, NOT Task tool)
- Interactive dialogue before handoff
- User confirmation required before TMUX handoff

## Example Usage

**User says:** "You screwed up. You should have delegated that to an engineer instead of trying to investigate yourself."

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

## Scope
Improvements to the target file

I've crystallized the issue. Ready to launch a new staff session to implement the improvement?
```

**User:** "Yes, go ahead."

**Your response (Phase 2):**
```bash
# Topic: source-code-access (derived from the mistake about using Grep inappropriately)

# Step 1: Write prompt to temp file
cat > /tmp/learn-prompt.txt << 'EOF'
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
tmux new-window -n learn-source-code-access -c ~/.config/nixpkgs 'staff "$(cat /tmp/learn-prompt.txt)"'
```

Then inform the user:
```
Created a new staff session in TMUX window `learn-source-code-access` to implement the improvement.

Switch to it with:
- `tmux select-window -t learn-source-code-access`

The new staff engineer will start with a brief clarification checkpoint (presenting what it understands and asking for adjustments), then propose specific improvements to the target file. You can review and approve the changes in that session.
```

## Success Criteria

- [ ] Mistake acknowledged and conversation context leveraged
- [ ] Interactive dialogue crystallized what happened, why it was wrong, and desired behavior
- [ ] User confirmed the crystallized context
- [ ] Structured prompt created with clear context and requirements
- [ ] TMUX window created and staff launched with prompt
- [ ] User informed about how to access the new session

## Notes

- **This skill does NOT implement the improvement itself** - it crystallizes the learning and hands off to a fresh staff session
- **Always target the staff-engineer prompt** - this skill is for improving staff engineer behavior specifically
- **User confirmation required** - don't launch TMUX session without explicit user approval
- **Leverage conversation history** - you already have context, use it to speed up dialogue
- **Keep dialogue focused** - iterate until clear, but don't over-complicate
