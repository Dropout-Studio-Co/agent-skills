"""check_instructions.py: the lean read-only audit survey."""
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(HERE, 'scripts', 'check_instructions.py')
SKILL_DIR = HERE
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))

DEFAULT_AGENTS = '# Fixture memory\n\nUse the documented commands.\n'
DEFAULT_README = '# Fixture\n\n```sh\npython3 -m unittest\n```\n'


def load_checker():
    spec = importlib.util.spec_from_file_location('check_instructions_under_test', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AuditCase(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix='audit-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo = os.path.join(self.tmp, 'repo')
        os.makedirs(self.repo)
        self.env = dict(os.environ)
        self.env.update({'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_SYSTEM': os.devnull,
                         'GIT_AUTHOR_NAME': 'fixture', 'GIT_AUTHOR_EMAIL': 'fixture@example.test',
                         'GIT_COMMITTER_NAME': 'fixture',
                         'GIT_COMMITTER_EMAIL': 'fixture@example.test'})
        self.write('AGENTS.md', DEFAULT_AGENTS)
        self.write('CLAUDE.md', '@AGENTS.md\n')
        self.write('README.md', DEFAULT_README)
        self.git('init', '-q', '-b', 'main')
        self.commit()

    # -- fixtures ---------------------------------------------------------
    def git(self, *args, cwd=None):
        return subprocess.run(['git'] + list(args), cwd=cwd or self.repo, capture_output=True,
                              text=True, env=self.env, check=True)

    def commit(self):
        self.git('add', '-A')
        self.git('commit', '-qm', 'fixture')

    def write(self, rel, text, repo=None):
        path = os.path.join(repo or self.repo, rel)
        os.makedirs(os.path.dirname(path) or (repo or self.repo), exist_ok=True)
        with open(path, 'w', encoding='utf-8', newline='') as handle:
            handle.write(text)
        return path

    def remove(self, rel):
        os.remove(os.path.join(self.repo, rel))

    def audit(self, *extra, repo=None):
        target = repo or self.repo
        proc = subprocess.run(
            [sys.executable, SCRIPT, 'audit', '--repo', target, '--json'] + list(extra),
            capture_output=True, text=True, cwd=self.repo, env=self.env)
        try:
            data = json.loads(proc.stdout)
        except ValueError:
            data = None
        return proc.returncode, data

    def ok_audit(self, *extra, repo=None):
        code, data = self.audit(*extra, repo=repo)
        self.assertEqual(code, 0, data)
        self.assertEqual(data['status'], 'ok', data)
        return data

    def by_path(self, data):
        return {item['path']: item for item in data['inventory']}


class DeliveryTests(AuditCase):
    def test_non_git_repository_is_in_place(self):
        plain = os.path.join(self.tmp, 'plain')
        os.makedirs(plain)
        self.write('AGENTS.md', DEFAULT_AGENTS, repo=plain)
        self.write('CLAUDE.md', '@AGENTS.md\n', repo=plain)
        data = self.ok_audit(repo=plain)
        self.assertEqual(data['delivery']['action'], 'in_place')
        self.assertEqual(data['delivery']['reason'], 'not a git repository')
        self.assertFalse(data['delivery']['dirty'])
        self.assertEqual(data['repo']['kind'], 'dir')

    def test_task_branch_is_in_place(self):
        self.git('checkout', '-q', '-b', 'feature')
        data = self.ok_audit()
        self.assertEqual(data['delivery']['action'], 'in_place')
        self.assertEqual(data['delivery']['reason'], 'task branch')

    def test_default_branch_without_a_pr_rule_is_in_place(self):
        data = self.ok_audit()
        self.assertEqual(data['repo']['default_branch'], 'main')
        self.assertEqual(data['repo']['current_branch'], 'main')
        self.assertEqual(data['delivery']['action'], 'in_place')
        self.assertEqual(data['delivery']['reason'],
                         'default branch without a written PR rule')
        self.assertEqual(data['delivery']['commands'], [])

    def test_default_branch_with_a_pr_rule_uses_a_worktree(self):
        self.write('AGENTS.md', DEFAULT_AGENTS + '\nAlways open a pull request before merging.\n')
        self.commit()
        data = self.ok_audit()
        self.assertEqual(data['delivery']['action'], 'worktree')
        self.assertIn('written PR rule', data['delivery']['reason'])
        commands = data['delivery']['commands']
        self.assertEqual(len(commands), 2)
        self.assertTrue(commands[0].startswith('git fetch origin -- '))
        self.assertTrue(commands[1].startswith('git worktree add -b docs/ds-sync-'))
        self.assertIn('"$HOME"', commands[1])

    def test_detached_head_uses_a_worktree(self):
        self.git('checkout', '-q', '--detach', 'HEAD')
        data = self.ok_audit()
        self.assertEqual(data['delivery']['action'], 'worktree')
        self.assertEqual(data['delivery']['reason'], 'detached HEAD')
        self.assertEqual(data['repo']['current_branch'], '')
        self.assertEqual(len(data['delivery']['commands']), 2)

    def test_dirty_memory_file_is_patch_only(self):
        self.write('AGENTS.md', DEFAULT_AGENTS + '\nUncommitted edit.\n')
        data = self.ok_audit()
        self.assertEqual(data['delivery']['action'], 'patch_only')
        self.assertEqual(data['delivery']['reason'], 'dirty memory file')
        self.assertTrue(data['delivery']['dirty'])

    def test_dirty_gemini_or_readme_is_patch_only(self):
        self.write('GEMINI.md', '@AGENTS.md\n')
        self.commit()
        self.write('GEMINI.md', '@AGENTS.md\nDirty edit.\n')
        data = self.ok_audit()
        self.assertEqual(data['delivery']['action'], 'patch_only')
        self.assertTrue(data['delivery']['dirty'])
        self.commit()
        self.write('README.md', DEFAULT_README + '\nDirty readme edit.\n')
        data = self.ok_audit()
        self.assertEqual(data['delivery']['action'], 'patch_only')
        self.assertTrue(data['delivery']['dirty'])

    def test_unknown_default_branch_is_patch_only(self):
        trunk = os.path.join(self.tmp, 'trunk')
        os.makedirs(trunk)
        self.write('AGENTS.md', DEFAULT_AGENTS, repo=trunk)
        self.write('CLAUDE.md', '@AGENTS.md\n', repo=trunk)
        self.git('init', '-q', '-b', 'trunk', cwd=trunk)
        self.git('add', '-A', cwd=trunk)
        self.git('commit', '-qm', 'fixture', cwd=trunk)
        data = self.ok_audit(repo=trunk)
        self.assertIsNone(data['repo']['default_branch'])
        self.assertEqual(data['delivery']['action'], 'patch_only')
        self.assertEqual(data['delivery']['reason'], 'unknown default branch')


class DiscoveryTests(AuditCase):
    def test_discovers_cross_agent_surfaces(self):
        files = {
            'AGENTS.override.md': 'Override.\n',
            'CLAUDE.local.md': 'Local notes.\n',
            'GEMINI.md': '@AGENTS.md\n',
            '.github/copilot-instructions.md': 'Read `AGENTS.md`.\n',
            '.github/instructions/ts.instructions.md': '---\napplyTo: "**/*.ts"\n---\nStrict.\n',
            '.claude/rules/api.md': 'Validate inputs.\n',
            '.claude/rules/scoped.md': '---\npaths:\n  - "src/**"\n---\nScoped.\n',
            '.agents/rules/shared.md': 'Shared rule.\n',
            '.cursor/rules/style.mdc': '---\nalwaysApply: true\n---\nTabs.\n',
            '.cursor/rules/ui.mdc': '---\nglobs: "*.tsx"\nalwaysApply: false\n---\nUI.\n',
            '.cursorrules': 'Legacy cursor.\n',
            '.windsurf/rules/w.md': 'Windsurf rule.\n',
            '.clinerules': 'Cline rule.\n',
            '.claude/commands/release.md': 'Release checklist.\n',
            '.agents/commands/run.md': 'Run command.\n',
            '.claude/agents/reviewer.md': 'Review.\n',
            '.agents/agents/helper.md': 'Help.\n',
            '.claude/output-styles/tone.md': 'Tone.\n',
            '.agents/skills/demo/SKILL.md': '---\nname: demo\ndescription: Demo.\n---\nBody.\n',
            '.claude/skills/tool/SKILL.md': '---\nname: tool\ndescription: Tool.\n---\nBody.\n',
            '.codex/skills/codex-helper/SKILL.md': '---\nname: codex-helper\ndescription: Codex.\n---\nBody.\n',
            '.gemini/skills/helper/SKILL.md': '---\nname: helper\ndescription: Help.\n---\nBody.\n',
            '.trail/learnings/note.md': '---\nstatus: active\n---\nNote.\n',
            'CONTRIBUTING.md': 'Contribute.\n',
            'ARCHITECTURE.md': 'Architecture.\n',
            'DEVELOPMENT.md': 'Development.\n',
            'docs/guide.md': 'Guide.\n',
        }
        for rel, text in files.items():
            self.write(rel, text)
        self.commit()
        data = self.ok_audit()
        found = self.by_path(data)
        for rel in files:
            self.assertIn(rel, found, rel)
        self.assertEqual(found['AGENTS.md']['category'], 'memory')
        self.assertEqual(found['AGENTS.md']['agent'], 'cross-agent')
        self.assertTrue(found['AGENTS.md']['always_loaded'])
        self.assertTrue(found['CLAUDE.local.md']['always_loaded'])
        self.assertEqual(found['GEMINI.md']['agent'], 'gemini')
        self.assertEqual(found['.github/copilot-instructions.md']['agent'], 'copilot')
        self.assertEqual(found['.github/instructions/ts.instructions.md']['category'], 'rules')
        self.assertTrue(found['.claude/rules/api.md']['always_loaded'])
        self.assertFalse(found['.claude/rules/scoped.md']['always_loaded'])
        self.assertTrue(found['.cursor/rules/style.mdc']['always_loaded'])
        self.assertFalse(found['.cursor/rules/ui.mdc']['always_loaded'])
        self.assertTrue(found['.cursorrules']['always_loaded'])
        self.assertEqual(found['.claude/commands/release.md']['category'], 'commands')
        self.assertEqual(found['.claude/agents/reviewer.md']['category'], 'subagents')
        self.assertEqual(found['.claude/output-styles/tone.md']['category'], 'output_styles')
        self.assertEqual(found['.agents/skills/demo/SKILL.md']['category'], 'skills')
        self.assertEqual(found['.codex/skills/codex-helper/SKILL.md']['category'], 'skills')
        self.assertEqual(found['.codex/skills/codex-helper/SKILL.md']['agent'], 'codex')
        self.assertEqual(found['.gemini/skills/helper/SKILL.md']['agent'], 'gemini')
        self.assertEqual(found['.trail/learnings/note.md']['category'], 'learnings')
        self.assertEqual(found['docs/guide.md']['category'], 'docs')

    def test_scope_filters_and_refuses_escape_or_missing(self):
        self.write('.claude/rules/a.md', 'Rule A.\n')
        self.write('.claude/rules/b.md', 'Rule B.\n')
        self.write('docs/guide.md', 'Guide.\n')
        self.commit()
        data = self.ok_audit('--scope', '.claude/rules')
        self.assertEqual(data['scope'], '.claude/rules')
        self.assertEqual([i['path'] for i in data['inventory']],
                         ['.claude/rules/a.md', '.claude/rules/b.md'])
        data = self.ok_audit('--scope', 'docs/guide.md')
        self.assertEqual([i['path'] for i in data['inventory']], ['docs/guide.md'])
        for bad in ('../outside', 'does/not/exist'):
            code, payload = self.audit('--scope', bad)
            self.assertEqual(code, 2, bad)
            self.assertEqual(payload['status'], 'invalid', bad)
        os.symlink(self.tmp, os.path.join(self.repo, 'linkout'))
        code, payload = self.audit('--scope', 'linkout')
        self.assertEqual(code, 2)
        self.assertEqual(payload['status'], 'invalid')

    def test_dot_scope_means_the_whole_repository(self):
        self.write('.claude/rules/a.md', 'Rule A.\n')
        self.commit()
        for value in ('.', './'):
            data = self.ok_audit('--scope', value)
            self.assertIsNone(data['scope'], value)
            self.assertIn('.claude/rules/a.md', self.by_path(data), value)

    def test_skills_dir_custom_and_escape_refusal(self):
        self.write('custom/skills/demo/SKILL.md',
                   '---\nname: demo\ndescription: Demo.\n---\nBody.\n')
        self.commit()
        data = self.ok_audit('--skills-dir', 'custom/skills')
        self.assertEqual(self.by_path(data)['custom/skills/demo/SKILL.md']['category'], 'skills')
        for bad in ('../outside', 'does/not/exist'):
            code, payload = self.audit('--skills-dir', bad)
            self.assertEqual(code, 2, bad)
            self.assertEqual(payload['status'], 'invalid', bad)

    def test_prunes_symlinked_dirs_nested_repos_and_caches(self):
        self.write('node_modules/pkg/AGENTS.md', 'Ignored.\n')
        self.write('graft/cache/AGENTS.md', 'Ignored.\n')
        self.write('.trail/cache/AGENTS.md', 'Ignored.\n')
        external = os.path.join(self.tmp, 'external')
        os.makedirs(external)
        self.write('AGENTS.md', DEFAULT_AGENTS, repo=external)
        os.symlink(external, os.path.join(self.repo, 'linked'))
        nested = os.path.join(self.repo, 'nested')
        os.makedirs(nested)
        self.write('AGENTS.md', DEFAULT_AGENTS, repo=nested)
        os.makedirs(os.path.join(nested, '.git'))
        self.commit()
        data = self.ok_audit()
        paths = self.by_path(data)
        for hidden in ('node_modules/pkg/AGENTS.md', 'graft/cache/AGENTS.md',
                       '.trail/cache/AGENTS.md', 'linked/AGENTS.md', 'nested/AGENTS.md'):
            self.assertNotIn(hidden, paths)


class ContextLoadTests(AuditCase):
    def test_single_budget_block_and_inode_dedup(self):
        self.remove('CLAUDE.md')
        os.symlink('AGENTS.md', os.path.join(self.repo, 'CLAUDE.md'))
        self.commit()
        data = self.ok_audit()
        self.assertNotIn('budget', data)
        size = len(DEFAULT_AGENTS.encode('utf-8'))
        expected = (size + 3) // 4
        self.assertEqual(data['context_load']['always_loaded_file_tokens'], expected)
        self.assertEqual(data['context_load']['always_loaded_tokens'], expected)
        self.assertEqual(data['context_load']['budget_cap'], 5000)
        self.assertFalse(data['context_load']['over_budget'])

    def test_oversized_always_loaded_file_and_budget_override(self):
        self.write('AGENTS.md', DEFAULT_AGENTS + '\n' + '\n'.join(
            'Rule line %d for the oversized fixture.' % i for i in range(320)) + '\n')
        self.commit()
        data = self.ok_audit()
        oversized = [i['path'] for i in data['context_load']['oversized']]
        self.assertIn('AGENTS.md', oversized)
        data = self.ok_audit('--budget-tokens', '10')
        self.assertEqual(data['context_load']['budget_cap'], 10)
        self.assertTrue(data['context_load']['over_budget'])
        code, payload = self.audit('--budget-tokens', '0')
        self.assertEqual(code, 2)
        self.assertEqual(payload['status'], 'invalid')

    def test_skill_descriptions_add_to_the_budget(self):
        desc = 'Demo skill for a fixture repository.'
        self.write('.agents/skills/demo/SKILL.md',
                   '---\nname: demo\ndescription: %s\n---\nBody.\n' % desc)
        self.commit()
        data = self.ok_audit()
        expected = (len(desc.encode('utf-8')) + 3) // 4
        self.assertEqual(data['context_load']['skill_description_tokens'], expected)
        self.assertEqual(data['context_load']['always_loaded_tokens'],
                         data['context_load']['always_loaded_file_tokens'] + expected)

    def test_block_description_stops_at_the_next_top_level_key(self):
        self.write('.agents/skills/demo/SKILL.md',
                   '---\nname: demo\ndescription: |\n  First line.\n  Second line.\n'
                   'metadata:\n  version: "1.0"\n---\nBody.\n')
        self.commit()
        data = self.ok_audit()
        expected = (len('First line. Second line.'.encode('utf-8')) + 3) // 4
        self.assertEqual(data['context_load']['skill_description_tokens'], expected)

    def test_symlinked_agents_counts_resolved_lines_for_oversized(self):
        big = '\n'.join('Rule %d' % i for i in range(320)) + '\n'
        self.write('docs/shared-agents.md', big)
        self.remove('AGENTS.md')
        os.symlink('docs/shared-agents.md', os.path.join(self.repo, 'AGENTS.md'))
        self.commit()
        data = self.ok_audit()
        oversized = {i['path']: i for i in data['context_load']['oversized']}
        self.assertIn('AGENTS.md', oversized)
        self.assertEqual(oversized['AGENTS.md']['lines'], 320)

    def test_disable_model_invocation_skill_has_zero_description_tokens(self):
        self.write('.agents/skills/manual/SKILL.md',
                   '---\nname: manual\ndescription: Manual-only workflow.\n'
                   'disable-model-invocation: true\n---\nBody.\n')
        self.commit()
        data = self.ok_audit()
        self.assertEqual(data['context_load']['skill_description_tokens'], 0)
        self.assertTrue(self.by_path(data)['.agents/skills/manual/SKILL.md']['disable_model_invocation'])


class ImportTests(AuditCase):
    def test_first_non_comment_line_passes(self):
        self.write('CLAUDE.md', '<!-- bridge -->\n@AGENTS.md\n')
        self.commit()
        self.assertTrue(self.ok_audit()['import']['ok'])

    def test_multi_line_html_comment_before_the_import_passes(self):
        self.write('CLAUDE.md', '<!--\nline 2\n-->\n@AGENTS.md\n')
        self.commit()
        self.assertTrue(self.ok_audit()['import']['ok'])

    def test_symlink_to_sibling_agents_passes(self):
        self.remove('CLAUDE.md')
        os.symlink('AGENTS.md', os.path.join(self.repo, 'CLAUDE.md'))
        self.commit()
        self.assertTrue(self.ok_audit()['import']['ok'])

    def test_backticked_import_fails(self):
        self.write('CLAUDE.md', '`@AGENTS.md`\n')
        self.commit()
        errors = self.ok_audit()['import']['errors']
        self.assertIn('backticked import', [e['error'] for e in errors])

    def test_missing_claude_warns_without_claude_surfaces_and_errors_with_them(self):
        self.remove('CLAUDE.md')
        self.commit()
        imp = self.ok_audit()['import']
        self.assertTrue(imp['ok'])
        self.assertEqual(imp['errors'], [])
        self.assertIn({'file': 'CLAUDE.md', 'error': 'missing CLAUDE.md import'}, imp['warnings'])
        self.write('.claude/rules/api.md', 'Validate inputs.\n')
        self.commit()
        imp = self.ok_audit()['import']
        self.assertFalse(imp['ok'])
        self.assertIn({'file': 'CLAUDE.md', 'error': 'missing CLAUDE.md import'}, imp['errors'])
        self.write('CLAUDE.md', '@AGENTS.md\n')
        self.remove('AGENTS.md')
        self.commit()
        errors = self.ok_audit()['import']['errors']
        self.assertIn({'file': 'AGENTS.md', 'error': 'missing AGENTS.md'}, errors)

    def test_wrong_symlink_fails(self):
        self.remove('CLAUDE.md')
        os.symlink('README.md', os.path.join(self.repo, 'CLAUDE.md'))
        self.commit()
        errors = self.ok_audit()['import']['errors']
        self.assertIn('symlink points elsewhere', [e['error'] for e in errors])

    def test_duplicated_agents_line_fails(self):
        line = 'Run the full integration suite before merging any release branch.'
        self.write('AGENTS.md', DEFAULT_AGENTS + '\n' + line + '\n')
        self.write('CLAUDE.md', '@AGENTS.md\n' + line + '\n')
        self.commit()
        errors = self.ok_audit()['import']['errors']
        self.assertTrue(any(e.get('error') == 'line duplicated from AGENTS.md' for e in errors))

    def test_nested_memory_files_are_checked(self):
        self.write('nested/AGENTS.md', DEFAULT_AGENTS)
        self.write('nested/CLAUDE.md', '@AGENTS.md\n')
        self.commit()
        self.assertTrue(self.ok_audit()['import']['ok'])
        self.write('nested/CLAUDE.md', 'See nested rules.\n')
        self.commit()
        errors = self.ok_audit()['import']['errors']
        self.assertIn({'file': 'nested/CLAUDE.md', 'error': 'missing @AGENTS.md import'}, errors)


class ReferenceTests(AuditCase):
    def base_manifest(self):
        self.write('package.json', '{"name": "fixture", "scripts": {"build": "echo ok"}}\n')
        self.write('Makefile', 'test:\n\techo ok\n')
        self.commit()

    def test_catches_broken_links_paths_and_manifest_targets(self):
        self.base_manifest()
        self.write('AGENTS.md', DEFAULT_AGENTS + '\n'
                   '- [bad](missing.md)\n'
                   '- `./missing/file.py`\n'
                   '- `npm run nope`\n'
                   '- `make nope`\n'
                   '- `npm run build`\n'
                   '- `make test`\n')
        self.commit()
        data = self.ok_audit()
        stale = {item['ref'] for item in data['references']['stale']}
        self.assertIn('missing.md', stale)
        self.assertIn('./missing/file.py', stale)
        self.assertIn('npm run nope', stale)
        self.assertIn('make nope', stale)
        self.assertNotIn('npm run build', stale)
        self.assertNotIn('make test', stale)

    def test_high_precision_avoids_common_false_positives(self):
        self.base_manifest()
        for rel in ('SKILL.md', 'task-profile.json', 'docs/guide.md'):
            self.write(rel, 'placeholder\n')
        self.write('.gitignore', '.env.local\n')
        self.write('AGENTS.md', DEFAULT_AGENTS + '\n'
                   '- `SKILL.md` and `task-profile.json`\n'
                   '- `docs/guide.md`\n'
                   '- `Move.target`\n'
                   '- `Dropout-Studio-Co/ds-agent-skills`\n'
                   '- `skills/<name>`\n'
                   '- `https://example.dev/path`\n'
                   '- [site](https://example.dev/docs)\n'
                   '- `.env.local`\n'
                   '- `npm run build` and `make test`\n')
        self.commit()
        data = self.ok_audit()
        self.assertEqual(data['references']['stale'], [])
        self.assertIn('Move.target', [i['ref'] for i in data['references']['items']])
        self.assertIn('Dropout-Studio-Co/ds-agent-skills', [i['ref'] for i in data['references']['items']])

    def test_gitignored_missing_markdown_link_is_not_stale(self):
        self.write('.gitignore', 'generated/**\n')
        self.write('AGENTS.md', DEFAULT_AGENTS + '\n[generated](generated/index.md)\n')
        self.commit()
        data = self.ok_audit()
        self.assertEqual(data['references']['stale'], [])
        self.assertEqual(data['references']['counts'].get('ignored'), 1)

    def test_cli_flags_and_make_options_are_not_classified(self):
        self.base_manifest()
        self.write('AGENTS.md', DEFAULT_AGENTS + '\n'
                   '- `make --help`\n'
                   '- pass `--json` for machine output\n')
        self.commit()
        data = self.ok_audit()
        refs = [item['ref'] for item in data['references']['items']]
        self.assertNotIn('make --help', refs)
        self.assertNotIn('--json', refs)
        self.assertEqual(data['references']['stale'], [])
        self.assertIsNone(data['references']['counts'].get('scoped'))

    def test_shorthand_package_scripts_and_script_runners(self):
        self.base_manifest()
        self.write('scripts/present.py', 'print("ok")\n')
        self.write('scripts/present.sh', 'echo ok\n')
        self.write('AGENTS.md', DEFAULT_AGENTS + '\n'
                   '```sh\n'
                   'pnpm build\n'
                   'bun build\n'
                   'yarn build\n'
                   'pnpm nope\n'
                   'bun nope\n'
                   'yarn nope\n'
                   'pnpm install\n'
                   'bun add vitest\n'
                   'python3 scripts/present.py\n'
                   'python3 scripts/missing.py\n'
                   'bash scripts/present.sh\n'
                   'bash scripts/missing.sh\n'
                   'python3 -m unittest\n'
                   '```\n')
        self.commit()
        data = self.ok_audit()
        stale = {item['ref'] for item in data['references']['stale']}
        for bad in ('pnpm nope', 'bun nope', 'yarn nope',
                    'python3 scripts/missing.py', 'bash scripts/missing.sh'):
            self.assertIn(bad, stale, bad)
        for good in ('pnpm build', 'bun build', 'yarn build', 'pnpm install',
                     'bun add vitest', 'python3 scripts/present.py',
                     'bash scripts/present.sh', 'python3 -m unittest'):
            self.assertNotIn(good, stale, good)


class BatchedIgnoreTests(AuditCase):
    """Unresolved references need one batched git check-ignore call, not one per reference."""

    def count_check_ignore(self, module):
        calls = []
        original = module.git

        def counting(args, cwd, input_text=None):
            if args[0] == 'check-ignore':
                calls.append(args)
            return original(args, cwd, input_text)

        module.git = counting
        self.addCleanup(setattr, module, 'git', original)
        return calls

    def test_many_unresolved_references_need_one_check_ignore_call(self):
        lines = ['- [generated %d](generated/file-%d.md)' % (i, i) for i in range(3)]
        lines += ['- [cache %d](cache/file-%d.md)' % (i, i) for i in range(3)]
        self.write('.gitignore', 'generated/\ncache/\n')
        self.write('AGENTS.md', DEFAULT_AGENTS + '\n' + '\n'.join(lines) + '\n')
        self.commit()
        module = load_checker()
        calls = self.count_check_ignore(module)
        code, payload = module.audit_command(self.repo)
        self.assertEqual(code, 0, payload)
        self.assertLessEqual(len(calls), 1, calls)
        self.assertEqual(payload['references']['counts'].get('ignored'), 6)
        self.assertEqual(payload['references']['stale'], [])

    def test_non_git_repository_keeps_missing_references_stale(self):
        plain = os.path.join(self.tmp, 'plain')
        os.makedirs(plain)
        self.write('AGENTS.md', DEFAULT_AGENTS + '\n- [gone](./gone/missing.md)\n', repo=plain)
        self.write('CLAUDE.md', '@AGENTS.md\n', repo=plain)
        module = load_checker()
        calls = self.count_check_ignore(module)
        code, payload = module.audit_command(plain)
        self.assertEqual(code, 0, payload)
        self.assertLessEqual(len(calls), 1, calls)
        self.assertIn('./gone/missing.md',
                      [item['ref'] for item in payload['references']['stale']])
        self.assertIsNone(payload['references']['counts'].get('ignored'))

    def test_traversal_ref_does_not_poison_gitignored_batch(self):
        self.write('.gitignore', 'generated/\n')
        self.write('AGENTS.md', DEFAULT_AGENTS + '\n'
                   '- [generated](generated/index.md)\n'
                   '- [outside](./../outside.md)\n')
        self.commit()
        module = load_checker()
        calls = self.count_check_ignore(module)
        code, payload = module.audit_command(self.repo)
        self.assertEqual(code, 0, payload)
        self.assertLessEqual(len(calls), 1, calls)
        self.assertEqual(payload['references']['counts'].get('ignored'), 1)
        self.assertNotIn('generated/index.md',
                         [item['ref'] for item in payload['references']['stale']])


class StructureTests(AuditCase):
    def test_dangling_imports_are_reported(self):
        self.write('AGENTS.md', DEFAULT_AGENTS + '\n@docs/missing.md\n')
        self.commit()
        dangling = self.ok_audit()['structure']['dangling_imports']
        self.assertEqual(len(dangling), 1)
        self.assertEqual(dangling[0]['import'], '@docs/missing.md')

    def test_skill_frontmatter_is_validated(self):
        self.write('.agents/skills/wrong/SKILL.md', '---\nname: other\n---\nBody.\n')
        self.write('.agents/skills/plain/SKILL.md', 'No frontmatter.\n')
        self.write('.agents/skills/good/SKILL.md',
                   '---\nname: good\ndescription: Good skill.\n---\nBody.\n')
        self.commit()
        issues = self.ok_audit()['structure']['skill_frontmatter']
        errors = {(i['file'], i['error']) for i in issues}
        self.assertTrue(any('does not match folder' in e for _f, e in errors))
        self.assertTrue(any('missing YAML frontmatter' == e for _f, e in errors))
        self.assertFalse(any(f == '.agents/skills/good/SKILL.md' for f, _e in errors))

    def test_cross_file_duplicates_are_capped_and_located(self):
        line = 'Always run the full integration suite before pushing any release branch.'
        self.write('AGENTS.md', DEFAULT_AGENTS + '\n' + line + '\n')
        self.write('GEMINI.md', '# Gemini\n\n' + line + '\n')
        self.commit()
        duplicates = self.ok_audit()['structure']['duplicates']
        self.assertEqual(len(duplicates), 1)
        self.assertEqual({spot['file'] for spot in duplicates[0]['locations']},
                         {'AGENTS.md', 'GEMINI.md'})

    def test_legacy_rule_overlaps_are_reported(self):
        self.write('.cursorrules', 'Legacy.\n')
        self.write('.cursor/rules/modern.mdc', '---\nalwaysApply: false\n---\nModern.\n')
        self.write('.windsurfrules', 'Legacy.\n')
        self.write('.windsurf/rules/modern.md', 'Modern.\n')
        self.commit()
        overlaps = self.ok_audit()['structure']['legacy_overlaps']
        self.assertEqual({item['legacy'] for item in overlaps},
                         {'.cursorrules', '.windsurfrules'})


class HygieneTests(AuditCase):
    def test_raw_home_paths_and_secrets_are_redacted(self):
        secret = 'sk-' + 'a' * 24
        self.write('.claude/rules/risky.md',
                   'Never commit ' + '/' + 'Users' + '/alice/private notes.\n'
                   'token=' + secret + '\n')
        self.write('.claude/rules/clean.md', 'Contact dev@example.com for help.\n')
        self.commit()
        hits = self.ok_audit()['hygiene']['redaction_hits']
        risky = [h for h in hits if h['file'] == '.claude/rules/risky.md']
        self.assertEqual(len(risky), 2)
        for hit in risky:
            self.assertIn('[REDACTED]', hit['redacted'])
        self.assertFalse(any(h['file'] == '.claude/rules/clean.md' for h in hits))

    def test_clean_instructions_have_no_hits(self):
        self.assertEqual(self.ok_audit()['hygiene']['redaction_hits'], [])

    def test_bun_builtin_test_and_eval_flags_are_not_stale(self):
        self.write('package.json', '{"name": "fixture", "scripts": {"lint": "echo ok"}}\n')
        self.write('AGENTS.md', (
            '# Notes\n\n'
            '```sh\n'
            'bun test\n'
            'bun build\n'
            'node -e "console.log(\'a/b\')"\n'
            'perl -e \'s/foo/bar/\'\n'
            '```\n'
        ))
        self.commit()
        stale = [item for item in self.ok_audit()['references']['stale']
                 if item['file'] == 'AGENTS.md']
        self.assertEqual(stale, [])


class DocsCoverageTests(AuditCase):
    def test_docs_coverage_reports_manifests_and_gaps(self):
        self.write('package.json', '{"name": "fixture", "scripts": {}}\n')
        self.write('Makefile', 'test:\n\techo ok\n')
        self.write('CONTRIBUTING.md', 'Contribute.\n')
        self.write('docs/architecture.md', 'Architecture.\n')
        self.commit()
        data = self.ok_audit()['docs_coverage']
        self.assertIn('package.json', data['manifests'])
        self.assertIn('Makefile', data['manifests'])
        self.assertIn('AGENTS.md', data['present_docs'])
        self.assertIn('CONTRIBUTING.md', data['present_docs'])
        self.assertEqual(data['missing_recommended_docs'], [])
        self.assertTrue(data['has_command_examples'])
        self.assertGreaterEqual(data['docs_file_count'], 3)

    def test_missing_recommended_docs_are_reported(self):
        self.remove('README.md')
        self.commit()
        data = self.ok_audit()['docs_coverage']
        self.assertIn('README.md', data['missing_recommended_docs'])
        self.assertFalse(data['has_command_examples'])


class SelfAuditTests(AuditCase):
    """A fixture mimicking ds-agent-skills AGENTS.md / CONTRIBUTING.md must stay clean."""

    AGENTS = """# ds-agent-skills - notes for agents

`skills/ds-agent-docs/scripts/check_instructions.py` runs a read-only audit.
`scripts/collect_sessions.py` collects evidence. See [AGENTS.md](./AGENTS.md).

```sh
python3 -m unittest discover -s skills/ds-deps-upgrade/tests -t skills/ds-deps-upgrade
bash skills/ds-dev-protocol/tests/smoke.sh
diff -rq -x __pycache__ -x graft skills/<name> ~/.agents/skills/<name>
```

Skills live under `skills/<name>` and keep `SKILL.md` and `task-profile.json`.
Scripts: `scripts/depup.py`, `scripts/review_task.py`, `scripts/collect_sessions.py`,
`scripts/check_instructions.py`, `scripts/gate.sh`, `scripts/premerge-and-merge.sh`,
`scripts/implement.sh`, `tests/smoke.sh`, `tests/implement-smoke.sh`.
State: `runs.jsonl`, `state.json`, `launchd.log`, `.env`, `.DS_Store`.

A GitHub slug such as `Dropout-Studio-Co/ds-agent-skills` is not a path, and `Move.target` is prose.
"""

    CONTRIBUTING = """# Contributing

`ds-consolidate` and `ds-ui-overhaul` resolve `../ds-deps-upgrade/scripts/review_task.py`
and `task-profile.json`. Read [AGENTS.md](./AGENTS.md) for sync rules.

[Conventional Commits](https://www.conventionalcommits.org/) and [MIT](./LICENSE).
"""

    def test_agent_skills_fixture_has_no_stale_references(self):
        self.write('AGENTS.md', self.AGENTS)
        self.write('CONTRIBUTING.md', self.CONTRIBUTING)
        self.write('LICENSE', 'MIT\n')
        for rel in ('task-profile.json', 'skills/ds-deps-upgrade/scripts/review_task.py',
                    'skills/ds-deps-upgrade/scripts/depup.py',
                    'skills/ds-agent-docs/scripts/collect_sessions.py',
                    'skills/ds-agent-docs/scripts/check_instructions.py',
                    'skills/ds-dev-protocol/scripts/gate.sh',
                    'skills/ds-dev-protocol/scripts/premerge-and-merge.sh',
                    'skills/ds-dev-protocol/scripts/implement.sh',
                    'skills/ds-dev-protocol/tests/smoke.sh',
                    'skills/ds-dev-protocol/tests/implement-smoke.sh'):
            self.write(rel, 'placeholder\n')
        for rel in ('skills/ds-deps-upgrade/tests', 'skills/ds-dev-protocol/tests'):
            os.makedirs(os.path.join(self.repo, rel), exist_ok=True)
        self.commit()
        data = self.ok_audit()
        stale = [item for item in data['references']['stale']
                 if item['file'] in ('AGENTS.md', 'CONTRIBUTING.md')]
        self.assertEqual(stale, [])
        self.assertTrue(data['import']['ok'])
        self.assertEqual(data['structure']['dangling_imports'], [])


class ContractTests(AuditCase):
    def test_script_is_executable(self):
        self.assertTrue(os.access(SCRIPT, os.X_OK))

    def test_audit_is_read_only(self):
        before = subprocess.check_output(['git', 'status', '--porcelain'], cwd=self.repo,
                                         env=self.env, text=True)
        self.ok_audit()
        after = subprocess.check_output(['git', 'status', '--porcelain'], cwd=self.repo,
                                        env=self.env, text=True)
        self.assertEqual(before, after)

    def test_invalid_inputs_exit_two_with_json(self):
        code, payload = self.audit(repo=os.path.join(self.tmp, 'missing'))
        self.assertEqual(code, 2)
        self.assertEqual(payload['status'], 'invalid')
        code, payload = self.audit('--budget-tokens', '-1')
        self.assertEqual(code, 2)
        self.assertEqual(payload['status'], 'invalid')

    def test_legacy_subcommands_are_gone(self):
        for command in ('check', 'stage', 'gate', 'apply'):
            proc = subprocess.run([sys.executable, SCRIPT, command, '--repo', self.repo],
                                  capture_output=True, text=True, env=self.env)
            self.assertEqual(proc.returncode, 2, command)
            self.assertNotIn('"status": "ok"', proc.stdout)

    def test_docs_and_references_exist(self):
        for rel in ('references/audit-rubric.md', 'references/agent-surfaces.md'):
            self.assertTrue(os.path.isfile(os.path.join(SKILL_DIR, rel)), rel)
        with open(os.path.join(SKILL_DIR, 'SKILL.md'), encoding='utf-8') as handle:
            text = handle.read()
        self.assertIn('# Audit & Sync Agent Docs (`ds-agent-docs`)', text)
        self.assertIn('check_instructions.py audit', text)
        self.assertIn('--budget-tokens', text)
        self.assertNotIn('.backpassrc.json', text)
        for banned in ('claude-opus', 'claude-sonnet', 'claude-haiku', 'opus 5.5',
                       'claude -p', 'claude --bg', 'claude auth', 'claude agents',
                       'claude attach', 'review_router.py', 'routed_task.py',
                       'routing.json', '--effort', 'xhigh', 'deepseek'):
            self.assertNotIn(banned.lower(), text.lower(), banned)


if __name__ == '__main__':
    unittest.main()
