# Project Planner — Worked Examples

Two complete worked examples showing the LogFrame planning framework applied end-to-end — from BACKGROUND AND CONTEXT through the CAUSAL RELATIONSHIP CHECK, including the necessity table, sufficiency checklist, causal chain diagram, and link-by-link validation. Read this file from `SKILL.md` when authoring a plan and you need to see the full framework applied concretely to a real request, section by section, rather than reasoning from the abstract rules alone.

## Complete Example: Test Infrastructure Improvement

**Stated request:** "We want to implement Bazel for our build system."

*This example shows the two-document structure. The one-pager portion (`test-infrastructure.md`) comes first; the companion portion (`test-infrastructure-DETAIL.md`) follows.*

### BACKGROUND AND CONTEXT - Why Are We Doing This?

The test suite has grown from 500 to 8,000 tests over three years with no infrastructure investment. Local runs now take 45 minutes, and three engineers cited slow CI as a top frustration in recent exit interviews. Leadership has prioritized developer tooling ahead of the next hiring cycle.

### GOAL - What Outcome Are We Achieving?

**Maze's engineering org delivers on quarterly product OKRs without infrastructure-related bottlenecks.**

### OBJECTIVE - What Change Are We Making?

By Q3 2026, developers are not blocked by slow tests or false-failure debugging during their daily work.

### SUCCESS MEASURES - How We Know We Achieved the Goal

| Base | Target | Means of Verification | Prerequisite |
|------|--------|----------------------|-------------|
| 45 min | <5 min | CI logs via `gh api /repos/owner/repo/actions/runs` | ✅ exists |
| 3 hrs/day/dev | <30 min/day/dev | Developer time tracking dashboard | ⚠️ no tracking exists → **Deliverable #4** |
| 2.1/5 | >4/5 | Quarterly developer survey Q12 | ✅ exists |

### ASSUMPTIONS - What We Can't Control

| Assumption | Risk Level | How to Monitor | Contingency Plan |
|------------|------------|----------------|-----------------|
| Developers will adopt local test workflow | Medium | Weekly CI usage via GitHub Actions API, monthly developer survey Q15 | If adoption <50% after 4 weeks, schedule mandatory onboarding sessions and pair-program with resistant engineers |

**Note:**
- Initial assumption "We can get analytics data" was converted to deliverable "Analytics instrumentation" (team has full control).
- "Existing test suite can be parallelized" was Low risk → Ignored (validated with week 1 proof-of-concept spike instead).

### DELIVERABLES - What We'll Build

1. **Fast Local Test Execution System**
   - Run full test suite in <5 minutes locally
   - Automatic test parallelization (run tests in parallel)
   - Intelligent test selection (only run tests affected by changes)

2. **Flaky Test Detection and Quarantine**
   - Auto-detect flaky tests (inconsistent pass/fail on same code)
   - Mark flaky tests clearly in CI output (visual indicator)
   - Quarantine system (run flaky tests but don't block merges)

3. **Developer Enablement Materials**
   - Written guide for local test workflow (setup + usage)
   - Loom video walkthrough (5 min, screen recording)
   - Migration helper script (automates setup for developers)

4. **Developer Time Tracking Dashboard**
   - Track time developers spend blocked by test failures (automated via CI event logs)
   - Dashboard showing daily/weekly blocked time per developer
   - API endpoint for programmatic access: `/api/metrics/developer-blocked-time`
   - **Rationale**: Added because "blocked time" success measure requires this capability (identified during Verification Feasibility Check)

5. **End of Project Status Report**
   - Validate each success measure (local test runtime, blocked time, satisfaction)
   - Table comparing Base | Target | Actual | Status for each measure
   - Document whether we achieved the goal: "Unblock developers, ship 50% faster"
   - Lessons learned and recommendations

Confidence: Adequate — direct causation once adoption assumption holds (mitigated by D3).

Full detail → [test-infrastructure-DETAIL.md](./test-infrastructure-DETAIL.md)

**Note:**
- Original request was "implement Bazel" but Five Whys revealed real need was faster tests. Bazel is one solution, but test parallelization achieves same outcome with less risk and complexity (existing tooling, not full build system migration).
- "Developer Time Tracking Dashboard" was added after Verification Feasibility Check revealed we couldn't collect "blocked time" data without it.

---

**Companion — `test-infrastructure-DETAIL.md`:**

Read the one-pager first: [test-infrastructure.md](./test-infrastructure.md)

### DELIVERABLE ESTIMATES

1. **Fast Local Test Execution System** — *Estimate: 3 work cards + 1 review (parallel batch) → P90: ~20m wall-clock*
2. **Flaky Test Detection and Quarantine** — *Estimate: 2 work cards + 1 review → P90: ~15m wall-clock*
3. **Developer Enablement Materials** — *Estimate: 2 work cards → P90: ~10m wall-clock*
4. **Developer Time Tracking Dashboard** — *Estimate: 2 work cards + 1 review → P90: ~15m wall-clock*
5. **End of Project Status Report** — *Estimate: 1 work card → P90: ~7m wall-clock*

### SUFFICIENT AND NECESSARY CHECK (Layers 1 + 2)

**Layer 1 — Necessity Table**

| # | Deliverable | Remove it — do success measures remain verifiable AND meet targets? | Verdict |
|---|-------------|---------------------------------------------------------------------|---------|
| D1 | Fast Local Test Execution | Without this, the "local test runtime <5min" success measure cannot be met — no mechanism exists to reduce 45min runtime. | Necessary |
| D2 | Flaky Test Detection & Quarantine | Without this, the "time blocked by flaky tests <30min/day/dev" success measure cannot be met — false failures continue blocking merges with no quarantine path. | Necessary |
| D3 | Developer Enablement Materials | Without this, the "developer satisfaction >4/5" success measure cannot meet its target — adoption friction from the absence of guides and migration scripts is the primary barrier the satisfaction measure is designed to detect. D3 is the only deliverable that addresses the adoption assumption, which is Medium-risk; without it, the assumption goes High-risk with no mitigation path. | Necessary |
| D4 | Developer Time Tracking Dashboard | Without this, the "blocked time <30min/day/dev" success measure has no verification path — no mechanism exists to collect blocked-time data. | Necessary |
| D5 | End of Project Status Report | Without this, no deliverable provides the Base vs Target vs Actual comparison required to verify all success measures at project close. | Necessary |

**Layer 2 — Sufficiency Checklist**

Objective: "By Q3 2026, developers are not blocked by slow tests or false-failure debugging during their daily work."

Are they sufficient together?

- ✓ "not blocked by slow tests" — D1 (fast local test execution system: parallelization + intelligent test selection under 5min)
- ✓ "not blocked by false-failure debugging" — D2 (flaky test detection + quarantine: stops false failures from blocking merges)
- ✓ "blocked time" (success measure term) — D4 (dashboard provides data collection for measuring unblocked time)
- ✓ "developer satisfaction" (success measure term) — D1 + D2 (faster tests and fewer false failures improve daily experience) + D3 (enablement reduces adoption friction)

Gaps? None identified. Every aspect of the objective (unblocked by slow tests, unblocked by false-failures) maps to a deliverable. Every success measure term has a deliverable providing the data or the improvement.

### CAUSAL RELATIONSHIP CHECK (Layer 3)

```
D1 (Fast Local Tests) ────────────────┐
D2 (Flaky Detection) ─────────────────┤
D3 (Enablement Materials) ────────────┼──→ OBJECTIVE: developers not blocked by slow tests or false failures
D4 (Time Tracking Dashboard) ─────────┤         ↓
D5 (Status Report) ───────────────────┘   GOAL: engineering org delivers OKRs without infra bottlenecks
+ ASSUMPTIONS:
  - Developers will adopt local test workflow (Medium, mitigated by D3)
  verified by: test runtime <5min, blocked time <30min/day, satisfaction >4/5
```

Link-by-link validation:

1. D1 → local test runtime <5min? Yes. Parallelization + intelligent selection directly reduce runtime. ✓
2. D2 → false failures stop blocking merges? Yes. Quarantine system isolates flaky tests from merge path. ✓
3. D3 → adoption assumption softened? Yes. Guides, video, migration script reduce friction. ✓
4. D4 → "blocked time" success measure verifiable? Yes. Dashboard provides the data collection capability identified as missing. ✓
5. D5 → outcomes validated? Yes. Status report compares Base vs Target vs Actual for all measures. (Note: D5 verifies outcomes but does not cause them — it's an accountability deliverable.) ✓
6. All deliverables together = objective met? Yes. D1-D4 deliver the systems, D5 validates results. Environmental change (unblocked developers) in place. ✓
7. Assumptions hold? Developers adopt (Medium) — mitigated by D3, monitored via CI usage + survey. ✓
8. DELIVERABLES + ASSUMPTIONS → OBJECTIVE → GOAL? If we deliver fast tests + flaky detection + enablement + tracking and developers adopt → objective met (developers not blocked). Unblocked developers → engineering org can deliver OKRs without infra drag → goal achieved. Runtime verifies speed ✓. Blocked time verifies unblocking ✓. Satisfaction verifies impact ✓. All trace to goal. ✓

Confidence: **Strong**. Direct causation — delivering the objective (developers not blocked by slow tests or false failures) with adoption assumption holding directly contributes to the goal (engineering org delivers OKRs without infrastructure bottlenecks).

**Key insight from causal check:** Added "Developer Enablement Materials" deliverable after recognizing that "developers adopt" assumption had Medium risk. Enablement materials reduce this risk by making adoption easier (guides, videos, migration script).

**Example End of Project Status Report (after project completion):**

| Success Measure | Base | Target | Actual | Status |
|-----------------|------|--------|--------|--------|
| Local test runtime | 45 min | <5 min | 4.2 min | ✅ Success |
| Time blocked by flaky tests | 3 hrs/day/dev | <30 min/day/dev | 25 min/day/dev | ✅ Success |
| Developer satisfaction | 2.1/5 | >4/5 | 4.3/5 | ✅ Success |

## Example 2: Small Project (Documentation Improvement)

**Stated request:** "We need better onboarding docs."

*This example shows the two-document structure. The one-pager portion (`onboarding-docs.md`) comes first; the companion portion (`onboarding-docs-DETAIL.md`) follows.*

### BACKGROUND AND CONTEXT - Why Are We Doing This?

The team doubled in size last quarter and we have no written onboarding materials — everything is passed mouth-to-ear. Senior engineers are losing 30%+ of their week to new-hire questions, and the last two new engineers both asked for better documentation in their 30-day check-ins.

### GOAL - What Outcome Are We Achieving?

**The team scales headcount without eroding senior engineering capacity.**

### OBJECTIVE - What Change Are We Making?

By October 1, 2026, new engineers self-serve answers to setup, architecture, and workflow questions without pulling senior engineers away from product work.

### SUCCESS MEASURES - How We Know We Achieved the Goal

| Base | Target | Means of Verification | Prerequisite |
|------|--------|----------------------|-------------|
| 4 weeks | <2 weeks | HR onboarding tracking (time to first merged PR) | ✅ exists |
| 60% | <20% | New engineer survey week 2 | ✅ exists |

### ASSUMPTIONS - What We Can't Control

| Assumption | Risk Level | How to Monitor | Contingency Plan |
|------------|------------|----------------|-----------------|
| New engineers will read documentation before asking questions | Medium | Doc page views via analytics, engineer survey week 2 | If doc page views remain low, add documentation links to PR template and onboarding checklist; schedule a mandatory docs walkthrough in week 1 |

**Note:** Initial assumption "Docs will be discoverable" converted to deliverable "Documentation site with search" (team has control).

### DELIVERABLES - What We'll Build

1. **Onboarding Documentation Site**
   - Setup guide (environment, tools, access)
   - Architecture overview with diagrams
   - Common workflows (branching, testing, deploying)
   - FAQ covering top 20 new engineer questions

2. **End of Project Status Report**
   - Validate each success measure (time to contribution, question time)
   - Table comparing Base | Target | Actual | Status for each measure
   - Document whether we achieved the goal: "New engineers contribute in <2 weeks"
   - Lessons learned

Confidence: Adequate — depends on adoption assumption (Medium risk, monitored).

Full detail → [onboarding-docs-DETAIL.md](./onboarding-docs-DETAIL.md)

---

**Companion — `onboarding-docs-DETAIL.md`:**

Read the one-pager first: [onboarding-docs.md](./onboarding-docs.md)

### DELIVERABLE ESTIMATES

1. **Onboarding Documentation Site** — *Estimate: 3 work cards + 1 review (parallel batch) → P90: ~20m wall-clock*
2. **End of Project Status Report** — *Estimate: 1 work card → P90: ~7m wall-clock*

### SUFFICIENT AND NECESSARY CHECK (Layers 1 + 2)

**Layer 1 — Necessity Table**

| # | Deliverable | Remove it — do success measures remain verifiable AND meet targets? | Verdict |
|---|-------------|---------------------------------------------------------------------|---------|
| D1 | Onboarding Documentation Site | Without this, no deliverable addresses "time to first merged PR" or "question time" — both success measures fail because the mechanism that reduces ramp-up time and interrupts does not exist. | Necessary |
| D2 | End of Project Status Report | Without this, no deliverable provides the Base vs Target vs Actual comparison required to verify all success measures at project close. | Necessary |

**Layer 2 — Sufficiency Checklist**

Objective: "By October 1, 2026, new engineers self-serve answers to setup, architecture, and workflow questions without pulling senior engineers away from product work."

Are they sufficient together?

- ✓ "self-serve answers to setup questions" — D1 (setup guide covering environment, tools, access)
- ✓ "self-serve answers to architecture questions" — D1 (architecture overview with diagrams)
- ✓ "self-serve answers to workflow questions" — D1 (branching, testing, deploying + FAQ)
- ✓ "without pulling senior engineers away" — D1 (FAQ covers top 20 questions, reducing interrupts)
- ✓ "time to contribution" (success measure term) — D1 (self-serve answers reduce ramp-up time)
- ✓ "question time" (success measure term) — D1 (FAQ + guides replace asking senior engineers)

Gaps? None identified. D1 covers every aspect of the objective (self-serve across setup, architecture, workflows). Both success measure terms are served by D1's content.

### CAUSAL RELATIONSHIP CHECK (Layer 3)

```
D1 (Onboarding Docs Site) ────────────┐
D2 (Status Report) ───────────────────┼──→ OBJECTIVE: new engineers self-serve without pulling senior engineers
                                                ↓
                                          GOAL: team scales headcount without eroding senior engineering capacity
+ ASSUMPTIONS:
  - New engineers will read docs before asking questions (Medium, monitored via page views + survey)
  verified by: time to first PR <2 weeks, question time <20%
```

Link-by-link validation:

1. D1 → self-serve answers available? Yes. Setup guide + architecture + workflows + FAQ cover the top question categories. ✓
2. D2 → outcomes validated? Yes. Status report compares Base vs Target vs Actual. ✓
3. All deliverables together = objective met? Yes. Docs site + status report = self-serve capability delivered. Environmental change in place. ✓
4. Assumptions hold? Engineers read docs (Medium) — monitored via page views + survey, contingency adds docs to PR template and mandatory walkthrough. ✓
5. DELIVERABLES + ASSUMPTIONS → OBJECTIVE → GOAL? If we deliver docs and engineers read them → they self-serve answers (objective met). Unblocked senior engineers → team can scale headcount without capacity erosion → goal achieved. Time to first PR verifies contribution speed ✓. Question time verifies self-service ✓. Both trace to goal. ✓

Confidence: **Adequate**. Logical chain — delivering docs (deliverables) + engineers reading them (assumption) → self-serve capability (objective) → scaling without capacity drain (goal). Depends on adoption assumption (Medium risk, monitored).

**Key insight:** This is a **minimal viable project** - only 2 deliverables (docs + status report). Shows you don't need complexity for valid planning. The three-layer check still applies — even minimal projects benefit from explicit validation.
