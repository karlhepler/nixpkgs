# Staff Engineer Reduction Validation Checklist

## Critical Behaviors to Verify After Reduction

After reducing staff-engineer.md to ~400 lines, verify these behaviors are preserved:

### Core Delegation Protocol
- [ ] 4-step protocol present: Check Board → Create Card → Task → Skill
- [ ] Mnemonic included for reinforcement
- [ ] BLOCKING REQUIREMENT emphasized

### Investigation Prohibition
- [ ] "Let me check..." explicitly called out as anti-pattern
- [ ] No Read, Grep, gh commands listed as forbidden
- [ ] Delegate investigation rule is clear

### Stay Available
- [ ] Core principle stated: delegate so you can keep talking
- [ ] Blocking conversation is identified as anti-pattern

### Permission Handling
- [ ] Background agents use kanban comments + blocked status
- [ ] Format examples provided
- [ ] Staff engineer executes after review

### Understand WHY Before Delegating
- [ ] XY Problem awareness included
- [ ] Paraphrase first pattern
- [ ] Decision framework: when to ask vs delegate

### Mandatory Reviews
- [ ] Table of high-risk work types requiring reviews
- [ ] Infrastructure, auth, database, CI/CD covered
- [ ] Reviews are NON-NEGOTIABLE (not optional)

### Risk-Based Team Composition
- [ ] Risk is PRIMARY decision factor
- [ ] Parallel as DEFAULT for risky/complex work
- [ ] High/Medium/Low risk framework
- [ ] Mandatory pairings table (security + infra, etc.)

### TODO-Based Review Process
- [ ] Create review tickets with --status todo
- [ ] Implementation completes BEFORE reviews
- [ ] Reviews progress through workflow separately

### Model Selection
- [ ] Sonnet default, Opus for complex, Haiku for trivial
- [ ] Autonomous selection with notification

### Kanban Workflow
- [ ] Column semantics (todo/doing/blocked/done/canceled)
- [ ] Priority system
- [ ] Session management

### Your Team Table
- [ ] All 16+ skills listed with trigger words

### Success Criteria Checklist
- [ ] Anti-patterns enumerated
- [ ] Before Every Response checklist

## Post-Reduction Testing

After validation, test with real scenarios:
1. Ask staff engineer to implement a feature requiring multiple specialists
2. Ask staff engineer to investigate a bug (should delegate to researcher)
3. Verify mandatory reviews trigger for infrastructure work
4. Verify board checks happen before delegation

## Rollback Plan

If any critical behavior is missing:
1. Restore from backup: staff-engineer.backup.md
2. Document what was lost
3. Revise reduction plan
4. Re-attempt reduction
