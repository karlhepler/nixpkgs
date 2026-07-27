# Document A — What Anthropic Officially Says About Prompting the v5 Model Family

**Status:** durable project documentation. **Written:** 2026-07-27. **Scope:** statement of Anthropic's official guidance only — no diagnosis of this repository, no proposed changes.

## Executive Summary

Six research passes over Anthropic's official documentation, synthesized into one cited statement of what Anthropic says about prompting the v5 family: **Claude Opus 5** (2026-07-24) and **Claude Sonnet 5** (2026-06-30). There is no Claude Haiku 5 — the lightweight tier remains Haiku 4.5. Claude Fable 5 and Claude Mythos 5 exist above Opus in the lineup but were not researched. A seventh pass (A7) was added by amendment and covers official guidance on authoring the artifact classes themselves — CLAUDE.md and memory files, output styles, agent definitions, and Agent Skills; see [§ Authoring Guidance By Artifact Class](#authoring-guidance-by-artifact-class) and [§ Amendment Log](#amendment-log).

Anthropic's framing is targeted subtraction, not rewrite:

> It performs well out of the box on existing Claude Opus 4.8 prompts. The following patterns cover the behaviors that most often require tuning.

Five things matter most for long-form agent prompts.

**1. Instructions the model now performs unprompted are documented as harmful to keep.** Opus 5 self-verifies; explicit verification instructions "cause over-verification," and removing them "reduces wasted tokens with no loss in quality." Scoped to Opus 5, with no Sonnet 5 equivalent.

**2. Literal instruction-following is the default.** Sonnet 5 "does not silently generalize an instruction from one item to another, and it does not infer requests you didn't make." Scope must be stated where it applies. Both v5 guides document that severity-gating language in review prompts is now obeyed literally, suppressing findings.

**3. Visible length is prompt-controlled, not parameter-controlled, on Opus 5.** Effort "controls how much the model thinks rather than how much it says." Sonnet 5 is the opposite case: it self-calibrates to task complexity.

**4. Aggressive emphasis language is documented as causing overtriggering.** `"CRITICAL: You MUST use this tool when..."` should become `"Use this tool when..."`. This is the strongest position Anthropic takes, and it is narrower than a general claim about ALL-CAPS, emoji, or repetition — see [§ Emphasis And Over-Steering](#emphasis-and-over-steering) for what is and is not covered.

**5. Three hard breaking changes.** Response prefill 400-errors on Claude 4.6+. Sampling parameters and manual `budget_tokens` thinking 400-error on Sonnet 5. Thinking is on by default on both v5 models and cannot be disabled above `high` effort on Opus 5.

Structurally, Anthropic recommends XML tags to disambiguate mixed content types, longform data at the top with the query at the end (up to 30% quality gain in tests), 3–5 examples, positive framing over negative, and one sentence of role framing.

## What Changed For v5

This section is organized by consequence — what breaks, what silently changes, what guidance reversed — rather than by source page. Every item is labelled with its evidentiary status.

### Documented By Anthropic

#### C1. Response prefill is dead, not discouraged — hard 400 error on Claude 4.6+

This is a breaking change, not a style shift. Two inputs (A3, A4) established it independently from two different pages.

> Starting with Claude 4.6 models and Claude Mythos Preview, prefilled responses (providing a partial assistant message for Claude to continue from) on the last assistant turn are no longer supported. Requests with prefilled assistant messages to these models return a 400 error. Model intelligence and instruction following have advanced such that most use cases of prefill no longer require it. Earlier models continue to support prefills, and adding assistant messages elsewhere in the conversation is not affected.

Source: https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices — section "Migrating away from prefilled responses".

The consistency page carries the same constraint as an inline override of its own older advice:

> Prefilling is not supported on Claude 4.6 and later models and Claude Mythos Preview. Use structured outputs on models that support it, or system prompt instructions, instead.

Source: https://platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/increase-consistency — section "Prefill Claude's response". A4 records this as "the clearest 'does NOT help (anymore)' signal found" in its pass: the technique 400-errors rather than degrading gracefully. Documented replacements: Structured Outputs instead of JSON-prefill; a direct "respond without preamble" system-prompt instruction instead of a preamble-suppressing prefill; native refusal calibration instead of prefill-based refusal steering; moving continuations into the user turn.

#### C2. Sampling parameters are rejected on Sonnet 5

> If you previously relied on `temperature` for stylistic variety, note that setting `temperature`, `top_p`, or `top_k` to a non-default value returns a 400 error on Claude Sonnet 5. This constraint is new for Sonnet-class models. Remove these parameters when migrating, and use system-prompt instructions to guide tone and variety instead.

Source: https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-sonnet-5 — section "Tone and writing style". The "What's new" page adds that "the same constraint was previously introduced on Claude Opus 4.7" (https://platform.claude.com/docs/en/about-claude/models/whats-new-sonnet-5). Consequence for prompting: run-to-run stylistic variety must now be produced by prompt content, since the parameter lever is gone.

#### C3. Manual extended thinking is removed on Sonnet 5

> Manual extended thinking (`thinking: {type: "enabled", budget_tokens: N}`) is not supported on Claude Sonnet 5 and returns a 400 error. It was deprecated on Claude Sonnet 4.6 and is now removed. Use adaptive thinking with the effort parameter instead.

Source: https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-sonnet-5 — section "Calibrating effort and thinking depth". Paired code contrast, verbatim from the companion page:

```python
# Not supported on Claude Sonnet 5 (returns 400)
thinking = {"type": "enabled", "budget_tokens": 32000}

# Use this instead
thinking = {"type": "adaptive"}
```

Source: https://platform.claude.com/docs/en/about-claude/models/whats-new-sonnet-5 — section "Manual extended thinking removed".

#### C4. Thinking is on by default on both v5 models — and Opus 5 caps disabling it

The cross-model page states the whole matrix in one place:

> On Claude Opus 4.6 through Claude Opus 4.8 and Claude Sonnet 4.6, thinking is off when you omit the `thinking` parameter. On Claude Opus 5 and Claude Sonnet 5, thinking is on by default when you omit the `thinking` parameter; on Claude Opus 5, you can disable it only at effort `high` or lower. On Claude Fable 5 and Claude Mythos 5, thinking is always on, regardless of whether you set the `thinking` parameter.

Source: https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices — section "Leverage thinking & interleaved thinking capabilities".

The Opus 5 cap is API-enforced per request:

> On Claude Opus 5, `thinking: {"type": "disabled"}` is accepted only when the effort level is `high` or below. Setting `thinking: {"type": "disabled"}` with effort `xhigh` or `max` returns a 400 error. This is generally available behavior on Claude Opus 5 onward, enforced on each request, and it is a breaking change from Claude Opus 4.8, where disabling thinking was independent of the effort level.

> The check is enforced on each request: every request's effort and thinking configuration is validated independently, so a request that raises effort to `xhigh` or `max` while thinking is disabled is rejected even if earlier requests in the conversation were accepted.

Source: https://platform.claude.com/docs/en/about-claude/models/migration-guide — section "Migrating to Claude Opus 5 from Claude Opus 4.8" → Breaking changes. Paired before/after, verbatim:

```python
# Before — accepted on Claude Opus 4.8, rejected on Claude Opus 5
client.messages.create(
    model="claude-opus-4-8",
    max_tokens=16000,
    thinking={"type": "disabled"},
    output_config={"effort": "xhigh"},
    messages=[{"role": "user", "content": "..."}],
)

# After (option 1) — remove the thinking field to re-enable thinking
client.messages.create(
    model="claude-opus-5",
    max_tokens=16000,
    output_config={"effort": "xhigh"},  # thinking is on by default
    messages=[{"role": "user", "content": "..."}],
)

# After (option 2) — keep thinking disabled and lower the effort
client.messages.create(
    model="claude-opus-5",
    max_tokens=16000,
    thinking={"type": "disabled"},
    output_config={"effort": "high"},  # or "medium", "low"
    messages=[{"role": "user", "content": "..."}],
)
```

Consequence for `max_tokens` sizing, stated identically on two pages:

> Because `max_tokens` is a hard limit on total output (thinking plus response text), revisit it for workloads that ran without thinking on Claude Opus 4.8.

Source: https://platform.claude.com/docs/en/about-claude/models/whats-new-opus-5 — section "Thinking on by default". The Sonnet 5 page states the same for Sonnet 4.6 workloads and adds a failure signature: "if the budget is tight, you may see a response that is almost entirely thinking followed by a truncated answer and `stop_reason: 'max_tokens'`."

#### C5. Sonnet 5 has a new tokenizer — ~30% more tokens for identical text

> Because Claude Sonnet 5 uses a new tokenizer that produces approximately 30% more tokens for the same text, `max_tokens` limits tuned for Claude Sonnet 4.6 may truncate equivalent output. The exact increase depends on the content and workload shape.

Source: https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-sonnet-5. The launch announcement gives a range of ~1.0–1.35x rather than a single figure (https://www.anthropic.com/news/claude-sonnet-5) — see [§ Contradictions And Ambiguities In The Sources](#contradictions-and-ambiguities-in-the-sources). Four impact surfaces are named: token counts and usage fields; context-window capacity measured in actual text; `max_tokens` budgets; per-request cost at unchanged per-token price. This directly affects any prompt whose size was measured against a 4.x model.

#### C6. Instruction-following became literal

> Claude Sonnet 5 interprets prompts literally and explicitly, particularly at lower effort levels. It does not silently generalize an instruction from one item to another, and it does not infer requests you didn't make. The upside of this literalism is precision, and it generally performs better for API use cases with carefully tuned prompts, structured extraction, and pipelines where you want predictable behavior. If you need Claude to apply an instruction broadly, state the scope explicitly (for example, "Apply this formatting to every section, not just the first one").

Source: https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-sonnet-5 — section "More literal instruction following". A2 assesses this as the single most architecturally consequential directive on that page. The same literalism is documented from the review-harness angle on both v5 guides — see catalog directive D9.

#### C7. Default verbosity moved in opposite directions on the two v5 models

Opus 5 got longer and does not respond to the effort lever:

> Claude Opus 5's default user-facing responses run longer than prior Opus models'. The effort parameter controls how much the model thinks rather than how much it says: lowering effort can reduce thinking volume without reliably shortening the visible response. To control response length, prompt for it explicitly.

Source: https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-opus-5 — section "Response length and verbosity".

Sonnet 5 self-calibrates:

> Claude Sonnet 5 calibrates response length to the complexity of the task rather than defaulting to a fixed verbosity. This usually means shorter answers on simple lookups and longer ones on open-ended analysis.

Source: https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-sonnet-5 — section "Response length and verbosity". The cross-model page names Opus 5 as the explicit exception to the generation-wide concision trend:

> Claude's latest models have a more concise and natural communication style compared to previous models ... Claude Opus 5 is an exception on verbosity: its default user-facing responses run longer than prior models', and raising or lowering effort does not reliably change visible response length. Prompt explicitly for conciseness instead.

Source: https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices — section "Communication style and verbosity". Consequence: the two tiers require opposite tuning postures on length.

#### C8. Written files, not just chat turns, run longer on Opus 5

> Separate from conversational verbosity, files that Claude Opus 5 writes to disk (reports, Markdown documents, summaries) are often longer than on prior models. If your product includes Claude-authored documents, add explicit length calibration:

Source: https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-opus-5 — section "Written deliverable length". This is a distinct lever from conversational verbosity, and the docs treat it as needing its own instruction.

#### C9. Progress narration increased on Opus 5 and improved on Sonnet 5 — with opposite prescriptions

Opus 5 narrates more and needs shaping:

> Claude Opus 5 narrates readily during agentic work: it tends to announce what it is about to do, and its per-message output in agentic sessions is often longer than prior models'. It benefits from explicit guidance on how to communicate with the user during a task.

Sonnet 5 narrates well and legacy scaffolding should come out:

> Claude Sonnet 5 provides regular, higher-quality updates to the user throughout long agentic traces. If you've added scaffolding to force interim status messages ("After every 3 tool calls, summarize progress"), try removing it.

Sources: https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-opus-5 — section "User-facing progress updates"; https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-sonnet-5 — section "User-facing progress updates".

#### C10. Self-verification instructions became counterproductive on Opus 5

> Claude Opus 5 verifies its own work without being told to. If your prompt contains explicit verification instructions ("include a final verification step for any non-trivial task," "use a subagent to verify"), remove them: instructions like these cause over-verification on Claude Opus 5, and removing them reduces wasted tokens with no loss in quality. The same applies to legacy harness scaffolding that adds separate verification steps.

Source: https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-opus-5 — section "Task scope and over-verification". The cross-model page states the exception explicitly and tells migrators to delete rather than reword:

> Ask Claude to self-check. Append something like "Before you finish, verify your answer against [test criteria]." This catches errors reliably, especially for coding and math. Claude Opus 5 is the exception: it verifies its own work well without explicit instruction, and verification instructions carried over from prompts tuned for earlier models can cause over-verification, adding tokens and latency. When migrating to Claude Opus 5, remove these instructions rather than rewriting them.

Source: https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices. Note the asymmetry: for every model other than Opus 5, the self-check instruction is still endorsed.

#### C11. Aggressive emphasis language now causes overtriggering

This is the only place in the fetched corpus where Anthropic addresses emphasis wording directly.

> Claude Opus 4.5 and Claude Opus 4.6 are also more responsive to the system prompt than previous models. If your prompts were designed to reduce undertriggering on tools or skills, these models may now overtrigger. The fix is to dial back any aggressive language. Where you might have said "CRITICAL: You MUST use this tool when...", you can use more normal prompting like "Use this tool when...".

> Remove over-prompting. Tools that undertriggered in previous models are likely to trigger appropriately now. Instructions like "If in doubt, use [tool]" will cause overtriggering.

Source: https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices — sections "Tool usage" and "Overthinking and excessive thoroughness". Both statements are scoped in the text to Opus 4.5/4.6 and to tool/skill triggering. See [§ Emphasis And Over-Steering](#emphasis-and-over-steering) for exactly how far this does and does not extend.

#### C12. Delegation propensity increased on Opus 5

> Claude Opus 5 delegates to subagents more readily than prior models. Delegation pays off on genuinely independent, sizeable tracks of work, but it multiplies cost and time when applied to small tasks.

Source: https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-opus-5 — section "Controlling subagent spawning". The cross-model page places this in a lineage: "Claude Opus 4.6 has a strong predilection for subagents and may spawn them in situations where a simpler, direct approach would suffice." No equivalent statement exists for Sonnet 5 — A6 confirmed by full-page inspection that the Sonnet 5 guide contains zero occurrences of "subagent," "sub-agent," "delegat," or "spawn."

#### C13. The recommended effort starting point moved down for Opus

The effort page places three model generations' recommendations consecutively, which makes this the clearest before/after statement in the entire corpus.

Opus 4.7 (the baseline being migrated away from):

> **Start with `xhigh` for coding and agentic use cases**, and use `high` as the minimum for most intelligence-sensitive workloads. Step down to `medium` for cost-sensitive workloads, or up to `max` only when your evals show measurable headroom at `xhigh`.

Opus 4.8 (inherits 4.7):

> The guidance for Claude Opus 4.7 also applies to Claude Opus 4.8. **Start with `xhigh` for coding and agentic use cases**, use `high` for most other intelligence-sensitive workloads, and step down to `medium` or `low` only when you've measured that the lower level holds quality on your evals.

Opus 5 (the change):

> Claude Opus 5 supports all five effort levels. **Start with `high`, the default**, and adjust based on your evals: step up to `xhigh` for demanding coding and agentic work, or to `max` when a task justifies unconstrained token spending, and use `low` and `medium` liberally as your primary control for token cost and response time wherever your evals show quality holds. If you carried effort settings over from an earlier model, run a fresh effort sweep on your evals rather than reusing them.

Source: https://platform.claude.com/docs/en/build-with-claude/effort — subsections "Recommended effort levels for Claude Opus 4.7", "...Claude Opus 4.8", "...Claude Opus 5".

Sonnet 5's default did not move: "On Claude Sonnet 5, effort defaults to `high`, the same as on Claude Sonnet 4.6. For the hardest coding and agentic tasks, raise effort to `xhigh`."

#### C14. Three prompting techniques were demoted, not removed

Manual chain-of-thought became a fallback rather than the primary reasoning technique:

> **Prefer general instructions over prescriptive steps.** A prompt like "think thoroughly" often produces better reasoning than a hand-written step-by-step plan. Claude's reasoning frequently exceeds what a human would prescribe.

> **Manual chain-of-thought (CoT) prompting as a fallback.** When thinking is off, you can still encourage step-by-step reasoning by asking Claude to think through the problem. Use structured tags like `<thinking>` and `<answer>` to cleanly separate reasoning from the final output.

Explicit prompt chaining narrowed to a specific justification:

> With adaptive thinking and subagent orchestration, Claude handles most multistep reasoning internally. Explicit prompt chaining (breaking a task into sequential API calls) is still useful when you need to inspect intermediate outputs or enforce a specific pipeline structure.

Prefill (see C1) went from technique to error. Source for all three: https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices — sections "Leverage thinking & interleaved thinking capabilities", "Chain complex prompts", "Migrating away from prefilled responses".

#### C15. The documentation itself was reorganized — cite current URLs

Two structural findings, each verified rather than assumed.

A3 established that the eight historic core-technique pages (be clear and direct, multishot, chain of thought, XML tags, role prompting, prefill, chain prompts, long context tips) no longer exist standalone. It redirect-tested four of the old URLs (`be-clear-and-direct`, `chain-of-thought`, `long-context-tips`, `use-xml-tags`) and all four returned the body of the consolidated page, while two out-of-family controls (`prompt-engineering/increase-consistency`, `prompt-engineering/mitigate-jailbreaks`) returned HTTP 404. That asymmetry is what distinguishes "merged" from "deleted." The overview page confirms the intent:

> All prompting techniques (from clarity and examples to XML structuring, role prompting, thinking, and prompt chaining) are covered in [Prompting best practices]... That's the living reference; start there.

Source: https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/overview.

A4 established that the reliability pages moved out of `prompt-engineering/` entirely and now live under `test-and-evaluate/strengthen-guardrails/`. The prompt-engineering index does not link to them at all. A4 also found that `keep-claude-in-character` is no longer a standalone page — two independent fetches returned the `increase-consistency` body byte-for-byte, and A4 explicitly trusted those direct fetches over a stale search-engine snippet that still titled it as a separate page.

Consequence for this effort: any citation to a historic URL is citing a page that no longer exists as such. The bibliography below uses current URLs only.

#### C16. Explicit non-changes worth recording

Opus 5 pricing is unchanged from Opus 4.8: "$5 per million input tokens and $25 per million output tokens, unchanged from Claude Opus 4.8" (https://platform.claude.com/docs/en/about-claude/models/whats-new-opus-5). Sonnet 5 is described as "a drop-in replacement for Claude Sonnet 4.6" with unchanged request/response/streaming shapes. Sonnet 5's tool definitions and response shapes are unchanged. Opus 5's prompt-cache minimum dropped from 1,024 to 512 tokens, and Priority Tier is not supported on Opus 5 — both operational, neither a prompting change.

### Inference From Sources

Everything in this subsection is labelled INFERENCE. None of it is a statement Anthropic made.

**INFERENCE 1 — Opus-5-scoped directives should not be assumed to apply to Sonnet 5.** A5 reasoned that Opus 5's self-verification behavior "plausibly reduces the need for explicit 'double check your work' instructions," but then checked and found Anthropic scopes D9/D12 explicitly to Opus 5, with no Sonnet-5-scoped equivalent in the Sonnet 5 guide. A2 reached the same conclusion independently and stated it as an asymmetry: "the 'remove your explicit verify-your-work instructions' directive is stated as a hard requirement only for Opus 5. Whether Sonnet 5 needs the same treatment is not addressed either way on its own page." Treat cross-tier extension of any Opus-5 directive as unconfirmed.

**INFERENCE 2 — the review-harness literalism finding is generation-wide, not tier-specific.** Both v5 guides document the same phenomenon and recommend the same coverage-first-then-filter fix, independently. A2 labels this "confirmed as a v5-generation-wide trait, not a Sonnet-vs-Opus divergence." That label is A2's inference from two parallel statements; Anthropic does not itself say "this applies to the whole v5 generation."

**INFERENCE 3 — long, complex system prompts are named as a trigger for unwanted adaptive thinking.** The Sonnet 5 guide says thinking may fire more often than desired, "which can happen with large or complex system prompts." A2 infers from this that prompt bulk has a measurable latency cost via unwanted thinking activation. The causal claim in the doc is real; the extrapolation to any particular prompt corpus is inference.

**INFERENCE 4 — Anthropic's own documentation form is itself evidence.** A1 observed that across all four Opus-5-family pages the prose is uniformly short per directive, with no ALL-CAPS emphasis, no emoji, no numbered "Hard Rules" lists, and no independent restatement of the same rule across unrelated sections. A3 observed that Anthropic's own worked examples of a well-formed instruction block are single XML-tagged prose paragraphs of 10–30 lines rather than bullet catalogs. These are accurate observations about the documents. Reading them as *implicit guidance* is INFERENCE — Anthropic nowhere states that its own documentation form is a recommended prompt form.

### Where The Sources Are Silent

Named explicitly so downstream documents do not cite this one as authority for claims Anthropic never made.

- **Emphasis technique.** No source addresses ALL-CAPS, emoji, or restatement as devices. The nearest statement (C11) is scoped to tool/skill triggering language on Opus 4.5/4.6. See [§ Emphasis And Over-Steering](#emphasis-and-over-steering).
- **Over-steering as quality degradation.** No source states that stacking many constraints degrades output *quality*. The documented harm from redundant instructions is cost and latency (C10), and the documented harm from aggressive language is overtriggering (C11).
- **Instruction ordering inside a system prompt.** No source states where critical instructions belong within a system prompt. The only positional claim is about longform *data* placement in long-context tasks (see [§ Structural Conventions For Prompts](#structural-conventions-for-prompts)).
- **Total prompt length.** No source gives a recommended maximum length for a system prompt, an output style, or an agent-definition body — and for the latter two the absence was later confirmed by full-page reads, see [§ The Two Numbers, And The Two Absences](#the-two-numbers-and-the-two-absences). *Amended:* the original six inputs found numeric length guidance only for skill files (500-line body) and skill descriptions (1,024 characters); the A7 amendment added a second class with a number, project-instruction files, at a "target under 200 lines per CLAUDE.md file" (D33).
- **Run-to-run consistency for non-creative work.** A1 found no statement on determinism or variance reduction on any Opus-5 page; A4 found the guardrails pages never mention `temperature` or `stop_sequences`.
- **Parallel tool-call default behavior changes in v5.** A1 found no statement about whether Opus 5 changed its default parallel-vs-sequential tool-calling tendency. The cross-model parallel-tool guidance (D24) is not v5-specific.
- **Sonnet 5 subagent behavior.** Confirmed absent by full-page inspection, not merely unfound (A6).

## Directive Catalog

Every distinct actionable directive found across the inputs, deduplicated. D1–D32 come from the original six inputs. D33 and above were added by the A7 amendment and are scoped to *artifact-class authoring* rather than to model prompting — see [§ Authoring Guidance By Artifact Class](#authoring-guidance-by-artifact-class) for their full context and quotes. Where two or more inputs recorded the same directive, both are cited. Strength is classified as **hard requirement** (API-enforced or stated as a rule), **recommendation** (Anthropic advises it), or **behavioral observation** (a documented model tendency the reader must design around, with no imperative attached).

Model scope is stated on every entry. Directives marked *(Opus 5 only)* or *(Sonnet 5 only)* were found only on that model's page, and per [INFERENCE 1](#inference-from-sources) must not be assumed to transfer.

### D1 — Remove explicit self-verification instructions *(Opus 5 only)*

**Imperative:** delete verification instructions and legacy verification scaffolding from Opus 5 prompts rather than rewording them.

> Claude Opus 5 verifies its own work without being told to. If your prompt contains explicit verification instructions ("include a final verification step for any non-trivial task," "use a subagent to verify"), remove them: instructions like these cause over-verification on Claude Opus 5, and removing them reduces wasted tokens with no loss in quality. The same applies to legacy harness scaffolding that adds separate verification steps.

**Source:** https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-opus-5 — "Task scope and over-verification". Also stated on https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices. Recorded independently by A1 (D1), A5 (D9), A2 (D24).
**Strength:** recommendation, grounded in a behavioral observation. The cross-model page raises it to an explicit instruction to delete rather than rewrite when migrating.

### D2 — Do not instruct re-checks the model already performs *(Opus 5 only)*

**Imperative:** drop "double-check your answer" / "re-verify before responding" from Opus 5 prompts.

> Claude Opus 5 catches and fixes its own mistakes well without prompting. Avoid instructing re-checks it already performs ("double-check your answer," "re-verify before responding"); like verification instructions, these compound with the model's own behavior and add cost without improving results.

**Source:** https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-opus-5 — "Self-correction". Recorded by A1 (D4) and A5 (D12).
**Strength:** recommendation. Note the documented harm is cost, not quality: "add cost without improving results."

### D3 — Constrain scope explicitly for narrow tasks *(Opus 5 only)*

**Imperative:** for narrow tasks, state the scope boundary in the prompt; Opus 5 will otherwise widen it on its own judgment.

> Claude Opus 5 can also expand the scope of a task, adding steps that weren't requested or applying its own judgment about what the task should be. For narrow tasks, constrain scope explicitly:

Anthropic's own example text, verbatim:

```text
Deliver what was asked, at the scope intended. Make routine judgment calls yourself, and check in only when different readings of the request would lead to materially different work. If the request seems mistaken or a better approach exists, say so in a sentence and continue with the task as asked rather than quietly narrowing, widening, or transforming it. Finish the whole task, and stop short of actions that are clearly beyond what was asked.
```

**Source:** https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-opus-5 — "Task scope and over-verification". Recorded by A1 (D2) and A5 (D10).
**Strength:** recommendation, grounded in a behavioral observation (scope creep).

### D4 — Guard against over-engineering with an explicit scope block *(cross-model)*

**Imperative:** when the model adds unrequested files, abstractions, or flexibility, constrain it with a concrete scope block rather than a general plea for simplicity.

Anthropic's full worked prompt, verbatim:

```text
Avoid over-engineering. Only make changes that are directly requested or clearly
necessary. Keep solutions simple and focused:

- Scope: Don't add features, refactor code, or make "improvements" beyond what was
asked. A bug fix doesn't need surrounding code cleaned up. A simple feature doesn't need
extra configurability.

- Documentation: Don't add docstrings, comments, or type annotations to code you didn't
change. Only add comments where the logic isn't self-evident.

- Defensive coding: Don't add error handling, fallbacks, or validation for scenarios
that can't happen. Trust internal code and framework guarantees. Only validate at system
boundaries (user input, external APIs).

- Abstractions: Don't create helpers, utilities, or abstractions for one-time
operations. Don't design for hypothetical future requirements. The right amount of
complexity is the minimum needed for the current task.
```

**Source:** https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices — "Overeagerness". Recorded by A2 (D25), which notes the doc attributes the behavior to Opus 4.5/4.6 and does not confirm it as Sonnet-5-specific.
**Strength:** recommendation.

### D5 — Prompt explicitly for conciseness; effort will not do it *(Opus 5)*

**Imperative:** add an explicit conciseness instruction to control visible response length on Opus 5. Do not expect the effort parameter to shorten output.

> Claude Opus 5's default user-facing responses run longer than prior Opus models'. The effort parameter controls how much the model thinks rather than how much it says: lowering effort can reduce thinking volume without reliably shortening the visible response. To control response length, prompt for it explicitly.

Anthropic's two example forms, verbatim. A full instruction for a user-facing product:

```text
Keep responses focused, brief, and concise. Keep disclaimers and caveats short, and spend most of the response on the main answer. When asked to explain something, give a high-level summary unless an in-depth explanation is specifically requested.
```

A short reminder for use near the end of a long system prompt:

```text
<tone_preference>
Keep outputs reasonably concise.
</tone_preference>
```

**Source:** https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-opus-5 — "Response length and verbosity". Independently restated on https://platform.claude.com/docs/en/build-with-claude/effort: "Effort controls thinking volume, not visible response length: on Claude Opus 5, changing effort does not reliably shorten responses, so prompt for length instead." Recorded by A1 (D6), A5 (D5), A2 (§1).
**Strength:** recommendation, grounded in a behavioral observation. A5 classifies it as a hard requirement on the grounds that no other lever exists.

### D6 — Add explicit length calibration for written deliverables *(Opus 5)*

**Imperative:** for Claude-authored files (reports, Markdown, summaries), add a length instruction distinct from any conversational-verbosity instruction.

> Separate from conversational verbosity, files that Claude Opus 5 writes to disk (reports, Markdown documents, summaries) are often longer than on prior models. If your product includes Claude-authored documents, add explicit length calibration:

```text
Match the length of written documents to what the task needs: cover the substance, but do not pad with filler sections, redundant summaries, or boilerplate.
```

**Source:** https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-opus-5 — "Written deliverable length". Recorded by A1 (D8) and A5 (D8).
**Strength:** recommendation.

### D7 — Shape narration cadence, and prefer positive examples over prohibitions *(Opus 5)*

**Imperative:** describe the cadence and shape of progress updates you want. To change narration style, show the style you want rather than listing what to avoid.

> Claude Opus 5 narrates readily during agentic work: it tends to announce what it is about to do, and its per-message output in agentic sessions is often longer than prior models'. It benefits from explicit guidance on how to communicate with the user during a task. To tune narration down, describe the cadence and shape you want:

```text
Before your first tool call, say in one sentence what you're about to do. While working, give a brief update only when you find something important or change direction. When you finish, lead with the outcome: your first sentence should answer "what happened" or "what did you find," with supporting detail after it for readers who want it.
```

> To tune narration up, or change its style, the same lever applies in the other direction: explicitly describe what updates should look like and provide examples. Positive examples of the communication style you want tend to be more effective than instructions about what not to do.

**Source:** https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-opus-5 — "User-facing progress updates". Recorded by A1 (D7) and A5 (D6, D7). The Sonnet 5 guide states the same preference for its own verbosity guidance: "Positive examples showing how Claude can communicate with the appropriate level of concision tend to be more effective than negative examples or instructions that tell the model what not to do."
**Strength:** recommendation. The positive-over-negative sub-claim is the most emphasis-adjacent statement in either model guide — see [§ Emphasis And Over-Steering](#emphasis-and-over-steering).

### D8 — Remove forced interim-status scaffolding *(Sonnet 5)*

**Imperative:** try deleting scaffolding that forces periodic status messages; specify update shape only if the native calibration is wrong for your use case.

> Claude Sonnet 5 provides regular, higher-quality updates to the user throughout long agentic traces. If you've added scaffolding to force interim status messages ("After every 3 tool calls, summarize progress"), try removing it. If you find that the length or contents of Claude Sonnet 5's user-facing updates are not well-calibrated to your use case, explicitly describe what these updates should look like in the prompt and provide examples.

**Source:** https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-sonnet-5 — "User-facing progress updates". Recorded by A2 (D11) and A5.
**Strength:** recommendation.

### D9 — Ask for exhaustive reporting and filter in a separate pass *(both v5 models)*

**Imperative:** in review prompts, do not use severity-gating or "be conservative" language if you want coverage. Ask for everything and filter downstream.

Opus 5:

> If your review prompt says "only report high-severity issues" or "be conservative," the model may follow that instruction literally and report less; ask it to report everything and filter in a separate pass instead.

Sonnet 5, with the mechanism spelled out:

> When a review prompt says things like "only report high-severity issues," "be conservative," or "don't nitpick," Claude Sonnet 5 may follow that instruction more faithfully than earlier models did: it may investigate the code just as thoroughly, identify the bugs, and then not report findings it judges to be below your stated bar. ... Precision typically rises, but measured recall can fall even though the model's underlying bug-finding ability has improved.

Anthropic's recommended coverage-first prompt, verbatim:

```text
Report every issue you find, including ones you are uncertain about or consider low-severity. Do not filter for importance or confidence at this stage - a separate verification step will do that. Your goal here is coverage: it is better to surface a finding that later gets filtered out than to silently drop a real bug. For each finding, include your confidence level and an estimated severity so a downstream filter can rank them.
```

And, if single-pass self-filtering is genuinely wanted:

> If you do want the model to self-filter in a single pass, be concrete about where the bar is rather than using qualitative terms like "important": for example, "report any bugs that could cause incorrect behavior, a test failure, or a misleading result; only omit nits like pure style or naming preferences."

**Sources:** https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-opus-5 — "Capability improvements"; https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-sonnet-5 — "Code review harnesses". Recorded by A1 (D9), A2 (D17), A5 (D1).
**Strength:** recommendation. Documented independently on both v5 model pages — the only directive in this catalog with that property.

### D10 — Limit correction narration to corrections that matter *(Opus 5 only)*

**Imperative:** instruct the model to surface corrections to its own earlier statements only when the error changes the user's code, conclusions, or decisions.

> The model also narrates corrections to its earlier statements more than prior models do, which can be undesirable in user-facing products. To limit correction narration to corrections that matter:

```text
Only correct an earlier statement when the error would change the user's code, conclusions, or decisions. State corrections plainly and briefly, then continue the task. For slips that change nothing for the user, make the fix and move on without noting it.
```

**Source:** https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-opus-5 — "Self-correction". Recorded by A1 (D5) and A5 (D13).
**Strength:** recommendation.

### D11 — State scope explicitly at each point of application *(Sonnet 5)*

**Imperative:** do not rely on the model generalizing an instruction from one item to another. If an instruction applies broadly, say so.

> Claude Sonnet 5 interprets prompts literally and explicitly, particularly at lower effort levels. It does not silently generalize an instruction from one item to another, and it does not infer requests you didn't make. ... If you need Claude to apply an instruction broadly, state the scope explicitly (for example, "Apply this formatting to every section, not just the first one").

**Source:** https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-sonnet-5 — "More literal instruction following". Recorded by A2 (D12) and A5.
**Strength:** hard requirement in effect — A2 classifies it as the most architecturally consequential directive on the page, because it changes what a single statement of a rule accomplishes.

### D12 — Be clear and direct; test against the golden rule *(cross-model)*

**Imperative:** request the behavior you want explicitly rather than relying on inference, and test the prompt on a human with minimal context.

> Claude responds well to clear, explicit instructions. Being specific about your desired output can help enhance results. If you want "above and beyond" behavior, explicitly request it rather than relying on the model to infer this from vague prompts.

> **Golden rule:** Show your prompt to a colleague with minimal context on the task and ask them to follow it. If they'd be confused, Claude will be too.

Before/after, verbatim both sides:

```text
Less effective:
Create an analytics dashboard

More effective:
Create an analytics dashboard. Include as many relevant features and interactions as possible. Go beyond the basics to create a fully-featured implementation.
```

A7 records the same directive restated for CLAUDE.md authoring, with a verifiability test attached and three paired examples:

> **Specificity**: write instructions that are concrete enough to verify. For example: 'Use 2-space indentation' instead of 'Format code properly' … 'Run `npm test` before committing' instead of 'Test your changes' … 'API handlers live in `src/api/handlers/`' instead of 'Keep files organized'

**Source:** https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices — "Be clear and direct". The CLAUDE.md-scoped restatement: https://code.claude.com/docs/en/memory — "Write effective instructions", plus "The more specific and concise your instructions, the more consistently Claude follows them" (same page, "CLAUDE.md vs auto memory"). Recorded by A3, A2 (D19), and A7.
**Strength:** recommendation. The A7 citation adds an adherence claim the cross-model page does not make: on the memory page, specificity and concision are tied directly to how consistently Claude follows the instruction.

### D13 — Give the motivation behind an instruction, not just the instruction *(cross-model)*

**Imperative:** explain why a constraint exists; the model generalizes correctly from the explanation.

> Providing context or motivation behind your instructions, such as explaining to Claude why such behavior is important, can help Claude better understand your goals and deliver more targeted responses.

Before/after, verbatim both sides — note that the "less effective" side is itself an ALL-CAPS negative prohibition:

```text
Less effective:
NEVER use ellipses

More effective:
Your response will be read aloud by a text-to-speech engine, so never use ellipses since the text-to-speech engine will not know how to pronounce them.
```

> Claude is smart enough to generalize from the explanation.

**Source:** https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices — "Add context to improve performance". Recorded by A3 and A2 (D20).
**Strength:** recommendation. This is the single closest thing in the corpus to a paired example contrasting bare ALL-CAPS prohibition against a reasoned instruction — but Anthropic's stated variable is the *presence of motivation*, not the capitalization. See [§ Emphasis And Over-Steering](#emphasis-and-over-steering).

### D14 — Effort: start at the default and use low/medium liberally *(Opus 5)*

**Imperative:** start at `high`, tune down to `low`/`medium` as the primary cost/latency control wherever quality holds, step up to `xhigh` for demanding coding and agentic work.

> Efficiency at lower effort: `low` and `medium` effort produce strong quality at a fraction of the tokens and latency of higher settings. Start with the default (`high`) and adjust based on your evals: use `low` and `medium` liberally as your primary control for token cost and response time wherever quality holds, and step up to `xhigh` for demanding coding and agentic work.

**Source:** https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-opus-5 — "Capability improvements"; corroborated verbatim on https://platform.claude.com/docs/en/build-with-claude/effort. Recorded by A1 (D10) and A5 (D2).
**Strength:** recommendation.

### D15 — Raise effort rather than prompting around under-thinking *(Sonnet 5)*

**Imperative:** if reasoning is shallow on a complex problem, raise effort. Only fall back to a prompt-level nudge when effort is pinned for latency.

> Claude Sonnet 5 respects effort levels strictly, especially at the low end. At `low` and `medium`, the model scopes its work to what was asked rather than going above and beyond. This is good for latency and cost, but on moderately complex tasks running at `low` effort there is some risk of under-thinking.
>
> If you observe shallow reasoning on complex problems, raise effort to `high` or `xhigh` rather than prompting around it.

The documented fallback if effort must stay low:

```text
This task involves multistep reasoning. Think carefully through the problem before responding.
```

**Source:** https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-sonnet-5 — "Calibrating effort and thinking depth". Recorded by A2 (D4).
**Strength:** hard requirement on ordering (raise effort first), with a fallback recommendation. Note this is the opposite posture from D14: Opus 5's docs are permissive about low/medium, Sonnet 5's carry an explicit under-thinking caveat at the same levels.

### D16 — Re-run an effort sweep instead of carrying defaults forward *(both v5 models)*

**Imperative:** do not reuse effort settings tuned for a 4.x model. Sweep again on your own evals.

> If you carried effort settings over from an earlier model, run a fresh effort sweep on your evals rather than reusing them.

Also, for benchmarking across generations:

> As a rough cross-model mapping when migrating: Claude Sonnet 5 at medium is comparable in intelligence to Claude Sonnet 4.6 at high, and Claude Sonnet 5 at high is comparable to Claude Sonnet 4.6 at max. When benchmarking, match by observed thinking length rather than effort name.

**Sources:** https://platform.claude.com/docs/en/build-with-claude/effort; https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-sonnet-5. Recorded by A1 (D10, D22) and A2 (D3).
**Strength:** recommendation. See [C13](#c13-the-recommended-effort-starting-point-moved-down-for-opus) for the before/after that makes this concrete.

### D17 — Steer adaptive-thinking triggering when it fires too often *(Sonnet 5)*

**Imperative:** if thinking blocks appear more often than wanted — which the doc ties to large or complex system prompts — add explicit steering rather than disabling thinking.

> The triggering behavior for adaptive thinking is steerable. If you find the model emitting thinking blocks more often than you'd like, which can happen with large or complex system prompts, add guidance to steer it.

```text
Thinking adds latency and should only be used when it will meaningfully improve answer quality, typically for problems that require multistep reasoning. When in doubt, respond directly.
```

**Source:** https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-sonnet-5 — "Calibrating effort and thinking depth". Recorded by A2 (D7).
**Strength:** recommendation. The clause "which can happen with large or complex system prompts" is the only place in the corpus where prompt bulk is named as a cause of a measurable side effect.

### D18 — Prefer thinking-on-at-low-effort over thinking-disabled *(Opus 5)*

**Imperative:** control token cost by lowering effort, not by disabling thinking.

> With thinking disabled, two artifacts can occasionally appear in the model's visible output. The primary mitigation for both is to keep thinking enabled and control token cost with lower effort levels instead of disabling thinking: for most tasks, thinking enabled at `low` effort performs better than thinking disabled at similar cost.

**Source:** https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-opus-5 — "Running with thinking disabled". Recorded by A1 (D13) and A5 (D14).
**Strength:** recommendation, grounded in a quality-per-cost comparison.

### D19 — Use one combined instruction for forced-thinking-disabled integrations *(Opus 5)*

**Imperative:** where thinking must stay off, use a single instruction that permits a sentence before a tool call, gives a fallback when no tool fits, and states a general rule against internal tags.

> For integrations that must keep thinking disabled, a single combined instruction mitigates both artifacts: it gives the model explicit permission to speak before a tool call, an alternative to forcing a call when no tool fits, and a general rule against internal tags:

```text
When you use a tool, you may say a brief sentence first. If no tool can express what the user asked for, say so instead of guessing. Do not include internal or system XML tags in your response.
```

The two artifacts this addresses, as behavioral observations:

> **Tool calls as text.** With thinking disabled, the model occasionally writes a tool call into its user-facing text instead of emitting a structured `tool_use` block. The turn completes normally and the call never runs, and in agentic loops the leaked text stays in the conversation history, so later turns are affected as well. This is most common on tool-heavy workloads such as search.

> **Internal XML tags in output.** With thinking disabled, the model can emit `<thinking>` tags or other internal XML tags into its visible response.

**Source:** https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-opus-5 — "Running with thinking disabled". Recorded by A1 (D14, D16) and A5 (D15).
**Strength:** recommendation for the instruction; behavioral observation for the artifacts.

### D20 — Remove any rule telling the model not to think or not to reason *(Opus 5)*

**Imperative:** delete anti-thinking system-prompt rules. They increase the leakage they were meant to suppress.

> If your system prompt contains a rule instructing the model not to think or not to reason, remove it; that kind of instruction increases tag leakage.

**Source:** https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-opus-5 — "Running with thinking disabled". Recorded by A1 (D15) and A5 (D16).
**Strength:** recommendation, grounded in a paradoxical behavioral observation. This is one of only two documented cases in the corpus where a prohibition produces the opposite of its intent — the other is D21.

### D21 — Do not name thinking tags specifically; use the general form *(Opus 5)*

**Imperative:** phrase anti-internal-tag instructions generally rather than calling out `<thinking>` by name.

> Instructions that call out thinking tags by name are less effective than the general form, so avoid naming them specifically.

**Source:** https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-opus-5 — "Running with thinking disabled". Recorded by A1 (D16) and A5 (D17).
**Strength:** behavioral observation with an attached recommendation. Notable because it is a documented case where *more specific* prohibition wording performs *worse*.

### D22 — Revisit `max_tokens`; start at 64k for `xhigh`/`max` *(both v5 models)*

**Imperative:** re-size `max_tokens` for any workload that previously ran without thinking, and leave large headroom at high effort levels.

> Because `max_tokens` is a hard limit on total output (thinking plus response text), revisit it for workloads that ran without thinking on Claude Opus 4.8.

> When running Claude Opus 5 at `xhigh` or `max` effort, set a large `max_tokens` so the model has room to think and act across subagents and tool calls. Starting at 64k tokens and tuning from there is a reasonable default.

**Sources:** https://platform.claude.com/docs/en/about-claude/models/whats-new-opus-5; https://platform.claude.com/docs/en/build-with-claude/effort; https://platform.claude.com/docs/en/about-claude/models/migration-guide (migration checklist: "If you run at `xhigh` or `max` effort, raise `max_tokens` to at least 64k as a starting point."). Recorded by A1 (D18, D19) and A2 (D6).
**Strength:** hard requirement in effect — under-sizing silently truncates. A1 notes the 64k figure is repeated identically across three independent Opus-5 pages, making it the most corroborated concrete number in the corpus.

### D23 — Nudge tool use explicitly when thinking is off *(Sonnet 5)*

**Imperative:** if you rely on tool calls with thinking disabled, add an explicit system-prompt nudge; effort is also a tool-usage lever.

> Claude Sonnet 5 is more agentic than Claude Sonnet 4.6 by default and will reach for tools and run self-verification loops more readily. With thinking disabled, the model is less likely to reach for tools or consider searching; if you rely on tool calls with thinking off, add an explicit nudge in the system prompt. Effort is also a lever for tool usage: `high` or `xhigh` effort settings show substantially more tool usage in agentic search and coding.

**Source:** https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-sonnet-5 — "Tool use triggering". Recorded by A2 (D10) and A5.
**Strength:** behavioral observation plus recommendation. Note the thinking-disabled failure mode differs by tier: Sonnet 5 under-reaches for tools; Opus 5 leaks tool calls into text (D19).

### D24 — Steer parallel tool calling in either direction *(cross-model)*

**Imperative:** independent tool calls already run in parallel by default; use explicit language to push reliability toward ~100% or to force sequential execution.

> Claude's latest models run independent tool calls in parallel. ... While the model has a high success rate in parallel tool calling without prompting, you can boost this to ~100% or adjust the aggression level.

Anthropic's own block for maximizing parallelism, verbatim:

```text
<use_parallel_tool_calls>
If you intend to call multiple tools and there are no dependencies between the tool
calls, make all of the independent tool calls in parallel. Prioritize calling tools
simultaneously whenever the actions can be done in parallel rather than sequentially.
For example, when reading 3 files, run 3 tool calls in parallel to read all 3 files into
context at the same time. Maximize use of parallel tool calls where possible to increase
speed and efficiency. However, if some tool calls depend on previous calls to inform
dependent values like the parameters, do NOT call these tools in parallel and instead
call them sequentially. Never use placeholders or guess missing parameters in tool
calls.
</use_parallel_tool_calls>
```

And for the opposite direction:

```text
Execute operations sequentially with brief pauses between each step to ensure stability.
```

**Source:** https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices — "Optimize parallel tool calling". Recorded by A2 (D22) and A3.
**Strength:** recommendation, cross-model and not v5-specific.

### D25 — Use direct imperatives when you want action, not suggestions *(cross-model)*

**Imperative:** phrase the request as the action you want performed.

Before/after, verbatim both sides:

```text
Less effective (Claude will only suggest):
Can you suggest some changes to improve this function?

More effective (Claude will make the changes):
Change this function to improve its performance.
```

**Source:** https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices — "Tool usage". Recorded by A3 and A2 (D21).
**Strength:** recommendation. Reinforces D11 from a different angle.

### D26 — Front-load the full task specification in the first turn *(Sonnet 5)*

**Imperative:** specify task, intent, and constraints completely up front; minimize the number of user turns needed to convey them.

> Providing well-specified, clear, and accurate task descriptions upfront can help maximize autonomy and intelligence while minimizing extra token usage after user turns. In contrast, ambiguous or underspecified prompts conveyed progressively over multiple user turns tend to relatively reduce token efficiency and sometimes performance.

> To maximize both performance and token efficiency in coding products, use `xhigh` or `high` effort, add autonomous features like an auto mode, and reduce the number of human interactions required from your users.

**Source:** https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-sonnet-5 — "Interactive coding products". Recorded by A2 (D16) and A5.
**Strength:** recommendation. For delegated sub-agents this is more than an efficiency tip — see D31, where fresh-context isolation makes front-loading mechanically necessary.

### D27 — Re-validate vision workarounds; give tools for visual verification *(Opus 5)*

**Imperative:** retire prompt-side vision workarounds tuned for earlier models, and give the model tools to crop and verify rather than relying on thinking.

> Vision: Claude Opus 5 is strong on chart, document, and diagram understanding, and on UI and frontend visual replication. Re-validate any prompt-side vision workarounds you tuned for prior models; they may no longer be needed. Vision performance is strongest when the model has tools to iteratively analyze, crop, and visually verify its work, and tool use is a more cost-effective lever than thinking alone.

**Source:** https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-opus-5 — "Capability improvements". Recorded by A1 (D11) and A5 (D3).
**Strength:** recommendation.

### D28 — Re-evaluate tone and style prompts against the new baseline *(Sonnet 5)*

**Imperative:** if a specific voice matters, re-test style prompts on the new model; prose style may have shifted.

> As with any new model, prose style on long-form writing may shift. If your product relies on a specific voice, re-evaluate style prompts against the new baseline.

**Source:** https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-sonnet-5 — "Tone and writing style". Recorded by A2 (D14).
**Strength:** recommendation.

### D29 — For design work, give concrete specs or use propose-then-build *(Sonnet 5)*

**Imperative:** generic anti-slop instructions shift the model to a different fixed default rather than producing variety. Either specify a concrete alternative, or have the model propose options first.

> Generic instructions ("don't use that color," "make it clean and minimal") tend to shift the model to a different fixed palette rather than producing variety. Two approaches work reliably.

The propose-then-build pattern, verbatim:

```text
Before building, propose 4 distinct visual directions tailored to this brief (each as: bg hex / accent hex / typeface, plus a one-line rationale). Ask the user to pick one, then implement only that direction.
```

> Because `temperature` is not accepted on Claude Sonnet 5, this approach is the recommended way to produce meaningfully different design directions across runs.

**Source:** https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-sonnet-5 — "Design and frontend defaults". Recorded by A2 (D15).
**Strength:** recommendation. Included in this catalog despite being domain-specific because the underlying finding generalizes: a *negative* instruction moved the model to a different fixed default rather than producing the intended variety.

### D30 — Only add context the model does not already have *(skills)*

**Imperative:** challenge every paragraph of authored instruction against its token cost.

> Only add context Claude doesn't already have. Challenge each piece of information: "Does Claude really need this explanation?" "Can I assume Claude knows this?" "Does this paragraph justify its token cost?"

**Source:** https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices — "Default assumption: Claude is already very smart". Recorded by A6, and re-verified by A7, which records the section as "Core principles" ("Concise is key") and quotes the framing sentence: "Default assumption: Claude is already very smart. Only add context Claude doesn't already have."
**Strength:** recommendation. A6 notes this is the same underlying principle as D1/D2 — do not restate what the model already does or knows — applied to authoring rather than prompting. It is the closest thing in the corpus to a general instruction-density principle, and it is scoped to skill files, not to system prompts generally.

### D31 — Front-load everything a sub-agent needs; it starts with no shared context *(agents)*

**Imperative:** put the complete task context in the delegation message. A non-fork sub-agent cannot see anything else.

> Each subagent starts with a fresh, isolated context window. It doesn't see your conversation history, the skills you've already invoked, or the files Claude has already read. Claude composes a delegation message that summarizes the task, and the subagent works from there. The exception is a fork, which inherits the parent conversation instead of starting fresh.

**Source:** https://code.claude.com/docs/en/sub-agents — "What loads at startup". Recorded by A6 (D25), and independently re-verified by A7 against the same page. A7 adds the explicit not-inherited enumeration:

> Some main-conversation state never reaches a non-fork subagent: **Output style**: a subagent runs its own system prompt, so your output style doesn't shape its responses, except in a fork. **Auto memory**: the main conversation's auto memory isn't loaded. … **Context window size**: a subagent's context window is sized by its own model, not the parent's.

**Strength:** behavioral/architectural fact, not a recommendation. See [§ Agent And Multi-Agent Guidance](#agent-and-multi-agent-guidance) for what does and does not propagate, D41 for the output-style half stated as its own directive, and [§ Agent Definitions](#agent-definitions) for A7's full startup-context quotes.

### D32 — Match degrees of freedom to task fragility *(skills)*

**Imperative:** give fragile, must-be-exact operations low-freedom exact scripts; give open-ended judgment calls high-freedom heuristics.

A6 records three named levels (high/medium/low freedom) with a "narrow bridge vs. open field" analogy: fragile, error-prone, must-be-exact operations get exact scripts with no room for interpretation; open-ended judgment calls get heuristic guidance.

**Source:** https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices — "Set appropriate degrees of freedom". Recorded by A6.
**Strength:** recommendation. Reported as a paraphrase because A6 recorded it as a paraphrase rather than a verbatim quote — flagged in [§ Coverage Gaps](#coverage-gaps).

### D33 — Target under 200 lines per CLAUDE.md file *(CLAUDE.md)*

**Imperative:** keep each CLAUDE.md under 200 lines. Longer files are documented as reducing adherence, not merely as costing tokens.

> **Size**: target under 200 lines per CLAUDE.md file. Longer files consume more context and reduce adherence. If your instructions are growing large, use path-scoped rules so instructions load only when Claude works with matching files. You can also split content into imports for organization, though imported files still load and enter the context window at launch.

> Files over 200 lines consume more context and may reduce adherence.

**Source:** https://code.claude.com/docs/en/memory — "Write effective instructions" and "My CLAUDE.md is too large". Recorded by A7.
**Strength:** recommendation, and the only numeric length target in the corpus that is tied to *adherence* rather than to cost alone. It is not an enforced cap: "CLAUDE.md files are loaded in full regardless of length, though shorter files produce better adherence" (same page, "How it works"). The hard 200-line/25KB limit on the same page applies only to `MEMORY.md`.

### D34 — Structure a CLAUDE.md with markdown headers and bullets *(CLAUDE.md)*

**Imperative:** group related instructions under markdown headers with bullets rather than writing dense paragraphs.

> **Structure**: use markdown headers and bullets to group related instructions. Claude scans structure the same way readers do: organized sections are easier to follow than dense paragraphs.

**Source:** https://code.claude.com/docs/en/memory — "Write effective instructions". Recorded by A7.
**Strength:** recommendation. Note the artifact scope: this is the one place in the corpus where Anthropic prescribes *markdown* structure for a named artifact class. The XML-tag prescription in [§ Structural Conventions For Prompts](#structural-conventions-for-prompts) is scoped to disambiguating mixed content types within an API prompt and does not conflict with this.

### D35 — Remove contradicting instructions; a contradiction resolves arbitrarily *(CLAUDE.md)*

**Imperative:** periodically review CLAUDE.md files, nested CLAUDE.md files, and `.claude/rules/` and delete conflicting or outdated instructions.

> **Consistency**: if two rules contradict each other, Claude may pick one arbitrarily. Review your CLAUDE.md files, nested CLAUDE.md files in subdirectories, and `.claude/rules/` periodically to remove outdated or conflicting instructions.

> Look for conflicting instructions across CLAUDE.md files. If two files give different guidance for the same behavior, Claude may pick one arbitrarily.

**Source:** https://code.claude.com/docs/en/memory — "Write effective instructions" and "Claude isn't following my CLAUDE.md". Recorded by A7.
**Strength:** recommendation, grounded in a stated behavioral fact ("may pick one arbitrarily"). This is the first directive in the catalog about *internal consistency* of authored instructions rather than about their content.

### D36 — Keep a CLAUDE.md to always-true facts; move procedures to skills and path-scoped content to rules *(CLAUDE.md)*

**Imperative:** admit only facts Claude should hold in every session. Relocate anything that is a multi-step procedure or that matters to only one part of the codebase.

> Keep it to facts Claude should hold in every session: build commands, conventions, project layout, 'always do X' rules. If an entry is a multi-step procedure or only matters for one part of the codebase, move it to a skill or a path-scoped rule instead.

The stated triggers for adding content at all:

> Treat CLAUDE.md as the place you write down what you'd otherwise re-explain. Add to it when: Claude makes the same mistake a second time; A code review catches something Claude should have known about this codebase; You type the same correction or clarification into chat that you typed last session; A new teammate would need the same context to be productive.

**Source:** https://code.claude.com/docs/en/memory — "When to add to CLAUDE.md". Recorded by A7.
**Strength:** recommendation. The `/doctor` trim policy on the same page is the tool-enforced version of the same boundary: it "cuts content Claude can derive from the codebase, such as directory layouts, dependency lists, and architecture overviews, and keeps pitfalls, rationale, and conventions that differ from tool defaults."

### D37 — Do not use `@path` imports to reduce context cost *(CLAUDE.md)*

**Imperative:** use `@path` imports for organization only. If the goal is a smaller context footprint, use path-scoped rules or a skill instead.

> Splitting into `@path` imports helps organization but doesn't reduce context, since imported files load at launch.

> Imported files are expanded and loaded into context at launch alongside the CLAUDE.md that references them. … Imported files can recursively import other files, with a maximum depth of four hops.

**Source:** https://code.claude.com/docs/en/memory — "My CLAUDE.md is too large" and "Import additional files". Recorded by A7.
**Strength:** hard mechanism fact with an attached recommendation. See [§ Splitting Content Across Files](#splitting-content-across-files--which-mechanisms-reduce-context-and-which-do-not) for the full three-way comparison and for the explicit scope limit on this finding — it applies to CLAUDE.md `@path` imports and is not a statement about reference patterns in other artifact classes.

### D38 — Use block-level HTML comments for maintainer notes in a CLAUDE.md *(CLAUDE.md)*

**Imperative:** put notes intended for human maintainers in block-level HTML comments; they cost nothing.

> Block-level HTML comments (`<!-- maintainer notes -->`) in CLAUDE.md files are stripped before the content is injected into Claude's context. Use them to leave notes for human maintainers without spending context tokens on them. Comments inside code blocks are preserved.

**Source:** https://code.claude.com/docs/en/memory — "How CLAUDE.md files load". Recorded by A7.
**Strength:** documented mechanism with an attached recommendation.

### D39 — Write anything that must be guaranteed as a hook or a settings rule, not as prompt text *(cross-artifact)*

**Imperative:** if an instruction must hold regardless of the model's judgment, implement it as a `PreToolUse` hook or a settings-level rule. Prompt text cannot carry it.

> Both are loaded at the start of every conversation. Claude treats them as context, not enforced configuration. To block an action regardless of what Claude decides, use a PreToolUse hook instead.

> If the instruction is something that must run at a specific point, such as before every commit or after each file edit, write it as a hook instead. Hooks execute as shell commands at fixed lifecycle events and apply regardless of what Claude decides to do.

> Settings rules are enforced by the client regardless of what Claude decides to do. CLAUDE.md instructions shape Claude's behavior but are not a hard enforcement layer.

**Source:** https://code.claude.com/docs/en/memory — "CLAUDE.md vs auto memory", "Claude isn't following my CLAUDE.md", "Deploy organization-wide CLAUDE.md". Recorded by A7.
**Strength:** hard requirement in effect, and the most consequential single directive the A7 amendment adds — it bounds what *any* amount of prompt text can accomplish. Sourcing caveat: A7 never fetched the hooks documentation itself, so this rests on the memory page's own cross-references. See [§ Enforcement Beyond Prompt Text](#enforcement-beyond-prompt-text).

### D40 — Use an output style for role, tone, and format; use CLAUDE.md for project knowledge *(output styles)*

**Imperative:** do not put project, convention, or codebase content in an output style.

> Output styles change how Claude responds, not what Claude knows. They modify the system prompt to set role, tone, and output format. Use one when you keep re-prompting for the same voice or format every turn, or when you want Claude to act as something other than a software engineer.

> For instructions about your project, conventions, or codebase, use CLAUDE.md instead.

**Source:** https://code.claude.com/docs/en/output-styles — intro section. Recorded by A7.
**Strength:** recommendation. A7 records that this is the *only* explicit misuse warning anywhere on the output-styles page.

### D41 — Do not expect an output style to reach a sub-agent *(output styles / agents)*

**Imperative:** any behavior a delegated sub-agent must exhibit has to live in that sub-agent's own definition. An output style shapes the main conversation only.

> Output styles apply to the main conversation only: a subagent runs its own system prompt, so styles don't change how subagents respond. A fork is the exception, because it inherits the parent's full system prompt.

> Some main-conversation state never reaches a non-fork subagent: **Output style**: a subagent runs its own system prompt, so your output style doesn't shape its responses, except in a fork.

**Sources:** https://code.claude.com/docs/en/output-styles — "How output styles work"; https://code.claude.com/docs/en/sub-agents — "What loads at startup". Recorded by A6 (via the sub-agents page) and independently re-verified by A7 from both pages.
**Strength:** documented platform behavior, not advice. This is the only directive in the catalog corroborated by two different official product pages.

### D42 — Write a subagent `description` that names the domain and states the trigger *(agents)*

**Imperative:** the `description` field is the routing signal. State both what the agent does and when it should be used.

> Claude uses each subagent's description to decide when to delegate tasks. When you create a subagent, write a clear description so Claude knows when to use it.

> Claude automatically delegates tasks based on the task description in your request, the `description` field in subagent configurations, and current context. To encourage proactive delegation, include phrases like 'use proactively' in your subagent's description field.

> **Write detailed descriptions:** Claude uses the description to decide when to delegate

**Source:** https://code.claude.com/docs/en/sub-agents — intro, "Understand automatic delegation", "Example subagents" (Best practices tip). Recorded by A7.
**Strength:** recommendation. Anthropic's own worked examples both pair a domain with an explicit trigger condition — `"Expert code review specialist. Proactively reviews code for quality, security, and maintainability. Use immediately after writing or modifying code."` Note the structural parallel to the skill `description` rules already in the catalog: in both artifact classes the description is the selection surface, not documentation.

### D43 — Give each subagent one job and only the tools it needs *(agents)*

**Imperative:** scope each subagent to a single task and grant the minimum tool set. Check the definitions into version control.

> **Limit tool access:** grant only necessary permissions for security and focus

> **Design focused subagents:** each subagent should excel at one specific task

> **Check into version control:** share project subagents with your team

**Source:** https://code.claude.com/docs/en/sub-agents — "Example subagents" (Best practices tip). Recorded by A7.
**Strength:** recommendation. Note what is *not* here: no guidance of any kind on how long a subagent's markdown body should be. See [§ The Two Numbers, And The Two Absences](#the-two-numbers-and-the-two-absences).

### D44 — Control who may invoke a skill with `disable-model-invocation` and `user-invocable` *(skills)*

**Imperative:** gate side-effecting workflows to user invocation only; gate non-actionable background knowledge to model invocation only.

> `disable-model-invocation: true`: Only you can invoke the skill. Use this for workflows with side effects or that you want to control timing, like `/commit`, `/deploy`, or `/send-slack-message`. You don't want Claude deciding to deploy because your code looks ready." / "`user-invocable: false`: Only Claude can invoke the skill. Use this for background knowledge that isn't actionable as a command.

**Source:** https://code.claude.com/docs/en/skills — "Control who invokes a skill". Recorded by A7.
**Strength:** recommendation with a documented mechanism behind it. This is the skills-side counterpart to D39: it is a configuration-level control over timing rather than a prompt-text request.

### D45 — Test a skill against every model tier it will run on *(skills)*

**Imperative:** evaluate the same skill on each tier, asking a different question of each.

> Test your Skill with all the models you plan to use it with. **Claude Haiku** (fast, economical): Does the Skill provide enough guidance? **Claude Sonnet** (balanced): Is the Skill clear and efficient? **Claude Opus** (powerful reasoning): Does the Skill avoid over-explaining?

**Source:** https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices — "Test with all models you plan to use". Recorded by A7.
**Strength:** recommendation. The three questions are not interchangeable — Anthropic pairs under-specification risk with the small model and over-explanation risk with the large one. The page names tiers without version numbers.

### D46 — Avoid the three named skill-content anti-patterns *(skills)*

**Imperative:** use forward slashes in paths, do not present multiple approaches unless necessary, and do not include information that will go stale.

> ### Avoid Windows-style paths — Always use forward slashes in file paths, even on Windows

> ### Avoid offering too many options — Don't present multiple approaches unless necessary

> ### Avoid time-sensitive information — Don't include information that will become outdated

**Source:** https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices — "Anti-patterns to avoid" and "Content guidelines". Recorded by A7.
**Strength:** recommendation. The middle item is the closest thing in the corpus to a statement against optionality in authored instructions, and it is scoped to skill content.

## Structural Conventions For Prompts

What the sources say about the shape of a prompt, as opposed to its content. This section is the one a later rewrite would be executed against, so quotes are preserved in full and gaps are named rather than smoothed over.

**XML tags versus markdown headings.** The consolidated best-practices page prescribes XML tags for one specific job — disambiguating mixed content types within a single prompt — not as a blanket replacement for markdown:

> XML tags help Claude parse complex prompts unambiguously, especially when your prompt mixes instructions, context, examples, and variable inputs. Wrapping each type of content in its own tag (for example, `<instructions>`, `<context>`, `<input>`) reduces misinterpretation.

Two stated best practices for tag use:

> Use consistent, descriptive tag names across your prompts.

> Nest tags when content has a natural hierarchy (documents inside `<documents>`, each inside `<document index="n">`).

Source: https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices — "Structure prompts with XML tags".

The only source that treats markdown headings as an equal alternative is the context-engineering post, which puts them on the same footing: structure prompts with XML tags **or** Markdown headers into distinct sections, e.g. `<background_information>`, `<instructions>`. Source: https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents (recorded by A6; note A6's caveat that this post's content was retrieved through the fetch tool's markdown-conversion pipeline rather than a raw-HTML comparison, so heading names in that source are reported as given). **No source in this corpus states that XML tags outperform markdown headings for section delimitation in general.** The documented advantage of tags is specifically about marking content *type* — "this text is a literal instruction" versus "this text is background context" — which a heading does not encode.

**Where instructions belong relative to context.** This is the strongest positional claim anywhere in the corpus, and it is about data placement, not rule placement:

> **Put longform data at the top:** Place your long documents and inputs near the top of your prompt, above your query, instructions, and examples. This improves performance across all models.

> Queries at the end can improve response quality by up to 30 percent in tests, especially with complex, multidocument inputs.

Source: https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices — "Long context prompting". A3 classifies the 30 percent figure as a measured claim rather than a stylistic preference.

**Instruction ordering within a system prompt is not addressed.** A1 checked all four Opus-5-family pages and found no statement about where critical instructions belong. A2 checked the Sonnet 5 page, the Opus 5 page, and the cross-model page and reached the same conclusion, explicitly distinguishing the long-context data-placement rule above from instruction ordering: the 30-percent finding "is about document/data placement in long-context tasks, not about ordering of instructions/rules within a system prompt itself." The single adjacent data point is Anthropic's own example in D5 of placing a short `<tone_preference>` block "near the end of a long system prompt" — one practical placement suggestion for one instruction, not a general principle. Do not cite this document as authority for a front-loading rule about instructions.

**How many examples.**

> Examples are one of the most reliable ways to steer Claude's output format, tone, and structure. A few well-crafted examples (known as few-shot or multishot prompting) improve accuracy and consistency.

> Include 3–5 examples for best results. You can also ask Claude to evaluate your examples for relevance and diversity, or to generate additional ones based on your initial set.

Three stated requirements for examples: **relevant** (mirror the actual use case), **diverse** (cover edge cases, avoid unintended pattern-matching), **structured** (wrap each in `<example>` tags, multiple in `<examples>` tags). Source: same page — "Use examples effectively".

**How to delimit sections.** For multi-document content the prescription is concrete:

> **Structure document content and metadata with XML tags:** When using multiple documents, wrap each document in `<document>` tags with `<document_content>` and `<source>` (and other metadata) subtags for clarity.

Source: same page — "Long context prompting".

**How to specify output format.** Four techniques, in the order the docs present them:

> 1. **Tell Claude what to do instead of what not to do**
>    * Instead of: "Do not use markdown in your response"
>    * Try: "Your response should be composed of smoothly flowing prose paragraphs."

> 2. Use XML format indicators — Try: "Write the prose sections of your response in `<smoothly_flowing_prose_paragraphs>` tags."

> 3. Match your prompt style to the desired output

> 4. Use detailed prompts for specific formatting preferences

Source: same page — "Control the format of responses". A3 notes the page frames the first of these as "particularly effective," which is stronger than a passing tip.

**Prompt style influences output style.** This is a mechanism claim, not just advice:

> The formatting style used in your prompt may influence Claude's response style. If you are still experiencing steerability issues with output formatting, try matching your prompt style to your desired output style as closely as possible. For example, removing markdown from your prompt can reduce the volume of markdown in the output.

Source: same page — "Control the format of responses".

**Role and persona framing is minimal.** The docs ask for one sentence, not a backstory:

> Setting a role in the system prompt focuses Claude's behavior and tone for your use case. Even a single sentence makes a difference

The example given verbatim is `"You are a helpful coding assistant specializing in Python."` Source: same page — "Give Claude a role". The consistency page adds a second role-related technique — pre-briefing scenarios:

> * **Use system prompts to set the role:** Use system prompts to define Claude's role and personality. This sets a strong foundation for consistent responses.
> * **Prepare Claude for possible scenarios:** Provide a list of common scenarios and expected responses in your prompts. This "trains" Claude to handle diverse situations without breaking character.

Source: https://platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/increase-consistency — "Keep Claude in character".

**The shape of Anthropic's own instruction blocks.** A3 recorded that every worked "good instruction block" example on the best-practices page — the markdown-avoidance block, the `<use_parallel_tool_calls>` block, the `<frontend_aesthetics>` block — has the same form: a single named XML tag wrapping 10–30 lines of prose paragraphs. One example, verbatim:

```text
<avoid_excessive_markdown_and_bullet_points>
When writing reports, documents, technical explanations, analyses, or any long-form
content, write in clear, flowing prose using complete paragraphs and sentences. Use
standard paragraph breaks for organization and reserve markdown primarily for `inline
code`, code blocks, and simple headings (## and ###). Avoid using **bold** and *italics*.
...
</avoid_excessive_markdown_and_bullet_points>
```

Source: https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices. Treating this observed form as *guidance* is [INFERENCE 4](#inference-from-sources) — Anthropic does not state that its own example format is the recommended format.

**Prompt length: no general guidance exists.** No source in this corpus gives a recommended maximum length for a system prompt, an output style, or an agent definition. A1 and A2 both checked and both report the absence, and the A7 amendment later confirmed the output-style and agent-definition absences by reading each page end to end — see [§ The Two Numbers, And The Two Absences](#the-two-numbers-and-the-two-absences). *Amended:* one artifact class the original six inputs had no guidance for does have a number — CLAUDE.md files carry a "target under 200 lines" (D33), added by A7. The only numeric length guidance the original six inputs found applies to skill files:

> Keep SKILL.md body under 500 lines for optimal performance. If your content exceeds this, split it into separate files using the progressive disclosure patterns described earlier.

And to skill metadata: `description` "Must be non-empty. Maximum 1,024 characters. Cannot contain XML tags"; `name` "Maximum 64 characters." Source: https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices (recorded by A6 as D27–D29). The related structural rule for multi-file skills:

> Claude may partially read files when they're referenced from other referenced files. When encountering nested references, Claude might use commands like `head -100` to preview content rather than reading entire files, resulting in incomplete information. Keep references one level deep from SKILL.md.

Source: same page — "Avoid deeply nested references".

The nearest thing to a general length principle is the context-engineering post's stated objective, which is a direction rather than a threshold:

> find the smallest set of high-signal tokens that maximize the likelihood of your desired outcome

Source: https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents.

## Authoring Guidance By Artifact Class

All material in this section comes from `.scratchpad/A7-authoring-guidance.md`, a gap-fill research pass added after the original six. Where the sections above record what Anthropic says about prompt *content* in the abstract, this section records what Anthropic says about authoring the four configuration artifact classes themselves: CLAUDE.md and memory files, output styles, agent definitions, and Agent Skills. A7's source scope was restricted to `docs.claude.com`, `code.claude.com`, `platform.claude.com`, `anthropic.com`, and the `anthropics` GitHub organization; third-party guides were logged and used for nothing (see the A7 group in [§ Source Bibliography](#source-bibliography)).

All four classes have at least one dedicated official page, and A7 obtained quote-backed coverage of all four. Two of the four have an explicit numeric length target. Two have none — and in both of those cases the absence was established by reading the full page end to end rather than by a search miss.

Because a later document will be executed against this section, quotes are carried verbatim and at length rather than summarized.

### The Two Numbers, And The Two Absences

| Artifact class | Official length guidance | Source |
|---|---|---|
| CLAUDE.md and memory files | **"target under 200 lines per CLAUDE.md file"** — a soft target framed in terms of adherence, not an enforced cap | https://code.claude.com/docs/en/memory |
| Agent Skills (`SKILL.md` body) | **"Keep SKILL.md body under 500 lines"** — stated three times across two official pages | https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices; https://code.claude.com/docs/en/skills |
| Output styles | **None.** No line-count, KB, or token-budget guidance anywhere on the page | https://code.claude.com/docs/en/output-styles (full page read; confirmed absence) |
| Agent definitions (markdown system-prompt body) | **None.** No line-count, KB, or token-budget guidance anywhere on the page | https://code.claude.com/docs/en/sub-agents (full page read; confirmed absence) |

**The two absences are coverage facts about Anthropic's documentation, not failures of research.** A7 records the method for each rather than asserting the absence bare. For output styles:

> This absence was checked directly against the full fetched page content, not inferred from a search miss — the page has no section titled anything like "size," "length," or "how large," and no such guidance appears in the "How output styles work" or "Create a custom output style" sections where CLAUDE.md's equivalent guidance lives.

Source: `.scratchpad/A7-authoring-guidance.md`, reporting on https://code.claude.com/docs/en/output-styles. And for agent definitions:

> Unlike CLAUDE.md's explicit "under 200 lines" target, **no line-count, KB, or token-budget guidance for a subagent's markdown-body system prompt is stated anywhere on this page.** This is a genuine documented absence, not an inference — the page discusses context cost only in terms of "isolated context window" and preloaded-skill/CLAUDE.md content, never a size ceiling for the subagent's own prompt body.

Source: `.scratchpad/A7-authoring-guidance.md`, reporting on https://code.claude.com/docs/en/sub-agents.

The consequence for any downstream argument is symmetric and should be stated plainly: for output styles and agent definitions there is **no official ceiling to exceed and no official endorsement of length either**. A length-based case about either artifact class cannot cite Anthropic in either direction. A7 quantifies the framing without supplying authority for it: this repository's two output styles "are ~6-15x the size of any numerically-limited artifact class this research found, with zero official ceiling to check them against either way."

A7's own summary of the relative strength of the two numbers that do exist:

> This is the single clearest numeric length ceiling found anywhere in this research pass across all four artifact classes — more explicit than CLAUDE.md's "target under 200 lines" (a target, softer wording) and far more explicit than output styles or agent definitions (no numeric guidance at all, see above).

### CLAUDE.md And Memory Files

The canonical page is https://code.claude.com/docs/en/memory ("How Claude remembers your project"), which is the redirect target of https://docs.claude.com/en/docs/claude-code/memory. A7 records that no separate tutorial-style authoring page exists — this one page "serves both as reference and as the de facto authoring guide," confirmed by two searches that both surfaced only it.

**Size — the 200-line target, stated twice.**

> **Size**: target under 200 lines per CLAUDE.md file. Longer files consume more context and reduce adherence. If your instructions are growing large, use path-scoped rules so instructions load only when Claude works with matching files. You can also split content into imports for organization, though imported files still load and enter the context window at launch.

Source: https://code.claude.com/docs/en/memory — "Write effective instructions".

> Files over 200 lines consume more context and may reduce adherence.

Source: same page — "My CLAUDE.md is too large".

**The 200-line figure is a recommendation for CLAUDE.md and a hard limit only for `MEMORY.md`.** This distinction is Anthropic's, and it matters because the same number appears in both places with different force:

> This limit applies only to `MEMORY.md`. CLAUDE.md files are loaded in full regardless of length, though shorter files produce better adherence.

Source: same page — "How it works" (auto memory). A7's own note on the distinction, carried through because it prevents a misreading: "CLAUDE.md itself has no hard enforced size cap (no truncation) — only the *auto-memory* `MEMORY.md` index has a hard 200-line/25KB read-limit with a rewrite-triggering error. CLAUDE.md's '200 lines' is a recommendation for adherence, not an enforced ceiling."

**Structure — markdown headers and bullets, explicitly.** This is the one place in the corpus where Anthropic prescribes markdown structure for an artifact class rather than XML tags (contrast [§ Structural Conventions For Prompts](#structural-conventions-for-prompts), where the XML-tag prescription is scoped to disambiguating mixed content types):

> **Structure**: use markdown headers and bullets to group related instructions. Claude scans structure the same way readers do: organized sections are easier to follow than dense paragraphs.

**Specificity — concrete enough to verify, with three paired examples.**

> **Specificity**: write instructions that are concrete enough to verify. For example: 'Use 2-space indentation' instead of 'Format code properly' … 'Run `npm test` before committing' instead of 'Test your changes' … 'API handlers live in `src/api/handlers/`' instead of 'Keep files organized'

**Consistency — contradictions resolve arbitrarily.**

> **Consistency**: if two rules contradict each other, Claude may pick one arbitrarily. Review your CLAUDE.md files, nested CLAUDE.md files in subdirectories, and `.claude/rules/` periodically to remove outdated or conflicting instructions.

Sources for the three above: https://code.claude.com/docs/en/memory — "Write effective instructions". The same point is repeated in the troubleshooting section as an explicit anti-pattern:

> Make instructions more specific. 'Use 2-space indentation' works better than 'format code nicely.' Look for conflicting instructions across CLAUDE.md files. If two files give different guidance for the same behavior, Claude may pick one arbitrarily.

Source: same page — "Claude isn't following my CLAUDE.md".

**What belongs, and what should be moved elsewhere.** Anthropic gives both a trigger for adding content and a boundary on what class of content belongs at all:

> Treat CLAUDE.md as the place you write down what you'd otherwise re-explain. Add to it when: Claude makes the same mistake a second time; A code review catches something Claude should have known about this codebase; You type the same correction or clarification into chat that you typed last session; A new teammate would need the same context to be productive.

> Keep it to facts Claude should hold in every session: build commands, conventions, project layout, 'always do X' rules. If an entry is a multi-step procedure or only matters for one part of the codebase, move it to a skill or a path-scoped rule instead.

Source: https://code.claude.com/docs/en/memory — "When to add to CLAUDE.md".

**CLAUDE.md is not part of the system prompt, and compliance is not guaranteed.** This is a mechanism fact with direct consequences for how much weight any CLAUDE.md instruction can be expected to carry:

> CLAUDE.md content is delivered as a user message after the system prompt, not as part of the system prompt itself. Claude reads it and tries to follow it, but there's no guarantee of strict compliance, especially for vague or conflicting instructions.

Source: same page — "Claude isn't following my CLAUDE.md".

> Both are loaded at the start of every conversation. Claude treats them as context, not enforced configuration. To block an action regardless of what Claude decides, use a PreToolUse hook instead. The more specific and concise your instructions, the more consistently Claude follows them.

Source: same page — "CLAUDE.md vs auto memory". See [§ Enforcement Beyond Prompt Text](#enforcement-beyond-prompt-text) for the full form of that redirect.

**Load order and concatenation.**

> CLAUDE.md files can live in several locations, each with a different scope. The table below lists them in load order, from broadest scope to most specific… Managed policy … User instructions `~/.claude/CLAUDE.md` … Project instructions `./CLAUDE.md` or `./.claude/CLAUDE.md` … Local instructions `./CLAUDE.local.md`

> All discovered files are concatenated into context rather than overriding each other. Across the directory tree, content is ordered from the filesystem root down to your working directory… instructions closer to where you launched Claude are read last.

Sources: same page — "Choose where to put CLAUDE.md files" and "How CLAUDE.md files load".

**Block-level HTML comments are stripped before injection.** A documented mechanism for zero-cost maintainer notes:

> Block-level HTML comments (`<!-- maintainer notes -->`) in CLAUDE.md files are stripped before the content is injected into Claude's context. Use them to leave notes for human maintainers without spending context tokens on them. Comments inside code blocks are preserved.

Source: same page — "How CLAUDE.md files load".

**Anthropic ships a tool that trims a CLAUDE.md, and its trim policy is itself guidance.** What `/doctor` cuts and what it keeps is the clearest statement anywhere of what Anthropic considers dead weight in a project-instruction file:

> The `/doctor` checkup proposes trims for a checked-in CLAUDE.md: it cuts content Claude can derive from the codebase, such as directory layouts, dependency lists, and architecture overviews, and keeps pitfalls, rationale, and conventions that differ from tool defaults.

Source: same page — "My CLAUDE.md is too large".

**Where CLAUDE.md sits on the context-cost spectrum relative to rules and skills.**

> Rules load into context every session or when matching files are opened. For task-specific instructions that don't need to be in context all the time, use skills instead, which only load when you invoke them or when Claude determines they're relevant to your prompt.

Source: same page — "Organize rules with `.claude/rules/`". A7 reads this as the clearest official statement of the three-way spectrum: "CLAUDE.md and paths-less rules = always-injected at launch; path-scoped rules = conditionally injected on matching file access; skills = on-demand/model-decided invocation only."

### Output Styles

The canonical page is https://code.claude.com/docs/en/output-styles, read in full by A7.

**Mechanism — an output style modifies the system prompt directly.** This is the mechanical difference from CLAUDE.md, which arrives as a user message afterward:

> Output styles change how Claude responds, not what Claude knows. They modify the system prompt to set role, tone, and output format. Use one when you keep re-prompting for the same voice or format every turn, or when you want Claude to act as something other than a software engineer.

> A custom output style adds your instructions to the system prompt and lets you choose whether to keep Claude Code's built-in software engineering instructions. Keep them when you're changing how Claude communicates but still coding, like always answering with a diagram. Leave them out when Claude isn't doing software engineering at all, like a writing assistant or data analyst.

**The one explicit misuse warning on the page** — and A7 confirms it is the only one:

> For instructions about your project, conventions, or codebase, use CLAUDE.md instead.

Sources: https://code.claude.com/docs/en/output-styles — intro section. A7's finding on anti-patterns: "The only explicit anti-pattern/misuse warning on this page is the CLAUDE.md-substitution guidance quoted above … No other explicit 'don't do X' statements about output-style authoring appear on the page."

**File format and frontmatter.**

> A custom output style is a Markdown file: frontmatter for metadata, then the instructions to add to the system prompt.

Source: same page — "Create a custom output style". Documented frontmatter fields, per A7: `name`, `description` ("shown in the `/config` picker"), `keep-coding-instructions` (default `false`), `force-for-plugin` (plugin-only, default `false`). A7 records the negative explicitly: "No `model`, `tools`, or other agent-definition-style fields are documented for output styles."

**No length guidance — and token cost is discussed qualitatively only.** The page addresses cost without ever quantifying a target size:

> Token usage depends on the style. Adding instructions to the system prompt increases input tokens, though prompt caching reduces this cost after the first request in a session. The built-in Explanatory and Learning styles produce longer responses than Default by design, which increases output tokens. For custom styles, output token usage depends on what your instructions tell Claude to produce.

Source: same page — "How output styles work". See [§ The Two Numbers, And The Two Absences](#the-two-numbers-and-the-two-absences) for the confirmed-absence method.

**When a change takes effect.**

> Output style is part of the system prompt, which Claude Code reads once at session start. Changes take effect after `/clear` or a new session.

Source: same page — "Change your output style".

**Scope — an output style does not reach a sub-agent.** This is the single most consequential statement on the page for any coordinator-style prompt:

> Output styles apply to the main conversation only: a subagent runs its own system prompt, so styles don't change how subagents respond. A fork is the exception, because it inherits the parent's full system prompt.

Source: same page — "How output styles work". Independently corroborated on the sub-agents page (see [§ Agent Definitions](#agent-definitions) below and D31), which names output style explicitly among the things that never reach a non-fork subagent. Document A already carried this fact from A6; A7 adds the output-styles page as a second official source for it.

**Anthropic's own four-way comparison of the mechanisms.** Quoted because it is the only place all four artifact classes are placed against each other:

> Output styles | Modifies the system prompt | You want a different role, tone, or default response format every turn" / "CLAUDE.md | Adds a user message after the system prompt | Claude should always know your project conventions and codebase context" / "Agents | Runs a subagent with its own system prompt, model, and tools | You want a separately scoped helper for a focused task" / "Skills | Loads task-specific instructions when invoked or relevant | You have a reusable workflow

Source: same page — "Comparisons to related features". (Quoted as A7 recorded it, including A7's row separators; the table's cell boundaries are preserved rather than reflowed.)

### Agent Definitions

The canonical page is https://code.claude.com/docs/en/sub-agents, which A7 read in full (~1,235 lines).

**File format and required fields.**

> Subagent files use YAML frontmatter for configuration, followed by the system prompt in Markdown

> The following fields can be used in the YAML frontmatter. Only `name` and `description` are required.

Sources: https://code.claude.com/docs/en/sub-agents — "Write subagent files" and "Supported frontmatter fields". A7 records the full documented field list: `name` (required), `description` (required), `tools`, `disallowedTools`, `model`, `permissionMode`, `maxTurns`, `skills`, `mcpServers`, `hooks`, `memory`, `background`, `effort`, `isolation`, `color`, `initialPrompt`. A7 also records a specific negative: "No `mcp:` frontmatter field is documented anywhere on this page — only `mcpServers` (a structured field for granting MCP server access, not an informational-only marker)."

**The `description` field is the routing signal.**

> Claude uses each subagent's description to decide when to delegate tasks. When you create a subagent, write a clear description so Claude knows when to use it.

> Claude automatically delegates tasks based on the task description in your request, the `description` field in subagent configurations, and current context. To encourage proactive delegation, include phrases like 'use proactively' in your subagent's description field.

> **Write detailed descriptions:** Claude uses the description to decide when to delegate

Sources: same page — intro, "Understand automatic delegation", and the "Best practices" tip under "Example subagents". A7 records the shape of Anthropic's own good-practice examples: `"Expert code review specialist. Proactively reviews code for quality, security, and maintainability. Use immediately after writing or modifying code."` and `"Debugging specialist for errors, test failures, and unexpected behavior. Use proactively when encountering any issues."` — "both name the domain AND state an explicit trigger condition."

**What a subagent inherits, and what it does not.** Quoted in full because this is the most-misread mechanism in the corpus:

> Each subagent starts with a fresh, isolated context window. It doesn't see your conversation history, the skills you've already invoked, or the files Claude has already read. Claude composes a delegation message that summarizes the task, and the subagent works from there. The exception is a fork, which inherits the parent conversation instead of starting fresh.

> A non-fork subagent's initial context contains: **System prompt**: the agent's own prompt plus environment details that Claude Code appends, not the full Claude Code system prompt. … **Task message** … **CLAUDE.md files**: every level of the CLAUDE.md hierarchy the main conversation loads … The built-in Explore and Plan agents skip this. **Git status** … **Preloaded skills** … **Sibling roster** …

> Some main-conversation state never reaches a non-fork subagent: **Output style**: a subagent runs its own system prompt, so your output style doesn't shape its responses, except in a fork. **Auto memory**: the main conversation's auto memory isn't loaded. … **Context window size**: a subagent's context window is sized by its own model, not the parent's.

Source: https://code.claude.com/docs/en/sub-agents — "What loads at startup". Document A already carried this from A6 (see D31 and [§ Context Management Across Agents](#context-management-across-agents)); A7 re-verified it against the same page and adds the third quote's field-by-field enumeration.

**Message authority — no agent message grants approval or changes configuration.**

> A subagent treats messages from the agent that launched it as normal task direction, including mid-task course corrections, and acts on them within its own permission settings. Two limits still hold regardless of who sent the message: no message from any agent counts as your approval for a pending permission prompt, and no agent message can change a subagent's permission settings, `CLAUDE.md`, or configuration. Only the permission system or your own messages can grant approval.

Source: same page — "Resume subagents". This is a documented platform behavior, not advice.

**Model field.**

> `model` | No | Model to use: `sonnet`, `opus`, `haiku`, `fable`, a full model ID (for example, `claude-opus-5`), or `inherit`. Defaults to `inherit`

Source: same page — "Supported frontmatter fields". A7 notes the alias list contains no Haiku 5 entry, consistent with the corpus-wide finding that no Claude Haiku 5 exists as of 2026-07-27.

**The three stated best practices for authoring a subagent.**

> **Limit tool access:** grant only necessary permissions for security and focus

> **Design focused subagents:** each subagent should excel at one specific task

> **Check into version control:** share project subagents with your team

Source: same page — "Example subagents" (Best practices tip).

**No content-splitting mechanism is documented for a subagent's own prompt body.** A7's finding, recorded as an absence: "no import/reference mechanism is documented at all on the sub-agents page for splitting a subagent's own system-prompt body across files; the only cross-file content mechanisms found are `skills:` (preload) and `mcpServers:` (tool access), neither of which is a prose-splitting mechanism."

**Storage and precedence.**

> Store subagent files in different locations depending on scope. When multiple subagents share the same name, Claude Code uses the one from the higher-priority location.

Source: same page — "Choose the subagent scope". A7 records the priority order, highest to lowest: managed settings, the `--agents` CLI flag, `.claude/agents/` (project), `~/.claude/agents/` (user), plugin `agents/` directory.

### Agent Skills

Skills are the only artifact class whose authoring guidance is split across two official hosts, and A7 records that both must be cited: https://code.claude.com/docs/en/skills for Claude-Code-specific frontmatter, storage, and invocation, and https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices for the cross-tool Agent Skills authoring standard.

**The 500-line limit, stated three times across both hosts.** Document A already carried this figure from A6 via the platform best-practices page; A7 corroborates it from a second official page and records all three occurrences:

> Keep SKILL.md body under 500 lines for optimal performance.

Source: https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices — "Token budgets".

> Practical guidance: Keep SKILL.md body under 500 lines for optimal performance. Split content into separate files when approaching this limit.

Source: same page — "Progressive disclosure patterns".

> Keep `SKILL.md` under 500 lines. Move detailed reference material to separate files.

Source: https://code.claude.com/docs/en/skills — "Add supporting files" (Tip callout).

**Frontmatter field limits — and an unreconciled discrepancy between the two official hosts.**

> `name`: Maximum 64 characters; Must contain only lowercase letters, numbers, and hyphens; Cannot contain XML tags; Cannot contain reserved words: 'anthropic', 'claude'" / "`description`: Must be non-empty; Maximum 1,024 characters; Cannot contain XML tags; Should describe what the Skill does and when to use it

Source: https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices — "Skill structure" (YAML frontmatter note).

> All fields are optional. Only `description` is recommended so Claude knows when to use the skill.

> `description` | Recommended | What the skill does and when to use it. Claude uses this to decide when to apply the skill. If omitted, uses the first paragraph of markdown content. Put the key use case first: the combined `description` and `when_to_use` text is truncated at 1,536 characters in the skill listing to reduce context usage.

Source: https://code.claude.com/docs/en/skills — "Frontmatter reference". A7 flags the two figures rather than resolving them:

> Note the discrepancy between the two official sources: platform.claude.com's Agent Skills standard caps `description` at 1,024 characters; code.claude.com states the Claude-Code-specific truncation point for the combined `description` + `when_to_use` listing display is 1,536 characters. These are not necessarily contradictory (one may be the standard's validation limit, the other Claude Code's display truncation), but this research did not find a single page reconciling them — flagged rather than silently resolved.

A7 records the Claude-Code-specific frontmatter field list as: `name`, `description`, `when_to_use`, `argument-hint`, `arguments`, `disable-model-invocation`, `user-invocable`, `allowed-tools`, `disallowed-tools`, `model`, `effort`, `context`, `agent`, `background`, `hooks`, `paths`, `shell`.

**Description authoring — third person, specific, non-vague.** Document A already carried the third-person rule from A6; A7 re-verified it and adds the selection-pressure framing and the vague-description examples:

> **Always write in third person**. The description is injected into the system prompt, and inconsistent point-of-view can cause discovery problems. **Good:** 'Processes Excel files and generates reports' **Avoid:** 'I can help you process Excel files' **Avoid:** 'You can use this to process Excel files'

> Each Skill has exactly one description field. The description is critical for skill selection: Claude uses it to choose the right Skill from potentially 100+ available Skills.

> Avoid vague descriptions like these: `description: Helps with documents` / `description: Processes data` / `description: Does stuff with files`

Source: https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices — "Writing effective descriptions".

**Progressive disclosure — the mechanism, stated explicitly.**

> SKILL.md serves as an overview that points Claude to detailed materials as needed, like a table of contents in an onboarding guide.

> Metadata pre-loaded: At startup, the name and description from all Skills' YAML frontmatter are loaded into the system prompt. Files read on-demand: Claude uses bash Read tools to access SKILL.md and other files from the filesystem when needed. Scripts executed efficiently … No context penalty for large files: Reference files, data, or documentation don't consume context tokens until actually read.

Sources: same page — "Progressive disclosure patterns" and "Runtime environment".

> Reference supporting files from `SKILL.md` so Claude knows what each file contains and when to load it… Large reference docs, API specifications, or example collections don't consume context tokens until actually read.

Source: https://code.claude.com/docs/en/skills — "Add supporting files". (A7 records this page's phrasing as: "Large reference docs, API specifications, or example collections don't need to load into context every time the skill runs.")

A7 records three named organizational patterns for progressive disclosure on the platform page — "High-level guide with references," "Domain-specific organization," "Conditional details" — and assesses the whole cluster as "the single most complete and prescriptive piece of official authoring guidance found across all four artifact classes in this research pass."

**Anti-pattern: nested references beyond one level.** Already carried in Document A from A6; A7 re-verified it and records the mechanism:

> Claude may partially read files when they're referenced from other referenced files. When encountering nested references, Claude might use commands like `head -100` to preview content rather than reading entire files, resulting in incomplete information. **Keep references one level deep from SKILL.md**.

Source: https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices — "Avoid deeply nested references".

**Three further named anti-patterns, plus the density principle.**

> ### Avoid Windows-style paths — Always use forward slashes in file paths, even on Windows

> ### Avoid offering too many options — Don't present multiple approaches unless necessary

> ### Avoid time-sensitive information — Don't include information that will become outdated

> Default assumption: Claude is already very smart. Only add context Claude doesn't already have.

Sources: same page — "Anti-patterns to avoid", "Content guidelines", "Core principles" ("Concise is key"). The last of these is the same statement Document A already carries as D30.

**Invocation control — who may invoke a skill.**

> `disable-model-invocation: true`: Only you can invoke the skill. Use this for workflows with side effects or that you want to control timing, like `/commit`, `/deploy`, or `/send-slack-message`. You don't want Claude deciding to deploy because your code looks ready." / "`user-invocable: false`: Only Claude can invoke the skill. Use this for background knowledge that isn't actionable as a command.

Source: https://code.claude.com/docs/en/skills — "Control who invokes a skill".

**Running a skill in a sub-agent, and how that differs from preloading a skill into one.**

> Add `context: fork` to your frontmatter when you want a skill to run in isolation. The skill content becomes the prompt that drives the subagent. It won't have access to your conversation history.

> Skill with `context: fork` | System prompt: From agent type | Task: SKILL.md content | Also loads: CLAUDE.md, except when the agent is Explore or Plan" / "Subagent with `skills` field | System prompt: Subagent's markdown body | Task: Claude's delegation message | Also loads: Preloaded skills + CLAUDE.md

Source: https://code.claude.com/docs/en/skills — "Run skills in a subagent".

**Evaluation-first authoring.** Already carried in Document A from A6; A7 re-verified the imperative verbatim:

> **Create evaluations BEFORE writing extensive documentation.** This ensures your Skill solves real problems rather than documenting imagined ones.

Source: https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices — "Build evaluations first".

**Test across every model tier the skill will run on — with a different question per tier.**

> Test your Skill with all the models you plan to use it with. **Claude Haiku** (fast, economical): Does the Skill provide enough guidance? **Claude Sonnet** (balanced): Is the Skill clear and efficient? **Claude Opus** (powerful reasoning): Does the Skill avoid over-explaining?

Source: same page — "Test with all models you plan to use". A7 notes the page names tiers generically with no version numbers attached, so it "neither confirms nor conflicts with the 'no Haiku 5' fact from prior passes; it is simply silent on version."

**Storage locations.** Per https://code.claude.com/docs/en/skills ("Where skills live"), as recorded by A7: `.claude/skills/` (project, nested directories scanned, walking up from cwd to repo root), `~/.claude/skills/` (user, all projects), plugin `skills/` subdirectories (namespaced), and `.claude/commands/` files (legacy custom-commands format — "Custom commands have been merged into skills").

### Splitting Content Across Files — Which Mechanisms Reduce Context And Which Do Not

This subsection is separated out because the distinction is easy to collapse and expensive to get wrong. Anthropic documents several ways to move content out of a main file, and **they do not have the same context economics.**

**CLAUDE.md `@path` imports do NOT reduce context.** Stated directly, in the troubleshooting section for an oversized CLAUDE.md:

> Splitting into `@path` imports helps organization but doesn't reduce context, since imported files load at launch.

And the mechanism behind it:

> CLAUDE.md files can import additional files using `@path/to/import` syntax. Imported files are expanded and loaded into context at launch alongside the CLAUDE.md that references them. … Imported files can recursively import other files, with a maximum depth of four hops.

Sources: https://code.claude.com/docs/en/memory — "My CLAUDE.md is too large" and "Import additional files".

**CLAUDE.md path-scoped rules DO reduce context.** They load conditionally:

> If your instructions are growing large, use path-scoped rules so instructions load only when Claude works with matching files.

Source: same page — "Write effective instructions". A7 records that `.claude/rules/` files with `paths:` frontmatter are "loaded only 'when Claude works with matching files'," and that rules *without* `paths:` load every session like CLAUDE.md itself.

**Agent Skills' supporting files DO reduce context.** This is the only mechanism in A7's corpus with an explicit zero-cost-until-read statement:

> No context penalty for large files: Reference files, data, or documentation don't consume context tokens until actually read.

Source: https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices — "Runtime environment".

**Agent definitions have no documented prose-splitting mechanism at all** — see [§ Agent Definitions](#agent-definitions).

A7's own conclusion, carried verbatim because the framing is the load-bearing part:

> Conclusion for the migration: whether "splitting into referenced files loaded on demand" actually saves context depends entirely on WHICH mechanism is used. CLAUDE.md imports do not save context (common misconception); only path-scoped rules and skill supporting-files genuinely do.

**Scope limit on the `@path` finding — do not generalize it.** The "imports do not reduce context" statement is specifically about the CLAUDE.md `@path/to/import` syntax on the memory page. It is **not** a statement about reference patterns in general, and A7 does not extend it to any other artifact class. In particular, **A7 does not address ordinary markdown-link references from an output style body to separate documents** — the output-styles page A7 read in full contains no reference-or-import mechanism discussion of any kind, and A7's answer to that question enumerates only CLAUDE.md imports, CLAUDE.md path-scoped rules, skills, and agent definitions. Whether an ordinary markdown link inside an output style is auto-injected or read on demand is therefore **unaddressed by A7 and unsupported by anything in this section**; any claim about it must rest on a different source. Extending the `@path` finding to cover it would be a factual error.

### Enforcement Beyond Prompt Text

A7's answer to the question of whether any officially documented mechanism makes an instruction reliably followed. The answer is that prompt text never guarantees anything, and two non-prompt mechanisms do.

**Hooks — the documented mechanism for "regardless of what Claude decides."**

> Both are loaded at the start of every conversation. Claude treats them as context, not enforced configuration. To block an action regardless of what Claude decides, use a PreToolUse hook instead.

> If the instruction is something that must run at a specific point, such as before every commit or after each file edit, write it as a hook instead. Hooks execute as shell commands at fixed lifecycle events and apply regardless of what Claude decides to do.

Sources: https://code.claude.com/docs/en/memory — "CLAUDE.md vs auto memory" and "Claude isn't following my CLAUDE.md".

**Settings-level rules — client-enforced rather than model-judged.**

> Settings rules are enforced by the client regardless of what Claude decides to do. CLAUDE.md instructions shape Claude's behavior but are not a hard enforcement layer.

Source: same page — "Deploy organization-wide CLAUDE.md". A7 names `permissions.deny` and `sandbox.enabled` as the keys the page contrasts against managed CLAUDE.md.

A7's conclusion: "prompt text (CLAUDE.md, output styles, agent system prompts, skill content) is never a guarantee, only an influence; the only two officially documented guarantee mechanisms are (a) hooks, specifically PreToolUse for blocking, and (b) settings-level permission/sandbox enforcement (`permissions.deny`, `sandbox.enabled`), which are enforced by the client rather than left to model judgment."

**Sourcing caveat on the hooks half of this.** A7 records that it never fetched the hooks documentation itself: "that citation rests entirely on the memory page's own cross-references to hooks ('use a PreToolUse hook instead'), not on independently fetching the hooks documentation itself." The claim is Anthropic's, from the memory page; the hooks pages themselves are uncovered in this corpus.

## Reliability And Consistency Techniques

All material in this section comes from A4's pass over the `test-and-evaluate/strengthen-guardrails/` family, plus the consistency-relevant parts of the consolidated best-practices page. Note the URL path: these pages are no longer under `prompt-engineering/` — see [C15](#c15-the-documentation-itself-was-reorganized--cite-current-urls).

Each technique is classified as **prompt-level** (achievable inside a single prompt), **architecture-level** (requires additional calls, subsystems, or code), or **post-hoc** (happens after generation).

### Hallucination Reduction

**Grant explicit permission to abstain — prompt-level.**

> **Allow Claude to say "I don't know":** Explicitly give Claude permission to admit uncertainty. This simple technique can drastically reduce false information.

**Quote-first grounding for long documents — prompt-level, scoped to >20k tokens.**

> **Use direct quotes for factual grounding:** For tasks involving long documents (>20k tokens), ask Claude to extract word-for-word quotes first before performing its task. This grounds its responses in the actual text, reducing hallucinations.

**Citation-then-retraction — prompt-level with an in-conversation verification step.**

> **Verify with citations**: Make Claude's response auditable by having it cite quotes and sources for each of its claims. You can also have Claude verify each claim by finding a supporting quote after it generates a response. If it can't find a quote, it must retract the claim.

**Chain-of-thought verification — prompt-level.**

> **Chain-of-thought verification**: Ask Claude to explain its reasoning step-by-step before giving a final answer. This can reveal faulty logic or assumptions.

**Best-of-N comparison — architecture-level.** Requires N calls plus a diffing step outside the prompt.

> **Best-of-N verification**: Run Claude through the same prompt multiple times and compare the outputs. Inconsistencies across outputs could indicate hallucinations.

**Iterative refinement — prompt-level but requires a second turn.**

> **Iterative refinement**: Use Claude's outputs as inputs for follow-up prompts, asking it to verify or expand on previous statements. This can catch and correct inconsistencies.

**External knowledge restriction — prompt-level.**

> **External knowledge restriction**: Explicitly instruct Claude to only use information from provided documents and not its general knowledge.

All quotes above: https://platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/reduce-hallucinations.

**Anthropic's own honesty caveat on the whole set — post-hoc verification is required regardless.** This is the docs stating plainly that none of the above is a complete fix:

> Remember, while these techniques significantly reduce hallucinations, they don't eliminate them entirely. Always validate critical information, especially for high-stakes decisions.

### Output Consistency

**Specify the output format precisely — prompt-level.**

> Precisely define your desired output format using JSON, XML, or custom templates so that Claude follows every output formatting element you require.

**Constrain with concrete examples rather than abstract instructions — prompt-level.** Stated comparatively, not as an alternative:

> Provide examples of your desired output. This is more effective than abstract instructions.

**Retrieval grounding — architecture-level.**

> For tasks requiring consistent context (for example, chatbots, knowledge bases), use retrieval to ground Claude's responses in a fixed information set.

**Task decomposition — prompt-level, multiple calls.**

> Break down complex tasks into smaller, consistent subtasks. Each subtask gets Claude's full attention, reducing inconsistency errors across scaled workflows.

All quotes above: https://platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/increase-consistency.

**The page's own redirect away from prompt engineering entirely, for the strictest consistency need.** A4 records this as the clearest such statement in its whole pass:

> If you need Claude to always output valid JSON that conforms to a specific schema, use Structured Outputs instead of the prompt engineering techniques below. Structured outputs provide guaranteed schema compliance and are specifically designed for this use case. The techniques below are useful for general output consistency or when you need flexibility beyond strict JSON schemas.

Source: same page, top-of-page tip.

### Techniques The Sources Say Do Not Help

**Response prefill.** The single unambiguous "this no longer works" finding in the corpus. It does not degrade — it 400-errors. See [C1](#c1-response-prefill-is-dead-not-discouraged--hard-400-error-on-claude-46) for the full quote and the documented replacements. Both A3 and A4 established this independently from different pages. The consistency page and the prompt-leak page both still describe prefill as a technique in their body text and then override themselves with an inline note, which is worth knowing if either page is read quickly.

**Aggressive and redundant emphasis language, for tool and skill triggering.** See [C11](#c11-aggressive-emphasis-language-now-causes-overtriggering) and [§ Emphasis And Over-Steering](#emphasis-and-over-steering).

**Naming thinking tags specifically in a suppression instruction.** Less effective than the general form — see D21.

**Instructing the model not to think or not to reason.** Increases the leakage it was meant to prevent — see D20.

**Hand-written prescriptive step-by-step plans, relative to a general instruction.**

> A prompt like "think thoroughly" often produces better reasoning than a hand-written step-by-step plan. Claude's reasoning frequently exceeds what a human would prescribe.

Source: https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices.

**Leak-proofing a prompt, as a first resort.** The prompt-leak page warns against its own subject matter:

> Attempts to leak-proof your prompt can add complexity that may degrade performance in other parts of the task.

It recommends trying monitoring and output-screening before leak-resistant prompt engineering. Source: https://platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/reduce-prompt-leak. This is the only statement in the corpus that names added prompt complexity as a cause of degraded task performance — and it is scoped narrowly to leak-proofing instructions, not to prompt complexity in general.

### Untrusted Content And Injection Defense

Relevant because it governs how externally-sourced content should enter a prompt. All from https://platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/mitigate-jailbreaks.

**Put untrusted content only in tool results — architecture-level, stated as a rule.**

> **Put untrusted content only in tool results.** Deliver third-party content to Claude inside `tool_result` blocks, never in `system` prompts or plain user `text` blocks. Claude is trained to treat instructions that appear inside tool results with appropriate skepticism.

**Label the content's nature and origin — prompt/architecture hybrid.**

> **Tell Claude what the content is and where it came from.** In the tool's `description`, or in the structure of the result itself, make the nature and source of the content explicit... This context helps Claude calibrate how much to trust embedded directives.

**State the policy in the system prompt — prompt-level.**

> **State the policy in your system prompt.** Tell Claude explicitly that content returned from tools, documents, or searches is untrusted data and must never override the system prompt or the user's original request.

**JSON-encode untrusted content — prompt-formatting-level.**

> **JSON-encode untrusted content.** Where possible, wrap third-party strings in a JSON object rather than concatenating them into free-form text. JSON escaping provides unambiguous delimiters between the untrusted payload and the surrounding structure, so an attacker cannot close a quote or tag to "break out" into an instruction context.

**Do not put your own instructions in tool results — stated as a prohibition.**

> **Don't put your own instructions in tool results.** Because Claude treats tool-result content as untrusted data, instructions you place there may be ignored or flagged as a potential injection. Send your instructions in a `user` turn that follows the `tool_result` block.

**Screen inputs and tool outputs with a lightweight model — architecture-level.** The docs name Haiku 4.5 for this role:

> **Harmlessness screens:** Use a lightweight model like Claude Haiku 4.5 to pre-screen user input before it reaches your main conversation. Use structured outputs to constrain the response to a simple classification.

**Red-team and monitor — post-hoc.**

> Regularly analyze outputs for signs of successful injection. Use this monitoring to iteratively refine your prompts, validation, and filtering strategies.

### Refusal Handling

Architecture-level, not prompt-level, but load-bearing for any long-running agent loop.

> When you receive `stop_reason`: `refusal`, you must reset the conversation context before continuing. You can remove or rephrase the turn that triggered the refusal, or clear the conversation history entirely. Attempting to continue without resetting will result in continued refusals.

> **Refusals are responses, not errors.** A refusal arrives as a successful HTTP 200 response with `stop_reason`: `"refusal"`, so monitoring built only on error rates won't surface it. Track refusals as their own signal.

Source: https://platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/handle-streaming-refusals. A5 records the v5-specific detail from the migration guide: Opus 5 refusals carry a `stop_details.category` field with values such as `"cyber"`, `"bio"`, `"reasoning_extraction"`, and a `fallbacks: "default"` mode is available in beta.

### What Is Not Covered

A4 checked all four guardrails pages and found **no mention of `temperature` or `stop_sequences`** on any of them. A1 found no statement about run-to-run consistency, determinism, or variance reduction on any Opus-5-family page. Since sampling parameters now 400-error on Sonnet 5 ([C2](#c2-sampling-parameters-are-rejected-on-sonnet-5)), the parameter-level determinism lever is gone and the docs do not replace it with a documented prompt-level equivalent for non-creative work. The one documented substitute is domain-specific: the propose-then-build pattern for design variety (D29), which Anthropic explicitly frames as the recommended replacement "because `temperature` is not accepted on Claude Sonnet 5."

## Agent And Multi-Agent Guidance

### Sub-Agent Delegation — Complete Verbatim Text, And What It Does Not Say

This is the most-misread area in the corpus, so it is quoted completely. A6 re-fetched both v5 prompting guides specifically to establish the exact boundaries of this guidance.

**The guidance exists only in the Opus 5 prompting guide.** A6 fetched the full Sonnet 5 page and found "zero occurrences of 'subagent,' 'sub-agent,' 'delegat,' or 'spawn'" across all ten of its sections. That is a confirmed negative from direct full-page inspection, not an unresearched gap.

The complete "Controlling subagent spawning" section, every sentence:

> Claude Opus 5 delegates to subagents more readily than prior models. Delegation pays off on genuinely independent, sizeable tracks of work, but it multiplies cost and time when applied to small tasks. If your harness supports subagents, give explicit guidance on which scenarios warrant delegation, or set deterministic caps on how many agents can be launched. For example:

Anthropic's example delegation policy, verbatim:

```text
Delegate to a subagent only for large tasks that are genuinely independent and parallelizable, such as a wide multi-file investigation. Do not delegate work you can finish yourself in a handful of tool calls, and do not use subagents to verify or double-check your own work. If one subagent can complete the task, use one rather than several, and keep spawn counts low.
```

And the paired capability bullet:

> **Multi-agent coordination:** Claude Opus 5 coordinates teams of subagents well, with effective writer-verifier patterns and few cases of agents overwriting each other's work. For cost-sensitive workloads, cap delegation; see Controlling subagent spawning.

Source for all three: https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-opus-5 — sections "Controlling subagent spawning" and "Capability improvements".

**No numeric cap appears anywhere in this guidance.** A6 states this plainly: the guidance is "entirely qualitative ... with the illustrative example prompt itself only saying 'keep spawn counts low' — no number is given." Any downstream claim that Anthropic's prompting guidance specifies a delegation count is unsupported. See [§ Contradictions And Ambiguities In The Sources](#contradictions-and-ambiguities-in-the-sources) for how this correction was arrived at.

Note also the clause "do not use subagents to verify or double-check your own work," which is Anthropic's example text rather than a standalone rule, and which coheres with D1/D2: the objection is to delegated re-verification specifically, not to delegation in general.

### The Only Numeric Caps Are Product-Enforced, Not Prompting Guidance

These come from the Claude Code product documentation — a different source and a different kind of guidance than the model prompting guides. They are enforced limits, not advice.

> By default, when 20 subagents are running in a session, spawning another with the Agent tool fails with `Concurrent subagent limit reached`, and the error tells Claude not to retry. Spawning succeeds again when the running count drops below the limit. To change the limit, set `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS` to any positive whole number.

> By default, Claude can spawn at most 200 subagents per session. To raise the limit, set `CLAUDE_CODE_MAX_SUBAGENTS_PER_SESSION` to any positive whole number; there is no upper bound, but the limit can't be turned off.

> By default, a subagent can spawn subagents of its own, up to three layers below the main conversation. At the depth limit, Claude Code withholds the `Agent` tool from every subagent except a fork, so a subagent at the limit does its delegated work itself and returns one summary.

Source: https://code.claude.com/docs/en/sub-agents — sections "Concurrent subagent limit", "Session subagent limit", "Let subagents spawn their own subagents". A6 records the nesting default's version history verbatim, which matters because the default has moved twice: "v2.1.172 through v2.1.216: subagents could nest by default, up to five layers deep, and the limit couldn't be changed. v2.1.217 through v2.1.218: the limit defaulted to one... v2.1.219 raised the default to three."

### Orchestrator Patterns

Anthropic's canonical architecture post distinguishes two things that are often conflated:

- **Workflows** — "systems where LLMs and tools are orchestrated through predefined code paths."
- **Agents** — "systems where LLMs dynamically direct their own processes and tool usage, maintaining control over how they accomplish tasks."

Five named workflow patterns: prompt chaining, routing, parallelization, orchestrator-workers, and evaluator-optimizer. The orchestrator-workers pattern is described as "a central LLM dynamically breaks down tasks, delegates them to worker LLMs, and synthesizes their results," where "subtasks aren't pre-defined, but determined by the orchestrator based on specific input."

The post's guardrail warning, verbatim in substance: agents require "extensive testing in sandboxed environments, along with appropriate guardrails," because "agents' autonomy means higher costs, and potential for compounding errors." Its framework advice is to "start with the API directly before frameworks" — "many patterns can be implemented in a few lines of code."

Source: https://www.anthropic.com/engineering/building-effective-agents (recorded by A5).

### Context Management Across Agents

**Context is framed as a finite resource to be curated.** The governing principle from the context-engineering post:

> find the smallest set of high-signal tokens that maximize the likelihood of your desired outcome

**System-prompt altitude.** The post's calibration test for how specific a system prompt should be: "specific enough to guide behavior effectively, yet flexible enough to provide the model with strong heuristics."

**Externalize rather than hold in context.** Agents should maintain "lightweight identifiers (file paths, stored queries, web links, etc.) and use these references to dynamically load data into context at runtime using tools" rather than keeping everything resident.

**Compaction.** Apply when approaching context-window limits; the mechanism is "summarizing its contents, and reinitiating a new context window with the summary." A named lighter alternative is "clearing tool calls and results" once they are no longer needed, described as the "safest lightest touch" approach. The stated priority order is to maximize recall first, then improve the precision of what is kept.

**Sub-agent context isolation as a token-economy pattern.** Sub-agents "explore extensively, using tens of thousands of tokens or more, but returns only a condensed, distilled summary of its work (often 1,000-2,000 tokens)," achieving "clear separation of concerns—the detailed search context remains isolated within sub-agents, while the lead agent focuses on synthesizing and analyzing the results."

Source for the above: https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents. A6 flags a sourcing caveat on this post: content was retrieved through the fetch tool's markdown-conversion-and-synthesis pipeline rather than a raw-HTML comparison, so short specific quotes (the "smallest set of high-signal tokens" line, the "1,000-2,000 tokens" figure) carry high confidence while section-heading names are reported as the pipeline gave them.

**What actually reaches a delegated sub-agent.** The mechanical version of the same fact, from the product docs, is precise enough to be load-bearing:

> A non-fork subagent's initial context contains: System prompt... Task message... CLAUDE.md files: every level of the CLAUDE.md hierarchy the main conversation loads, including `~/.claude/CLAUDE.md`, project rules, `CLAUDE.local.md`, and managed policy files. The built-in Explore and Plan agents skip this. Git status: a snapshot taken at the start of the parent session... Preloaded skills... Sibling roster...

A6 records that output style, auto memory, and the parent's actual context-window size are explicitly named as *not* propagating. Also:

> Subagents support automatic compaction using the same logic as the main conversation. Compaction triggers under the same conditions.

Sub-agent transcripts persist independently of the main conversation and are unaffected by the main conversation's own compaction. Source: https://code.claude.com/docs/en/sub-agents — "What loads at startup", "Auto-compaction".

### Long-Horizon Persistence And State Across Turns

**Structured note-taking outside the context window.** The context-engineering post's documented pattern: agents should "regularly write notes persisted to memory outside of the context window. These notes get pulled back into the context window at later times," maintaining "persistent memory with minimal overhead" across multi-step tasks.

**Re-grounding after compaction.** After summarization the agent continues "with this compressed context plus the five most recently accessed files," then reads its own notes and resumes. Source: https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents.

**State format guidance.** From the consolidated best-practices page:

> **Use structured formats for state data:** ... use JSON or other structured formats to help Claude understand schema requirements.
> **Use unstructured text for progress notes:** Freeform progress notes work well for tracking general progress and context.
> **Use git for state tracking:** Git provides a log of what's been done and checkpoints that can be restored.

Source: https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices — "State management best practices", under "Long-horizon reasoning and state tracking".

**Persistence as a model capability claim.** The Sonnet 5 announcement claims higher task-completion persistence — Sonnet 5 "finishes complex tasks where previous Sonnet models would stop short" and "checks its own output without explicitly being asked." Source: https://www.anthropic.com/news/claude-sonnet-5.

### Tool Design For Agents

> Think of how you would describe your tool to a new hire on your team.

> input parameters should be unambiguously named: instead of a parameter named `user`, try a parameter named `user_id`.

> Namespacing (grouping related tools under common prefixes) can help delineate boundaries between lots of tools.

The stated consequence of namespacing: "By selectively implementing tools whose names reflect natural subdivisions of tasks, you simultaneously reduce the number of tools... loaded into the agent's context."

On error responses: "you can prompt-engineer your error responses to clearly communicate specific and actionable improvements, rather than opaque error codes or tracebacks." The post also documents a `response_format` enum pattern letting the calling agent choose a concise or detailed tool response.

Source: https://www.anthropic.com/engineering/writing-tools-for-agents.

**The boundary-clarity test, from the context-engineering post.** This is the sharpest diagnostic in the corpus for whether a multi-agent or multi-tool decomposition is well-formed:

> If a human engineer can't definitively say which tool should be used in a given situation, an AI agent can't be expected to do better.

**Where tool instructions live is barely distinguished from the system prompt.** A6 reports that the writing-tools post "does not explicitly address this division," beyond noting that tool descriptions are "dynamically loaded into Claude's system prompt" — so functionally both compete for the same context budget. A6 records this as a genuine gap in the source rather than papering over it.

### Skills

**The description field is the highest-leverage surface**, because it is what Claude matches against to decide whether to trigger:

> Your description must provide enough detail for Claude to know when to select this Skill, while the rest of SKILL.md provides the implementation details.

> Always write in third person. The description is injected into the system prompt, and inconsistent point-of-view can cause discovery problems. Good: 'Processes Excel files and generates reports'. Avoid: 'I can help you process Excel files'. Avoid: 'You can use this to process Excel files'.

**Naming.**

> Consider using gerund form (verb + -ing) for Skill names, as this clearly describes the activity or capability the Skill provides... Avoid: Vague names: helper, utils, tools. Overly generic: documents, data, files. Reserved words: anthropic-helper, claude-tools. Inconsistent patterns within your skill collection.

Hard constraints on the same fields: `name` maximum 64 characters, lowercase letters/numbers/hyphens only, no XML tags, and cannot contain the reserved words "anthropic" or "claude"; `description` maximum 1,024 characters, non-empty, no XML tags.

**Evaluation before documentation.**

> Create evaluations BEFORE writing extensive documentation. This ensures your Skill solves real problems rather than documenting imagined ones.

A6 records the five-step process: identify gaps by running Claude without the skill, create at least three evaluation scenarios, establish a baseline, write minimal instructions, iterate.

**MCP tool references inside skills must be fully qualified** (`ServerName:tool_name`), "especially when multiple MCP servers are available," or Claude may fail to locate the tool.

Source for the above: https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices. See also D30 (only add context Claude does not already have), D32 (degrees of freedom), and the 500-line / one-level-deep structural rules in [§ Structural Conventions For Prompts](#structural-conventions-for-prompts).

**Skills versus sub-agents versus staying in the main conversation.** The one explicit decision boundary found:

> Consider Skills instead when you want reusable prompts or workflows that run in the main conversation context rather than isolated subagent context.

Source: https://code.claude.com/docs/en/sub-agents — "Choose between subagents and main conversation". A6 records the three-way split as: skills for in-context reusable workflows; sub-agents for isolated context and verbose-output containment; the main conversation for frequent back-and-forth, shared multi-phase context, and latency-sensitive quick edits.

## Emphasis And Over-Steering

**Bottom line, stated first because it will be cited: Anthropic does not take a position on ALL-CAPS, emoji emphasis, or restating instructions.** Across all seven research passes and every page fetched — two model prompting guides, the consolidated best-practices page, two "what's new" pages, the migration guide, the effort page, five guardrails pages, three engineering-blog posts, the Claude Code sub-agents doc, the Claude Code memory page, the Claude Code output-styles page, and the Agent Skills docs — no source addresses typographic or repetition-based emphasis as a technique. There is exactly one adjacent statement, and it is narrower than it is usually taken to be.

The A7 amendment searched four further official pages devoted specifically to authoring prompt-configuration artifacts and found nothing on emphasis either. That does not change this finding; it widens the evidence base for it. See finding 8 below for the one genuinely new adjacent claim A7 did contribute, which concerns *file length* and not emphasis.

Any downstream document that cites Document A as authority for "Anthropic says stop using ALL-CAPS" or "Anthropic says repetition degrades adherence" would be citing something that is not here. If emphasis practices need to change, the case has to rest on other grounds — context cost, maintainability, internal consistency, measured behavior — and this document's job is to make unmistakably clear that those grounds are not Anthropic's stated guidance.

### What The Sources Actually Say

**1. Aggressive tool-triggering language should be dialed back — the one direct statement.** This is the strongest and most-cited passage, so its scope matters:

> Claude Opus 4.5 and Claude Opus 4.6 are also more responsive to the system prompt than previous models. If your prompts were designed to reduce undertriggering on tools or skills, these models may now overtrigger. The fix is to dial back any aggressive language. Where you might have said "CRITICAL: You MUST use this tool when...", you can use more normal prompting like "Use this tool when...".

Source: https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices — "Tool usage".

Three scope limits are visible in the text itself and should not be dropped when quoting it. It is scoped to **Claude Opus 4.5 and 4.6**, not to the v5 family. It is scoped to **tool and skill triggering**, not to instruction adherence generally. And the stated failure mode is **overtriggering** — the model doing the thing too often — not degraded output quality or ignored instructions. A2 flags exactly this: the passage "is Opus-4.5/4.6-specific tool-triggering language dial-back, not a general statement about ALL-CAPS/repetition/emoji style, and is not confirmed to extend to Sonnet 5."

That said, this is the closest Anthropic comes to naming the pattern, and the before/after pair is concrete: `"CRITICAL: You MUST use this tool when..."` → `"Use this tool when..."`. Both the capitalization and the modal escalation disappear in the recommended form. What Anthropic does *not* say is which of those two changes carries the effect.

**2. Restating an instruction as a hedge is named as over-prompting.**

> Remove over-prompting. Tools that undertriggered in previous models are likely to trigger appropriately now. Instructions like "If in doubt, use [tool]" will cause overtriggering.

Source: same page — "Overthinking and excessive thoroughness". This is the nearest thing to a statement about redundant instruction, and it too is about tool triggering. It concerns a *hedging* instruction ("if in doubt") rather than restatement of the same rule in multiple places, which is a different pattern and is not addressed.

**3. Positive framing outperforms negative framing — stated three times, in three contexts.** This is the most-corroborated emphasis-adjacent finding in the corpus.

For output format, with a paired example:

> 1. **Tell Claude what to do instead of what not to do**
>    * Instead of: "Do not use markdown in your response"
>    * Try: "Your response should be composed of smoothly flowing prose paragraphs."

For agentic narration style, from the Opus 5 guide:

> Positive examples of the communication style you want tend to be more effective than instructions about what not to do.

For response concision, from the Sonnet 5 guide:

> Positive examples showing how Claude can communicate with the appropriate level of concision tend to be more effective than negative examples or instructions that tell the model what not to do.

Sources: https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices — "Control the format of responses"; https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-opus-5 — "User-facing progress updates"; https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-sonnet-5 — "Response length and verbosity".

Note carefully what this does and does not establish. It establishes that **negative-only framing is weaker than positive framing** for steering style and format. It does not establish anything about the *intensity* with which a negative instruction is expressed. A prohibition stated calmly and a prohibition stated in capitals are equally negative-framed; the sources distinguish positive from negative, not loud from quiet.

**4. Two documented cases where a prohibition produced the opposite of its intent.** These are the only mechanistic evidence in the corpus that emphasis can backfire, and both are narrow.

> If your system prompt contains a rule instructing the model not to think or not to reason, remove it; that kind of instruction increases tag leakage.

> Instructions that call out thinking tags by name are less effective than the general form, so avoid naming them specifically.

Source: https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-opus-5 — "Running with thinking disabled". The second is notable in the opposite direction from the usual intuition: *more specific* prohibition wording performs *worse* than general wording. A1 records both as "genuine 'specificity/positive-framing beats negative/named-target framing' findings" while stating plainly that "neither is a direct statement about visual/typographic emphasis devices."

**5. A before/after pair whose "less effective" side happens to be an ALL-CAPS prohibition.** This is the passage most likely to be misread as an emphasis finding:

```text
Less effective:
NEVER use ellipses

More effective:
Your response will be read aloud by a text-to-speech engine, so never use ellipses since the text-to-speech engine will not know how to pronounce them.
```

Source: https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices — "Add context to improve performance". The section is titled and framed entirely around *motivation*, not capitalization: "Providing context or motivation behind your instructions... can help Claude better understand your goals," and "Claude is smart enough to generalize from the explanation." The variable Anthropic is manipulating is the presence of a stated reason. The capitalization change from `NEVER` to `never` is incidental to the example and is never commented on. Reading this as evidence against ALL-CAPS is an over-read.

**6. Generic negative instructions can shift a default rather than remove it.** From the design context, but the mechanism generalizes:

> Generic instructions ("don't use that color," "make it clean and minimal") tend to shift the model to a different fixed palette rather than producing variety.

Source: https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-sonnet-5 — "Design and frontend defaults". A prohibition without a specified replacement moved the model to a different fixed behavior rather than achieving the intent. This is consistent with finding 3 and is the most concrete demonstration of it.

**7. Anthropic uses ALL-CAPS and negative framing in its own recommended prompts.** Worth recording because it cuts against an over-reading of the above. Anthropic's own `<frontend_aesthetics>` block, which the Sonnet 5 guide offers as a recommended system-prompt snippet, opens with capitals and a prohibition: "NEVER use generic AI-generated aesthetics like overused font families..." Its own `<use_parallel_tool_calls>` block (D24) contains "do NOT call these tools in parallel" and "Never use placeholders." A page that recommended against ALL-CAPS emphasis and modal escalation would presumably not ship example blocks that use both. This is not evidence that emphasis helps; it is evidence that Anthropic is not treating it as a variable at all.

**8. Length is documented as reducing adherence — for CLAUDE.md files specifically, and on a different axis from emphasis.** Added by the A7 amendment. This is the one genuinely new statement in this area, and its scope needs stating as carefully as its content.

> **Size**: target under 200 lines per CLAUDE.md file. Longer files consume more context and reduce adherence.

> Files over 200 lines consume more context and may reduce adherence.

> This limit applies only to `MEMORY.md`. CLAUDE.md files are loaded in full regardless of length, though shorter files produce better adherence.

> The more specific and concise your instructions, the more consistently Claude follows them.

Sources: https://code.claude.com/docs/en/memory — "Write effective instructions", "My CLAUDE.md is too large", "How it works", "CLAUDE.md vs auto memory". Recorded by A7.

What this establishes: for one named artifact class, Anthropic states a link between *file length* and *adherence* — not merely between length and cost. Every prior statement in the corpus about the harm of excess instruction was framed as cost, latency, or tool overtriggering (see the bullets below); this is the first that names adherence, and it is stated four times on the same page.

What it does **not** establish, and must not be stretched to cover:

- It says nothing about emphasis technique. ALL-CAPS, emoji, and restatement remain entirely unaddressed across all seven passes.
- It says nothing about the *number of constraints*. The stated variable is file length in lines, not rule count, rule intensity, or rule redundancy. A short file with many terse rules and a long file with few verbose ones are not distinguished by this guidance.
- It is scoped to **CLAUDE.md and memory files only**. The output-styles page and the sub-agents page each state no length guidance at all — see [§ The Two Numbers, And The Two Absences](#the-two-numbers-and-the-two-absences). Extending the 200-line adherence claim to an output style or an agent definition would be inventing a position Anthropic has not taken.
- The 200-line figure is a target, not a cap. Anthropic states in the same breath that CLAUDE.md files "are loaded in full regardless of length."

### What The Sources Do Not Say

Each item below was checked against all seven inputs and is a confirmed absence, not an unexamined area. The A7 amendment re-checked this list against four further official pages — the memory page, the output-styles page, the sub-agents page, and the two Agent Skills authoring pages — and found nothing that changes any item on it.

- **ALL-CAPS as a device.** Never discussed. The string "CRITICAL: You MUST" appears once, inside the tool-triggering passage in finding 1. No source states whether capitalization affects adherence, positively or negatively.
- **Emoji emphasis.** Never mentioned in any fetched page. A1 confirms this for all four Opus-5-family pages; A2 confirms it for the Sonnet 5, Opus 5, best-practices, and what's-new pages.
- **Repetition and restatement of the same rule across sections.** Not addressed. A2 states this precisely: literalism "means Sonnet 5 needs the scope stated explicitly at each point of application, not that repetition itself is endorsed or discouraged — the doc is silent on whether repetition helps or hurts." The over-prompting statement in finding 2 concerns a hedging instruction, not restatement.
- **`IMPORTANT` / `NEVER` / `MUST` escalation as a graded technique.** No source ranks modal strength or discusses escalation. `NEVER` appears in Anthropic's own example prompts on both sides of a before/after pair (findings 5 and 7).
- **Whether piling on constraints degrades output quality.** Not stated anywhere. A2 checked specifically and reports: "No source states that stacking many constraints/rules degrades response quality or adherence." The documented harms of redundant instruction are (a) **cost and latency** — "add cost without improving results," "adding tokens and latency" (D1, D2); (b) **overtriggering** of tools and skills (findings 1 and 2); and (c) one narrowly-scoped performance claim about leak-proofing specifically: "Attempts to leak-proof your prompt can add complexity that may degrade performance in other parts of the task" (https://platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/reduce-prompt-leak). A1 preserves this distinction deliberately: "the doc's framing is cost/efficiency degradation from redundant constraints, not a quality-degradation warning per se." **The A7 amendment does not close this gap.** Its adherence claim (finding 8 above) is keyed to CLAUDE.md *file length in lines*, not to the number, intensity, or redundancy of constraints, and it is scoped to one artifact class. No source in any of the seven passes states that stacking constraints degrades quality or adherence.
- **The direction of causation on over-steering generally.** Notably, the Opus 5 guide documents the *opposite* problem more prominently: too *few* constraints, producing scope expansion (D3). Anthropic's stated over-steering concern is confined to instructions that duplicate behavior the model already exhibits.

### Per-Input Disposition

Recorded so a reader can see that the silence was searched for rather than assumed.

| Input | Emphasis technique | Over-steering |
|---|---|---|
| A1 (Opus 5 guide + 3 companions) | NOT DIRECTLY ADDRESSED for ALL-CAPS, "IMPORTANT", "NEVER", or emoji — "never mentioned on any of the four pages." Two narrower analogous findings recorded (positive-over-negative; general-over-named). | ADDRESSED, but as cost/efficiency degradation from redundant constraints, explicitly not as quality degradation. |
| A2 (Sonnet 5 guide + 4 cross-refs) | NOT ADDRESSED anywhere in the four pages fetched. One adjacent statement found (the tool-triggering dial-back), explicitly flagged as Opus-4.5/4.6-scoped and not confirmed to extend to Sonnet 5. | NOT ADDRESSED directly or explicitly as a named phenomenon. |
| A3 (consolidated core-technique page) | Records the tool-triggering dial-back and the over-prompting statement as anti-patterns "called out by the docs." Source of the strongest available quote. | Same two statements; both scoped to tool/skill triggering. |
| A4 (guardrails family) | Not in scope; no emphasis content found. Contributes the one leak-proofing complexity/performance statement. | The leak-proofing statement is the only prompt-complexity-degrades-performance claim in the corpus, and it is narrowly scoped. |
| A5 (broader official sweep) | No emphasis findings. Records D7 (positive examples) and D16/D17 (anti-thinking rules, named tags). | No over-steering findings beyond D9/D12's cost framing. |
| A6 (orchestration, context, tools, skills) | No emphasis findings. Contributes D30 ("Does this paragraph justify its token cost?") as the nearest instruction-density principle — scoped to skill authoring. | The context-engineering framing ("smallest set of high-signal tokens") is a token-economy argument, not an adherence-degradation argument. |
| A7 (artifact-class authoring: memory, output styles, sub-agents, skills ×2) | NOT ADDRESSED on any of the five pages read in full. No ALL-CAPS, emoji, modal-escalation, or restatement guidance of any kind. Adds four further official pages to the confirmed-absence set without changing the finding. | ADDRESSED, and this is the one new contribution in this area: the memory page states four times that CLAUDE.md **length** reduces adherence, not merely cost (finding 8). Scoped to CLAUDE.md files only; says nothing about constraint count, constraint intensity, or emphasis. The output-styles and sub-agents pages state no length guidance at all. |

## Contradictions And Ambiguities In The Sources

Nine items. Some are disagreements between the research passes; some are ambiguities inside Anthropic's own documentation. Both kinds matter downstream, so both are recorded.

### 1. Delegation capping — A5 versus A6, resolved in A6's favor

**The disagreement.** A5's "Agent Architecture Guidance" section is titled "From the Opus 5 and Sonnet 5 prompting guides" and presents delegation-capping guidance (its D4 and D11) under that heading, which reads as though both guides contain it. A6 re-fetched both full pages specifically to check, and found that the Sonnet 5 guide "contains no section, heading, or sentence about subagents, delegation, or spawn caps at all" — zero occurrences of "subagent," "sub-agent," "delegat," or "spawn" across its ten sections.

**Resolution: A6 wins.** A6 verified by direct full-page inspection; A5 summarized. This document carries A6's narrower framing throughout: the delegation guidance is Opus-5-only. A6 also notes, fairly, that A5's individual citations were themselves always sourced to the Opus 5 guide — the overreach was in the section grouping, not in A5's quotes, which A6 confirmed were "accurate and complete."

**A second, separate correction in the same area: no numeric cap exists.** A numeric delegation cap was specifically looked for and not found. Anthropic's prompting guidance is entirely qualitative — "set deterministic caps on how many agents can be launched" and "keep spawn counts low," with no digit anywhere. The only numeric caps in official material are the Claude Code product limits (20 concurrent, 200 per session, 3 nesting layers), which are a different kind of artifact entirely: enforced product limits rather than prompt-text advice. This is recorded because a downstream reader needs to know the search was performed and came back empty, rather than assuming the number is somewhere in the docs and simply was not extracted.

### 2. Tokenizer increase — two different figures from two official pages

The Sonnet 5 prompting guide and the "what's new" page both say "approximately 30% more tokens for the same text." The launch announcement gives a range of roughly 1.0–1.35x (A5's reading of https://www.anthropic.com/news/claude-sonnet-5). These are compatible — 30% sits inside the range — but a reader planning budgets should know the docs give a point estimate while the announcement gives a spread, and that both pages caveat it with "the exact increase depends on the content and workload shape." Neither is wrong; do not cite the 30% figure as a precise multiplier.

### 3. A Sonnet-5 migration-guide anchor that does not resolve

A2 made three separate attempts against https://platform.claude.com/docs/en/about-claude/models/migration-guide — full-page extraction, a targeted anchor fetch for `#migrating-from-claude-sonnet-4-6-to-claude-sonnet-5`, and a full heading enumeration — and found no Sonnet-specific section. It enumerated 36 H3 headings, covering only Fable 5/Mythos 5 paths and five Opus 5 paths. Both the Sonnet 5 prompting guide and the best-practices page link to that exact anchor.

A2 explicitly declines to call this a broken link, since the fetch tool may have rendering or length limits on a very large multi-model page. A web-search cross-check returned only content matching the "what's new" page's own migration subsection, not new content. **Status: unresolved.** The authoritative Sonnet-5 migration content used in this document is the "Migration guide" subsection of https://platform.claude.com/docs/en/about-claude/models/whats-new-sonnet-5, which A2 captured in full.

### 4. Anthropic's own prefill guidance contradicts itself within single pages

Both https://platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/increase-consistency and https://platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/reduce-prompt-leak still present prefill as a live technique in their body text — "Prefill the `Assistant` turn with your desired format. This trick bypasses Claude's friendly preamble and enforces your structure" — and then override themselves with an inline note that it 400-errors on Claude 4.6+. A reader skimming either page's technique list will pick up dead advice. The override is authoritative; the body text is stale.

### 5. "Drop-in compatible" versus a two-breaking-change, nine-item migration checklist

The Opus 5 prompting guide says "It performs well out of the box on existing Claude Opus 4.8 prompts," and the Sonnet 5 material calls Sonnet 5 "a drop-in replacement for Claude Sonnet 4.6." The migration guide simultaneously documents two breaking changes and a nine-item checklist for Opus 5, and the Sonnet 5 migration content lists three breaking changes.

This is a framing ambiguity rather than a factual conflict: the compatibility claims are about *prompt text*, and the breaking changes are about *API parameters*. But the two claims sit on pages that link to each other without reconciling, and A1 flags the risk explicitly — the compatibility framing is a signal about how aggressively to rewrite, and it should not be read as "nothing needs to change."

### 6. Self-check instructions: endorsed generally, prohibited for Opus 5

The best-practices page states both positions in one passage: "Ask Claude to self-check... This catches errors reliably, especially for coding and math. Claude Opus 5 is the exception." So a self-check instruction is recommended for Sonnet 5 and prohibited for Opus 5. The ambiguity is that Sonnet 5's own guide never addresses verification instructions either way — it says only that Sonnet 5 "will ... run self-verification loops more readily" than 4.6. A2 records this as an asymmetry and a documentation gap, not a resolved position: "Whether Sonnet 5 needs the same treatment is not addressed either way on its own page." Any harness spanning both tiers has to make an undocumented choice here.

### 7. Opposite effort postures for the two v5 tiers

Opus 5: "use `low` and `medium` liberally as your primary control for token cost and response time wherever quality holds." Sonnet 5: "on moderately complex tasks running at `low` effort there is some risk of under-thinking," and "raise effort to `high` or `xhigh` rather than prompting around it."

Not a contradiction — different models, different documented risk profiles. It becomes an ambiguity the moment a single effort policy is applied across both tiers, because the two guides point in opposite directions at the same nominal setting. A2 flags this as directly consequential for any architecture that pairs an Opus coordinator with Sonnet workers.

### 8. Delegated verification: discouraged in one place, praised in another

Anthropic's example delegation policy says "do not use subagents to verify or double-check your own work." The capability bullet two sections earlier praises Opus 5 for "effective writer-verifier patterns" in multi-agent coordination. A6 flags this as "a point of interpretation, not a contradiction" — the plausible reading is that the prohibition targets a sub-agent re-checking the *same* work the parent just did, while writer-verifier refers to a structurally distinct review role. Anthropic does not draw that line itself, so the boundary is genuinely ambiguous.

### 9. Manual chain-of-thought is recommended in exactly the scenario where its tags leak

The best-practices page recommends manual CoT as a fallback "when thinking is off," using "structured tags like `<thinking>` and `<answer>` to cleanly separate reasoning from the final output." The Opus 5 guide documents that with thinking disabled, "the model can emit `<thinking>` tags or other internal XML tags into its visible response," and prescribes an instruction against internal tags (D19) as the mitigation. So the one condition under which manual `<thinking>`-tag CoT is recommended is the same condition under which `<thinking>` tag leakage is a documented artifact, and the recommended mitigation for the artifact is an instruction that would suppress the technique. Neither page acknowledges the other. Unresolved.

### Items Checked And Found Not To Conflict

- **A3's HTTP 404 on `prompt-engineering/increase-consistency` versus A4's live `test-and-evaluate/strengthen-guardrails/increase-consistency`.** Looks like a conflict; is not. A3 used the old path as a deliberate control to prove the core-technique pages were *merged* rather than *deleted*; A4 found the page alive at its new home. Both are correct and together they establish the relocation.
- **Directive numbering across inputs.** A1 extracted 22 Opus-5-family directives; A5 itemized 18 from the same guide. Different granularity and different page scope (A1 included three companion pages), not disagreement about content. A1 and A5 quotes agree verbatim where they overlap.
- **`keep-claude-in-character` as a standalone page.** A search snippet titles it as one; two independent direct fetches returned the `increase-consistency` body byte-for-byte. A4 trusted the fetches over the snippet. This document follows that resolution.

## Coverage Gaps

What this document does not cover, and why. The downstream gap analysis should treat every item here as a boundary on what Document A can be cited for.

### Input Files

All six research inputs were present, non-empty, and read in full before writing: `.scratchpad/A1-opus5-guide.md` (380 lines), `.scratchpad/A2-sonnet5-guide.md` (451), `.scratchpad/A3-core-techniques.md` (314), `.scratchpad/A4-reliability.md` (278), `.scratchpad/A5-official-sources.md` (170), `.scratchpad/A6-agent-orchestration.md` (174). No input was missing or visibly truncated mid-section. **No content in this document was invented to fill an input-file gap.**

Note that the originating card listed five inputs; A6 was added after the card was written. A6 is incorporated throughout and supersedes A5 where the two conflict (see contradiction 1).

A seventh input, `.scratchpad/A7-authoring-guidance.md` (391 lines), was added by amendment after the original synthesis was written. It was present, non-empty, and read in full before any edit was made, and no content attributed to it was invented. A7's contribution is confined to [§ Authoring Guidance By Artifact Class](#authoring-guidance-by-artifact-class), directives D33–D46, finding 8 and the A7 row in [§ Emphasis And Over-Steering](#emphasis-and-over-steering), the additions recorded in this section, and the A7 group in [§ Source Bibliography](#source-bibliography). See [§ Amendment Log](#amendment-log).

### Gaps Closed By The A7 Amendment

**Official documentation on authoring CLAUDE.md / project-instruction files — now closed.** The original synthesis recorded this as its most material gap, in these terms: A5 "states plainly that this area was 'not searched for in this pass at all. No coverage claim of any kind should be inferred.' A6 did not cover it either," and the consequence was that "the artifacts most likely to be rewritten downstream are exactly project-instruction files, and this document contains no Anthropic guidance specifically about that artifact class."

A7 closed it. Anthropic does have a dedicated page — https://code.claude.com/docs/en/memory — and it carries an explicit 200-line target, structure and specificity and consistency directives, a what-belongs boundary, an import mechanism with stated context economics, and a statement that CLAUDE.md is not part of the system prompt and carries no compliance guarantee. All of it is quoted in [§ CLAUDE.md And Memory Files](#claudemd-and-memory-files) and catalogued as D33–D39.

Two boundaries on that closure remain in force:

- **The original warning against generalizing the skill-authoring guidance still stands.** The 500-line body, 1,024-character description, one-level-deep reference, degrees-of-freedom, and instruction-density rules govern skill files. A7 confirms CLAUDE.md has its own separate and differently-worded guidance, so the two must not be merged.
- **A7 found no separate authoring *tutorial*.** Its two searches "surfaced the same single canonical page rather than a separate authoring guide," so the memory page "serves both as reference and as the de facto authoring guide." There is no second, more prescriptive page waiting to be found.

### Sources That Could Not Be Reached

**The Claude Opus 5 and Claude Sonnet 5 system cards / model cards were not read.** This is the largest single gap in the corpus. A5 located the Sonnet 5 system card as an official PDF on `www-cdn.anthropic.com`, dated 2026-06-30, reported at 145 pages. A6 attempted to fetch and process it and the attempt failed because the file is approximately 15.6MB, which exceeded the available tool and context budget. Per explicit instruction the PDF was not re-attempted in this pass either. **No third-party summary was substituted.** Any prompting-relevant behavioral characterization in the system cards — instruction following, verbosity, tool use, reasoning depth, refusal behavior, agentic persistence, context handling, and any published eval methodology — is therefore unverified here. Closing this gap requires either a dedicated pass with page-range PDF extraction or an official non-PDF mirror, which A6 notes was not searched for and is therefore an unknown rather than a confirmed absence.

**Claude Fable 5 and Claude Mythos 5 launch announcements and prompting guidance.** Both models are confirmed to exist as officially-named, currently-shipping models above Opus in the lineup, via the effort page's per-model tables (A5). Their dedicated announcement pages were not located. A1 saw a link to `prompting-claude-fable-5` and deliberately did not follow it as out of scope. If either model becomes relevant, none of this document's model-specific directives can be assumed to apply to it.

**Claude Haiku 4.5 prompting guidance.** Not sought by any pass. Since there is no Haiku 5, and the lightweight tier remains Haiku 4.5, any guidance for that tier is outside this document entirely. The only Haiku mention in the corpus is the guardrails page naming Haiku 4.5 as a pre-screening model.

**The Sonnet-5 migration-guide anchor.** Unresolved after three fetch attempts — see contradiction 3.

**Claude Code release notes and changelog filtered to v5 entries.** A5 identified this as unsearched. Not attempted in any pass. Any v5-related product behavior change documented only in release notes is uncovered.

**Anthropic's multi-agent research system post.** Identified by A5 via search but never fetched by any pass.

**The Claude Code hooks documentation (`/docs/en/hooks`, `/docs/en/hooks-guide`).** Named by A7 as deliberately not attempted: "No search or fetch was attempted against `/docs/en/hooks` or `/docs/en/hooks-guide` despite PreToolUse hooks being cited as the answer to repository question 6 — that citation rests entirely on the memory page's own cross-references to hooks ('use a PreToolUse hook instead'), not on independently fetching the hooks documentation itself." D39 therefore rests on the memory page, not on the hooks pages. Anything the hooks documentation says about hook authoring, event types, matcher semantics, or handler types is uncovered by this document.

**Parts of https://code.claude.com/docs/en/skills.** A7 read two ranges of the persisted page and names the ranges it did not read line by line: "Bundled skills," "Getting started," "Where skills live" (covered only via a search-result summary, not verbatim-quoted), "Restrict Claude's skill access," "Evaluate and iterate," "Share skills," "Generate visual output," and "Troubleshooting." A7 states that "no directive was extracted from these unread ranges, and none is claimed."

**The Agent Skills overview page** (https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview) was fetched by A6 but not independently re-fetched by A7, which relied on the best-practices page's own restatement of the frontmatter rules. Cross-referenced repeatedly by the best-practices page for "complete Skill structure details."

**CLI-flag and Agent SDK subagent definition paths.** A7 saw both on the sub-agents page and explored neither beyond a frontmatter-field-parity statement, having scoped itself to file-based Markdown+YAML definitions.

### Questions The Documentation Does Not Answer

These are not research failures. The official documentation simply does not address them.

- **Is there a recommended maximum prompt length?** Not for a system prompt, an output style, or an agent-definition body. *Amended:* two artifact classes do have numeric guidance — CLAUDE.md files ("target under 200 lines", D33) and skill files (500-line body). See [§ The Two Numbers, And The Two Absences](#the-two-numbers-and-the-two-absences) and [§ Structural Conventions For Prompts](#structural-conventions-for-prompts).
- **Where should critical instructions go inside a system prompt?** Not addressed by any source. The 30-percent long-context finding is about data placement, not instruction placement, and A1 and A2 both verified the distinction independently.
- **Do ALL-CAPS, emoji, or repeated restatement help or hurt?** Not addressed. See [§ Emphasis And Over-Steering](#emphasis-and-over-steering), which documents the confirmed absence at length.
- **Does adding many constraints degrade output quality?** Not stated. The documented harms are cost, latency, and tool overtriggering.
- **How do you get run-to-run consistency on non-creative work now that sampling parameters are rejected?** Unanswered. The guardrails pages never mention `temperature` or `stop_sequences`; the one documented substitute (propose-then-build) is design-specific.
- **Did v5 change default parallel-versus-sequential tool-calling behavior?** A1 found no statement either way on any Opus-5 page. The parallel-tool guidance in D24 is cross-model and not v5-specific.
- **Does Sonnet 5 over-delegate to nested sub-agents?** Confirmed unaddressed — the Sonnet 5 guide has no subagent content at all. Relevant to any design with nested delegation.
- **How much instruction belongs in a tool definition versus the system prompt?** A6 reports the writing-tools post "does not explicitly address this division." Functionally both compete for the same budget, since tool descriptions are injected into the system prompt.

The following were added by the A7 amendment. Every one of them is a **coverage fact about Anthropic's documentation**, established by reading the relevant page rather than by failing to find one. A downstream gap analysis needs each of these to know which of its proposed changes can and cannot cite official authority.

- **How long should an output style be?** **Not addressed by official documentation.** A7 read https://code.claude.com/docs/en/output-styles in full and found "zero line-count, KB, or token-budget guidance for the instruction body," with the page discussing token cost only qualitatively. There is no ceiling to exceed and no endorsement of length either. A length-based argument about an output style cannot cite Anthropic in either direction.
- **How long should an agent definition's markdown body be?** **Not addressed by official documentation.** A7 read https://code.claude.com/docs/en/sub-agents in full: "no line-count, KB, or token-budget guidance for a subagent's markdown-body system prompt is stated anywhere on this page."
- **Is there a dedicated official CLAUDE.md authoring tutorial, separate from the reference page?** No. A7 ran two searches and both "surfaced the same single canonical page rather than a separate authoring guide."
- **Which `description` character limit governs a skill — 1,024 or 1,536?** Unreconciled. The Agent Skills standard caps `description` at 1,024 characters; Claude Code states the combined `description` + `when_to_use` listing text "is truncated at 1,536 characters." A7 found no single official page reconciling the two and flagged it "rather than silently resolved." Recorded here rather than in [§ Contradictions And Ambiguities In The Sources](#contradictions-and-ambiguities-in-the-sources) so that section's nine-item numbering is not disturbed by the amendment.
- **Are ordinary markdown-link references from an output style body auto-injected, or read on demand?** **Not addressed by A7 at all.** A7's answer on file-splitting enumerates four mechanisms — CLAUDE.md `@path` imports, CLAUDE.md path-scoped rules, skill supporting files, and agent definitions — and output styles appear in none of them. The output-styles page contains no reference-or-import mechanism discussion of any kind. The "imports do not reduce context" finding (D37) is specific to the CLAUDE.md `@path` syntax and **must not be extended** to ordinary markdown links in any other artifact class; doing so would attribute to Anthropic a claim it has not made about a mechanism its documentation does not discuss. See the scope limit at the end of [§ Splitting Content Across Files](#splitting-content-across-files--which-mechanisms-reduce-context-and-which-do-not).
- **What do the hooks pages say about authoring hooks?** Uncovered. A7 cited PreToolUse hooks as the documented enforcement mechanism (D39) on the strength of the memory page's cross-reference, and deliberately never fetched the hooks documentation itself.

### Sourcing Caveats On What Is Included

- **The context-engineering blog post** was retrieved through the fetch tool's markdown-conversion-and-synthesis pipeline rather than a raw-HTML comparison. A6 flags that short specific quotes carry high confidence while section-heading names are reported as the pipeline gave them. Quotes from that post in this document inherit that caveat.
- **D32 (degrees of freedom) is a paraphrase, not a verbatim quote.** A6 recorded it as a paraphrase of a three-level framework with a "narrow bridge vs. open field" analogy. This document preserves it as a paraphrase and labels it as such rather than manufacturing quotation marks around it.
- **Several directives are corroborated by a second page rather than a second independent source.** Where the migration guide restates the prompting guide's own text, A1 labels that as cross-reference rather than independent corroboration. That distinction is preserved.
- **Page dates are mostly unavailable.** The `platform.claude.com` documentation pages carry no visible publication or revision date. All were fetched 2026-07-27. Announcement pages are dated (Sonnet 5: 2026-06-30; Opus 5: 2026-07-24).

### Deliberately Out Of Scope

This document does not diagnose this repository, does not compare Anthropic's guidance against any file in it, and does not propose any change. Those are separate documents by design — a gap analysis, an adversarial verification, and an implementation plan. Every "Implications For Our Repo" section in the six input files was read and deliberately not carried forward. Document A's usefulness as a citation base depends on it containing nothing but what Anthropic says.

## Source Bibliography

Grouped by the research input that fetched each source. All URLs are the current ones as of 2026-07-27 — historic pre-reorganization URLs are deliberately excluded (see [C15](#c15-the-documentation-itself-was-reorganized--cite-current-urls)). Pages fetched by more than one input are listed under the input that extracted the most from them, with cross-references noted.

### From `.scratchpad/A1-opus5-guide.md`

- https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-opus-5 — the Opus 5 prompting guide. Primary source for D1–D10, D14, D18–D21, D27 and the delegation guidance. Also fetched by A2, A5, A6.
- https://platform.claude.com/docs/en/about-claude/models/whats-new-opus-5 — Opus 5 capability, API, and behavior-change summary. Source of the bundled "Model behavior differences" paragraph and the `max_tokens` guidance.
- https://platform.claude.com/docs/en/about-claude/models/migration-guide — Opus 5 migration path from Opus 4.8: two breaking changes, six recommended changes, nine-item checklist, and the paired thinking/effort code example. Also probed by A2 and A5.
- https://platform.claude.com/docs/en/build-with-claude/effort — the effort-parameter reference, with consecutive per-model recommendation subsections for Opus 4.7, 4.8, and 5. Source of the clearest before/after in the corpus (C13). Also fetched by A5.

### From `.scratchpad/A2-sonnet5-guide.md`

- https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-sonnet-5 — the Sonnet 5 prompting guide. Primary source for D8, D9, D11, D15, D17, D23, D26, D28, D29. Also fetched by A5 and A6.
- https://platform.claude.com/docs/en/about-claude/models/whats-new-sonnet-5 — Sonnet 5 capability specs, the three breaking changes, the new tokenizer, and the authoritative three-item Sonnet 5 migration subsection.
- https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices — the consolidated cross-model living reference. Also the primary source for A3; see below.

### From `.scratchpad/A3-core-techniques.md`

- https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices — the single consolidated core-technique page that replaced eight historic per-technique pages. Primary source for D4, D12, D13, D24, D25, all of [§ Structural Conventions For Prompts](#structural-conventions-for-prompts), the prefill deprecation, and the emphasis dial-back quotes.
- https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/overview — the section index, which confirms the consolidation ("That's the living reference; start there"). Also fetched by A4.
- Historic URLs redirect-tested by A3 to establish the consolidation, all resolving to the consolidated page: `prompt-engineering/be-clear-and-direct`, `prompt-engineering/chain-of-thought`, `prompt-engineering/long-context-tips`, `prompt-engineering/use-xml-tags`. Two out-of-family controls returned HTTP 404 (`prompt-engineering/increase-consistency`, `prompt-engineering/mitigate-jailbreaks`), which is what distinguishes merge from deletion. Cited here as method, not as content sources.

### From `.scratchpad/A4-reliability.md`

- https://platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/reduce-hallucinations — the seven hallucination-reduction techniques and Anthropic's own non-guarantee caveat.
- https://platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/increase-consistency — output-consistency techniques, the Structured Outputs redirect, and the embedded "Keep Claude in character" subsection.
- https://platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/mitigate-jailbreaks — direct and indirect prompt-injection defense, including the untrusted-content channel rules.
- https://platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/reduce-prompt-leak — prompt-leak strategies and the one statement in the corpus that added prompt complexity can degrade task performance.
- https://platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/handle-streaming-refusals — `stop_reason: "refusal"` handling and the context-reset requirement.
- https://platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/keep-claude-in-character — fetched twice; returns the `increase-consistency` body. Recorded as not a standalone page.

### From `.scratchpad/A5-official-sources.md`

- https://www.anthropic.com/news/claude-opus-5 — Opus 5 launch announcement, 2026-07-24. Source of the 26%-fewer-tokens claim and the mid-conversation tool-change capability.
- https://www.anthropic.com/news/claude-sonnet-5 — Sonnet 5 launch announcement, 2026-06-30. Source of the persistence, hallucination-rate, and sycophancy claims, and the 1.0–1.35x tokenizer range.
- https://www.anthropic.com/engineering/building-effective-agents — Anthropic's canonical agent-architecture post: the workflow-versus-agent distinction, five workflow patterns including orchestrator-workers, and the guardrail and framework advice.
- https://www.anthropic.com/news/claude-haiku-4-5 — cited for the negative result. A5's search for a "Claude Haiku 5" returned nothing; Haiku 4.5, released 2025-10-15, remains the lightweight tier.
- Sonnet 5 System Card (official PDF on `www-cdn.anthropic.com`, 2026-06-30, ~145 pages) — located but never fetched. Listed for traceability only; **no claim in this document rests on it.** See [§ Coverage Gaps](#coverage-gaps).

### From `.scratchpad/A6-agent-orchestration.md`

- https://code.claude.com/docs/en/sub-agents — the highest-value single source in the corpus for agent mechanics: the three product-enforced numeric caps and their version history, the exact contents of a fresh sub-agent's startup context, sub-agent auto-compaction behavior, and the skills-versus-sub-agents decision boundary.
- https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents — context as a finite resource, the smallest-high-signal-token-set principle, compaction and note-taking patterns, the sub-agent token-economy figures, and the tool-boundary clarity test. Carries A6's fetch-pipeline sourcing caveat.
- https://www.anthropic.com/engineering/writing-tools-for-agents — tool naming, namespacing, parameter naming, `response_format`, and actionable error responses.
- https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices — skill description and naming rules with hard field limits, the 500-line body guideline, the one-level-deep reference rule, instruction-density guidance, degrees of freedom, evaluation-first development, and MCP tool-reference qualification.
- https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview — Agent Skills overview, fetched alongside the best-practices page.
- Opus 5 and Sonnet 5 system cards — attempted and abandoned at ~15.6MB. Recorded as an honest gap, with no substitute source used.

### From `.scratchpad/A7-authoring-guidance.md`

Added by amendment. A7's scope was official Anthropic hosts only — `docs.claude.com`, `code.claude.com`, `platform.claude.com`, `anthropic.com`, and the `anthropics` GitHub organization.

- https://code.claude.com/docs/en/memory — "How Claude remembers your project." The single most productive source in the A7 pass and the only official page covering CLAUDE.md authoring. Primary source for D33–D39: the 200-line target, the structure/specificity/consistency triad, the what-belongs boundary, `@path` import semantics, load order and concatenation, HTML-comment stripping, the `/doctor` trim policy, the "delivered as a user message after the system prompt" mechanism, and the hooks-and-settings enforcement redirect. Read in full in a single fetch, no truncation.
- https://docs.claude.com/en/docs/claude-code/memory — the pre-redirect URL for the page above. Recorded because it is the URL most external material cites; it redirects to `code.claude.com/docs/en/memory`, and the resolved target is what A7 fetched and what this document cites.
- https://code.claude.com/docs/en/output-styles — "Output styles." Primary source for D40 and D41: the system-prompt-modification mechanism, the `keep-coding-instructions` choice, the CLAUDE.md-substitution warning, the frontmatter field list, the main-conversation-only scope with the fork exception, the session-start/`/clear` timing, the qualitative token-cost statement, and the four-way comparison table. Read in full in a single fetch. **Also the source of a confirmed absence**: no length guidance of any kind.
- https://code.claude.com/docs/en/sub-agents — re-fetched independently by A7 (also A6's highest-value source; see above). A7 contributes the frontmatter field list with only `name` and `description` required, the absence of any documented `mcp:` field, the `description`-as-routing-signal quotes and worked examples, the three authoring best practices (D42, D43), the message-authority statement, the `model` alias list, storage precedence, and the full not-inherited enumeration merged into D31. **Also the source of a confirmed absence**: no length guidance for a subagent's markdown body. Read in full across two Read calls on a persisted 1,235-line tool result.
- https://code.claude.com/docs/en/skills — "Extend Claude with skills." Claude-Code-specific skill frontmatter (including the 1,536-character listing truncation), the third occurrence of the 500-line limit, supporting-file referencing, `disable-model-invocation` / `user-invocable` (D44), `context: fork` and the fork-versus-preload comparison, and storage locations. Read in two ranges of a persisted page; the unread ranges are named in [§ Coverage Gaps](#coverage-gaps) and no directive is claimed from them.
- https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices — re-fetched independently by A7 (also cited under A6). A7 contributes the two further occurrences of the 500-line limit, the frontmatter character limits, the third-person description rule with its Good/Avoid pairs, the vague-description examples, the progressive-disclosure and runtime-environment quotes including "No context penalty for large files," the nested-reference anti-pattern, the three content anti-patterns (D46), the evaluation-first imperative, and the per-tier testing guidance (D45).

A7 logged twelve third-party sources encountered during its searches — `medium.com/@codecentrevibe`, `cuong.io/blog`, `maketocreate.com`, `productbuilder.net`, `claudecode101.com`, `shareuhack.com`, `claudelog.com`, `blog.laozhang.ai`, `joseparreogarcia.substack.com`, `hidekazu-konishi.com`, `github.com/VoltAgent/awesome-claude-code-subagents`, `codewithmukesh.com` — and extracted no directive from any of them. It also encountered two domains that mirror official documentation under non-Anthropic hosts, `cld-docs.onlinetool.cc` and `claude-wiki.com`, and deliberately neither fetched nor cited either. No claim in this document traces to any of them.

### Sources Deliberately Not Used

A5 logged five third-party sources surfaced during its sweep — `tech-ish.com`, `emergent.sh`, `simonwillison.net`, `thenewstack.io`, `handyai.substack.com` — and used none of them for directive extraction. This document uses none of them either. Every quote above traces to an `anthropic.com`, `platform.claude.com`, or `code.claude.com` page fetched on 2026-07-27.

## Amendment Log

Recorded so a later reader can separate the original synthesis from what was added afterward.

### Amendment 1 — 2026-07-27 — artifact-class authoring guidance

**Driven by:** `.scratchpad/A7-authoring-guidance.md` (391 lines), a gap-fill research pass over official Anthropic guidance on authoring the four prompt-configuration artifact classes in this repository. A7 was commissioned because the original synthesis flagged its own largest gap: it contained no Anthropic guidance about project-instruction files, which is the artifact class a downstream migration targets first.

**Added:**

- A new top-level section, [§ Authoring Guidance By Artifact Class](#authoring-guidance-by-artifact-class), placed immediately after [§ Structural Conventions For Prompts](#structural-conventions-for-prompts) as the continuation of that material. It carries a per-class subsection for CLAUDE.md and memory files, output styles, agent definitions, and Agent Skills, plus two cross-cutting subsections: one on which file-splitting mechanisms actually reduce context, and one on enforcement beyond prompt text.
- Fourteen directives, D33–D46, all scoped to artifact-class authoring rather than model prompting.
- Finding 8 in [§ Emphasis And Over-Steering](#emphasis-and-over-steering), plus an A7 row in that section's per-input disposition table.
- A [§ Gaps Closed By The A7 Amendment](#gaps-closed-by-the-a7-amendment) subsection, six new entries under "Questions The Documentation Does Not Answer," five new entries under "Sources That Could Not Be Reached," and an A7 entry under "Input Files" — all in [§ Coverage Gaps](#coverage-gaps).
- An A7 group in [§ Source Bibliography](#source-bibliography) listing six official URLs and A7's twelve unused third-party sources plus two deliberately-unfetched mirror domains.
- A pointer sentence in the Executive Summary.

**The four findings the amendment exists to carry:**

1. **CLAUDE.md has an official 200-line target** (https://code.claude.com/docs/en/memory) — the most actionable number in the corpus, because it governs the artifact class a migration touches first. It is a target tied to adherence, not an enforced cap.
2. **Agent Skills have an explicit 500-line cap**, stated three times across two official pages. Document A already carried this figure via A6; A7 corroborated it from a second host.
3. **Output styles have no official length guidance** — a confirmed absence from a full-page read.
4. **Agent-definition bodies have no official length guidance** — likewise a confirmed absence from a full-page read.

Findings 3 and 4 are recorded as documented absences in the same register this document already uses for Anthropic's silence on emphasis. Their consequence is stated explicitly rather than left implicit: a length-based argument about an output style or an agent definition has no official authority to cite in either direction.

**The mechanism finding, stated separately because collapsing it is expensive:** CLAUDE.md `@path` imports do **not** reduce context — imported files load at launch — while Agent Skills' supporting files **do**, carrying no context cost until read. A plan that tried to shrink an always-injected CLAUDE.md by relocating content into `@`-imports would achieve nothing and believe it had succeeded. The finding is scoped to the CLAUDE.md `@path` syntax and is explicitly *not* extended to ordinary markdown-link references from any other artifact class; A7 does not address that case at all, and the amendment says so rather than generalizing.

**What the amendment did not change:**

- **The emphasis finding stands untouched.** A7 found no guidance on ALL-CAPS, emoji, modal escalation, or restatement across five further official pages. That was recorded as another input finding nothing, which widens the evidence base for the existing conclusion rather than altering it. A7's one new adjacent claim concerns file length, on a different axis, and is explicitly marked as not closing the constraint-stacking gap.
- **No change was proposed to this repository.** Document A remains a statement of what Anthropic says. Diagnosis and planning stay in separate documents.
- **The nine-item numbering in [§ Contradictions And Ambiguities In The Sources](#contradictions-and-ambiguities-in-the-sources) was left alone.** A7 surfaced one genuine documentation ambiguity — the 1,024-versus-1,536 skill `description` limits — and it is recorded under "Questions The Documentation Does Not Answer" instead, to avoid renumbering a section other documents may already cite.
- **Nothing was removed except the one gap A7 closed.** The retired "no CLAUDE.md authoring guidance" gap was not deleted outright; its original wording is preserved inside the closed-gap subsection so the history stays legible.

**Three statements were corrected because A7's evidence made them stale**, each marked *Amended* in place: the "Total prompt length" bullet in [§ Where The Sources Are Silent](#where-the-sources-are-silent), the "Prompt length: no general guidance exists" paragraph in [§ Structural Conventions For Prompts](#structural-conventions-for-prompts), and the "Is there a recommended maximum prompt length?" bullet in [§ Coverage Gaps](#coverage-gaps). All three asserted that skill files were the only artifact class with numeric length guidance, which the 200-line CLAUDE.md target makes false. The corrections narrow the claim to the classes where the absence still holds and name the two classes where a number now exists.

**One pre-existing defect was observed and deliberately left as found:** the "Total prompt length" bullet's original cross-reference pointed the 500-line and 1,024-character figures at "D28 and D30," which do not carry them (they live in [§ Structural Conventions For Prompts](#structural-conventions-for-prompts) and now also in [§ Agent Skills](#agent-skills)). The amendment's rewrite of that bullet replaced the broken pointer with section links; no other stale cross-reference elsewhere in the document was hunted down, since that was outside the amendment's scope.
