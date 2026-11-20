---
title: "Workflow skills run because the protocol names them, not because of their descriptions"
author: Beyourahi
date: 2026-11-20
branch: main
id: l-145648b7
scope: repo
status: active
src: agent
touches:
  - skills/execution-protocol/SKILL.md
---

## Decided
Third-party workflow skills (tdd, diagnosing-bugs, code-review, pr, retro, setup-pre-commit from mattpocock/skills) are used automatically by naming them in the execution protocol, read by path at the phase where each applies. Their descriptions say "when the user wants...", so a skill never triggered on its own during autonomous protocol runs (0 loads in about 2,000 sessions for 5 of the 6). The implementer cannot load skills (the OpenCode agent denies skill/external_directory; the Sonnet fallback runs with no setting sources), so tdd's text is put into each brief by the brief builder instead.

## Tried and ruled out
- A prompt-submit hook that reminds the agent: machine policy allows no new hooks, and it would cost tokens on every prompt.
- Editing the installed skill descriptions, or retro's disable-model-invocation flag: those are third-party copies that `npx skills update` overwrites.
- Folding code-review into the Opus gate brief: any gate-brief change means rescoring the gate eval set. code-review runs as a pre-review pair that is not a gate instead.

## Watch out
- Use Skill('code-review') and you get Claude Code's built-in /code-review, not this skill. Always read it by path.
- SKILL.md is 41 bytes under the raised 25600-byte smoke cap; any further growth needs a cap change.
- The tdd section appears only when a tdd folder sits beside the skill folder (the installed root). The repo checkout has none, so the smoke tests use temp layouts.

In the code: skills/execution-protocol/SKILL.md step 4 "Workflow skills (Rahi 2026-11-20, MUST)"; scripts/implement_lib.py `brief` (sibling tdd lookup); tests/implement-smoke.sh tdd checks; tests/smoke.sh "SKILL size 25600 max". PR #19.
