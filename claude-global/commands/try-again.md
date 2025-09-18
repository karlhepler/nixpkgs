---
description: Generate refined prompt after implementation failure using reinforcement learning
---

# 🔄 Try Again - Reinforcement Learning Loop

**⚠️ IMPORTANT: This command generates a PROMPT for the user to copy. DO NOT create a plan or use ExitPlanMode.**

## 🧠 ANALYZING FAILURE MODE...

### Step 1: Checking for Provided Feedback

**Direct Feedback:** $ARGUMENTS

### Step 2: Conversation History Analysis

**Since no specific feedback was provided, I must analyze our conversation to identify what went wrong.**

Scanning conversation history for failure indicators...

📍 **Failure Indicators I'm Scanning For:**
- Direct corrections: "no", "not what I asked", "don't", "stop"
- Redirections: "actually", "instead", "just", "only"
- Scope violations: "I didn't ask for", "unnecessary", "too much"
- **Follow-up issues after plan approval** = implementation failure
- User having to test/fix things I should have gotten right
- "I addressed your concern" = should have anticipated first time

📋 **Issues Detected:**

1. **[Main problem statement]**
   - Specific detail about what went wrong
   - Another specific detail or example

2. **[Another problem statement]**
   - Specific detail
   - Additional context if needed

3. **[Third problem if found]**
   - Detail about this issue

*Note: Ensure ONE blank line between each numbered item for readability.*

❓ **Please review each numbered issue:**
- Tell me which issues are actual problems (YES/include) vs not problems (NO/exclude)
- Add any context, corrections, or additional guidance
- Mention anything I missed

**Your feedback:**

*Note: I'll parse your response flexibly - numbers on separate lines, mixed with context, however you prefer to respond.*

### Step 3: Generating Comprehensive Refined Prompt

After gathering ALL failure information (provided arguments + conversation analysis + user confirmation), I will generate:

---

# 🔄 REINFORCEMENT LEARNING ITERATION

## 🎯 ORIGINAL TASK
[Exact reproduction of the original request]

## 🚨 CRITICAL FAILURE PREVENTION

### ❌ Complete Failure Analysis:

**From Conversation History:**
[Reference confirmed issues by number: Issue #1, Issue #2, etc.]

**From User Feedback:**
[Additional issues and context provided]

### 🛑 MANDATORY CONSTRAINTS FOR THIS ATTEMPT:

**SPECIFIC FAILURES TO AVOID:**
[Reference each confirmed failure with prevention strategy]
- Issue #1: [Prevention strategy]
- Issue #2: [Prevention strategy]
- Issue #3: [Prevention strategy]

**CRITICAL CONSTRAINTS:**
- Implement ONLY what's requested - nothing more
- Anticipate edge cases/concerns upfront, don't wait for user to find them
- Test thoroughly BEFORE presenting as "complete"
- If plan approved but follow-up needed = implementation was insufficient

**MANDATORY CHECKS:**
- Before starting: "Does my approach handle all obvious edge cases?"
- During work: "Am I adding anything beyond the request?"
- Before calling complete: "Would this actually work in real usage?"

## 📋 IMPLEMENTATION REQUIREMENTS

1. Read existing patterns FIRST
2. Use existing approaches in codebase
3. Implement MINIMAL working solution
4. Think through edge cases BEFORE implementing
5. STOP when requirements fully met

### Must NOT Do:
[Prohibitions based on numbered failures]
- Related to Issue #1: [Specific prohibition]
- Related to Issue #2: [Specific prohibition]

## 🔍 COMPLETION CHECKLIST

□ Matches EXACT request?
□ Avoided ALL failure modes?
□ Anticipates obvious edge cases?
□ Uses existing patterns?
□ Zero unrequested additions?
□ Actually works in real usage?

## 💡 ACCUMULATED LEARNINGS

**Iteration History:**
- Attempt 1 Failed: [Reference confirmed issues by number]
- Key Lessons: [Most critical patterns learned from failures]

**Critical Reminders:**
- This is a RETRY after specific failures
- Previous attempt failed for DOCUMENTED reasons
- SCOPE DISCIPLINE is paramount
- When uncertain, ASK rather than assume

---

## Next Steps:

1. **Copy the refined prompt BELOW** (not a plan - just the prompt text)
2. **Run `git kill`** to reset repository
3. **Run `/clear new`** for fresh Claude instance
4. **Paste the refined prompt** to begin improved implementation

---

**COPY THIS REFINED PROMPT:**

[The refined prompt text appears here for copying - this is NOT a plan]

This reinforcement learning system improves with each iteration by:
- Analyzing conversation history for ALL corrections
- Building comprehensive failure prevention instructions
- Creating increasingly specific guardrails
- Accumulating learnings across attempts