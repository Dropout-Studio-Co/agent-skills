---
name: review-loop
description: Independent, evidence-backed, model- and harness-agnostic review of a finished change before it lands, following the global Review standard (risk tier, verification, parallel finders, finding verification, severity, three-round cap, diff-only follow-ups, dedup). Use after implementing anything non-trivial, before commit/push/merge, or when asked to review a diff, branch or PR.
---

# Review loop

Owner of the procedure behind the Review section of `~/.agents/policies/engineering-principles.md`.
Repo `REVIEW.md` and AGENTS rules win on detail. Composes existing skills; does not replace them.

## 1. Pin and classify

- Pin the candidate: `base=$(git merge-base origin/<default> HEAD)`, `head=$(git rev-parse HEAD)`.
  Review exactly `git diff $base...$head` (plus uncommitted work if it will ship).
- Tier from the change: Low, Medium or High (Review standard). Any path listed as sensitive in the
  repo's `REVIEW.md` or CODEOWNERS is High.
- Read `REVIEW.md` if present; it defines what failure means, what to skip and the report format.
  Built-in review commands (for example Claude Code's `/code-review`) may not load `REVIEW.md`, so
  always hand `REVIEW.md` to every finder explicitly. If the repo ships a tier script (Horcrux:
  `bun run review:tier`), use its result as the floor.

## 2. Verify before reviewing

Run the repo's own checks (lint, types, tests, build; migrations when schema changed) and, for UI or
user flows, exercise the behavior. Keep the exact commands and results. For Medium and High, run a
simplification pass on the diff first (a harness simplify command where available; otherwise ask for
reuse/dead-code/over-abstraction cleanups only) so reviewers judge the final shape. A red check is a finding;
do not spend reviewer tokens on a candidate that fails its own checks.

## 3. Find (fresh context, parallel only when the tier warrants)

| Tier   | Finders                                                                                              |
| ------ | ---------------------------------------------------------------------------------------------------- |
| Low    | Self-review of the diff against REVIEW.md.                                                           |
| Medium | One independent reviewer on correctness, regressions and the whole REVIEW.md failure list.           |
| High   | Independent finder (correctness, architecture vs owning contracts, regressions, whole failure list) + separate independent security pass over the whole failure list, as an attacker would (e.g. `security-review`). |

Model- and harness-agnostic, within the session's routing: use whichever agent and model the session
already has (Claude Code, OpenCode or another; never Codex CLI, Pi or a GPT model, all retired; a repo may restrict
this to an approved list). **When the execution protocol applies, its routing wins** (`~/.agents/skills/execution-protocol/SKILL.md`): every gate runs only through its `scripts/gate.sh`, on the reviewer its steps 1 and 7 define; this skill names no gate model. Outside that protocol, any model or
harness the session already has may review, and no model, provider, harness, plugin, paid subscription
or external review service is ever a review gate; a different model is welcome, never required.

**Independent** = a reviewer that did not write the change, in a fresh context: a separate subagent,
a new session in the same or another harness, or an equivalent isolated process. A forked or
context-inheriting subagent, a resumed authoring session, or one that reads the author's transcript
or task notes does not count; continuing the same reviewer across rounds is fine. Each High pass
runs in its own fresh context.

If a required independent review cannot run (no subagent or session, reviewer failed, unusable
output), retry with another agent, model or session under existing accounts, limited to the repo's
approved agents when it has a list. Starting a separate reviewer this way is not a routing fallback:
the session's own model and harness never switch, and no new API keys, credits, top-ups or billing
are added. When the execution protocol applies, a gate that cannot run follows its steps 1 and 7 instead; do not land and record the blocker. Otherwise, if no reviewer works, do not land
and record the blocker.

Brief each finder with the requirement, the diff command, REVIEW.md path, the files it needs, tier,
the finding format below, and the ledger of already-reported findings with their outcomes, plus
operating limits (absolute path or worktree, read-only/prepare-only, Trail-first and repo rules).
Read-only finders cannot run Trail: when the diff touches Trail-supported source, run
`trail blast --no-owners --base <base> <worktree-root>` (structural, no model call; `<base>` is the commit the brief's diff
starts from, so the radius covers exactly the committed changes under review — with `--base` it diffs
`<base>...HEAD` only, so commit work that will ship first or state that uncommitted changes are not in
the radius) and paste its output into
each brief as the blast-radius starting point. Skip it for docs/config/`.svelte`-only diffs; on
failure, note the limit in the brief. It never covers `.svelte` callers, so an empty radius is
not proof of no callers.
Never include the author's reasoning, conclusions or leading questions. Use the `code-review` skill when a standards/spec split helps.

Built-in local review output may not follow the requested summary or severity format even when it
reads the guide. Preserve the raw output, verify and classify each finding against REVIEW.md, and
write the final count/severity summary before presenting it. An incomplete, usage-limited or
unclassified result is not a passing review or evidence of zero bugs.

## 4. Verify each finding

Before acting on a finding, confirm it against the code: trace input → failure, or reproduce it.
For High tier, a second fresh agent may vote on disputed Important findings. Drop anything without
`file:line` evidence. Tag survivors **Important**, **Nit** (max five) or **Pre-existing**.

## 5. Fix and converge

- Fix every Important finding at its root cause and every instance of its bug class; re-run the
  affected checks. Resolve rejected findings with a one-line reason.
- Round 2 and 3 review only `git diff <last-reviewed-sha>...HEAD`. Never re-raise a finding in the
  ledger. After round 3, stop: rethink the approach or escalate; do not loop.

## 6. Record

Write `review.md` with the evidence for the task (e.g. `~/.local/state/dev-evidence/<task>/`):
candidate SHA, tier, checks run and results, reviewer mechanism (agent, model, subagent or session)
and what each brief contained, findings with outcome
(`fixed | wrong | intentional | irrelevant`) and rounds. Append one line per finding to
`~/.local/state/review-metrics/findings.jsonl`:
`{"date","task","repo","sha","tier","round","severity","class","outcome","reviewer"}`, where `task` is
the evidence/task identifier so reviews in the same repo on the same day do not merge. This is the data
for false-positive rate, rounds-to-pass and reviewer accuracy; `~/.agents/bin/review-metrics
[repo]` summarizes it with eval scores and the repo's revert share. When a change later causes an
incident or revert, add it to the repo's regression evals (e.g. `docs/review/evals/`). When the
same finding class keeps coming back, fix it at its source (lint rule, test, skill or instruction).

## Finding format

`[Important|Nit|Pre-existing] file:line — failure scenario (input/state → wrong result). Evidence: …. Fix: ….`
Summary line first: `N Important, N Nit, N Pre-existing`.
