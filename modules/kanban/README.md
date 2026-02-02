# Kanban CLI - Insertion Sort Workflow

File-based kanban board system designed for multi-agent coordination using an insertion sort pattern.

## Philosophy: Think Before You Add

This kanban system enforces **intentional prioritization** by requiring you to think about **where** a new card belongs in relation to existing work, just like insertion sort requires understanding the sorted list before inserting.

## Quick Start

```bash
# Initialize board (auto-created in git root or current directory)
kanban init

# See current state
kanban list

# Add first card to empty column (defaults to priority 1000)
kanban add "Implement feature X" --persona Developer

# Add another card - MUST specify position for non-empty todo
kanban add "Fix critical bug" --top --persona Developer
kanban add "Write docs" --bottom --persona Scribe
kanban add "Add tests" --after 001 --persona Developer

# View your work
kanban todo           # View todo cards
kanban doing          # View in-progress cards
kanban next           # Get next card to work on

# Work a card
kanban move 001 doing
kanban comment 001 "Started implementation"
kanban move 001 done
```

## Insertion Sort Workflow

### The Pattern

When adding a card to any column:

1. **Read** - Run `kanban list` to see ALL existing cards and their priorities
2. **Understand** - Comprehend the relative importance/urgency of existing cards
3. **Determine** - Decide where your new card fits in the priority order
4. **Position** - Use position flags to place the card correctly
5. **Verify** - Check `kanban list` again to confirm proper placement

### Why This Matters

Like insertion sort examining a sorted array before inserting, this workflow forces you to:
- **Consider context** - What's already queued?
- **Make trade-offs** - Is this more important than existing work?
- **Maintain order** - Keep the backlog prioritized, not just added to randomly
- **Communicate intent** - Your position choice signals relative importance to other agents

## Priority System

### How Priority Works

- **Lower number = Higher priority** (appears earlier in list)
- **Priority 0** - Minimum allowed (no negatives)
- **Priority 1000** - Default for first card in empty column (baseline)
- **Spacing** - System uses increments of 5-10 to leave room for future insertions

### Priority Assignment Rules

| Scenario | Position Flag | Priority Assignment |
|----------|---------------|---------------------|
| Empty column, first card | (none) | 1000 (baseline) |
| Non-empty todo | **REQUIRED** | Based on position |
| `--top` | Insert at top | `min(existing) - 10`, floor at 0 |
| `--bottom` | Insert at bottom | `max(existing) + 10` |
| `--after <card>` | After specific card | `card_priority + 5` |
| `--before <card>` | Before specific card | `card_priority - 5`, floor at 0 |

### Example Priority Sequence

```
[   0] Fix production outage    (--top, went below previous min)
[1000] Implement feature X       (first card, default baseline)
[1005] Add tests for feature X   (--after 001)
[2000] Write documentation       (--bottom on second add)
[2010] Update README             (--bottom again)
```

## Position Flags

### `--top` - Highest Priority

Places card at the top of the column (earliest in work order).

```bash
# Critical bug - needs immediate attention
kanban add "Fix security vulnerability" --top --persona Developer
```

**Use when:** Card is more urgent than ALL existing cards.

### `--bottom` - Lowest Priority

Places card at the bottom of the column (latest in work order).

```bash
# Nice-to-have improvement
kanban add "Refactor legacy code" --bottom --persona Developer
```

**Use when:** Card is less urgent than ALL existing cards.

### `--after <card>` - Relative Positioning

Places card immediately after specified card.

```bash
# Implementation follows planning
kanban add "Implement API endpoint" --after 001-design-api --persona Developer
```

**Use when:** Card has a natural dependency or sequence relationship.

### `--before <card>` - Relative Positioning

Places card immediately before specified card.

```bash
# Testing must happen before deployment
kanban add "Run integration tests" --before 005-deploy --persona Developer
```

**Use when:** Card must happen before another specific card.

## Common Workflows

### Solo Work

```bash
# Morning routine: Check board state
kanban list

# Add new tasks with priority consideration
kanban add "Fix bug #123" --top
kanban add "Update docs" --bottom

# Get next work
kanban next

# Work the card
kanban move 001 doing
# ... do work ...
kanban move 001 done

# Repeat
kanban next
```

### Multi-Agent Coordination

```bash
# Each agent filters by session (auto-detected in Claude Code)
kanban todo                    # See your session's todo cards
kanban add "My task" --top     # Add to your session

# Check what other agents are doing
kanban doing --all-sessions

# Avoid conflicts - check before claiming
kanban list
kanban move 003 doing  # Claim unclaimed card
```

### Reprioritization

```bash
# Emergency - bump card to top
kanban top 005

# Deprioritize - move to bottom
kanban bottom 003

# Fine-tuning - move up/down by small increments
kanban up 002      # Decrease priority by 10
kanban down 004    # Increase priority by 10
```

## Session Isolation

Cards can be scoped to specific Claude Code sessions for parallel agent work:

```bash
# Add card to specific session
kanban add "Agent-specific task" --session abc123 --top

# View only current session's cards (auto-detected)
kanban todo

# View all sessions
kanban todo --all-sessions

# View specific session
kanban todo --session abc123
```

Session ID is auto-detected from environment when running in Claude Code.

## Priority Best Practices

### Do's

- **Check first** - Always run `kanban list` before adding
- **Think relative** - Consider where card fits among existing work
- **Use spacing** - Position flags create appropriate gaps (5-10 priority units)
- **Stay positive** - Priorities must be >= 0 (system validates this)
- **Start high** - First card defaults to 1000, leaving room below

### Don'ts

- **Don't guess** - Don't add cards without reviewing existing priorities
- **Don't append blindly** - Don't always use `--bottom` (consider importance!)
- **Don't ignore order** - Priority order signals work sequence to other agents
- **Don't assume** - Empty columns are fine with no position flag, but non-empty require it

### When Priority Numbers Get Crowded

If you run out of room between cards (e.g., priorities 1000, 1001, 1002):

```bash
# Option 1: Use --before or --after with existing small gaps
kanban add "Urgent fix" --before 1001  # Creates priority 996

# Option 2: Reprioritize entire column with larger spacing
# (Manual operation - reorder existing cards to 1000, 2000, 3000, etc.)
```

The system uses increments of 5-10 specifically to avoid this issue in normal use.

## Command Reference

### Board Management

```bash
kanban init [path]              # Create board structure
kanban list                     # Show full board overview
kanban list --show-done         # Include done column
kanban clear                    # Delete all cards (with confirmation)
kanban clear --yes              # Skip confirmation
```

### Card Operations

```bash
kanban add "title" [flags]      # Add card (see Position Flags above)
kanban show <card>              # Display card contents
kanban edit <card> [flags]      # Edit card content/metadata
kanban delete <card>            # Delete card
kanban comment <card> "msg"     # Add comment to card
```

### Card Movement

```bash
kanban move <card> <column>     # Move to different column
kanban top <card>               # Move to top of current column
kanban bottom <card>            # Move to bottom of current column
kanban up <card>                # Increase priority (decrease number by 10)
kanban down <card>              # Decrease priority (increase number by 10)
```

### Viewing & Filtering

```bash
kanban todo                     # View todo column
kanban doing                    # View doing column
kanban blocked                  # View blocked column
kanban done                     # View done column

# Session filtering (for multi-agent work)
kanban todo --session <id>      # Specific session
kanban todo --all-sessions      # All sessions

# Work selection
kanban next                     # Get highest priority card
kanban next --persona Developer # Filter by persona
kanban next --skip 2            # Skip first 2 cards
```

### History

```bash
kanban history                  # Show all completed cards
kanban history --since today    # Today's completions
kanban history --since week     # Last 7 days
kanban history --since 2024-01-01  # Since specific date
```

## Architecture

### File Structure

```
.kanban/
├── todo/
│   ├── 001-implement-feature-x.md
│   └── 002-fix-bug.md
├── doing/
│   └── 003-write-docs.md
├── blocked/
└── done/
    └── 004-completed-task.md
```

### Card Format

```markdown
---
persona: Developer
priority: 1000
session: abc123
created: 2024-01-01T12:00:00Z
updated: 2024-01-01T13:00:00Z
---

# Implement Feature X

Task description here...

## Activity
- [2024-01-01 12:30] Started work
- [2024-01-01 13:00] Completed implementation
```

## Integration with Claude Code

The kanban CLI is designed for Claude Code agent coordination:

- **Auto-allowed** - Claude agents don't need permission prompts for kanban commands
- **Session isolation** - Auto-detects session IDs from environment
- **Shared filesystem** - Multiple agents coordinate via file-based cards
- **Priority-driven** - `kanban next` ensures agents work highest priority items first

### Typical Agent Usage

```bash
# Agent starts work
kanban next --persona Developer

# Agent claims card
kanban move <card> doing

# Agent adds progress notes
kanban comment <card> "Implemented core logic"
kanban comment <card> "Added tests"

# Agent completes work
kanban move <card> done

# Agent gets next card
kanban next --persona Developer
```

## Why Insertion Sort?

The insertion sort pattern enforces **intentional backlog management**:

1. **Forces context** - Must look at existing work before adding
2. **Prevents chaos** - Can't just append randomly to backlog
3. **Maintains order** - Priority sequence is always clear
4. **Signals intent** - Position choice communicates importance
5. **Enables coordination** - Multiple agents can work from same prioritized queue

Just like insertion sort examines the sorted array before inserting, this workflow makes you examine the current backlog before adding new work.

## Troubleshooting

### "Error: Position required"

You tried to add a card to a non-empty todo column without specifying position.

**Solution:** Run `kanban list`, then add with `--top`, `--bottom`, `--after`, or `--before`.

### "Error: Priority must be >= 0"

You tried to create a card with negative priority (system prevented this).

**Solution:** This should not happen in normal use. If it does, the system has protected you from invalid state.

### Cards out of order

Manually edited priority values or moved cards between columns.

**Solution:** Use `kanban up/down/top/bottom` to adjust priorities within column.

### Running out of priority space

Too many cards with priorities too close together (e.g., 1000, 1001, 1002).

**Solution:** System uses increments of 5-10 to prevent this. If it happens, manually reprioritize with larger spacing.

## Related Documentation

- Main project: `/Users/karlhepler/.config/nixpkgs/CLAUDE.md`
- Module location: `/Users/karlhepler/.config/nixpkgs/modules/kanban/`
- Command source: `/Users/karlhepler/.config/nixpkgs/modules/kanban/kanban.py`
