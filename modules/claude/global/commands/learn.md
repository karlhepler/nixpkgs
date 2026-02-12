---
name: learn
description: Interactive learning session to crystallize mistakes and improve staff-engineer prompt. Use when user says "you screwed up", "that's wrong", "you made a mistake", "that was incorrect", "learn from this", "remember this for next time". Guides dialogue to understand what happened, what went wrong, and what should happen, then launches new staff session to implement improvements.
version: 1.0
keep-coding-instructions: true
---

# Learn - Crystallize Mistakes and Improve Staff Engineer Prompt

**Purpose:** Turn staff engineer mistakes into prompt improvements through interactive dialogue followed by handoff to a fresh staff session for implementation.

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
- **Scope:** Always improvements to `modules/claude/global/output-styles/staff-engineer.md`

### Phase 2: TMUX Handoff (New Staff Session)

Once the user confirms the crystallized context:

1. **Create new TMUX window**
2. **Navigate to nixpkgs:** `cd ~/.config/nixpkgs`
3. **Launch staff:** Run `staff` command (NOT `claude` directly)
4. **Inject structured prompt** with the crystallized mistake context

**TMUX pattern (borrowed from workout-staff):**
```bash
# Window name MUST be topic-specific to avoid conflicts
# Format: learn-<topic-in-kebab-case>
# Examples: learn-date-awareness, learn-tmux-naming, learn-source-code-access
tmux new-window -d -n learn-<topic> -c ~/.config/nixpkgs "staff 'Your structured prompt here'"
```

**The structured prompt must include:**
- What the staff engineer did wrong (concrete example)
- Why it was wrong (root cause analysis)
- What should happen instead (desired behavior)
- Scope constraint (always staff-engineer.md improvements)
- Clear instruction to implement the improvement

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
Improvements to `modules/claude/global/output-styles/staff-engineer.md`
```

**Present this to the user and ask:** "I've crystallized the issue. Ready to launch a new staff session to implement the improvement?"

## Phase 2: TMUX Handoff

**Only proceed after user confirms (e.g., "yes", "go ahead", "do it").**

### Step 1: Build the Structured Prompt

Create a prompt for the new staff session that includes:

**Prompt Template:**
```
The staff engineer made a mistake that needs to be addressed by improving the staff-engineer.md prompt file.

## Context: What Went Wrong

**What Happened:**
[Concrete description from Phase 1]

**Why It Was Wrong:**
[Explanation from Phase 1]

**Desired Behavior:**
[Specific guidance from Phase 1]

## Your Task

Update `modules/claude/global/output-styles/staff-engineer.md` to prevent this mistake in the future.

**Requirements:**
1. Identify the section(s) that need updating
2. Propose specific changes (additions, clarifications, or new guidelines)
3. Ensure changes are clear, actionable, and integrated well with existing content
4. Add to git and run `hms` to deploy the updated prompt

**Approach:**
- Read the current staff-engineer.md file
- Locate the relevant section (or determine if a new section is needed)
- Propose the specific edit
- Confirm with the user before implementing

The goal is to make the staff engineer's behavior more reliable by encoding this lesson in the prompt.
```

### Step 2: Create TMUX Window and Launch Staff

**CRITICAL: Generate a topic-specific window name to avoid conflicts.**

Use the pattern from workout-staff (TMUX window creation with command injection):

```bash
# Window name format: learn-<topic-in-kebab-case>
# Examples: learn-date-awareness, learn-tmux-naming, learn-source-code-access
# Generate name from the crystallized learning topic
tmux new-window -n learn-<topic> -c ~/.config/nixpkgs
tmux send-keys -t learn-<topic> 'staff "YOUR_STRUCTURED_PROMPT_HERE"' C-m
```

**Important:**
- **Window name:** `learn-<topic>` where `<topic>` is derived from the learning subject in short kebab-case format
  - Examples: `learn-delegation-rules`, `learn-kanban-workflow`, `learn-code-access-prohibition`
- Working directory: `~/.config/nixpkgs` (guaranteed to exist)
- Command: `staff` (guaranteed to exist - it's the alias that launches Claude Code with staff-engineer output style)
- Prompt passed as first argument to `staff`

**Escape handling:** If the prompt contains quotes or special characters, use a heredoc pattern:

```bash
tmux new-window -n learn-<topic> -c ~/.config/nixpkgs
tmux send-keys -t learn-<topic> "staff \"$(cat <<'EOF'
[Your multi-line structured prompt here]
EOF
)\"" C-m
```

### Step 3: Inform the User

After launching the TMUX window, tell the user:

**Template:**
```
Created a new staff session in TMUX window `learn-<topic>` to implement the improvement.

Switch to it with:
- `tmux select-window -t learn-<topic>`

The new staff engineer has been given the context about what went wrong and will propose specific improvements to the staff-engineer.md prompt file. You can review and approve the changes in that session.
```

**Replace `<topic>` with the actual topic-specific window name you generated** (e.g., `learn-delegation-rules`).

## Important Constraints

**Guaranteed dependencies (no defensive checks needed):**
- `tmux` command exists (Nix-managed)
- `staff` command exists (shellapp in this repo)
- `~/.config/nixpkgs` directory exists (this repo's location)

**Scope is always staff-engineer prompt:**
This skill is specifically for improving `modules/claude/global/output-styles/staff-engineer.md`. The mistake crystallization should focus on staff engineer behavior, not other skills or agents.

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
Improvements to `modules/claude/global/output-styles/staff-engineer.md`

I've crystallized the issue. Ready to launch a new staff session to implement the improvement?
```

**User:** "Yes, go ahead."

**Your response (Phase 2):**
```bash
# Topic: source-code-access (derived from the mistake about using Grep inappropriately)
tmux new-window -n learn-source-code-access -c ~/.config/nixpkgs
tmux send-keys -t learn-source-code-access "staff \"$(cat <<'EOF'
The staff engineer made a mistake that needs to be addressed by improving the staff-engineer.md prompt file.

## Context: What Went Wrong

**What Happened:**
Staff engineer used Grep to search codebase for error handling patterns instead of delegating.

**Why It Was Wrong:**
Violated "NO SOURCE CODE ACCESS" rule. Staff engineer should coordinate via delegation, not investigate source code directly.

**Desired Behavior:**
When investigation is needed, create kanban card and delegate to appropriate engineer (e.g., swe-backend) via Task tool. Never use Read/Grep/Glob on source code.

## Your Task

Update `modules/claude/global/output-styles/staff-engineer.md` to prevent this mistake in the future.

**Requirements:**
1. Identify the section(s) that need updating (likely "NO SOURCE CODE ACCESS" or "What You Do vs What You Do NOT Do")
2. Propose specific changes (strengthen prohibitions, add examples, or clarify edge cases)
3. Ensure changes are clear, actionable, and integrated well with existing content
4. Add to git and run `hms` to deploy the updated prompt

**Approach:**
- Read the current staff-engineer.md file
- Locate the relevant section (or determine if a new section is needed)
- Propose the specific edit
- Confirm with the user before implementing

The goal is to make the staff engineer's behavior more reliable by encoding this lesson in the prompt.
EOF
)\"" C-m
```

Then inform the user:
```
Created a new staff session in TMUX window `learn-source-code-access` to implement the improvement.

Switch to it with:
- `tmux select-window -t learn-source-code-access`

The new staff engineer has been given the context about what went wrong and will propose specific improvements to the staff-engineer.md prompt file. You can review and approve the changes in that session.
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
- **Always target staff-engineer.md** - this skill is for improving staff engineer behavior specifically
- **User confirmation required** - don't launch TMUX session without explicit user approval
- **Leverage conversation history** - you already have context, use it to speed up dialogue
- **Keep dialogue focused** - iterate until clear, but don't over-complicate
