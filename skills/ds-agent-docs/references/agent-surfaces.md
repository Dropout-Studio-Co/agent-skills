# Cross-Agent Instruction & Config Surfaces

Verified repository-level instruction, rule, skill, and config paths across common AI coding agents. Use this reference to keep `AGENTS.md` as the single source of truth and avoid cross-agent duplication or drift.

## Documented Surface Map

| Agent / Tool | Primary Project Memory | Scoped Rules / Instructions | Skills / Commands / Agents | Notes |
| --- | --- | --- | --- | --- |
| **Cross-agent standard** | `AGENTS.md` (root + nested), `AGENTS.override.md` | `.agents/rules/*.md` | `.agents/skills/<name>/SKILL.md` | Canonical single source of truth across harnesses. |
| **Claude Code** | `CLAUDE.md` (root + nested), `CLAUDE.local.md` | `.claude/rules/**/*.md` (optional `paths:` frontmatter) | `.claude/skills/<name>/SKILL.md`, `.claude/commands/*.md`, `.claude/agents/*.md`, `.claude/output-styles/*.md` | Keep `CLAUDE.md` as a one-line `@AGENTS.md` import (or symlink) with zero duplicated rules. `CLAUDE.local.md` is personal/gitignored. |
| **OpenCode** | `AGENTS.md` (root + nested), falls back to `CLAUDE.md` | — | `.agents/skills/<name>/SKILL.md`, `.claude/skills/<name>/SKILL.md` | Reads `AGENTS.md` natively; no separate adapter file needed. |
| **Codex** | `AGENTS.md` (root + nested), `AGENTS.override.md` | — | `.agents/skills/<name>/SKILL.md`, `.codex/skills/<name>/SKILL.md` | Reads `AGENTS.md` natively; `AGENTS.override.md` overrides in a directory. |
| **Gemini CLI** | `GEMINI.md` (root + nested; configurable via `contextFileName`) | — | `.gemini/skills/<name>/SKILL.md`, `.agents/skills/<name>/SKILL.md` | Keep `GEMINI.md` thin (pointer or `@AGENTS.md` import) if `AGENTS.md` is canonical, or configure Gemini CLI to read `AGENTS.md`. |
| **Cursor** | `.cursor/rules/*.mdc` or `.cursor/rules/*.md` | `globs:` / `alwaysApply:` frontmatter in `.cursor/rules/` | — | `.cursorrules` at repo root is legacy; flag when both `.cursorrules` and `.cursor/rules/` exist. |
| **Windsurf** | `.windsurf/rules/*.md` | Mode/glob frontmatter in `.windsurf/rules/` | — | `.windsurfrules` at repo root is legacy; flag overlap with `.windsurf/rules/`. |
| **Cline** | `.clinerules` or `.clinerules/*.md` | Directory of markdown rule files | — | Keep aligned with `AGENTS.md` rather than duplicating full checklists. |
| **GitHub Copilot** | `.github/copilot-instructions.md` | `.github/instructions/*.instructions.md` (`applyTo:` frontmatter) | — | Keep concise and pointer-driven; avoid duplicating `AGENTS.md` verbatim. |

## Project Documentation Surfaces

Agents also rely on core repository documentation to orient and verify work:

- **Core docs:** `README.md`, `CONTRIBUTING.md`, `ARCHITECTURE.md`, `DEVELOPMENT.md`, and referenced files under `docs/**/*.md`.
- **Active learnings:** `.trail/learnings/*.md` with `status: active` (repo-local decision and gotcha records).

## Single-Source-of-Truth Pattern

When a repository supports multiple agents:

1. Put all shared project rules, commands, architecture pointers, and invariants in **`AGENTS.md`** (root + subtree `AGENTS.md` where needed).
2. Keep agent-specific entry files thin:
   - `CLAUDE.md` → `@AGENTS.md` (first non-comment line) or symlink to `AGENTS.md`.
   - `GEMINI.md` → `@AGENTS.md` (or a short pointer to `AGENTS.md` plus Gemini-only notes if any).
   - `.cursor/rules/`, `.github/copilot-instructions.md`, etc. → concise pointer to `AGENTS.md` plus only tool-specific glob/frontmatter rules.
3. Move large repeatable procedures into **`SKILL.md`** under `.agents/skills/<name>/` (or the repo's configured `skillsDir`) so they load on demand instead of inflating every turn's context window. Skills with `disable-model-invocation: true` in their frontmatter are user-invoked only and carry zero always-loaded context cost.
4. Keep **personal/local** overrides (`CLAUDE.local.md`, user home configs) separate from committed repository instructions; never write user-global rules into a repo's `AGENTS.md`.
