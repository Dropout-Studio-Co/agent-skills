# Fresh-context planning and review tasks

Planning, architecture analysis, consults and code/reconciliation/UI reviews run in a **fresh,
read-only context** separate from the authoring conversation. The helpers prepare inputs, bind
results to the exact candidate and write tamper-evident receipts; they never select a model,
override effort, probe providers or invoke an external model CLI.

## Model, harness and ds-dev-protocol rule

- **Default (independent operation):** Use the current session's harness, model and effort level
  for every step, including fresh-context planning, consult and review tasks. Never switch,
  select or enforce another model, harness, provider, CLI or effort level on your own.
- **Execution protocol exception:** When `ds-dev-protocol` is explicitly invoked alongside a
  skill for the task, `ds-dev-protocol`'s model-routing, planning, implementation and gate rules
  take precedence for the applicable tasks. When `ds-dev-protocol` is not explicitly invoked,
  the skill operates independently on the current session's configuration.

## Independence and unavailability

- **Fresh context** means a read-only subagent, a new isolated session on the current harness, or
  an equivalent fresh context that shares none of the authoring conversation's history or notes.
  The prompt file carries every input the task needs.
- **Never self-review in the authoring context** to satisfy a required independent review.
- **Unavailable fresh context:** If the current harness has no fresh-context mechanism, or if the
  fresh-context task fails to return a valid result block, mark the task `unavailable` with the
  reason (`review unavailable` / `planning unavailable` / `review_task.py unavailable`). Never
  fabricate a receipt or merge/deliver past an unavailable required review.
- **Parallel tasks:** Distinct `(kind, subject)` read-only review tasks on the same frozen candidate,
  and distinct `--kind architecture` tasks, may run concurrently. Keep the candidate tree frozen
  until every result is recorded, and never run duplicate-lens committees or concurrent prepares of
  the same `(kind, subject)`.

## Dependency-upgrade commands (`scripts/depup.py`)

### Reviews

1. **Prepare:** `depup.py review prepare <run_ref> --kind <critical|independent|security> [--subject S] [--required] [--context F] [--rerun]`
   - Writes `code.diff` (all non-lockfile changes), `lockfile.diff` (complete), `diffstat.txt`,
     optional redacted `context.*`, `prompt.md` and `entry.json` (`status: "pending"`) under
     `<run_dir>/reviews/<kind>-<subject>-<candidate12>/`.
   - If a completed review already exists for that exact candidate (and `--rerun` is not set),
     returns it with `reused: true`.
2. **Execute:** Run `prompt.md` in a fresh, read-only context on the current session's
   configuration (see the model rule above). Save the full answer to the printed `output_path`.
3. **Record:** `depup.py review record <run_ref> --review-id <id> --output <file> --reviewer "<fresh-context-id>"`
   - Verifies the worktree candidate commit did not change since `prepare` (a changed tree discards
     the result and marks the review `unavailable` with `tree_changed: true`).
   - Parses the final `DEPUP_REVIEW_RESULT_BEGIN … END` JSON block (`verdict: "pass"|"fail"`,
     `findings` with severity `Important|Nit|Pre-existing`; any `Important` finding forces `fail`).
   - Writes `review.md` and candidate-bound `receipt.json` (SHA-256 of `review.md`, `kind:
     "<kind>-review"`, distinct reviewer identity per review ID so `independent` and `security`
     reviews remain distinct fresh sessions).
4. **Unavailable:** `depup.py review unavailable <run_ref> --review-id <id> --reason "<why>"`
   - Marks a pending review `unavailable`. Pending or unavailable `required` entries stay on disk
     and downgrade `PASS` to `PARTIAL` in `depup.py report`.

### Architecture and planning

1. **Prepare:** `depup.py planning prepare <run_ref> --context <file> [--kind plan|architecture] [--subject S] [--rerun]`
   - Kinds: `plan` (default; whole upgrade) and `architecture` (`--subject` required; one
     high-risk item). Used in both `plan` and `upgrade` mode.
   - Read target: the owned worktree once it exists, else the repository (`plan` mode, read-only).
   - Reuse key: `(kind, subject, target, tree_fingerprint, context_sha256)`.
2. **Execute:** Run `prompt.md` in a fresh, read-only context on the current session's
   configuration (see the model rule above).
3. **Record:** `depup.py planning record <run_ref> --plan-id <id> --output <file> --planner "<fresh-context-id>"`
   - Verifies `tree_fingerprint(target)` did not change during planning (a mutation discards the
     result, sets `tree_changed: true` and makes `report` flag the user checkout as changed).
   - Parses `DEPUP_PLAN_RESULT_BEGIN … END` JSON (`summary`, non-empty `decisions`, `steps`
     non-empty for `plan`, `risks`, `holds`, `open_questions`).
   - Writes `plan.md`, `plan.json`, `receipt.json` and `entry.json`. `report` copies every plan
     entry from disk into `planning`; planner output is advisory data validated by the main session.
4. **Unavailable:** `depup.py planning unavailable <run_ref> --plan-id <id> --reason "<why>"`

## Sibling skills (`scripts/review_task.py`)

`scripts/review_task.py` gives skills without a depup run journal the same fresh-context
prepare/record/unavailable workflow, candidate binding, reuse and required-review gate. Each
sibling skill ships `<skill>/task-profile.json` (role, binding rules, `plan_kinds`, `review_kinds`
with focus text; `evidence: git-inventory` adds helper-collected Git facts; `rendered_evidence:
required` needs `--rendered-evidence` or `--no-rendered-evidence`). Profiles declare no model,
harness or effort overrides.

- Runs live in `~/.local/state/agent-tasks/<skill>/<repo-key>/<run-id>/` (`AGENT_TASK_STATE_DIR`).
- `start --skill <name> --repo . [--base REF]` fixes the review base (default `HEAD`).
- `plan` and `review` prepare `prompt.md` and return `reused: true` when an unchanged candidate and
  inputs already have a completed entry.
- `record RUN --task-id ID --output F --by "<fresh-context-id>"` checks the tree fingerprint (and
  live git-inventory hash for `git-inventory` reviews), parses the JSON result block and writes
  `receipt.json`.
- `unavailable RUN --task-id ID --reason "<why>"` records an unrunnable task without satisfying
  the gate.
- `gate RUN [--require KIND[:SUBJECT]]...` passes only when every required `(kind, subject)`
  (including any ever marked `--required` under `required/` or legacy `required.json`) has a latest `completed` `pass`
  entry for the current working-tree fingerprint and run base, with an intact `receipt.json` and
  matching live `git-inventory` SHA-256, and no review of the current candidate failed.
- Files named by absolute path in a rendered-evidence manifest (safe image/video/PDF extensions
  only) are copied into the task directory so a read-only reviewer can inspect them.
- Current sibling users: `ds-consolidate` (`plan` / `consult` / `architecture`, `reconciliation`
  and `code` reviews) and `ds-ui-overhaul` (`plan` / `architecture`, `code` / `ui-ux` / `accessibility`
  reviews).
