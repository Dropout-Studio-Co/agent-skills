"""check_instructions.py: delivery, evidence, references, claims, gates, apply and docs."""
import hashlib
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(HERE, 'scripts', 'check_instructions.py')
COLLECTOR = os.path.join(HERE, 'scripts', 'collect_sessions.py')
SKILL_DIR = HERE
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))

DEFAULT_AGENTS = (
    "# Fixture memory\n"
    "\n"
    "`AGENTS.md` is the source of truth for this repository.\n"
    "\n"
    "## Commands\n"
    "\n"
    "- Run `python3 -m unittest` before merging.\n"
)


def load_module(name, path):
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def digest_text(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


class CheckerCase(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix='checker-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo = os.path.join(self.tmp, 'repo')
        os.makedirs(self.repo)
        self.stage_dir = os.path.join(self.tmp, 'stage')
        self.private = os.path.join(self.tmp, 'private')
        os.makedirs(self.private, mode=0o700)
        self._inputs = 0
        self.git_env = {
            'GIT_AUTHOR_NAME': 'fixture', 'GIT_AUTHOR_EMAIL': 'fixture@example.test',
            'GIT_COMMITTER_NAME': 'fixture', 'GIT_COMMITTER_EMAIL': 'fixture@example.test',
            'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_SYSTEM': os.devnull,
        }
        self.write('AGENTS.md', DEFAULT_AGENTS)
        self.write('CLAUDE.md', '@AGENTS.md\n')
        self.git('init', '-q', '-b', 'main')
        self.git('add', '.')
        self.commit('init')
        self.repo_id = self.compute_repo_id()

    # -- fixtures ---------------------------------------------------------
    def git(self, *args, cwd=None):
        env = {k: v for k, v in os.environ.items()
               if k not in ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE', 'GIT_COMMON_DIR')}
        env.update(self.git_env)
        return subprocess.run(['git'] + list(args), cwd=cwd or self.repo, capture_output=True,
                              text=True, env=env, check=True)

    def commit(self, message):
        self.git('add', '-A')
        self.git('commit', '-qm', message)

    def write(self, rel, text):
        path = os.path.join(self.repo, rel)
        os.makedirs(os.path.dirname(path) or self.repo, exist_ok=True)
        with open(path, 'w', encoding='utf-8', newline='') as handle:
            handle.write(text)
        return path

    def read(self, rel):
        with open(os.path.join(self.repo, rel), encoding='utf-8', newline='') as handle:
            return handle.read()

    def compute_repo_id(self):
        out = self.git('rev-parse', '--git-common-dir').stdout.strip()
        common = out if os.path.isabs(out) else os.path.join(self.repo, out)
        return hashlib.sha256(os.path.realpath(common).encode('utf-8', 'replace')).hexdigest()

    def checker(self, *args, cwd=None):
        env = dict(os.environ)
        env.update({'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_SYSTEM': os.devnull})
        return subprocess.run([sys.executable, SCRIPT] + list(args), capture_output=True,
                              text=True, cwd=cwd or self.repo, env=env)

    def checker_env(self, extra, *args, cwd=None):
        env = dict(os.environ)
        env.update({'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_SYSTEM': os.devnull})
        env.update(extra)
        return subprocess.run([sys.executable, SCRIPT] + list(args), capture_output=True,
                              text=True, cwd=cwd or self.repo, env=env)

    def check(self):
        proc = self.checker('check', '--repo', self.repo, '--json')
        return proc.returncode, json.loads(proc.stdout)

    def stage(self):
        proc = self.checker('stage', '--repo', self.repo, '--out', self.stage_dir, '--json')
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        return json.loads(proc.stdout)

    def proposed(self, rel, text):
        path = os.path.join(self.stage_dir, 'proposed', rel)
        os.makedirs(os.path.dirname(path) or self.stage_dir, exist_ok=True)
        with open(path, 'w', encoding='utf-8', newline='') as handle:
            handle.write(text)

    def proposed_read(self, rel):
        with open(os.path.join(self.stage_dir, 'proposed', rel), encoding='utf-8',
                  newline='') as handle:
            return handle.read()

    def base_read(self, rel):
        with open(os.path.join(self.stage_dir, 'base', rel), encoding='utf-8',
                  newline='') as handle:
            return handle.read()

    def json_input(self, payload, name=None):
        self._inputs += 1
        name = name or 'input-%d.json' % self._inputs
        path = os.path.join(self.private, name)
        with open(path, 'w', encoding='utf-8') as handle:
            json.dump(payload, handle)
        return path

    def evidence(self, sessions=None, repo_id=None, name=None):
        payload = {
            'version': 1,
            'repo_id': repo_id if repo_id is not None else self.repo_id,
            'generated_at': '2026-01-01T00:00:00Z',
            'window_days': 60,
            'counts': {'total': len(sessions or []), 'interactive': len(sessions or []),
                       'headless': 0, 'excluded': 0, 'shown': len(sessions or []),
                       'opencode_v1_only': 0},
            'date_range': {'start': '2026-01-01', 'end': '2026-01-01'},
            'drift': [],
            'sessions': sessions or [],
        }
        self._inputs += 1
        name = name or 'evidence-%d.json' % self._inputs
        path = os.path.join(self.private, name)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        fd = os.open(path, flags, 0o600)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(payload, handle)
        return path

    def claims(self, claims, explained=None, name=None):
        return self.json_input({'version': 1, 'claims': claims,
                                'explained_stale': explained or []}, name)

    def gate(self, claims, explained=None, sessions=None):
        evidence = self.evidence(sessions or [])
        claims_path = self.claims(claims, explained)
        self.last_evidence = evidence
        self.last_claims = claims_path
        proc = self.checker('gate', '--stage', self.stage_dir, '--evidence', evidence,
                            '--claims', claims_path, '--json')
        return proc.returncode, json.loads(proc.stdout)

    def apply(self):
        proc = self.checker('apply', '--stage', self.stage_dir, '--json')
        return proc.returncode, proc.stdout

    def codes(self, payload):
        return {finding.get('code') for finding in payload.get('findings', [])}

    def session(self, sid, text=None, group=None, messages=None, errors=None, kind='interactive'):
        human = messages if messages is not None else ([self.message(text)] if text else [])
        return {'id': sid, 'source': sid.split(':', 1)[0], 'kind': kind,
                'date': '2026-01-01', 'group': group or sid, 'human': human,
                'errors': errors or []}

    def message(self, text, msg=None, correction=False):
        return {'msg': msg or digest_text(text)[:16], 'text': text, 'correction': correction}

    def snapshot(self):
        files = {}
        for dirpath, dirnames, filenames in os.walk(self.repo):
            dirnames[:] = [d for d in dirnames if d != '.git']
            for name in filenames:
                path = os.path.join(dirpath, name)
                rel = os.path.relpath(path, self.repo)
                with open(path, 'rb') as handle:
                    files[rel] = hashlib.sha256(handle.read()).hexdigest()
        return files

    def git_state(self):
        head = self.git('rev-parse', 'HEAD').stdout.strip()
        refs = self.git('show-ref').stdout
        status = self.git('status', '--porcelain').stdout
        return head, refs, status


class CommandContractTests(CheckerCase):
    """A8: CLI contract, exit codes, executable bit and read-only commands."""

    def test_script_is_executable(self):
        mode = stat.S_IMODE(os.stat(SCRIPT).st_mode)
        self.assertTrue(mode & 0o111, oct(mode))
        self.assertTrue(os.access(SCRIPT, os.X_OK))

    def test_check_returns_the_documented_json(self):
        code, payload = self.check()
        self.assertEqual(code, 0)
        self.assertEqual(payload['version'], 1)
        self.assertEqual(payload['status'], 'ok')
        for key in ('id', 'kind', 'head', 'default_branch'):
            self.assertIn(key, payload['repo'])
        for key in ('action', 'reason', 'dirty', 'commands'):
            self.assertIn(key, payload['delivery'])
        for key in ('tokens', 'cap', 'over'):
            self.assertIn(key, payload['budget'])
        for key in ('ok', 'errors'):
            self.assertIn(key, payload['import'])
        self.assertIsInstance(payload['references'], list)
        self.assertIsInstance(payload['leads'], list)
        self.assertIsInstance(payload['user_global_candidates'], list)

    def test_stage_creates_a_private_stage(self):
        payload = self.stage()
        self.assertEqual(payload['status'], 'ok')
        self.assertEqual(stat.S_IMODE(os.stat(self.stage_dir).st_mode), 0o700)
        with open(os.path.join(self.stage_dir, 'manifest.json'), encoding='utf-8') as handle:
            manifest = json.loads(handle.read())
        self.assertEqual(manifest['repo']['id'], self.repo_id)
        paths = [entry['path'] for entry in manifest['files']]
        self.assertIn('AGENTS.md', paths)
        self.assertIn('CLAUDE.md', paths)
        self.assertTrue(os.path.isfile(os.path.join(self.stage_dir, 'base', 'AGENTS.md')))
        self.assertTrue(os.path.isfile(os.path.join(self.stage_dir, 'proposed', 'AGENTS.md')))

    def test_stage_refuses_an_existing_or_in_repo_destination(self):
        os.makedirs(self.stage_dir)
        code, _ = self.checker('stage', '--repo', self.repo, '--out', self.stage_dir,
                               '--json').returncode, None
        self.assertEqual(code, 2)
        inside = os.path.join(self.repo, 'stage-here')
        proc = self.checker('stage', '--repo', self.repo, '--out', inside, '--json')
        self.assertEqual(proc.returncode, 2)
        self.assertFalse(os.path.exists(inside))

    def test_gate_rejects_invalid_or_unsafe_claims_with_exit_two(self):
        self.stage()
        evidence = self.evidence([])
        gate_path = os.path.join(self.stage_dir, 'gate.json')
        inside = os.path.join(self.repo, 'claims.json')
        with open(inside, 'w', encoding='utf-8') as handle:
            json.dump({'version': 1, 'claims': [], 'explained_stale': []}, handle)
        proc = self.checker('gate', '--stage', self.stage_dir, '--evidence', evidence,
                            '--claims', inside, '--json')
        self.assertEqual(proc.returncode, 2, proc.stdout)
        self.assertFalse(os.path.exists(gate_path))
        real = self.claims([])
        link = os.path.join(self.private, 'claims-link.json')
        os.symlink(real, link)
        proc = self.checker('gate', '--stage', self.stage_dir, '--evidence', evidence,
                            '--claims', link, '--json')
        self.assertEqual(proc.returncode, 2, proc.stdout)
        self.assertFalse(os.path.exists(gate_path))
        broken = os.path.join(self.private, 'claims-broken.json')
        with open(broken, 'w', encoding='utf-8') as handle:
            handle.write('{not json')
        proc = self.checker('gate', '--stage', self.stage_dir, '--evidence', evidence,
                            '--claims', broken, '--json')
        self.assertEqual(proc.returncode, 2, proc.stdout)
        self.assertFalse(os.path.exists(gate_path))

    def test_gate_rejects_missing_evidence_and_apply_rejects_a_missing_gate(self):
        self.stage()
        claims_path = self.claims([])
        proc = self.checker('gate', '--stage', self.stage_dir, '--evidence',
                            os.path.join(self.private, 'absent.json'), '--claims', claims_path,
                            '--json')
        self.assertEqual(proc.returncode, 2)
        proc = self.checker('apply', '--stage', self.stage_dir, '--json')
        self.assertEqual(proc.returncode, 2)

    def test_check_stage_and_gate_leave_the_repository_byte_identical(self):
        before = self.snapshot()
        head_before, refs_before, status_before = self.git_state()
        self.check()
        self.assertEqual(self.snapshot(), before)
        self.stage()
        evidence = self.evidence([])
        claims_path = self.claims([])
        self.checker('gate', '--stage', self.stage_dir, '--evidence', evidence,
                     '--claims', claims_path, '--json')
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.git_state(), (head_before, refs_before, status_before))


class ReferenceClassificationTests(CheckerCase):
    """A9: one case per reference class, then the gate rules."""

    def setUp(self):
        super().setUp()
        self.write('skills/consolidate/SKILL.md', '---\nname: consolidate\ndescription: plan\n---\n')
        self.write('nested/unique_helper.py', 'VALUE = 1\n')
        self.write('nested/second_helper.py', 'VALUE = 2\n')
        with open(os.path.join(self.repo, '.gitignore'), 'a', encoding='utf-8') as handle:
            handle.write('.local-state/\n')
        self.write('AGENTS.md', DEFAULT_AGENTS + (
            '\n## References\n\n'
            '- `skills/consolidate/SKILL.md`\n'
            '- `.local-state/run.json`\n'
            '- `unique_helper.py`\n'
            '- `https://example.test/doc`\n'
            '- `src/missing.py`\n'
            '\n```sh\n'
            'mysterytool --fast\n'
            '```\n'))
        self.commit('references')

    def reference_classes(self):
        _code, payload = self.check()
        return {item['ref']: item['class'] for item in payload['references']}

    def test_every_reference_class(self):
        classes = self.reference_classes()
        self.assertEqual(classes['skills/consolidate/SKILL.md'], 'ok')
        self.assertEqual(classes['.local-state/run.json'], 'ignored')
        self.assertEqual(classes['unique_helper.py'], 'scoped')
        self.assertEqual(classes['https://example.test/doc'], 'external')
        self.assertEqual(classes['src/missing.py'], 'stale')
        self.assertEqual(classes['mysterytool --fast'], 'unverified')

    def test_added_stale_and_unverified_references_block(self):
        self.stage()
        base = self.base_read('AGENTS.md')
        stale_line = '- See `src/missing.py` for details.'
        self.proposed('AGENTS.md', base + stale_line + '\n')
        claim = {'id': 'a1', 'type': 'Add', 'file': 'AGENTS.md',
                 'removed': [], 'added': [stale_line], 'basis': 'sessions',
                 'citations': []}
        code, payload = self.gate([claim])
        self.assertEqual(code, 1)
        self.assertIn('reference_stale', self.codes(payload))

    def test_script_runner_commands_are_classified_by_their_script_path(self):
        self.write('scripts/tool.sh', '#!/bin/sh\n')
        self.commit('script')
        self.write('AGENTS.md', DEFAULT_AGENTS + (
            '\n## Scripts\n\n'
            '- Run `bash scripts/tool.sh` before merging.\n'
            '- Run `python3 -m unittest discover -s tests` too.\n'
            '- Never run `bash scripts/missing.sh`.\n'))
        self.commit('script commands')
        classes = self.reference_classes()
        self.assertEqual(classes['bash scripts/tool.sh'], 'ok')
        self.assertEqual(classes['python3 -m unittest discover -s tests'], 'external')
        self.assertEqual(classes['bash scripts/missing.sh'], 'stale')

    def test_added_unverified_command_in_a_fence_blocks(self):
        self.stage()
        base = self.base_read('AGENTS.md')
        block = ['```sh', 'mysterytool --fast', '```']
        self.proposed('AGENTS.md', base + '\n' + '\n'.join(block) + '\n')
        claim = {'id': 'a1', 'type': 'Add', 'file': 'AGENTS.md', 'removed': [],
                 'added': block, 'basis': 'sessions', 'citations': []}
        code, payload = self.gate([claim])
        self.assertEqual(code, 1)
        self.assertIn('reference_unverified', self.codes(payload))

    def test_existing_stale_reference_must_be_fixed_or_explained(self):
        self.write('AGENTS.md', DEFAULT_AGENTS + '\n- See `src/missing.py` for details.\n')
        self.commit('stale')
        self.stage()
        code, payload = self.gate([])
        self.assertEqual(code, 1)
        self.assertIn('existing_stale', self.codes(payload))

        os.remove(self.stage_dir + '/gate.json')
        code, payload = self.gate([], explained=[{'file': 'AGENTS.md',
                                                  'ref': 'src/missing.py',
                                                  'reason': 'removed upstream'}])
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload['status'], 'no_change')

    def test_existing_stale_reference_can_be_fixed(self):
        self.write('AGENTS.md', DEFAULT_AGENTS + '\n- See `src/missing.py` for details.\n')
        self.commit('stale')
        self.stage()
        old = '- See `src/missing.py` for details.'
        new = '- See `skills/consolidate/SKILL.md` for details.'
        self.proposed('AGENTS.md', self.base_read('AGENTS.md').replace(old, new))
        claim = {'id': 'f1', 'type': 'Fix', 'file': 'AGENTS.md', 'removed': [old],
                 'added': [new], 'basis': 'reference'}
        code, payload = self.gate([claim])
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload['status'], 'pass')

    def test_explained_stale_references_in_several_files_pass(self):
        self.write('.agents/skills/demo/SKILL.md',
                   '---\nname: demo\ndescription: demo\n---\n\n'
                   '- See `src/other-missing.py` for details.\n')
        self.write('AGENTS.md', DEFAULT_AGENTS + '\n- See `src/missing.py` for details.\n')
        self.commit('stale references')
        self.stage()
        code, payload = self.gate([], explained=[
            {'file': 'AGENTS.md', 'ref': 'src/missing.py', 'reason': 'removed upstream'},
            {'file': '.agents/skills/demo/SKILL.md', 'ref': 'src/other-missing.py',
             'reason': 'removed upstream'}])
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload['status'], 'no_change')
        self.assertNotIn('existing_stale', self.codes(payload))

    def test_existing_ok_references_are_only_reported(self):
        self.write('AGENTS.md', DEFAULT_AGENTS
                   + '- Read `skills/consolidate/SKILL.md` and `https://example.test/doc`.\n')
        self.commit('clean references')
        self.stage()
        line = '- Check `skills/consolidate/SKILL.md` again.'
        self.proposed('AGENTS.md', self.base_read('AGENTS.md') + line + '\n')
        claim = {'id': 'a1', 'type': 'Add', 'file': 'AGENTS.md', 'removed': [],
                 'added': [line], 'basis': 'repo_proof',
                 'proof': {'file': 'skills/consolidate/SKILL.md', 'contains': 'consolidate'}}
        code, payload = self.gate([claim])
        self.assertEqual(code, 0, payload)
        self.assertTrue(payload['reported'])


class RedactedExplainTests(CheckerCase):
    """V2 replay: an explained stale reference may be named in redacted form."""

    def test_explained_stale_accepts_the_redacted_ref(self):
        address = 'alice' + '@' + 'example.test'
        self.write('AGENTS.md', DEFAULT_AGENTS + '\n- Contact `' + address + '` for access.\n')
        self.commit('stale contact')
        _code, payload = self.check()
        refs = {item['ref'] for item in payload['references']}
        self.assertIn('[REDACTED]', refs)
        self.stage()
        code, payload = self.gate([], explained=[{'file': 'AGENTS.md', 'ref': '[REDACTED]',
                                                  'reason': 'the contact has moved'}])
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload['status'], 'no_change')


class ShellFenceTests(CheckerCase):
    """V2 replay: only shell fences are parsed as commands."""

    def references(self):
        _code, payload = self.check()
        return payload['references']

    def test_plain_fence_with_a_tree_is_not_a_command(self):
        tree = ['```', 'repo', '├── routes/', '└── src/', '```']
        self.write('AGENTS.md', DEFAULT_AGENTS + '\n' + '\n'.join(tree) + '\n')
        self.commit('tree')
        refs = [item['ref'] for item in self.references()]
        self.assertNotIn('├── routes/', refs)
        self.assertNotIn('└── src/', refs)

    def test_text_fence_is_not_a_command(self):
        tree = ['```text', '├── routes/', '└── src/', '```']
        self.write('AGENTS.md', DEFAULT_AGENTS + '\n' + '\n'.join(tree) + '\n')
        self.commit('tree')
        refs = [item['ref'] for item in self.references()]
        self.assertNotIn('├── routes/', refs)

    def test_sh_fence_still_classifies_commands(self):
        block = ['```sh', 'mysterytool --fast', '```']
        self.write('AGENTS.md', DEFAULT_AGENTS + '\n' + '\n'.join(block) + '\n')
        self.commit('command')
        classes = {item['ref']: item['class'] for item in self.references()}
        self.assertEqual(classes['mysterytool --fast'], 'unverified')


class StaleFenceTests(CheckerCase):
    """Round 1 review: a stale command inside a shell fence can be fixed or removed."""

    def setUp(self):
        super().setUp()
        self.write('package.json', json.dumps(
            {'name': 'x', 'scripts': {'build': 'true', 'test': 'true'}}))
        self.old = 'npm run old-script'
        self.write('AGENTS.md', DEFAULT_AGENTS + '\n```sh\n' + self.old + '\n```\n')
        self.commit('stale fence')

    def test_stale_fence_command_can_be_fixed(self):
        self.stage()
        self.proposed('AGENTS.md', self.base_read('AGENTS.md').replace(
            self.old, 'npm run build'))
        claim = {'id': 'f1', 'type': 'Fix', 'file': 'AGENTS.md',
                 'removed': [self.old], 'added': ['npm run build'],
                 'basis': 'reference'}
        code, payload = self.gate([claim])
        self.assertEqual(code, 0, payload)

    def test_stale_fence_command_can_be_removed(self):
        self.stage()
        self.proposed('AGENTS.md', self.base_read('AGENTS.md').replace(
            self.old + '\n', ''))
        claim = {'id': 'r1', 'type': 'Remove', 'file': 'AGENTS.md',
                 'removed': [self.old], 'added': [], 'basis': 'repo_disproof'}
        code, payload = self.gate([claim])
        self.assertEqual(code, 0, payload)

    def test_a_valid_fence_command_is_not_a_disproof(self):
        self.stage()
        self.proposed('AGENTS.md', self.base_read('AGENTS.md').replace(
            self.old + '\n', ''))
        claim = {'id': 'r1', 'type': 'Remove', 'file': 'AGENTS.md',
                 'removed': [self.old], 'added': [], 'basis': 'repo_disproof'}
        self.write('package.json', json.dumps(
            {'name': 'x', 'scripts': {'old-script': 'true', 'build': 'true'}}))
        self.commit('script exists now')
        code, payload = self.gate([claim])
        self.assertEqual(code, 1, payload)
        self.assertIn('remove_unsupported', self.codes(payload))


class ImportCheckTests(CheckerCase):
    """A10: import pass and fail matrix, including nested memory files."""

    def import_report(self):
        _code, payload = self.check()
        return payload['import']

    def test_import_first_non_comment_line_passes(self):
        self.write('CLAUDE.md', '<!-- bridge -->\n\n@AGENTS.md\n')
        self.commit('comment bridge')
        self.assertTrue(self.import_report()['ok'])

    def test_symlink_to_sibling_agents_passes(self):
        os.remove(os.path.join(self.repo, 'CLAUDE.md'))
        os.symlink('AGENTS.md', os.path.join(self.repo, 'CLAUDE.md'))
        self.commit('symlink bridge')
        self.assertTrue(self.import_report()['ok'])

    def test_backticked_import_fails(self):
        self.write('CLAUDE.md', '`@AGENTS.md`\n')
        self.commit('backticked')
        report = self.import_report()
        self.assertFalse(report['ok'])
        self.assertIn('backticked import', [error['error'] for error in report['errors']])

    def test_missing_import_and_missing_file_fail(self):
        self.write('CLAUDE.md', '# Claude only\n')
        self.commit('no import')
        report = self.import_report()
        self.assertFalse(report['ok'])
        self.assertIn('missing @AGENTS.md import',
                      [error['error'] for error in report['errors']])
        os.remove(os.path.join(self.repo, 'AGENTS.md'))
        self.commit('no agents')
        report = self.import_report()
        self.assertFalse(report['ok'])
        self.assertIn('missing AGENTS.md', [error['error'] for error in report['errors']])

    def test_symlink_elsewhere_fails(self):
        self.write('OTHER.md', '@AGENTS.md\n')
        os.remove(os.path.join(self.repo, 'CLAUDE.md'))
        os.symlink('OTHER.md', os.path.join(self.repo, 'CLAUDE.md'))
        self.commit('wrong symlink')
        report = self.import_report()
        self.assertFalse(report['ok'])
        self.assertIn('symlink points elsewhere',
                      [error['error'] for error in report['errors']])

    def test_duplicated_line_fails(self):
        shared = '- Always run the collector tests after changing the collector.'
        self.write('AGENTS.md', DEFAULT_AGENTS + shared + '\n')
        self.write('CLAUDE.md', '@AGENTS.md\n' + shared + '\n')
        self.commit('duplicate')
        report = self.import_report()
        self.assertFalse(report['ok'])
        self.assertIn('line duplicated from AGENTS.md',
                      [error['error'] for error in report['errors']])

    def test_nested_agents_without_claude_fails(self):
        self.write('sub/AGENTS.md', '# Sub\n\n- Keep this subtree tidy.\n')
        self.commit('nested orphan')
        report = self.import_report()
        self.assertFalse(report['ok'])
        self.assertTrue(any(error['file'] == 'sub/CLAUDE.md'
                            and error['error'] == 'missing CLAUDE.md import'
                            for error in report['errors']), report)

    def test_nested_import_fix_reads_the_sibling_agents(self):
        duplicate = '- Keep this subtree tidy.'
        self.write('sub/AGENTS.md', '# Sub\n\n' + duplicate + '\n')
        self.write('sub/CLAUDE.md', '@AGENTS.md\n' + duplicate + '\n')
        self.commit('duplicated nested line')
        self.stage()
        self.proposed('sub/CLAUDE.md', '@AGENTS.md\n')
        claim = {'id': 'f1', 'type': 'Fix', 'file': 'sub/CLAUDE.md',
                 'removed': [duplicate], 'added': [], 'basis': 'import'}
        code, payload = self.gate([claim])
        self.assertEqual(code, 0, payload)

    def test_gate_blocks_broken_imports_in_the_proposed_tree(self):
        self.stage()
        self.proposed('CLAUDE.md', '`@AGENTS.md`\n')
        claim = {'id': 'f1', 'type': 'Fix', 'file': 'CLAUDE.md',
                 'removed': ['@AGENTS.md'], 'added': ['`@AGENTS.md`'], 'basis': 'import'}
        code, payload = self.gate([claim])
        self.assertEqual(code, 1)
        self.assertIn('import_check', self.codes(payload))

    def test_gate_accepts_a_symlinked_claude_md(self):
        os.remove(os.path.join(self.repo, 'CLAUDE.md'))
        os.symlink('AGENTS.md', os.path.join(self.repo, 'CLAUDE.md'))
        self.write('package.json', json.dumps({'name': 'x', 'marker': 'needle'}))
        self.commit('symlinked bridge')
        self.stage()
        line = '- The needle marker is documented in `AGENTS.md`.'
        self.proposed('AGENTS.md', self.base_read('AGENTS.md') + line + '\n')
        claim = {'id': 'a1', 'type': 'Add', 'file': 'AGENTS.md', 'removed': [],
                 'added': [line], 'basis': 'repo_proof',
                 'proof': {'file': 'package.json', 'contains': 'needle'}}
        code, payload = self.gate([claim])
        self.assertEqual(code, 0, payload)

    def test_nested_memory_files_get_the_same_check(self):
        self.write('sub/AGENTS.md', '# Sub\n\n- Keep this subtree tidy.\n')
        self.write('sub/CLAUDE.md', '@AGENTS.md\n')
        self.commit('nested ok')
        self.assertTrue(self.import_report()['ok'])
        self.write('sub/CLAUDE.md', '`@AGENTS.md`\n')
        self.commit('nested bad')
        report = self.import_report()
        self.assertFalse(report['ok'])
        self.assertTrue(any(error['file'] == 'sub/CLAUDE.md' for error in report['errors']))


class SurfaceExclusionTests(CheckerCase):
    """V2 replay: scratch and nested worktree copies never join the surface."""

    def surface(self):
        module = load_module('checker_for_surface', SCRIPT)
        return module.surface_paths(self.repo)

    def test_scratch_and_nested_worktree_copies_are_not_surface_files(self):
        self.write('.backpass/synthesis/AGENTS.md', '# Scratch\n')
        self.write('.claude/worktrees/foo/AGENTS.md', '# Worktree\n')
        self.write('.claude/worktrees/foo/.git', 'gitdir: elsewhere\n')
        self.write('.worktrees/bar/AGENTS.md', '# Worktree\n')
        self.write('.worktrees/bar/.git', 'gitdir: elsewhere\n')
        self.write('vendored/repo/AGENTS.md', '# Vendored\n')
        os.makedirs(os.path.join(self.repo, 'vendored', 'repo', '.git'))
        paths = self.surface()
        self.assertNotIn('.backpass/synthesis/AGENTS.md', paths)
        self.assertNotIn('.claude/worktrees/foo/AGENTS.md', paths)
        self.assertNotIn('.worktrees/bar/AGENTS.md', paths)
        self.assertNotIn('vendored/repo/AGENTS.md', paths)
        _code, payload = self.check()
        self.assertTrue(payload['import']['ok'], payload['import'])

    def test_root_surface_still_includes_nested_memory_files(self):
        self.write('sub/AGENTS.md', '# Sub\n\n- Keep this subtree tidy.\n')
        self.write('sub/CLAUDE.md', '@AGENTS.md\n')
        paths = self.surface()
        self.assertIn('sub/AGENTS.md', paths)
        self.assertIn('sub/CLAUDE.md', paths)


class SymlinkEscapeTests(CheckerCase):
    """Round 1 review: symlinked directories never escape the repository root."""

    def outside_skill(self):
        outside = os.path.join(self.tmp, 'outside-skills')
        os.makedirs(os.path.join(outside, 'demo'), exist_ok=True)
        with open(os.path.join(outside, 'demo', 'SKILL.md'), 'w', encoding='utf-8') as handle:
            handle.write('---\nname: demo\ndescription: demo\n---\n')
        return outside

    def test_symlinked_skills_directory_is_not_a_surface(self):
        outside = self.outside_skill()
        os.makedirs(os.path.join(self.repo, '.agents'), exist_ok=True)
        os.symlink(outside, os.path.join(self.repo, '.agents', 'skills'))
        module = load_module('checker_for_escape', SCRIPT)
        self.assertFalse(module.is_surface_path('.agents/skills/demo/SKILL.md', self.repo))
        out = self.stage()
        self.assertNotIn('.agents/skills/demo/SKILL.md', out['files'])

    def test_symlinked_skill_child_is_skipped(self):
        outside = self.outside_skill()
        os.makedirs(os.path.join(self.repo, '.agents', 'skills'), exist_ok=True)
        os.symlink(os.path.join(outside, 'demo'),
                   os.path.join(self.repo, '.agents', 'skills', 'demo'))
        out = self.stage()
        self.assertNotIn('.agents/skills/demo/SKILL.md', out['files'])

    def test_configured_skills_dir_cannot_escape_through_a_symlink(self):
        outside = self.outside_skill()
        os.symlink(outside, os.path.join(self.repo, 'skills-link'))
        self.write('.backpassrc.json', json.dumps({'skillsDir': 'skills-link'}))
        self.commit('unsafe skills dir')
        module = load_module('checker_for_skills_dir', SCRIPT)
        self.assertFalse(module.is_surface_path('skills-link/demo/SKILL.md', self.repo))
        out = self.stage()
        self.assertNotIn('skills-link/demo/SKILL.md', out['files'])

    def test_directory_symlink_escape_is_refused_by_gate(self):
        outside = os.path.join(self.tmp, 'outside-sub')
        os.makedirs(outside, exist_ok=True)
        os.symlink(outside, os.path.join(self.repo, 'sub'))
        self.stage()
        self.proposed('sub/AGENTS.md', '# Sub\n')
        proc = self.checker('gate', '--stage', self.stage_dir,
                            '--evidence', self.evidence([]),
                            '--claims', self.claims([]), '--json')
        self.assertEqual(proc.returncode, 2, proc.stdout)

    def test_git_and_backpass_paths_are_not_surface(self):
        module = load_module('checker_for_hidden_paths', SCRIPT)
        self.assertFalse(module.is_surface_path('.git/AGENTS.md', self.repo))
        self.assertFalse(module.is_surface_path('.backpass/AGENTS.md', self.repo))
        self.assertFalse(module.is_surface_path('.worktrees/x/AGENTS.md', self.repo))
        self.assertFalse(module.is_surface_path('.claude/worktrees/x/AGENTS.md', self.repo))
        self.stage()
        claim = {'id': 'r1', 'type': 'Remove', 'file': '.git/AGENTS.md',
                 'removed': ['- x'], 'added': [], 'basis': 'repo_disproof'}
        proc = self.checker('gate', '--stage', self.stage_dir,
                            '--evidence', self.evidence([]),
                            '--claims', self.claims([claim]), '--json')
        self.assertEqual(proc.returncode, 2, proc.stdout)


class ImportScopeTests(CheckerCase):
    """V2 replay: only imports in touched or newly broken directories block."""

    def broken_template(self):
        self.write('starters/demo/AGENTS.md', '# Demo\n\n- Demo line.\n')
        self.write('starters/demo/CLAUDE.md', '# Claude only\n')
        self.write('package.json', json.dumps({'name': 'x', 'marker': 'needle'}))
        self.commit('broken template')

    def test_unrelated_valid_edit_ignores_a_preexisting_template_error(self):
        self.broken_template()
        self.stage()
        line = '- The needle marker is documented in `AGENTS.md`.'
        self.proposed('AGENTS.md', self.base_read('AGENTS.md') + line + '\n')
        claim = {'id': 'a1', 'type': 'Add', 'file': 'AGENTS.md', 'removed': [],
                 'added': [line], 'basis': 'repo_proof',
                 'proof': {'file': 'package.json', 'contains': 'needle'}}
        code, payload = self.gate([claim])
        self.assertEqual(code, 0, payload)
        self.assertNotIn('import_check', self.codes(payload))

    def test_breaking_a_touched_import_still_blocks(self):
        self.stage()
        self.proposed('CLAUDE.md', '`@AGENTS.md`\n')
        claim = {'id': 'f1', 'type': 'Fix', 'file': 'CLAUDE.md',
                 'removed': ['@AGENTS.md'], 'added': ['`@AGENTS.md`'], 'basis': 'import'}
        code, payload = self.gate([claim])
        self.assertEqual(code, 1)
        self.assertIn('import_check', self.codes(payload))

    def test_new_nested_agents_without_a_bridge_blocks(self):
        self.write('package.json', json.dumps({'name': 'x', 'marker': 'needle'}))
        self.commit('proof')
        self.stage()
        line = '- Keep `AGENTS.md` and the needle marker in sync.'
        self.proposed('sub/AGENTS.md', line + '\n')
        claim = {'id': 'a1', 'type': 'Add', 'file': 'sub/AGENTS.md', 'removed': [],
                 'added': [line], 'basis': 'repo_proof',
                 'proof': {'file': 'package.json', 'contains': 'needle'}}
        code, payload = self.gate([claim])
        self.assertEqual(code, 1)
        self.assertIn('import_check', self.codes(payload))


class BudgetTests(CheckerCase):
    """A11: byte accounting, cap parsing and the two budget gates."""

    def setUp(self):
        super().setUp()
        self.write('AGENTS.md', 'aaaa')
        os.remove(os.path.join(self.repo, 'CLAUDE.md'))
        os.symlink('AGENTS.md', os.path.join(self.repo, 'CLAUDE.md'))
        self.write('.agents/skills/demo/SKILL.md',
                   '---\nname: demo\ndescription: "12345678"\n---\n\nbody\n')
        self.commit('budget')

    def test_tokens_count_bytes_and_a_symlink_once(self):
        _code, payload = self.check()
        self.assertEqual(payload['budget']['tokens'], 3)
        self.assertEqual(payload['budget']['cap'], 5000)

    def test_multibyte_text_is_counted_in_bytes(self):
        self.write('AGENTS.md', 'é' * 8)  # 16 UTF-8 bytes
        self.commit('multibyte')
        _code, payload = self.check()
        self.assertEqual(payload['budget']['tokens'], 6)  # 16 + 8 = 24 bytes

    def test_invalid_and_valid_budget_tokens(self):
        self.write('.backpassrc.json', json.dumps({'budgetTokens': 'many'}))
        self.commit('bad cap')
        _code, payload = self.check()
        self.assertEqual(payload['budget']['cap'], 5000)
        self.write('.backpassrc.json', json.dumps({'budgetTokens': 123}))
        self.commit('good cap')
        _code, payload = self.check()
        self.assertEqual(payload['budget']['cap'], 123)

    def test_edit_from_under_the_cap_that_ends_over_is_blocked(self):
        self.write('.backpassrc.json', json.dumps({'budgetTokens': 50}))
        self.commit('cap')
        self.stage()
        line = '- ' + 'z' * 400
        self.proposed('AGENTS.md', self.base_read('AGENTS.md') + '\n' + line + '\n')
        claim = {'id': 'a1', 'type': 'Add', 'file': 'AGENTS.md', 'removed': [],
                 'added': [line], 'basis': 'sessions', 'citations': []}
        code, payload = self.gate([claim], sessions=[
            self.session('claude-code:1',
                         messages=[self.message('typed message here', msg='m1')])])
        self.assertEqual(code, 1)
        self.assertIn('budget_over', self.codes(payload))

    def test_over_cap_surface_must_end_strictly_smaller(self):
        self.write('.backpassrc.json', json.dumps({'budgetTokens': 1}))
        self.commit('tiny cap')
        self.stage()
        line = '- another line'
        self.proposed('AGENTS.md', self.base_read('AGENTS.md') + line + '\n')
        claim = {'id': 'a1', 'type': 'Add', 'file': 'AGENTS.md', 'removed': [],
                 'added': [line], 'basis': 'sessions', 'citations': []}
        code, payload = self.gate([claim], sessions=[
            self.session('claude-code:1',
                         messages=[self.message('typed message here', msg='m1')])])
        self.assertEqual(code, 1)
        self.assertIn('budget_not_smaller', self.codes(payload))


class ClaimContractTests(CheckerCase):
    """A12: hunks, phantom lines, unknown keys and unknown types."""

    def test_unmapped_hunk_blocks(self):
        self.stage()
        self.proposed('AGENTS.md', self.base_read('AGENTS.md') + '- an unclaimed line\n')
        code, payload = self.gate([])
        self.assertEqual(code, 1)
        self.assertIn('unmapped_hunk', self.codes(payload))

    def test_phantom_claim_line_blocks(self):
        self.stage()
        line = '- never in the file'
        self.write('AGENTS.md', DEFAULT_AGENTS + line + '\n')
        self.commit('base line')
        # Re-stage from the new base, then claim a line that is not there.
        shutil.rmtree(self.stage_dir)
        self.stage()
        self.proposed('AGENTS.md', self.base_read('AGENTS.md') + '- a real added line\n')
        claim = {'id': 'r1', 'type': 'Remove', 'file': 'AGENTS.md',
                 'removed': ['- a phantom removed line'], 'added': [],
                 'basis': 'repo_disproof'}
        code, payload = self.gate([claim])
        self.assertEqual(code, 1)
        self.assertIn('phantom_line', self.codes(payload))

    def test_a_claimed_line_that_the_diff_leaves_in_place_is_phantom(self):
        self.stage()
        unchanged = '`AGENTS.md` is the source of truth for this repository.'
        claim = {'id': 'c1', 'type': 'Compress', 'file': 'AGENTS.md',
                 'removed': [unchanged], 'added': []}
        code, payload = self.gate([claim])
        self.assertEqual(code, 1)
        self.assertIn('phantom_line', self.codes(payload))

    def test_a_stale_line_left_in_place_fails_phantom_and_existing_stale(self):
        stale = '- See `src/missing.py` for details.'
        self.write('AGENTS.md', DEFAULT_AGENTS + '\n' + stale + '\n')
        self.commit('stale')
        self.stage()
        claim = {'id': 'r1', 'type': 'Remove', 'file': 'AGENTS.md',
                 'removed': [stale], 'added': [], 'basis': 'repo_disproof'}
        code, payload = self.gate([claim])
        self.assertEqual(code, 1)
        self.assertIn('phantom_line', self.codes(payload))
        self.assertIn('existing_stale', self.codes(payload))

    def test_added_lines_that_redaction_would_change_are_blocked(self):
        self.write('package.json', json.dumps({'name': 'x', 'marker': 'needle'}))
        self.commit('proof')
        samples = ['gh' + 'p_' + 'a' * 36, 'alice' + '@' + 'example.test',
                   '/' + 'Users' + '/alice/private']
        for sample in samples:
            with self.subTest(sample):
                if os.path.isdir(self.stage_dir):
                    shutil.rmtree(self.stage_dir)
                self.stage()
                line = '- The needle note mentions ' + sample + '.'
                self.proposed('AGENTS.md', self.base_read('AGENTS.md') + line + '\n')
                claim = {'id': 'a1', 'type': 'Add', 'file': 'AGENTS.md', 'removed': [],
                         'added': [line], 'basis': 'repo_proof',
                         'proof': {'file': 'package.json', 'contains': 'needle'}}
                code, payload = self.gate([claim])
                self.assertEqual(code, 1, payload)
                self.assertIn('redaction_triggered', self.codes(payload))

    def test_unknown_claim_key_and_type_block(self):
        self.stage()
        self.proposed('AGENTS.md', self.base_read('AGENTS.md') + '- added\n')
        claim = {'id': 'a1', 'type': 'Add', 'file': 'AGENTS.md', 'removed': [],
                 'added': ['- added'], 'basis': 'sessions', 'citations': [], 'wibble': 1}
        code, payload = self.gate([claim])
        self.assertEqual(code, 1)
        self.assertIn('claim_schema', self.codes(payload))

        os.remove(os.path.join(self.stage_dir, 'gate.json'))
        claim = {'id': 'a1', 'type': 'Rewrite', 'file': 'AGENTS.md', 'removed': [],
                 'added': ['- added'], 'basis': 'sessions'}
        code, payload = self.gate([claim])
        self.assertEqual(code, 1)
        self.assertIn('claim_schema', self.codes(payload))


class QuoteGateTests(CheckerCase):
    """A13: quote validity, one human message, and verbatim additions."""

    LINE = '- Verify `skills/consolidate/SKILL.md` before editing routing profiles.'
    Q1 = 'verify the routing profiles before editing them'
    Q2 = 'the routing profiles broke again after editing'

    def setUp(self):
        super().setUp()
        self.write('skills/consolidate/SKILL.md', '---\nname: consolidate\ndescription: plan\n---\n')
        self.commit('skill')
        self.sessions = [
            self.session('claude-code:one', messages=[self.message(self.Q1, msg='a1')]),
            self.session('claude-code:two', messages=[self.message(self.Q2, msg='b1')]),
            self.session('claude-code:three', messages=[self.message('unrelated assistant chatter here', msg='c1')],
                         errors=['error text mentions routing profiles before editing']),
        ]

    def run_add(self, citations, added=None, sessions=None):
        self.stage()
        added = added or [self.LINE]
        self.proposed('AGENTS.md', self.base_read('AGENTS.md') + '\n'.join(added) + '\n')
        claim = {'id': 'a1', 'type': 'Add', 'file': 'AGENTS.md', 'removed': [],
                 'added': added, 'basis': 'sessions', 'citations': citations}
        return self.gate([claim], sessions=sessions if sessions is not None else self.sessions)

    def test_two_related_quotes_pass(self):
        code, payload = self.run_add([
            {'session': 'claude-code:one', 'quote': self.Q1},
            {'session': 'claude-code:two', 'quote': self.Q2}])
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload['status'], 'pass')

    def test_wrong_session_blocks(self):
        code, payload = self.run_add([
            {'session': 'claude-code:nope', 'quote': self.Q1},
            {'session': 'claude-code:two', 'quote': self.Q2}])
        self.assertEqual(code, 1)
        self.assertIn('add_unsupported', self.codes(payload))

    def test_error_text_never_satisfies_a_quote(self):
        code, payload = self.run_add([
            {'session': 'claude-code:three', 'quote': 'error text mentions routing profiles'},
            {'session': 'claude-code:two', 'quote': self.Q2}])
        self.assertEqual(code, 1)
        self.assertIn('add_unsupported', self.codes(payload))

    def test_a_quote_must_fit_inside_one_message(self):
        code, payload = self.run_add([
            {'session': 'claude-code:one', 'quote': 'verify the routing profiles broke again'},
            {'session': 'claude-code:two', 'quote': self.Q2}])
        self.assertEqual(code, 1)
        self.assertIn('add_unsupported', self.codes(payload))

    def test_too_short_elided_and_redacted_quotes_fail(self):
        for bad in ('routing profiles', 'verify ... editing', 'verify [REDACTED] profiles'):
            with self.subTest(bad):
                if os.path.isdir(self.stage_dir):
                    shutil.rmtree(self.stage_dir)
                code, payload = self.run_add([
                    {'session': 'claude-code:one', 'quote': bad},
                    {'session': 'claude-code:two', 'quote': self.Q2}])
                self.assertEqual(code, 1)
                self.assertIn('add_unsupported', self.codes(payload))

    def test_verbatim_quote_in_an_added_line_blocks(self):
        code, payload = self.run_add([
            {'session': 'claude-code:one', 'quote': self.Q1},
            {'session': 'claude-code:two', 'quote': self.Q2}],
            added=[self.Q1])
        self.assertEqual(code, 1)
        self.assertIn('quote_verbatim', self.codes(payload))

    def test_a_quote_with_the_word_redact_passes(self):
        first = 'please do not redact the helper names in logs'
        second = 'the helper names in logs are useful'
        sessions = [
            self.session('claude-code:one', messages=[self.message(first, msg='r1')]),
            self.session('claude-code:two', messages=[self.message(second, msg='r2')]),
        ]
        line = '- Use `skills/consolidate/SKILL.md` when the helper names in logs matter.'
        code, payload = self.run_add([
            {'session': 'claude-code:one', 'quote': first},
            {'session': 'claude-code:two', 'quote': second}], added=[line], sessions=sessions)
        self.assertEqual(code, 0, payload)

    def test_a_bad_citation_aside_valid_ones_is_reported(self):
        code, payload = self.run_add([
            {'session': 'claude-code:one', 'quote': self.Q1},
            {'session': 'claude-code:two', 'quote': self.Q2},
            {'session': 'claude-code:one', 'quote': 'routing profiles'}])
        self.assertEqual(code, 1)
        self.assertIn('quote_invalid', self.codes(payload))


class AddGateTests(CheckerCase):
    """A14: Add bases, dedupe and user-global blocking."""

    LINE = '- Keep `skills/consolidate/SKILL.md` in sync with the planner.'

    def setUp(self):
        super().setUp()
        self.write('skills/consolidate/SKILL.md', '---\nname: consolidate\ndescription: plan\n---\n')
        self.write('package.json', json.dumps({'scripts': {'test': 'true'}}))
        self.write('.trail/learnings/one.md', '---\nstatus: active\nscope: repo\n---\n\nLearning.\n')
        self.write('.trail/learnings/old.md', '---\nstatus: retired\nscope: repo\n---\n\nOld.\n')
        self.commit('add fixtures')
        self.quote = 'keep the consolidate planner in sync'
        self.sessions = [
            self.session('claude-code:a', messages=[self.message(self.quote, msg='a1')]),
            self.session('claude-code:b', messages=[self.message('skills in sync with planner', msg='b1')]),
        ]

    def run_add(self, claim, sessions=None, added=None):
        self.stage()
        added = added or [self.LINE]
        self.proposed('AGENTS.md', self.base_read('AGENTS.md') + '\n'.join(added) + '\n')
        claim = dict(claim)
        claim.setdefault('id', 'a1')
        claim.setdefault('type', 'Add')
        claim.setdefault('file', 'AGENTS.md')
        claim.setdefault('removed', [])
        claim['added'] = added
        return self.gate([claim], sessions=sessions if sessions is not None else self.sessions)

    def test_two_distinct_sessions_pass(self):
        code, payload = self.run_add({
            'basis': 'sessions',
            'citations': [{'session': 'claude-code:a', 'quote': self.quote},
                          {'session': 'claude-code:b',
                           'quote': 'skills in sync with planner'}]})
        self.assertEqual(code, 0, payload)

    def test_one_session_twice_and_forks_count_once(self):
        code, payload = self.run_add({
            'basis': 'sessions',
            'citations': [{'session': 'claude-code:a', 'quote': self.quote},
                          {'session': 'claude-code:a', 'quote': self.quote}]})
        self.assertEqual(code, 1)
        self.assertIn('add_unsupported', self.codes(payload))

        forked = [
            self.session('claude-code:a', group='shared', messages=[self.message(self.quote, msg='a1')]),
            self.session('claude-code:c', group='shared',
                         messages=[self.message('skills in sync with planner', msg='c1')]),
        ]
        if os.path.isdir(self.stage_dir):
            shutil.rmtree(self.stage_dir)
        code, payload = self.run_add({
            'basis': 'sessions',
            'citations': [{'session': 'claude-code:a', 'quote': self.quote},
                          {'session': 'claude-code:c', 'quote': 'skills in sync with planner'}]},
            sessions=forked)
        self.assertEqual(code, 1)
        self.assertIn('add_unsupported', self.codes(payload))

    def test_copied_message_ids_count_once(self):
        copied = [
            self.session('claude-code:a', messages=[self.message(self.quote, msg='same')]),
            self.session('claude-code:b', messages=[self.message(self.quote, msg='same')]),
        ]
        code, payload = self.run_add({
            'basis': 'sessions',
            'citations': [{'session': 'claude-code:a', 'quote': self.quote},
                          {'session': 'claude-code:b', 'quote': self.quote}]},
            sessions=copied)
        self.assertEqual(code, 1)
        self.assertIn('add_unsupported', self.codes(payload))

    def test_correction_basis_needs_a_correction_quote_with_the_anchor(self):
        sessions = [self.session(
            'claude-code:a',
            messages=[self.message("That's wrong, `skills/consolidate/SKILL.md` is the one",
                                   msg='a1', correction=True)])]
        code, payload = self.run_add({
            'basis': 'correction',
            'citations': [{'session': 'claude-code:a',
                           'quote': "That's wrong, `skills/consolidate/SKILL.md` is the one"}]},
            sessions=sessions)
        self.assertEqual(code, 0, payload)

        if os.path.isdir(self.stage_dir):
            shutil.rmtree(self.stage_dir)
        sessions = [self.session('claude-code:a',
                                 messages=[self.message("That's wrong, use bun here, not npm",
                                                        msg='a1', correction=True)])]
        code, payload = self.run_add({
            'basis': 'correction',
            'citations': [{'session': 'claude-code:a',
                           'quote': "That's wrong, use bun here, not npm"}]},
            sessions=sessions)
        self.assertEqual(code, 1)
        self.assertIn('add_unsupported', self.codes(payload))

    def test_repo_proof_basis(self):
        proof_line = '- The planner reads `skills/consolidate/SKILL.md` with true profiles.'
        code, payload = self.run_add({
            'basis': 'repo_proof',
            'proof': {'file': 'skills/consolidate/SKILL.md', 'contains': 'consolidate'}},
            added=[proof_line])
        self.assertEqual(code, 0, payload)

        if os.path.isdir(self.stage_dir):
            shutil.rmtree(self.stage_dir)
        code, payload = self.run_add({
            'basis': 'repo_proof',
            'proof': {'file': 'skills/consolidate/SKILL.md', 'contains': 'not-there'}},
            added=[proof_line])
        self.assertEqual(code, 1)
        self.assertIn('add_unsupported', self.codes(payload))

    def test_trail_basis_needs_an_active_repo_learning(self):
        code, payload = self.run_add({
            'basis': 'trail', 'trail': '.trail/learnings/one.md'})
        self.assertEqual(code, 0, payload)

        if os.path.isdir(self.stage_dir):
            shutil.rmtree(self.stage_dir)
        code, payload = self.run_add({
            'basis': 'trail', 'trail': '.trail/learnings/old.md'})
        self.assertEqual(code, 1)
        self.assertIn('add_unsupported', self.codes(payload))

    def test_trail_basis_rejects_unsafe_paths(self):
        self.write('.trail/notes/one.md', '---\nstatus: active\nscope: repo\n---\n')
        link = os.path.join(self.repo, '.trail', 'learnings', 'link.md')
        os.symlink(os.path.join(self.repo, '.trail', 'learnings', 'one.md'), link)
        self.commit('trail fixtures')
        unsafe = [
            os.path.join(self.repo, '.trail', 'learnings', 'one.md'),
            '.trail/learnings/../../AGENTS.md',
            '.trail/learnings/link.md',
            '.trail/notes/one.md',
        ]
        for path in unsafe:
            with self.subTest(path):
                if os.path.isdir(self.stage_dir):
                    shutil.rmtree(self.stage_dir)
                code, payload = self.run_add({'basis': 'trail', 'trail': path})
                self.assertEqual(code, 1, payload)
                self.assertIn('add_unsupported', self.codes(payload))

    def test_user_global_lines_are_blocked_and_reported(self):
        code, payload = self.run_add({
            'basis': 'sessions',
            'citations': [{'session': 'claude-code:a', 'quote': self.quote},
                          {'session': 'claude-code:b',
                           'quote': 'skills in sync with planner'}]},
            added=['- Always answer in a warm tone for every repo.'])
        self.assertEqual(code, 1)
        self.assertIn('user_global', self.codes(payload))


class RemoveGateTests(CheckerCase):
    """A15: disproof, harm, non_compliance and protected lines."""

    def setUp(self):
        super().setUp()
        self.stale = '- See `src/missing.py` for the old helper.'
        self.write('AGENTS.md', DEFAULT_AGENTS + '\n' + self.stale + '\n'
                   + '- Keep the fixture quiet.\n')
        self.commit('remove fixture')

    def test_repo_disproof_removes_a_stale_line(self):
        self.stage()
        proposed = self.base_read('AGENTS.md').replace(self.stale + '\n', '')
        self.proposed('AGENTS.md', proposed)
        claim = {'id': 'r1', 'type': 'Remove', 'file': 'AGENTS.md',
                 'removed': [self.stale], 'added': [], 'basis': 'repo_disproof'}
        code, payload = self.gate([claim])
        self.assertEqual(code, 0, payload)

    def test_repo_disproof_rejects_a_valid_line_beside_a_stale_one(self):
        valid = '- Keep the fixture quiet.'
        self.stage()
        proposed = self.base_read('AGENTS.md').replace(self.stale + '\n', '')
        proposed = proposed.replace(valid + '\n', '')
        self.proposed('AGENTS.md', proposed)
        claim = {'id': 'r1', 'type': 'Remove', 'file': 'AGENTS.md',
                 'removed': [self.stale, valid], 'added': [], 'basis': 'repo_disproof'}
        code, payload = self.gate([claim])
        self.assertEqual(code, 1)
        self.assertIn('remove_unsupported', self.codes(payload))

    def test_corroborated_harm_needs_two_correction_sessions(self):
        line = '- Keep the fixture quiet.'
        self.write('AGENTS.md', DEFAULT_AGENTS + '\n' + line + '\n')
        self.commit('clean base')
        self.stage()
        self.proposed('AGENTS.md', self.base_read('AGENTS.md').replace(line + '\n', ''))
        sessions = [
            self.session('claude-code:a',
                         messages=[self.message('stop keeping the fixture quiet', msg='a1',
                                                correction=True)]),
            self.session('claude-code:b',
                         messages=[self.message('keeping the fixture quiet is wrong', msg='b1',
                                                correction=True)]),
        ]
        claim = {'id': 'r1', 'type': 'Remove', 'file': 'AGENTS.md', 'removed': [line],
                 'added': [], 'basis': 'corroborated_harm',
                 'citations': [{'session': 'claude-code:a',
                                'quote': 'stop keeping the fixture quiet'},
                               {'session': 'claude-code:b',
                                'quote': 'keeping the fixture quiet is wrong'},
                               {'session': 'claude-code:a', 'quote': 'quiet'}]}
        code, payload = self.gate([claim], sessions=sessions)
        self.assertEqual(code, 1)
        self.assertIn('quote_invalid', self.codes(payload))

        claim['citations'] = claim['citations'][:2]
        code, payload = self.gate([claim], sessions=sessions)
        self.assertEqual(code, 0, payload)

    def test_non_compliance_and_other_bases_are_blocked(self):
        self.stage()
        self.proposed('AGENTS.md', self.base_read('AGENTS.md').replace(self.stale + '\n', ''))
        claim = {'id': 'r1', 'type': 'Remove', 'file': 'AGENTS.md',
                 'removed': [self.stale], 'added': [], 'basis': 'non_compliance'}
        code, payload = self.gate([claim])
        self.assertEqual(code, 1)
        self.assertIn('remove_basis', self.codes(payload))

    def test_protected_line_cannot_be_removed(self):
        protected = '- Never put secrets in the fixture.'
        self.write('AGENTS.md', DEFAULT_AGENTS + '\n' + self.stale + '\n' + protected + '\n')
        self.commit('protected')
        self.stage()
        self.proposed('AGENTS.md', self.base_read('AGENTS.md').replace(protected + '\n', ''))
        claim = {'id': 'r1', 'type': 'Remove', 'file': 'AGENTS.md',
                 'removed': [protected], 'added': [], 'basis': 'repo_disproof'}
        code, payload = self.gate([claim])
        self.assertEqual(code, 1)
        self.assertIn('remove_protected', self.codes(payload))


class ClaimScopeTests(CheckerCase):
    """Round 1 review: claim types cannot carry the other direction's lines."""

    def test_add_with_removed_lines_is_blocked(self):
        self.stage()
        self.proposed('AGENTS.md', self.base_read('AGENTS.md') + '- a new line\n')
        claim = {'id': 'a1', 'type': 'Add', 'file': 'AGENTS.md',
                 'removed': ['- a line that should not be here'],
                 'added': ['- a new line'], 'basis': 'sessions', 'citations': []}
        code, payload = self.gate([claim])
        self.assertEqual(code, 1, payload)
        self.assertIn('add_has_removed', self.codes(payload))

    def test_remove_with_added_lines_is_blocked(self):
        stale = '- See `src/missing.py` for details.'
        self.write('AGENTS.md', DEFAULT_AGENTS + '\n' + stale + '\n')
        self.commit('stale')
        self.stage()
        self.proposed('AGENTS.md', self.base_read('AGENTS.md').replace(
            stale + '\n', '- replacement line\n'))
        claim = {'id': 'r1', 'type': 'Remove', 'file': 'AGENTS.md',
                 'removed': [stale], 'added': ['- replacement line'],
                 'basis': 'repo_disproof'}
        code, payload = self.gate([claim])
        self.assertEqual(code, 1, payload)
        self.assertIn('remove_has_added', self.codes(payload))

    def import_fixture(self):
        self.write('sub/AGENTS.md', '# Sub\n\n- Keep the subtree tidy.\n')
        self.write('sub/CLAUDE.md', '`@AGENTS.md`\n')
        self.commit('nested import')

    def test_import_fix_repairs_a_backticked_import(self):
        self.import_fixture()
        self.stage()
        self.proposed('sub/CLAUDE.md', '@AGENTS.md\n')
        claim = {'id': 'f1', 'type': 'Fix', 'file': 'sub/CLAUDE.md',
                 'removed': ['`@AGENTS.md`'], 'added': ['@AGENTS.md'],
                 'basis': 'import'}
        code, payload = self.gate([claim])
        self.assertEqual(code, 0, payload)

    def test_import_fix_cannot_inject_other_lines(self):
        self.import_fixture()
        self.stage()
        self.proposed('sub/CLAUDE.md', '@AGENTS.md\n- Use the shared logger.\n')
        claim = {'id': 'f1', 'type': 'Fix', 'file': 'sub/CLAUDE.md',
                 'removed': ['`@AGENTS.md`'],
                 'added': ['@AGENTS.md', '- Use the shared logger.'],
                 'basis': 'import'}
        code, payload = self.gate([claim])
        self.assertEqual(code, 1, payload)
        self.assertIn('import_invalid_added', self.codes(payload))


class SmallEditTests(CheckerCase):
    """A16: no_change, the five-claim cap and Compress rules."""

    def test_identical_content_is_no_change_and_apply_writes_nothing(self):
        before = self.snapshot()
        self.stage()
        code, payload = self.gate([])
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload['status'], 'no_change')
        code, _out = self.apply()
        self.assertEqual(code, 0)
        self.assertEqual(self.snapshot(), before)

    def test_an_over_budget_repository_allows_no_change(self):
        self.write('.backpassrc.json', json.dumps({'budgetTokens': 1}))
        self.commit('over cap')
        self.stage()
        code, payload = self.gate([])
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload['status'], 'no_change')

    def test_more_than_five_add_and_remove_claims_block(self):
        self.stage()
        added = ['- line %d' % index for index in range(6)]
        self.proposed('AGENTS.md', self.base_read('AGENTS.md') + '\n'.join(added) + '\n')
        claims = [{'id': 'a%d' % i, 'type': 'Add', 'file': 'AGENTS.md', 'removed': [],
                   'added': [line], 'basis': 'sessions', 'citations': []}
                  for i, line in enumerate(added)]
        code, payload = self.gate(claims)
        self.assertEqual(code, 1)
        self.assertIn('too_many_claims', self.codes(payload))

    def test_compress_and_move_are_blocked_under_budget(self):
        line = '- Keep the fixture quiet.'
        self.write('AGENTS.md', DEFAULT_AGENTS + '\n' + line + '\n')
        self.commit('compress fixture')
        self.stage()
        self.proposed('AGENTS.md', self.base_read('AGENTS.md').replace(line + '\n', ''))
        compress = {'id': 'c1', 'type': 'Compress', 'file': 'AGENTS.md', 'removed': [line],
                    'added': []}
        code, payload = self.gate([compress])
        self.assertEqual(code, 1)
        self.assertIn('compress_under_budget', self.codes(payload))

        if os.path.isdir(self.stage_dir):
            shutil.rmtree(self.stage_dir)
        self.stage()
        move = {'id': 'm1', 'type': 'Move', 'file': 'AGENTS.md', 'removed': [line],
                'added': [], 'target': 'sub/AGENTS.md'}
        self.proposed('AGENTS.md', self.base_read('AGENTS.md').replace(line + '\n', ''))
        self.proposed('sub/AGENTS.md', '# Sub\n\n' + line + '\n')
        self.proposed('sub/CLAUDE.md', '@AGENTS.md\n')
        code, payload = self.gate([move])
        self.assertEqual(code, 1)
        self.assertIn('move_under_budget', self.codes(payload))

    def test_compress_must_shrink_and_keep_tokens_paths_numbers_directives(self):
        extra = '- Extra words that can go away entirely here.'
        self.write('AGENTS.md', DEFAULT_AGENTS + '\n' + extra + '\n')
        self.write('.backpassrc.json', json.dumps({'budgetTokens': 1}))
        self.commit('over cap')
        self.stage()
        self.proposed('AGENTS.md', self.base_read('AGENTS.md').replace(extra + '\n', ''))
        claim = {'id': 'c1', 'type': 'Compress', 'file': 'AGENTS.md', 'removed': [extra],
                 'added': []}
        code, payload = self.gate([claim])
        self.assertEqual(code, 0, payload)

        if os.path.isdir(self.stage_dir):
            shutil.rmtree(self.stage_dir)
        self.stage()
        lost = '- Run `python3 -m unittest` before merging.'
        self.proposed('AGENTS.md', self.base_read('AGENTS.md').replace(lost + '\n', ''))
        claim = {'id': 'c1', 'type': 'Compress', 'file': 'AGENTS.md', 'removed': [lost],
                 'added': []}
        code, payload = self.gate([claim])
        self.assertEqual(code, 1)
        self.assertIn('compress_lost_token', self.codes(payload))


class MoveTests(CheckerCase):
    """A17: nested and skill moves, bridges, identity and protection."""

    def setUp(self):
        super().setUp()
        self.write('sub/helper.py', 'VALUE = 1\n')
        self.lines = ['- Use `sub/helper.py` for parsing.',
                      '- Keep `sub/helper.py` small.']
        self.write('AGENTS.md', DEFAULT_AGENTS + '\n## Subtree\n\n' + '\n'.join(self.lines) + '\n')
        self.write('.backpassrc.json', json.dumps({'budgetTokens': 1}))
        self.commit('move fixture')

    def rewrite_base_crlf(self):
        text = self.read('AGENTS.md')
        self.write('AGENTS.md', text.replace('\n', '\r\n'))
        self.commit('crlf base')

    def do_move(self, target, lines=None, bridge='@AGENTS.md\n', crlf=False, target_text=None):
        lines = lines or self.lines
        self.stage()
        base = self.base_read('AGENTS.md')
        remaining = base
        for line in lines:
            remaining = remaining.replace(line + '\r\n', '').replace(line + '\n', '')
        self.proposed('AGENTS.md', remaining)
        if target_text is None:
            body = '\r\n'.join(lines) + '\r\n' if crlf else '\n'.join(lines) + '\n'
            if target.endswith('SKILL.md'):
                body = '---\nname: moved\ndescription: moved procedure\n---\n' + body
            target_text = body
        self.proposed(target, target_text)
        if bridge is not None:
            directory = os.path.dirname(target)
            if directory:
                self.proposed(os.path.join(directory, 'CLAUDE.md'), bridge)
        claim = {'id': 'm1', 'type': 'Move', 'file': 'AGENTS.md', 'removed': lines,
                 'added': [], 'target': target}
        return self.gate([claim])

    def test_nested_move_with_a_bridge_passes(self):
        code, payload = self.do_move('sub/AGENTS.md')
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload['status'], 'pass')

    def test_move_is_byte_identical_with_crlf(self):
        self.rewrite_base_crlf()
        code, payload = self.do_move('sub/AGENTS.md', crlf=True)
        self.assertEqual(code, 0, payload)
        with open(os.path.join(self.stage_dir, 'proposed', 'sub', 'AGENTS.md'), 'rb') as handle:
            self.assertIn(b'\r\n', handle.read())

    def test_move_from_crlf_to_lf_is_blocked(self):
        self.rewrite_base_crlf()
        code, payload = self.do_move('sub/AGENTS.md', crlf=False)
        self.assertEqual(code, 1)
        self.assertIn('move_not_identical', self.codes(payload))

    def test_move_from_lf_to_crlf_is_blocked(self):
        code, payload = self.do_move('sub/AGENTS.md', crlf=True)
        self.assertEqual(code, 1)
        self.assertIn('move_not_identical', self.codes(payload))

    def test_skill_move_passes(self):
        code, payload = self.do_move('.agents/skills/moved/SKILL.md', bridge=None)
        self.assertEqual(code, 0, payload)

    def test_extra_line_in_a_move_target_blocks(self):
        target = 'sub/AGENTS.md'
        self.stage()
        base = self.base_read('AGENTS.md')
        remaining = base
        for line in self.lines:
            remaining = remaining.replace(line + '\n', '')
        self.proposed('AGENTS.md', remaining)
        self.proposed(target, '\n'.join(self.lines) + '\n- An extra unmoved line.\n')
        self.proposed('sub/CLAUDE.md', '@AGENTS.md\n')
        claim = {'id': 'm1', 'type': 'Move', 'file': 'AGENTS.md', 'removed': self.lines,
                 'added': [], 'target': target}
        code, payload = self.gate([claim])
        self.assertEqual(code, 1)
        self.assertIn('unmapped_hunk', self.codes(payload))

    def test_extra_added_lines_in_a_move_claim_block(self):
        target = 'sub/AGENTS.md'
        self.stage()
        remaining = self.base_read('AGENTS.md')
        for line in self.lines:
            remaining = remaining.replace(line + '\n', '')
        self.proposed('AGENTS.md', remaining)
        self.proposed(target, '\n'.join(self.lines) + '\n- An extra claimed line.\n')
        self.proposed('sub/CLAUDE.md', '@AGENTS.md\n')
        claim = {'id': 'm1', 'type': 'Move', 'file': 'AGENTS.md',
                 'removed': self.lines, 'added': ['- An extra claimed line.'],
                 'target': target}
        code, payload = self.gate([claim])
        self.assertEqual(code, 1, payload)
        self.assertIn('move_extra_added', self.codes(payload))

    def test_a_prefix_sibling_path_is_the_wrong_subtree(self):
        self.write('sub-other/helper.py', 'VALUE = 2\n')
        line = '- Keep `sub-other/helper.py` small.'
        self.write('AGENTS.md', self.read('AGENTS.md') + line + '\n')
        self.commit('prefix sibling')
        self.stage()
        self.proposed('AGENTS.md', self.base_read('AGENTS.md').replace(line + '\n', ''))
        self.proposed('sub/AGENTS.md', line + '\n')
        self.proposed('sub/CLAUDE.md', '@AGENTS.md\n')
        claim = {'id': 'm1', 'type': 'Move', 'file': 'AGENTS.md', 'removed': [line],
                 'added': [], 'target': 'sub/AGENTS.md'}
        code, payload = self.gate([claim])
        self.assertEqual(code, 1, payload)
        self.assertIn('move_wrong_subtree', self.codes(payload))

    def test_wrong_subtree_blocks(self):
        code, payload = self.do_move('other/AGENTS.md')
        self.assertEqual(code, 1)
        self.assertIn('move_wrong_subtree', self.codes(payload))

    def test_missing_bridge_blocks(self):
        code, payload = self.do_move('sub/AGENTS.md', bridge=None)
        self.assertEqual(code, 1)
        self.assertIn('move_missing_bridge', self.codes(payload))

    def test_in_place_apply_writes_the_moved_file_and_bridge(self):
        self.git('checkout', '-q', '-b', 'feat/move')
        code, payload = self.do_move('sub/AGENTS.md')
        self.assertEqual(code, 0, payload)
        code, out = self.apply()
        self.assertEqual(code, 0, out)
        self.assertTrue(os.path.isfile(os.path.join(self.repo, 'sub', 'AGENTS.md')))
        self.assertEqual(self.read('sub/CLAUDE.md'), '@AGENTS.md\n')
        self.assertNotIn(self.lines[0], self.read('AGENTS.md'))

    def test_protected_lines_cannot_move(self):
        protected = '- Never edit `sub/helper.py` by hand.'
        self.write('AGENTS.md', DEFAULT_AGENTS + '\n' + protected + '\n')
        self.commit('protected move')
        code, payload = self.do_move('sub/AGENTS.md', lines=[protected])
        self.assertEqual(code, 1)
        self.assertIn('move_protected', self.codes(payload))


class BackpassTests(CheckerCase):
    """A18: version 1 ledgers from the main checkout, routing and immutability."""

    def write_backpass(self, root, payload=None):
        directory = os.path.join(root, '.backpass')
        os.makedirs(directory, exist_ok=True)
        payload = payload or {'version': 1, 'gaps': [
            {'domain': 'all', 'instruction': "always run `python3 -m unittest` first",
             'source': 'claude-code:abc123', 'sessions': 2},
            {'domain': 'web', 'instruction': 'prefer the drawer', 'source': 'claude-code:def456',
             'sessions': 1},
        ]}
        with open(os.path.join(directory, 'gap-ledger.json'), 'w', encoding='utf-8') as handle:
            json.dump(payload, handle)
        with open(os.path.join(directory, 'evidence-summary.json'), 'w', encoding='utf-8') as handle:
            json.dump({'version': 1, 'entries': []}, handle)
        return directory

    def write_ledger(self, entries, summary=None):
        directory = os.path.join(self.repo, '.backpass')
        os.makedirs(directory, exist_ok=True)
        with open(os.path.join(directory, 'gap-ledger.json'), 'w', encoding='utf-8') as handle:
            json.dump({'version': 1, 'entries': entries}, handle)
        with open(os.path.join(directory, 'evidence-summary.json'), 'w',
                  encoding='utf-8') as handle:
            json.dump(summary or {'version': 1, 'gaps': []}, handle)
        return directory

    def test_real_gap_ledger_sightings_route_and_hide_project_paths(self):
        entries = {
            'gap-one': {
                'proposedInstruction': 'Run the collector tests before merging.',
                'sessions': {
                    'h1': {'domain': 'project',
                           'source': 'claude · uuid-one · 2026-11-06',
                           'project': '/very/secret/project', 'projectRoot': '/very/secret/root'},
                    'h2': {'domain': 'Project',
                           'source': 'claude · uuid-two · 2026-11-07',
                           'project': '/very/secret/other', 'projectRoot': '/very/secret/other'},
                },
            },
            'gap-two': {
                'proposedInstruction': 'Answer briefly in every repository.',
                'sessions': {
                    'h3': {'domain': 'orchestration',
                           'source': 'claude · uuid-three · 2026-11-08',
                           'project': '/very/secret/project', 'projectRoot': '/very/secret/project'},
                },
            },
        }
        directory = self.write_ledger(entries)
        before = {}
        for name in os.listdir(directory):
            with open(os.path.join(directory, name), 'rb') as handle:
                before[name] = hashlib.sha256(handle.read()).hexdigest()
        _code, payload = self.check()
        self.assertEqual(len(payload['leads']), 1)
        self.assertEqual(len(payload['user_global_candidates']), 1)
        lead = payload['leads'][0]
        self.assertEqual(lead['transcript'], 'uuid-one')
        self.assertEqual(lead['sessions'], 2)
        self.assertTrue(lead['unverified'])
        self.assertNotIn('secret', json.dumps(payload))
        for name in os.listdir(directory):
            with open(os.path.join(directory, name), 'rb') as handle:
                self.assertEqual(hashlib.sha256(handle.read()).hexdigest(), before[name])

    def test_evidence_summary_orchestration_sightings_route_to_candidates(self):
        summary = {
            'version': 1,
            'gaps': [
                {'proposedInstruction': 'Prefer the shared logger.', 'sessions': 2,
                 'orchestrationSightings': 0, 'mixed': False,
                 'majorityOrchestration': False},
                {'proposedInstruction': 'Always use tabs.', 'sessions': 3,
                 'orchestrationSightings': 2, 'mixed': True,
                 'majorityOrchestration': True},
            ],
            'reportOnlyGaps': [
                {'proposedInstruction': 'Consider a drawer instead.', 'sessions': 1,
                 'orchestrationSightings': 1, 'mixed': False,
                 'majorityOrchestration': False},
            ],
        }
        self.write_ledger({}, summary)
        _code, payload = self.check()
        self.assertIn('Prefer the shared logger.', [lead['proposedInstruction']
                                                   for lead in payload['leads']])
        candidates = [item['proposedInstruction']
                      for item in payload['user_global_candidates']]
        self.assertIn('Always use tabs.', candidates)
        self.assertIn('Consider a drawer instead.', candidates)

    def test_list_entries_with_project_domain_are_leads(self):
        self.write_backpass(self.repo, {'version': 1, 'gaps': [
            {'domain': 'project', 'instruction': 'Keep the helper beside its caller.',
             'source': 'claude-code:proj1', 'sessions': 1},
            {'domain': 'web', 'instruction': 'Prefer the drawer.', 'source': 'claude-code:web1',
             'sessions': 1},
        ]})
        _code, payload = self.check()
        self.assertEqual([lead['transcript'] for lead in payload['leads']], ['proj1'])
        self.assertEqual(len(payload['user_global_candidates']), 1)

    def test_project_and_other_domains_route_and_backpass_is_unchanged(self):
        directory = self.write_backpass(self.repo)
        before = {}
        for name in os.listdir(directory):
            with open(os.path.join(directory, name), 'rb') as handle:
                before[name] = hashlib.sha256(handle.read()).hexdigest()
        _code, payload = self.check()
        self.assertEqual(len(payload['leads']), 1)
        self.assertEqual(len(payload['user_global_candidates']), 1)
        lead = payload['leads'][0]
        self.assertEqual(lead['transcript'], 'abc123')
        self.assertTrue(lead['unverified'])
        for name in os.listdir(directory):
            with open(os.path.join(directory, name), 'rb') as handle:
                self.assertEqual(hashlib.sha256(handle.read()).hexdigest(), before[name])

    def test_linked_worktree_reads_the_main_checkout(self):
        self.write_backpass(self.repo)
        self.commit('backpass')
        worktree = os.path.join(self.tmp, 'linked')
        self.git('worktree', 'add', '-q', '-b', 'linked-branch', worktree)
        proc = self.checker('check', '--repo', worktree, '--json')
        payload = json.loads(proc.stdout)
        self.assertEqual(len(payload['leads']), 1)

    def test_symlinked_backpass_and_unsupported_version(self):
        real = os.path.join(self.private, 'backpass-real')
        os.makedirs(real)
        outside = os.path.join(self.tmp, 'ledger')
        os.makedirs(outside)
        with open(os.path.join(outside, 'gap-ledger.json'), 'w', encoding='utf-8') as handle:
            json.dump({'version': 2, 'gaps': [{'domain': 'all', 'instruction': 'skip me'}]},
                      handle)
        os.symlink(outside, os.path.join(self.repo, '.backpass'))
        _code, payload = self.check()
        self.assertTrue(any('unsupported version' in note for note in payload.get('notes', [])))
        self.assertEqual(payload['leads'], [])

    def test_lead_text_is_redacted(self):
        secret = 'gh' + 'p_' + 'c' * 36
        self.write_backpass(self.repo, {'version': 1, 'gaps': [
            {'domain': 'all', 'instruction': 'use ' + secret, 'source': 'claude-code:x',
             'sessions': 1}]})
        _code, payload = self.check()
        self.assertNotIn('c' * 36, json.dumps(payload))
        self.assertIn('[REDACTED]', payload['leads'][0]['proposedInstruction'])


class DeliveryTests(CheckerCase):
    """A19: every delivery branch, patch mode and no new commits or refs."""

    def test_task_branch_is_in_place(self):
        self.git('checkout', '-q', '-b', 'feat/one')
        _code, payload = self.check()
        self.assertEqual(payload['delivery']['action'], 'in_place')

    def test_main_only_repository_is_in_place(self):
        _code, payload = self.check()
        self.assertEqual(payload['delivery']['action'], 'in_place')

    def test_default_branch_with_a_written_pr_rule_uses_a_worktree(self):
        self.write('CONTRIBUTING.md', 'Open a pull request for every change to main.\n')
        self.commit('pr rule')
        _code, payload = self.check()
        self.assertEqual(payload['delivery']['action'], 'worktree')
        commands = ' '.join(payload['delivery']['commands'])
        self.assertIn('git worktree add -b docs/sync-agent-instructions-', commands)
        self.assertNotIn('/' + 'Users' + '/', commands)

    def test_detached_head_uses_a_worktree(self):
        self.git('checkout', '-q', '--detach')
        _code, payload = self.check()
        self.assertEqual(payload['delivery']['action'], 'worktree')

    def test_shell_metacharacter_default_branch_is_unknown(self):
        shutil.rmtree(self.repo)
        os.makedirs(self.repo)
        self.write('AGENTS.md', DEFAULT_AGENTS)
        self.write('CLAUDE.md', '@AGENTS.md\n')
        branch = 'evil;id'
        self.git('init', '-q', '-b', branch)
        self.git('add', '.')
        self.commit('evil branch')
        config = os.path.join(self.private, 'gitconfig')
        with open(config, 'w', encoding='utf-8') as handle:
            handle.write('[init]\n\tdefaultBranch = %s\n' % branch)
        proc = self.checker_env({'GIT_CONFIG_GLOBAL': config},
                                'check', '--repo', self.repo, '--json')
        payload = json.loads(proc.stdout)
        self.assertIsNone(payload['repo']['default_branch'])
        self.assertEqual(payload['delivery']['action'], 'patch_only')
        self.assertEqual(payload['delivery']['commands'], [])

    def test_worktree_commands_quote_every_argument(self):
        module = load_module('checker_for_worktree_commands', SCRIPT)

        class FakeRepo:
            root = Path(self.repo)
            default_branch = 'main'

        commands = module.worktree_commands(FakeRepo())
        self.assertEqual(len(commands), 2)
        fetch = shlex.split(commands[0])
        self.assertEqual(fetch[-1], 'main')
        add = shlex.split(commands[1])
        self.assertIn('origin/main', add)
        self.assertIn('"$HOME"', commands[1])

        class EvilRepo:
            root = Path(self.repo)
            default_branch = 'evil;id'

        self.assertEqual(module.worktree_commands(EvilRepo()), [])

    def test_global_init_default_branch_respects_existing_branches(self):
        shutil.rmtree(self.repo)
        os.makedirs(self.repo)
        self.write('AGENTS.md', DEFAULT_AGENTS)
        self.write('CLAUDE.md', '@AGENTS.md\n')
        self.git('init', '-q', '-b', 'master')
        self.git('add', '.')
        self.commit('master only')
        config = os.path.join(self.private, 'gitconfig')
        with open(config, 'w', encoding='utf-8') as handle:
            handle.write('[init]\n\tdefaultBranch = main\n')
        proc = self.checker_env({'GIT_CONFIG_GLOBAL': config},
                                'check', '--repo', self.repo, '--json')
        payload = json.loads(proc.stdout)
        self.assertEqual(payload['repo']['default_branch'], 'master')
        self.assertEqual(payload['delivery']['action'], 'in_place')

        shutil.rmtree(self.repo)
        os.makedirs(self.repo)
        self.write('AGENTS.md', DEFAULT_AGENTS)
        self.write('CLAUDE.md', '@AGENTS.md\n')
        self.git('init', '-q', '-b', 'trunk')
        self.git('add', '.')
        self.commit('trunk only')
        proc = self.checker_env({'GIT_CONFIG_GLOBAL': config},
                                'check', '--repo', self.repo, '--json')
        payload = json.loads(proc.stdout)
        self.assertIsNone(payload['repo']['default_branch'])
        self.assertEqual(payload['delivery']['action'], 'patch_only')

    def test_dirty_memory_file_and_unknown_default_use_patch_only(self):
        self.write('AGENTS.md', DEFAULT_AGENTS + '- dirty line\n')
        _code, payload = self.check()
        self.assertEqual(payload['delivery']['action'], 'patch_only')
        self.assertTrue(payload['delivery']['dirty'])

        shutil.rmtree(self.repo)
        os.makedirs(self.repo)
        self.write('AGENTS.md', DEFAULT_AGENTS)
        self.write('CLAUDE.md', '@AGENTS.md\n')
        self.git('init', '-q', '-b', 'trunk')
        self.git('add', '.')
        self.commit('trunk only')
        _code, payload = self.check()
        self.assertEqual(payload['delivery']['action'], 'patch_only')
        self.assertIn('unknown default branch', payload['delivery']['reason'])

    def trunk_repo(self):
        shutil.rmtree(self.repo)
        os.makedirs(self.repo)
        self.write('AGENTS.md', DEFAULT_AGENTS)
        self.write('CLAUDE.md', '@AGENTS.md\n')
        self.write('package.json', json.dumps({'name': 'x', 'marker': 'needle'}))
        self.git('init', '-q', '-b', 'trunk')
        self.git('add', '.')
        self.commit('trunk only')
        self.repo_id = self.compute_repo_id()

    def test_patch_only_leaves_the_file_and_writes_an_applicable_patch(self):
        self.trunk_repo()
        before = self.snapshot()
        self.stage()
        line = '- The needle marker lives beside `AGENTS.md`.'
        self.proposed('AGENTS.md', self.base_read('AGENTS.md') + line + '\n')
        claim = {'id': 'a1', 'type': 'Add', 'file': 'AGENTS.md', 'removed': [],
                 'added': [line], 'basis': 'repo_proof',
                 'proof': {'file': 'package.json', 'contains': 'needle'}}
        code, payload = self.gate([claim])
        self.assertEqual(code, 0, payload)
        code, out = self.apply()
        self.assertEqual(code, 0, out)
        self.assertEqual(json.loads(out)['status'], 'patched')
        self.assertEqual(self.snapshot(), before)
        with open(os.path.join(self.stage_dir, 'staged.patch'), encoding='utf-8') as handle:
            patch = handle.read()
        self.assertIn('AGENTS.md', patch)
        clone = os.path.join(self.tmp, 'clone')
        self.git('clone', '-q', self.repo, clone)
        applied = subprocess.run(['git', 'apply', '-p2', os.path.join(self.stage_dir,
                                                                     'staged.patch')],
                                 cwd=clone, capture_output=True, text=True)
        self.assertEqual(applied.returncode, 0, applied.stderr)
        with open(os.path.join(clone, 'AGENTS.md'), encoding='utf-8') as handle:
            self.assertIn('needle marker lives', handle.read())

    def test_dirty_file_is_left_untouched_by_apply(self):
        self.write('package.json', json.dumps({'name': 'x', 'marker': 'needle'}))
        self.git('add', '-A')
        self.commit('proof')
        self.write('AGENTS.md', DEFAULT_AGENTS + '- dirty local line\n')
        dirty = self.read('AGENTS.md')
        self.stage()
        line = '- The needle marker is documented in `AGENTS.md`.'
        self.proposed('AGENTS.md', self.base_read('AGENTS.md') + line + '\n')
        claim = {'id': 'a1', 'type': 'Add', 'file': 'AGENTS.md', 'removed': [],
                 'added': [line], 'basis': 'repo_proof',
                 'proof': {'file': 'package.json', 'contains': 'needle'}}
        code, payload = self.gate([claim])
        self.assertEqual(code, 0, payload)
        code, out = self.apply()
        self.assertEqual(code, 0, out)
        self.assertEqual(json.loads(out)['status'], 'patched')
        self.assertEqual(self.read('AGENTS.md'), dirty)

    def test_in_place_apply_writes_the_staged_edit_without_a_commit(self):
        self.git('checkout', '-q', '-b', 'feat/apply')
        self.write('package.json', json.dumps({'name': 'x', 'marker': 'needle'}))
        self.git('add', '-A')
        self.commit('proof')
        head = self.git('rev-parse', 'HEAD').stdout.strip()
        self.stage()
        line = '- Keep `AGENTS.md` free of needle drift.'
        self.proposed('AGENTS.md', self.base_read('AGENTS.md') + line + '\n')
        claim = {'id': 'a1', 'type': 'Add', 'file': 'AGENTS.md', 'removed': [],
                 'added': [line], 'basis': 'repo_proof',
                 'proof': {'file': 'package.json', 'contains': 'needle'}}
        code, payload = self.gate([claim])
        self.assertEqual(code, 0, payload)
        code, out = self.apply()
        self.assertEqual(code, 0, out)
        self.assertEqual(json.loads(out)['status'], 'applied')
        self.assertIn(line, self.read('AGENTS.md'))
        self.assertEqual(self.git('rev-parse', 'HEAD').stdout.strip(), head)

    def test_no_command_creates_a_commit_or_ref(self):
        head, refs, status = self.git_state()
        self.check()
        self.stage()
        self.gate([])
        self.apply()
        self.assertEqual(self.git_state(), (head, refs, status))


class ConcurrentEditTests(CheckerCase):
    """A20: live changes, tampering and replacement failure."""

    def passing_edit(self, rel='AGENTS.md'):
        self.write('package.json', json.dumps({'name': 'x', 'marker': 'needle'}))
        self.git('add', '-A')
        self.commit('proof')
        self.stage()
        line = '- Keep `AGENTS.md` free of needle drift.'
        self.proposed(rel, self.base_read(rel) + line + '\n')
        claim = {'id': 'a1', 'type': 'Add', 'file': rel, 'removed': [], 'added': [line],
                 'basis': 'repo_proof',
                 'proof': {'file': 'package.json', 'contains': 'needle'}}
        code, payload = self.gate([claim])
        self.assertEqual(code, 0, payload)
        return line

    def test_live_edit_blocks_apply_without_writing(self):
        self.passing_edit()
        live = self.read('AGENTS.md')
        self.write('AGENTS.md', live + '- edited after the gate\n')
        code, out = self.apply()
        payload = json.loads(out)
        self.assertEqual(code, 1)
        self.assertEqual(payload['status'], 'concurrent_edit')
        self.assertIn('edited after the gate', self.read('AGENTS.md'))

    def test_untouched_surface_file_change_is_a_concurrent_edit(self):
        line = self.passing_edit()
        self.write('CLAUDE.md', '@AGENTS.md\n<!-- touched after the gate -->\n')
        code, out = self.apply()
        payload = json.loads(out)
        self.assertEqual(code, 1)
        self.assertEqual(payload['status'], 'concurrent_edit')
        self.assertNotIn(line, self.read('AGENTS.md'))

    def test_a_checkout_that_now_needs_a_worktree_is_refused(self):
        self.write('CONTRIBUTING.md', 'Open a pull request for every change.\n')
        self.commit('pr rule')
        self.git('checkout', '-q', '-b', 'feat/two')
        line = self.passing_edit()
        self.git('checkout', '-q', 'main')
        code, out = self.apply()
        payload = json.loads(out)
        self.assertEqual(code, 1)
        self.assertEqual(payload['status'], 'wrong_checkout')
        self.assertNotIn(line, self.read('AGENTS.md'))

    def test_tampered_proposed_claims_and_evidence_are_refused(self):
        line = self.passing_edit()
        self.proposed('AGENTS.md', self.base_read('AGENTS.md') + line + '\n- tampered\n')
        code, _out = self.apply()
        self.assertEqual(code, 1)

    def test_tampered_claims_and_evidence_are_refused(self):
        self.passing_edit()
        with open(self.last_claims, 'rb') as handle:
            claims_bytes = handle.read()
        with open(self.last_claims, 'ab') as handle:
            handle.write(b' ')
        code, _out = self.apply()
        self.assertEqual(code, 1)
        with open(self.last_claims, 'wb') as handle:
            handle.write(claims_bytes)
        with open(self.last_evidence, 'ab') as handle:
            handle.write(b' ')
        code, _out = self.apply()
        self.assertEqual(code, 1)

    def test_failed_replacement_leaves_no_temp_file(self):
        self.write('sub/AGENTS.md', '# Sub\n\n- Sub line.\n')
        self.commit('sub base')
        self.stage()
        self.proposed('AGENTS.md', self.base_read('AGENTS.md') + '- first added line\n')
        self.proposed('sub/AGENTS.md', self.base_read('sub/AGENTS.md') + '- second line\n')
        module = load_module('checker_for_temp_cleanup', SCRIPT)
        stage = Path(self.stage_dir)
        manifest = module.load_manifest(stage)
        original = self.read('AGENTS.md')
        real_copy = module.shutil.copyfile
        calls = {'count': 0}

        def flaky(source, target):
            calls['count'] += 1
            if calls['count'] == 2:
                raise OSError('injected replacement failure')
            return real_copy(source, target)

        module.shutil.copyfile = flaky
        try:
            code, payload = module._write_in_place(
                stage, manifest, Path(self.repo),
                ['AGENTS.md', 'sub/AGENTS.md'])
        finally:
            module.shutil.copyfile = real_copy
        self.assertEqual(code, 1, payload)
        self.assertEqual(self.read('AGENTS.md'), original)
        leftovers = [name for name in os.listdir(os.path.join(self.repo, 'sub'))
                     if name.startswith('.sync-')]
        self.assertEqual(leftovers, [])

    def test_failed_replacement_restores_the_base(self):
        self.write('sub/AGENTS.md', '# Sub\n\n- Sub line.\n')
        self.write('sub/CLAUDE.md', '@AGENTS.md\n')
        self.write('package.json', json.dumps({'name': 'x', 'marker': 'needle'}))
        self.git('add', '-A')
        self.commit('sub')
        self.stage()
        first = '- Keep `AGENTS.md` free of needle one.'
        second = '- Keep `sub/AGENTS.md` free of needle two.'
        self.proposed('AGENTS.md', self.base_read('AGENTS.md') + first + '\n')
        self.proposed('sub/AGENTS.md', self.base_read('sub/AGENTS.md') + second + '\n')
        claims = [
            {'id': 'a1', 'type': 'Add', 'file': 'AGENTS.md', 'removed': [],
             'added': [first], 'basis': 'repo_proof',
             'proof': {'file': 'package.json', 'contains': 'needle'}},
            {'id': 'a2', 'type': 'Add', 'file': 'sub/AGENTS.md', 'removed': [],
             'added': [second], 'basis': 'repo_proof',
             'proof': {'file': 'package.json', 'contains': 'needle'}},
        ]
        code, payload = self.gate(claims)
        self.assertEqual(code, 0, payload)
        before = self.read('AGENTS.md')
        subdir = os.path.join(self.repo, 'sub')
        os.chmod(subdir, 0o500)
        self.addCleanup(os.chmod, subdir, 0o755)
        code, out = self.apply()
        self.assertEqual(code, 1)
        self.assertEqual(self.read('AGENTS.md'), before)


class SyncSafetyTests(unittest.TestCase):
    """A21: the skill folder contains nothing the sync would hold."""

    def hold_regex(self):
        fragments = [
            "/" + "Users" + "/",
            "/" + "home" + "/",
            "sk" + "-" + "ant" + "-",
            "gh" + "p_",
            "gh" + "o_",
            "github" + "_pat_",
            "AK" + "IA[0-9A-Z]{16}",
            "xo" + "x[abpr]-",
            "-----BEGIN " + "[A-Z ]*PRIVATE KEY-----",
        ]
        return re.compile("|".join(fragments))

    def test_the_hold_regex_catches_each_held_pattern(self):
        pattern = self.hold_regex()
        samples = [
            "/" + "Users" + "/alice/x",
            "/" + "home" + "/alice/x",
            "sk" + "-" + "ant" + "-" + "a" * 24,
            "gh" + "p_" + "a" * 36,
            "gh" + "o_" + "a" * 36,
            "github" + "_pat_" + "a" * 30,
            "AK" + "IA" + "A" * 16,
            "xo" + "x" + "b" + "-" + "a" * 12,
            "-----BEGIN " + "RSA PRIVATE KEY-----",
        ]
        for sample in samples:
            self.assertTrue(pattern.search(sample), sample)

    def test_the_hold_regex_catches_bare_prefixes(self):
        pattern = self.hold_regex()
        samples = [
            "/" + "Users" + "/",
            "/" + "home" + "/",
            "sk" + "-" + "ant" + "-",
            "gh" + "p_",
            "gh" + "o_",
            "github" + "_pat_",
            "AK" + "IA" + "A" * 16,
            "xo" + "x" + "b" + "-",
            "-----BEGIN " + "PRIVATE KEY-----",
        ]
        for sample in samples:
            self.assertTrue(pattern.search(sample), sample)

    def test_every_skill_file_is_free_of_held_literals(self):
        pattern = self.hold_regex()
        sample = "gh" + "p_" + "d" * 36
        self.assertTrue(pattern.search(sample), "the assembled regex must catch a sample")
        for dirpath, dirnames, filenames in os.walk(SKILL_DIR):
            dirnames[:] = [name for name in dirnames if name != '__pycache__']
            for name in filenames:
                path = os.path.join(dirpath, name)
                with open(path, encoding='utf-8', errors='replace') as handle:
                    text = handle.read()
                self.assertIsNone(pattern.search(text), path)

    def test_collector_has_no_literal_token_prefix_but_still_redacts(self):
        with open(COLLECTOR, encoding='utf-8') as handle:
            source = handle.read()
        self.assertNotIn("gh" + "p_", source)
        self.assertNotIn("github" + "_pat_", source)
        module = load_module('collector_for_redaction', COLLECTOR)
        samples = ("gh" + "p_" + "e" * 36,
                   "github" + "_pat_" + "A" * 30,
                   "shp" + "at_" + "b" * 20)
        for sample in samples:
            self.assertIn('[REDACTED]', module.redact('value ' + sample))


class DocsTests(unittest.TestCase):
    """A22 and A23: the skill workflow and the repository docs."""

    def test_skill_has_the_eight_stages_in_order(self):
        with open(os.path.join(SKILL_DIR, 'SKILL.md'), encoding='utf-8') as handle:
            text = handle.read()
        lowered = text.lower()
        stages = ['delivery state', 'evidence', 'check', 'claims',
                  'smallest staged edit', 'gate', 'apply', 'report']
        positions = [lowered.find(stage) for stage in stages]
        self.assertNotIn(-1, positions, positions)
        self.assertEqual(positions, sorted(positions))

    def test_skill_has_no_commit_push_pr_or_merge_instruction(self):
        with open(os.path.join(SKILL_DIR, 'SKILL.md'), encoding='utf-8') as handle:
            text = handle.read().lower()
        for banned in ('git commit', 'git push', 'gh pr create', 'git merge',
                       'premerge-and-merge'):
            self.assertNotIn(banned, text)

    def test_skill_frontmatter_version_four(self):
        with open(os.path.join(SKILL_DIR, 'SKILL.md'), encoding='utf-8') as handle:
            text = handle.read()
        self.assertIn('version: "4.0"', text)
        for key in ('name:', 'description:', 'license:'):
            self.assertIn(key, text)

    def test_docs_name_existing_files_and_commands(self):
        for name in ('AGENTS.md', 'README.md', 'CONTRIBUTING.md'):
            with open(os.path.join(REPO_ROOT, name), encoding='utf-8') as handle:
                text = handle.read()
            self.assertIn('check_instructions.py', text, name)
            self.assertIn('collect_sessions.py', text, name)
            self.assertTrue(os.path.isfile(SCRIPT), name)
            self.assertTrue(os.path.isfile(COLLECTOR), name)
            self.assertTrue(os.path.isdir(os.path.join(HERE, 'tests')), name)


class GateR2RegressionTests(unittest.TestCase):
    """Regressions caught in Review R2 and Security R2."""

    def test_script_runners_flag_with_argument_are_external(self):
        module = load_module('checker_r2_flags', SCRIPT)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.check_call(['git', 'init', '-q', str(root)])
            (root / 'scripts').mkdir()
            (root / 'scripts/run.py').write_text('print(1)\n', encoding='utf-8')
            subprocess.check_call(['git', '-C', str(root), 'add', 'scripts/run.py'])
            refs = module.References(root)
            for cmd in (
                'pytest -k test_foo',
                'pytest -k foo.py',
                'pytest -m slow',
                'pytest -o addopts=',
                'python3 -c "print(1)"',
                'python3 -c "import foo.bar"',
                'node -e "console.log(1)"',
                'bash -c "echo hi"',
                'bash -lc "cd /tmp && echo hi"',
                'sh -ec "export FOO=a/b"',
                'ruby -e "puts 1"',
                'php -r "echo 1;"',
                "git status # check what's changed",
                "pytest # repo's tests",
            ):
                self.assertEqual(refs.classify(cmd, 'AGENTS.md'), 'external', cmd)
            self.assertEqual(refs.classify('python3 scripts/run.py', 'AGENTS.md'), 'ok')
            self.assertEqual(refs.classify("python3 scripts/run.py # won't write", 'AGENTS.md'), 'ok')
            self.assertEqual(refs.classify('python3 -W default scripts/run.py', 'AGENTS.md'), 'ok')
            self.assertEqual(refs.classify('python3 scripts/missing.py', 'AGENTS.md'), 'stale')
            self.assertEqual(refs.classify('python3 scripts/missing.py # <todo>', 'AGENTS.md'), 'stale')
            self.assertEqual(refs.classify('gh pr checks <n> --watch', 'AGENTS.md'), 'scoped')

    def test_move_target_traversal_rejected_before_stage_read(self):
        module = load_module('checker_r2_move', SCRIPT)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo = tmp_path / 'repo'
            repo.mkdir()
            subprocess.check_call(['git', 'init', '-q', str(repo)])
            (repo / 'AGENTS.md').write_text('# Rules\n- Keep things simple.\n', encoding='utf-8')
            subprocess.check_call(['git', '-C', str(repo), 'add', 'AGENTS.md'])
            subprocess.check_call([
                'git', '-C', str(repo), '-c', 'user.name=t', '-c', 'user.email=t@example.invalid',
                'commit', '-qm', 'init'
            ])
            stage = tmp_path / 'stage'
            code, _ = module.stage_command(str(repo), str(stage))
            self.assertEqual(code, 0)
            manifest = json.loads((stage / 'manifest.json').read_text(encoding='utf-8'))
            ev = tmp_path / 'evidence.json'
            ev.write_text(json.dumps({'version': 1, 'repo_id': manifest['repo']['id'], 'sessions': []}),
                          encoding='utf-8')
            os.chmod(ev, 0o600)
            secret = tmp_path / 'outside.txt'
            secret.write_text('top-secret-line\n', encoding='utf-8')
            claims = tmp_path / 'claims.json'
            claims.write_text(json.dumps({
                'version': 1,
                'claims': [{
                    'id': 'm1',
                    'type': 'Move',
                    'file': 'AGENTS.md',
                    'target': str(secret),
                    'removed': ['- Keep things simple.'],
                    'added': ['top-secret-line'],
                }],
            }), encoding='utf-8')
            os.chmod(claims, 0o600)
            gcode, payload = module.validate_gate(str(stage), str(ev), str(claims))
            self.assertEqual(gcode, 2)
            self.assertEqual(payload['status'], 'invalid')
            self.assertEqual(module.read_stage_file(str(stage), 'proposed', str(secret)), '')
            self.assertFalse(module.valid_branch('main\n'))


class AuditTests(CheckerCase):
    def run_audit(self, *extra):
        proc = subprocess.run(
            [sys.executable, SCRIPT, 'audit', '--repo', self.repo, '--json'] + list(extra),
            capture_output=True, text=True,
        )
        return proc.returncode, json.loads(proc.stdout)

    def test_discovers_cross_agent_surfaces_and_docs(self):
        self.write('GEMINI.md', '@AGENTS.md\n')
        self.write('CLAUDE.local.md', 'Local personal notes.\n')
        self.write('.github/copilot-instructions.md', 'Read `AGENTS.md` first.\n')
        self.write('.github/instructions/ts.instructions.md', '---\napplyTo: "**/*.ts"\n---\nUse strict TS.\n')
        self.write('.claude/rules/api.md', 'Always validate API inputs.\n')
        self.write('.claude/rules/scoped.md', '---\npaths:\n  - "src/**"\n---\nScoped rule.\n')
        self.write('.claude/commands/release.md', 'Run release checklist.\n')
        self.write('.claude/agents/reviewer.md', 'Review diffs carefully.\n')
        self.write('.cursor/rules/style.mdc', '---\nalwaysApply: true\n---\nUse tabs.\n')
        self.write('.cursor/rules/ui.mdc', '---\nglobs: "*.tsx"\nalwaysApply: false\n---\nUI rule.\n')
        self.write('.agents/skills/demo/SKILL.md', '---\nname: demo\ndescription: Demo skill.\n---\nBody.\n')
        self.write('.trail/learnings/2026-11-22-note.md', '---\nstatus: active\n---\nNote.\n')
        self.write('README.md', '# Repo\n\n```sh\npython3 -m unittest\n```\n')
        self.write('docs/architecture.md', '# Architecture\n')
        self.write('package.json', '{"name":"demo","scripts":{"test":"echo ok"}}\n')
        self.commit('add cross-agent files')

        code, data = self.run_audit()
        self.assertEqual(code, 0)
        self.assertEqual(data['command'], 'audit')
        self.assertEqual(data['status'], 'ok')
        by_path = {item['path']: item for item in data['inventory']}
        self.assertEqual(by_path['AGENTS.md']['category'], 'memory')
        self.assertTrue(by_path['AGENTS.md']['always_loaded'])
        self.assertEqual(by_path['GEMINI.md']['agent'], 'gemini')
        self.assertEqual(by_path['CLAUDE.local.md']['agent'], 'claude')
        self.assertEqual(by_path['.github/copilot-instructions.md']['agent'], 'copilot')
        self.assertEqual(by_path['.github/instructions/ts.instructions.md']['category'], 'rules')
        self.assertTrue(by_path['.claude/rules/api.md']['always_loaded'])
        self.assertFalse(by_path['.claude/rules/scoped.md']['always_loaded'])
        self.assertTrue(by_path['.cursor/rules/style.mdc']['always_loaded'])
        self.assertFalse(by_path['.cursor/rules/ui.mdc']['always_loaded'])
        self.assertEqual(by_path['.claude/commands/release.md']['category'], 'commands')
        self.assertEqual(by_path['.claude/agents/reviewer.md']['category'], 'subagents')
        self.assertEqual(by_path['.agents/skills/demo/SKILL.md']['category'], 'skills')
        self.assertEqual(by_path['.trail/learnings/2026-11-22-note.md']['category'], 'learnings')
        self.assertEqual(by_path['README.md']['category'], 'docs')
        self.assertEqual(by_path['docs/architecture.md']['category'], 'docs')
        self.assertIn('package.json', data['docs_coverage']['manifests'])
        self.assertTrue(data['docs_coverage']['has_command_examples'])
        self.assertEqual(data['docs_coverage']['missing_recommended_docs'], [])

    def test_scope_filtering_and_containment(self):
        self.write('.claude/rules/a.md', 'Check `missing/file.py`.\n')
        self.write('docs/guide.md', 'See `AGENTS.md`.\n')
        self.commit('add scoped files')

        code, data = self.run_audit('--scope', '.claude/rules')
        self.assertEqual(code, 0)
        self.assertEqual(data['scope'], '.claude/rules')
        self.assertEqual([item['path'] for item in data['inventory']], ['.claude/rules/a.md'])
        self.assertEqual(len(data['references']['stale']), 1)

        code_file, data_file = self.run_audit('--scope', 'docs/guide.md')
        self.assertEqual(code_file, 0)
        self.assertEqual([item['path'] for item in data_file['inventory']], ['docs/guide.md'])

        code_missing, data_missing = self.run_audit('--scope', 'does/not/exist')
        self.assertEqual(code_missing, 2)
        self.assertEqual(data_missing['status'], 'invalid')

        code_escape, data_escape = self.run_audit('--scope', '../outside')
        self.assertEqual(code_escape, 2)
        self.assertEqual(data_escape['status'], 'invalid')

    def test_detects_structural_issues_and_oversized_files(self):
        dup_line = 'Always run the full integration suite before pushing any release branch.'
        self.write('AGENTS.md', DEFAULT_AGENTS + '\n' + dup_line + '\n@docs/missing.md\n')
        self.write('GEMINI.md', '# Gemini\n' + dup_line + '\n')
        self.write('.cursorrules', 'Legacy cursor rules.\n')
        self.write('.cursor/rules/modern.mdc', '---\nalwaysApply: false\n---\nModern rule.\n')
        self.write('.agents/skills/bad-skill/SKILL.md', '---\nname: wrong-name\n---\nBody.\n')
        self.write('.claude/rules/huge.md', '\n'.join(f'- Rule line number {i} for testing.' for i in range(320)) + '\n')
        self.commit('add structural issues')

        code, data = self.run_audit()
        self.assertEqual(code, 0)
        structure = data['structure']
        self.assertEqual(len(structure['dangling_imports']), 1)
        self.assertEqual(structure['dangling_imports'][0]['import'], '@docs/missing.md')
        fm_errors = [item['error'] for item in structure['skill_frontmatter']]
        self.assertTrue(any('does not match folder' in err for err in fm_errors))
        self.assertTrue(any('missing frontmatter description' in err for err in fm_errors))
        self.assertEqual(len(structure['duplicates']), 1)
        self.assertEqual(len(structure['duplicates'][0]['locations']), 2)
        self.assertEqual(len(structure['legacy_overlaps']), 1)
        self.assertEqual(structure['legacy_overlaps'][0]['legacy'], '.cursorrules')
        oversized_paths = [item['path'] for item in data['context_load']['oversized']]
        self.assertIn('.claude/rules/huge.md', oversized_paths)

    def test_audit_is_read_only_and_docs_exist(self):
        before = subprocess.check_output(['git', 'status', '--porcelain'], cwd=self.repo, text=True)
        code, _ = self.run_audit()
        self.assertEqual(code, 0)
        after = subprocess.check_output(['git', 'status', '--porcelain'], cwd=self.repo, text=True)
        self.assertEqual(before, after)
        self.assertTrue(os.path.isfile(os.path.join(SKILL_DIR, 'references', 'audit-rubric.md')))
        self.assertTrue(os.path.isfile(os.path.join(SKILL_DIR, 'references', 'agent-surfaces.md')))


if __name__ == '__main__':
    unittest.main()
