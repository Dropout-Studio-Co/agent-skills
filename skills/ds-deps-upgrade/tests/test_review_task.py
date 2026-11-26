"""review_task.py: model- and harness-agnostic fresh-context tasks for ds-consolidate and ds-ui-overhaul.

Also verifies cross-skill model/harness neutrality across every non-exception skill in the repo.
No test calls any model or external CLI.
"""
import contextlib
import io
import json
import os
import py_compile
import re
import threading
import time
import unittest

from tests.support import SKILL_DIR, TempCase, git_init, load, sh, write
from tests.test_task_protocol import GOOD, PLAN_TEXT

rt = load('review_task_under_test', 'scripts/review_task.py')
tp = rt.tp
SKILLS = os.path.dirname(SKILL_DIR)
FAIL = (
    'Found a lost change.\n%s\n{"verdict": "fail", "summary": "lost work", "findings": [{"severity": '
    '"Important", "file": "feature", "line": 1, "summary": "stash@{0} not in main", "scenario": "dropped"}]}\n%s\n'
    % (tp.RESULT_BEGIN, tp.RESULT_END)
)
CONSULT = {
    'summary': 'keep it',
    'decisions': [{'decision': 'keep the branch', 'rationale': 'unclear owner',
                   'alternatives': ['delete: unproven']}],
    'risks': [],
    'holds': [{'item': 'branch x', 'reason': 'unclear'}],
    'open_questions': [],
}
CONSULT_TEXT = 'Consult follows.\n%s\n%s\n%s\n' % (tp.PLAN_BEGIN, json.dumps(CONSULT), tp.PLAN_END)


class TaskCase(TempCase):
    def setUp(self):
        super().setUp()
        self._rt_env = {k: os.environ.get(k) for k in ('AGENT_TASK_STATE_DIR', 'AGENT_TASK_SKILLS_DIR')}
        os.environ['AGENT_TASK_STATE_DIR'] = os.path.join(self.tmp, 'task-state')
        os.environ.pop('AGENT_TASK_SKILLS_DIR', None)
        self.repo = os.path.join(self.tmp, 'repo')
        write(os.path.join(self.repo, 'app.js'), 'export const a = 1;\n')
        git_init(self.repo)
        self.base = sh(['git', 'rev-parse', 'HEAD'], self.repo).stdout.strip()

    def tearDown(self):
        for key, value in self._rt_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        super().tearDown()

    def rt(self, *argv):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = rt.main(list(argv))
        return code, json.loads(buffer.getvalue())

    def start(self, skill):
        code, run = self.rt('start', '--skill', skill, '--repo', self.repo)
        self.assertEqual(code, 0, run)
        return run['run_dir']

    def handoff(self, text='requirements: keep main design\ntoken=SECRET-TOKEN-VALUE\n'):
        path = os.path.join(self.tmp, 'handoff.md')
        write(path, text)
        return path

    def commit(self, name, text, message='change'):
        write(os.path.join(self.repo, name), text)
        sh(['git', 'add', '-A'], self.repo)
        sh(['git', 'commit', '-q', '-m', message], self.repo)

    def complete_task(self, run, prep, text, by='fresh-context-1'):
        write(prep['output_path'], text)
        return self.rt('record', run, '--task-id', prep['id'], '--output', prep['output_path'], '--by', by)


class ProfileAndAgnosticComplianceTests(TaskCase):

    def test_review_task_loads_only_the_shared_protocol(self):
        with open(rt.__file__, encoding='utf-8') as handle:
            source = handle.read()
        self.assertNotIn('depup.py', source, 'review_task.py must not load depup.py')
        self.assertNotIn('review_task_depup', source)
        self.assertIs(rt.Refusal, rt.tp.Refusal)
        for name in ('run_cmd', 'git', 'tree_fingerprint', 'redact_output', 'read_json'):
            self.assertTrue(hasattr(rt.tp, name), name)

    def test_both_sibling_skills_ship_model_agnostic_profiles(self):
        for skill, kinds, plan_kinds in (
            ('ds-consolidate', {'reconciliation', 'code'}, {'plan', 'architecture', 'consult'}),
            ('ds-ui-overhaul', {'code', 'ui-ux', 'accessibility'}, {'plan', 'architecture'}),
        ):
            profile = rt.load_profile(skill)
            self.assertEqual(profile['skill'], skill)
            self.assertEqual(set(profile['review_kinds']), kinds)
            self.assertEqual(set(profile['plan_kinds']), plan_kinds)
            for spec in profile['review_kinds'].values():
                self.assertNotIn('effort', spec)
                self.assertNotIn('model', spec)
                self.assertNotIn('harness', spec)
            with open(os.path.join(SKILLS, skill, 'SKILL.md'), encoding='utf-8') as handle:
                text = handle.read()
            self.assertIn('review_task.py', text)
            self.assertIn('ds-dev-protocol', text)
            self.assertIn('explicitly invoked', text)
            for forbidden in ('Opus 5.5', 'xhigh', 'routed_task.py', 'review_router.py', 'DeepSeek', '--high'):
                self.assertNotIn(forbidden, text, '%s should not contain %s' % (skill, forbidden))
        self.assertEqual(rt.load_profile('ds-consolidate')['review_kinds']['reconciliation']['evidence'], 'git-inventory')

    def test_all_skills_follow_ds_naming_and_valid_frontmatter(self):
        expected = {'ds-consolidate', 'ds-deps-upgrade', 'ds-dev-protocol', 'ds-responsive', 'ds-handoff', 'ds-agent-docs', 'ds-ui-overhaul', 'ds-media-cleanup', 'ds-storage-audit'}
        actual = {d for d in os.listdir(SKILLS) if os.path.isdir(os.path.join(SKILLS, d)) and not d.startswith('.')}
        self.assertEqual(actual, expected)
        for skill in sorted(actual):
            self.assertRegex(skill, r'^ds-[a-z0-9]+(-[a-z0-9]+)*$')
            with open(os.path.join(SKILLS, skill, 'SKILL.md'), encoding='utf-8') as handle:
                text = handle.read()
            self.assertIn('name: %s\n' % skill, text, skill)
            self.assertIn('description:', text, skill)

    def test_profile_with_effort_model_or_harness_is_refused(self):
        skills = os.path.join(self.tmp, 'skills')
        os.makedirs(os.path.join(skills, 'demo'))
        os.environ['AGENT_TASK_SKILLS_DIR'] = skills
        for key, value in (('effort', 'high'), ('model', 'claude-opus-5-5'), ('harness', 'claude-code')):
            write(os.path.join(skills, 'demo', 'task-profile.json'), {
                'skill': 'demo', 'plan_kinds': {'plan': 'x'},
                'review_kinds': {'code': {'focus': 'x', key: value}}})
            with self.assertRaises(rt.Refusal):
                rt.load_profile('demo')

    def test_unknown_skill_or_kind_refused(self):
        code, out = self.rt('start', '--skill', 'no-such-skill', '--repo', self.repo)
        self.assertEqual(code, 1)
        self.assertIn('no task profile', out['error'])
        run = self.start('ds-consolidate')
        code, out = self.rt('review', run, '--kind', 'ui-ux', '--base', self.base)
        self.assertEqual(code, 1)
        self.assertIn('--kind must be one of', out['error'])

    def test_all_non_exception_skills_are_model_and_harness_agnostic(self):
        forbidden_re = re.compile(
            r'claude-opus|claude-sonnet|claude-haiku|\bopus 5\.5\b|claude -p|claude --bg|'
            r'claude auth|claude agents|claude attach|review_router\.py|routed_task\.py|'
            r'routing\.json|--effort|\bxhigh\b|deepseek', re.I)
        non_exception = ('ds-consolidate', 'ds-deps-upgrade', 'ds-ui-overhaul',
                         'ds-responsive', 'ds-handoff', 'ds-agent-docs', 'ds-storage-audit')
        for skill in non_exception:
            skill_dir = os.path.join(SKILLS, skill)
            for dirpath, dirnames, filenames in os.walk(skill_dir):
                dirnames[:] = [d for d in dirnames if d not in ('__pycache__', 'tests')]
                for name in filenames:
                    if not name.endswith(('.md', '.py', '.json')):
                        continue
                    full = os.path.join(dirpath, name)
                    rel = os.path.relpath(full, SKILLS)
                    with open(full, encoding='utf-8') as handle:
                        text = handle.read()
                    match = forbidden_re.search(text)
                    self.assertIsNone(match, '%s matched forbidden coupling %r' % (rel, match and match.group(0)))

        # Required sibling skills always exist; check optional siblings when present in this root.
        for skill in ('ds-consolidate', 'ds-deps-upgrade', 'ds-ui-overhaul'):
            with open(os.path.join(SKILLS, skill, 'SKILL.md'), encoding='utf-8') as handle:
                text = handle.read()
            self.assertIn('ds-dev-protocol', text, skill)
            self.assertIn('explicitly invoked', text, skill)
        for skill in ('ds-handoff',):
            skill_md = os.path.join(SKILLS, skill, 'SKILL.md')
            if os.path.isfile(skill_md):
                with open(skill_md, encoding='utf-8') as handle:
                    text = handle.read()
                self.assertIn('ds-dev-protocol', text, skill)
                self.assertIn('explicitly invoked', text, skill)


    def test_storage_audit_skill_contract(self):
        root = os.path.join(SKILLS, 'ds-storage-audit')
        skill_md = os.path.join(root, 'SKILL.md')
        self.assertTrue(os.path.isfile(skill_md), 'skills/ds-storage-audit/SKILL.md is missing')
        with open(skill_md, encoding='utf-8') as handle:
            text = handle.read()
        self.assertTrue(text.startswith('---\n'), 'SKILL.md needs YAML frontmatter')
        parts = text.split('---\n', 2)
        self.assertEqual(len(parts), 3, 'SKILL.md needs a closed YAML frontmatter block')
        front = parts[1]
        self.assertIn('name: ds-storage-audit\n', front)
        self.assertRegex(front, r'(?m)^argument-hint:\s*\S')
        self.assertRegex(front, r'(?m)^license:\s*MIT\s*$')
        description = re.search(r'(?m)^description:\s*(.+)$', front)
        self.assertIsNotNone(description, 'description is required')
        self.assertTrue(description.group(1).strip(), 'description must not be empty')
        self.assertLessEqual(len(description.group(1).strip()), 1024)
        self.assertNotIn('disable-model-invocation', front, 'storage audit is model-invoked')
        self.assertLessEqual(len(parts[2].splitlines()), 500, 'SKILL.md body must stay under 500 lines')

        markdown_files = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d != '__pycache__']
            for name in dirnames + filenames:
                self.assertFalse(os.path.islink(os.path.join(dirpath, name)),
                                 'symlink inside the skill: %s' % os.path.join(dirpath, name))
            for name in filenames:
                if name.endswith('.md'):
                    markdown_files.append(os.path.join(dirpath, name))
        self.assertIn(skill_md, markdown_files)

        skill_root = os.path.realpath(root)
        for path in markdown_files:
            with open(path, encoding='utf-8') as handle:
                body = handle.read()
            for target in re.findall(r'\[[^\]]*\]\(([^)]+)\)', body):
                target = target.strip().split('#', 1)[0].split('"', 1)[0].strip()
                if not target or re.match(r'^(?:[a-z][a-z0-9+.-]*:|#)', target, re.I):
                    continue
                resolved = os.path.realpath(os.path.join(os.path.dirname(path), target))
                self.assertTrue(resolved == skill_root or resolved.startswith(skill_root + os.sep),
                                '%s links outside the skill: %s' % (path, target))
                self.assertTrue(os.path.exists(resolved), '%s has a broken link: %s' % (path, target))

        # The sync refuses to push home paths and token-like strings; the skill must never carry one.
        leak_re = re.compile(
            r'/Users/|/home/|sk-ant-|ghp_|gho_|github_pat_|AKIA[0-9A-Z]{16}|xox[abpr]-|'
            r'-----BEGIN [A-Z ]*PRIVATE KEY-----')
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d != '__pycache__']
            for name in filenames:
                path = os.path.join(dirpath, name)
                with open(path, encoding='utf-8') as handle:
                    content = handle.read()
                match = leak_re.search(content)
                self.assertIsNone(match, '%s leaks a home path or secret-like value: %r'
                                  % (os.path.relpath(path, SKILLS), match and match.group(0)))

        def read(rel):
            with open(os.path.join(root, rel), encoding='utf-8') as handle:
                return handle.read()

        os_locations = read('references/os-locations.md')
        classification = read('references/safety-classification.md')
        lower_skill = parts[2].lower()

        for rel in ('references/os-locations.md', 'references/safety-classification.md'):
            self.assertIn(rel, parts[2], 'SKILL.md must disclose %s' % rel)
        for host in ('macOS', 'Linux', 'Windows', 'WSL'):
            self.assertIn(host, parts[2], 'host-OS detection must name %s' % host)
        for phrase in ('Pass A', 'Pass B'):
            self.assertIn(phrase, parts[2])
            self.assertIn(phrase, os_locations)
        self.assertIn('read-only', lower_skill)
        self.assertIn('never delete', lower_skill)
        self.assertIn('largest to smallest', lower_skill)
        self.assertIn('double-count', classification.lower())
        self.assertIn('firmlink', classification.lower())
        self.assertIn('sparse', classification.lower())
        self.assertIn('placeholder', classification.lower())
        self.assertIn('Safe to Recommend', classification)
        self.assertIn('Never Recommend', classification)
        for exclusion in ('System32', 'WinSxS', 'pagefile', 'hiberfil', 'swap', '.git',
                          'browser profile', 'credential', '.env'):
            self.assertIn(exclusion, classification)
        for required in ('What to delete', 'What it is', 'Space freed', 'nothing was deleted'):
            self.assertIn(required, parts[2])

        for ecosystem in ('Library/Caches', '.Trash', 'tmutil listlocalsnapshots',
                          'journalctl --disk-usage', 'apt', 'dnf', 'pacman', 'flatpak', 'snap',
                          'Recycle Bin', 'Get-Volume', 'DerivedData', 'DeviceSupport',
                          'CoreSimulator', 'Gradle', 'npm', 'pnpm', 'yarn', 'bun', 'deno',
                          'Playwright', 'Cypress', 'pip', 'uv', 'poetry', 'conda', 'Cargo',
                          'Go', 'Homebrew', 'Docker', 'Podman', 'Downloads',
                          '.dmg', '.pkg', '.iso', '.msi', '.exe', '.deb', '.rpm'):
            self.assertIn(ecosystem, os_locations)
        for placeholder in ('$HOME', '%LOCALAPPDATA%', '%USERPROFILE%', '%TEMP%'):
            self.assertIn(placeholder, os_locations)
        for bound in ('-x', '-d 3', 'max-depth'):
            self.assertIn(bound, os_locations)
        for sizing in ('docker system df', '25 MB', '1 MB', '-P'):
            self.assertIn(sizing, classification)

        # Presentation contract: one sequential numbered list owns every qualifying audit result.
        self.assertIn('numbered (ordered) list', lower_skill,
                      'SKILL.md must define the numbered (ordered) list presentation')
        for marker in ('1.', '2.', '3.'):
            self.assertIn(marker, parts[2],
                          'SKILL.md must show sequential %s numbering' % marker)
        self.assertIn('unnumbered', lower_skill,
                      'the Total line must be unnumbered, never a list item')
        self.assertIn('**Total**', parts[2],
                      'the report needs a bold Total summary line')
        for part in ('What to delete', 'What it is', 'Space freed'):
            self.assertIn(part, parts[2],
                          'SKILL.md must define the report part: %s' % part)
        self.assertIn('strictly descending by exact reclaimable bytes', lower_skill,
                      'items must sort by exact bytes, not the displayed label')
        self.assertIn('alphabetical', lower_skill,
                      'ties must break deterministically by alphabetical order')
        for discipline in ('single-line', 'newline', 'control character', 'markdown formatting'):
            self.assertIn(discipline, lower_skill,
                          'items must stay single-line and sanitize %s' % discipline)

        for stale in ('| What to delete | What it is | Space freed |',
                      '| :--- | :--- | ---: |', '### Table presentation',
                      '### Cell discipline', '1. What to delete:'):
            self.assertNotIn(stale, parts[2],
                             'the stale table-era marker must be gone: %s' % stale)

        for boundary in ('0 qualifying items', 'omit the numbered list', 'placeholder list',
                         'single qualifying item', 'closing note below the list',
                         'vanished', 're-check', 'multi-volume', 'no list'):
            self.assertIn(boundary, lower_skill,
                          'SKILL.md must define boundary behavior: %s' % boundary)

        # The worked example's numbering and arithmetic must be internally consistent.
        example_blocks = re.findall(r'```[^\n]*\n(.*?)```', parts[2], re.S)
        list_blocks = [block for block in example_blocks if re.search(r'(?m)^1\. ', block)]
        self.assertEqual(len(list_blocks), 1,
                         'SKILL.md needs exactly one fenced example containing the numbered list')
        example = list_blocks[0]
        self.assertNotIn('|', example, 'the worked example must not contain a GFM table row')
        size_re = re.compile(r'^(\d+(?:\.\d+)?)\s*(B|KB|MB|GB|TB)$')
        scale = {'B': 1, 'KB': 10 ** 3, 'MB': 10 ** 6, 'GB': 10 ** 9, 'TB': 10 ** 12}

        def as_bytes(value):
            match = size_re.match(value.strip().strip('*').strip())
            self.assertIsNotNone(match, 'unparseable example size: %r' % value)
            return float(match.group(1)) * scale[match.group(2)]

        item_re = re.compile(r'^(\d+)\. (.+)$')
        lines = [line.strip() for line in example.splitlines()]
        item_lines = [line for line in lines if item_re.match(line)]
        self.assertGreaterEqual(len(item_lines), 2,
                                'the example should show several numbered items')
        self.assertEqual([int(item_re.match(line).group(1)) for line in item_lines],
                         list(range(1, len(item_lines) + 1)),
                         'example numbering must be sequential and start at 1')
        item_sizes = []
        for line in item_lines:
            pieces = line.split(' — ')
            self.assertEqual(len(pieces), 3,
                             'each numbered item must fill the three report parts: %r' % line)
            self.assertRegex(pieces[0], r'^\d+\. \*\*.+\*\*$',
                             'each item must start with a bold name: %r' % line)
            item_sizes.append(as_bytes(pieces[-1]))
        for left, right in zip(item_sizes, item_sizes[1:]):
            self.assertGreaterEqual(left, right,
                                    'example items must be sorted largest to smallest')
        total_lines = [line for line in lines if line.startswith('**Total**')]
        self.assertEqual(len(total_lines), 1,
                         'the example needs exactly one unnumbered bold Total line')
        self.assertIsNone(item_re.match(total_lines[0]),
                          'the Total line must never be numbered')
        last_item = max(lines.index(line) for line in item_lines)
        self.assertGreater(lines.index(total_lines[0]), last_item,
                           'the Total line must sit below the numbered list')
        summed = round(sum(item_sizes))
        self.assertEqual(summed, round(as_bytes(total_lines[0].split(' — ')[-1])),
                         'the example Total must equal the sum of its numbered items')
        opening = re.search(r'free about ([\d.]+)\s*(B|KB|MB|GB|TB)', example)
        self.assertIsNotNone(opening, 'the example must open with the reclaimable total')
        self.assertEqual(summed, round(as_bytes('%s %s' % (opening.group(1), opening.group(2)))),
                         'the example opening total must match the summed items')

        # safety-classification.md must defer list layout to SKILL.md and describe list entries.
        lower_classification = classification.lower()
        self.assertIn('one item per numbered list entry', lower_classification,
                      'plain-language guidance must describe numbered list entries')
        self.assertIn('SKILL.md', classification,
                      'layout details must defer to SKILL.md')
        for part in ('What to delete', 'What it is', 'Space freed'):
            self.assertIn(part, classification,
                          'plain-language guidance must name the report part: %s' % part)
        for stale in ('one item per block', 'one item per row', 'report table'):
            self.assertNotIn(stale, lower_classification,
                             'stale table wording must be gone: %s' % stale)

        # Review round 1: only cache directories, never installed app trees or credential-bearing roots.
        self.assertNotIn(r'%LOCALAPPDATA%\Microsoft\Teams\`', os_locations,
                         'Teams Classic is an installed app directory, not a cache')
        self.assertIsNone(re.search(r'~/\.gradle/(?!caches)', os_locations),
                          'Gradle cleanup must stay scoped to caches/, never the bare ~/.gradle/')
        self.assertIsNone(re.search(r'%USERPROFILE%\.gradle\\(?!caches)', os_locations),
                          'Gradle cleanup must stay scoped to caches/, never the bare %USERPROFILE%\\.gradle\\')
        self.assertNotIn('mount read-only', os_locations.lower())
        for window_bound in ('-Depth 3', 'ReparsePoint', 'Offline'):
            self.assertIn(window_bound, os_locations,
                          'Windows Pass B must be depth-bounded and skip junctions and cloud-only placeholders')

        repo_root = os.path.dirname(SKILLS)
        readme = os.path.join(repo_root, 'README.md')
        if os.path.isfile(readme):
            with open(readme, encoding='utf-8') as handle:
                readme_text = handle.read()
            self.assertIn('A collection of 9 Dropout Studio', readme_text)
            self.assertIn('all 9 skills', readme_text)
            self.assertNotIn('A collection of 8 Dropout Studio', readme_text)
            self.assertNotIn('all 8 skills', readme_text)
            media = readme_text.split('### Media & Utilities', 1)
            self.assertEqual(len(media), 2, 'README.md needs a Media & Utilities section')
            self.assertIn('[`ds-storage-audit`](skills/ds-storage-audit/)', media[1])
        agents = os.path.join(repo_root, 'AGENTS.md')
        if os.path.isfile(agents):
            with open(agents, encoding='utf-8') as handle:
                agents_text = handle.read()
            self.assertIn('skills/ds-storage-audit/', agents_text)
            self.assertIn('os-locations.md', agents_text)
            self.assertIn('safety-classification.md', agents_text)


class PlanningAndConsultTests(TaskCase):

    def test_plan_prepare_record_redacts_handoff_and_reuses(self):
        run = self.start('ds-consolidate')
        code, prep = self.rt('plan', run, '--context', self.handoff())
        self.assertEqual((code, prep['status']), (0, 'pending'))
        self.assertTrue(prep['advisory'])
        task_dir = os.path.dirname(prep['entry'])
        with open(os.path.join(task_dir, 'prompt.md'), encoding='utf-8') as handle:
            prompt = handle.read()
        self.assertIn('authorizes nothing', prompt)
        self.assertIn('ds-consolidate skill', prompt)
        self.assertIn('proven in default branch', prompt)
        self.assertIn('restore point', prompt)
        with open(os.path.join(task_dir, 'context.md'), encoding='utf-8') as handle:
            context = handle.read()
        self.assertIn('keep main design', context)
        self.assertNotIn('SECRET-TOKEN-VALUE', context)

        code, entry = self.complete_task(run, prep, PLAN_TEXT)
        self.assertEqual((code, entry['status']), (0, 'completed'))
        self.assertEqual(sh(['git', 'status', '--porcelain'], self.repo).stdout, '')

        _, again = self.rt('plan', run, '--context', self.handoff())
        self.assertTrue(again['reused'])
        _, changed = self.rt('plan', run, '--context', self.handoff('requirements: new scope\n'))
        self.assertFalse(changed.get('reused'))
        self.assertEqual(changed['status'], 'pending')

    def test_high_risk_architecture_task_needs_subject(self):
        run = self.start('ds-ui-overhaul')
        code, out = self.rt('plan', run, '--context', self.handoff(), '--kind', 'architecture')
        self.assertEqual(code, 1)
        self.assertIn('--subject', out['error'])
        code, prep = self.rt('plan', run, '--context', self.handoff(), '--kind', 'architecture',
                             '--subject', 'shared Button primitive')
        self.assertEqual(code, 0)
        code, entry = self.complete_task(run, prep, PLAN_TEXT)
        self.assertEqual((code, entry['status'], entry['kind']), (0, 'completed', 'architecture'))
        with open(os.path.join(os.path.dirname(entry['entry']), 'prompt.md'), encoding='utf-8') as handle:
            self.assertIn('shared design-system primitive', handle.read())

    def test_consult_prepare_record_boundaries_and_merge_in_progress(self):
        run = self.start('ds-consolidate')
        code, out = self.rt('plan', run, '--context', self.handoff(), '--kind', 'consult')
        self.assertEqual(code, 1)
        self.assertIn('--subject is required for a consult task', out['error'])
        other = self.start('ds-ui-overhaul')
        code, out = self.rt('plan', other, '--context', self.handoff(), '--kind', 'consult', '--subject', 's')
        self.assertEqual(code, 1)
        self.assertIn('--kind must be one of', out['error'])

        # Consult works even while a merge conflict is in progress.
        sh(['git', 'checkout', '-q', '-b', 'side'], self.repo)
        self.commit('clash.txt', 'side\n', 'side change')
        sh(['git', 'checkout', '-q', '-'], self.repo)
        self.commit('clash.txt', 'main\n', 'main change')
        merge = sh(['git', 'merge', 'side'], self.repo, check=False)
        self.assertNotEqual(merge.returncode, 0)
        self.assertTrue(os.path.exists(os.path.join(self.repo, '.git', 'MERGE_HEAD')))

        code, prep = self.rt('plan', run, '--context', self.handoff(), '--kind', 'consult', '--subject', 'consult-1')
        self.assertEqual(code, 0)
        code, entry = self.complete_task(run, prep, CONSULT_TEXT)
        self.assertEqual((code, entry['status']), (0, 'completed'))
        self.assertTrue(os.path.exists(os.path.join(self.repo, '.git', 'MERGE_HEAD')))

        # Consult never satisfies the gate.
        code, gate = self.rt('gate', run, '--require', 'reconciliation')
        self.assertEqual(code, 1)
        self.assertIn('not run', gate['problems'][0])

    def test_consolidate_skill_preserves_consult_safety_boundaries(self):
        with open(os.path.join(SKILLS, 'ds-consolidate', 'SKILL.md'), encoding='utf-8') as handle:
            text = handle.read()
        self.assertIn('--kind consult --subject consult-<n>', text)
        self.assertIn('still wanted', text)
        self.assertIn('returns through PLAN', text)
        self.assertIn('none of the item', text)
        self.assertIn('authored by `gh api user`', text)
        step2 = text[text.index('STEP 2 \u2014 RECONCILE'):text.index('STEP 3 \u2014 VERIFY')]
        for required in ('build or test failure', 'do not push', 'git status --porcelain'):
            self.assertIn(required, step2)
        step3 = text[text.index('STEP 3 \u2014 VERIFY'):text.index('STEP 4 \u2014 CLEANUP')]
        for required in ('unclear re-check', 're-run the reconciliation review'):
            self.assertIn(required, step3)
        step4 = text[text.index('STEP 4 \u2014 CLEANUP'):text.index('If planning, a consult')]
        self.assertNotIn('consult', step4.lower())
        focus = rt.load_profile('ds-consolidate')['plan_kinds']['consult']
        self.assertIn('batch', focus)
        self.assertIn('never treat your recommendation as proof', focus)


class ReviewGateTests(TaskCase):

    def test_gate_blocks_until_required_review_passes_on_current_candidate(self):
        run = self.start('ds-ui-overhaul')
        self.commit('app.js', 'export const a = 2;\n')
        code, gate = self.rt('gate', run, '--require', 'code')
        self.assertEqual(code, 1)
        self.assertIn('not run', gate['problems'][0])

        _, prep = self.rt('review', run, '--kind', 'code', '--base', self.base, '--required')
        self.assertEqual(self.rt('gate', run)[0], 1, 'pending review never satisfies the gate')
        _, failed = self.complete_task(run, prep, FAIL)
        self.assertEqual(failed['verdict'], 'fail')
        self.assertEqual(self.rt('gate', run)[0], 1, 'required review declared once stays required')

        self.commit('app.js', 'export const a = 3;\n', 'fix finding')
        _, stale = self.rt('gate', run)
        self.assertIn('not run', stale['problems'][0], 'old candidate review never counts')

        _, prep2 = self.rt('review', run, '--kind', 'code', '--base', self.base, '--required')
        _, passed = self.complete_task(run, prep2, GOOD)
        self.assertEqual(passed['verdict'], 'pass')
        code, gate = self.rt('gate', run)
        self.assertEqual((code, gate['ok']), (0, True))
        _, again = self.rt('review', run, '--kind', 'code', '--base', self.base, '--required')
        self.assertTrue(again['reused'])

        write(os.path.join(self.repo, 'new.js'), 'x\n')  # untracked edit is a new candidate
        self.assertEqual(self.rt('gate', run)[0], 1)

    def test_unavailable_and_tampered_reviews_block_gate(self):
        run = self.start('ds-ui-overhaul')
        _, prep = self.rt('review', run, '--kind', 'code', '--base', self.base, '--required')
        code, entry = self.rt('unavailable', run, '--task-id', prep['id'],
                              '--reason', 'harness has no subagents')
        self.assertEqual((code, entry['status']), (0, 'unavailable'))
        self.assertEqual(self.rt('gate', run)[0], 1)

        _, prep2 = self.rt('review', run, '--kind', 'code', '--base', self.base, '--required', '--rerun')
        _, passed = self.complete_task(run, prep2, GOOD)
        self.assertEqual(self.rt('gate', run)[0], 0)
        with open(os.path.join(os.path.dirname(passed['entry']), 'review.md'), 'a', encoding='utf-8') as handle:
            handle.write('edited by the author\n')
        self.assertEqual(self.rt('gate', run)[0], 1)

    def test_rerun_cannot_clear_failed_non_required_review_or_accept_missing_artifact(self):
        run = self.start('ds-consolidate')
        _, rec_prep = self.rt('review', run, '--kind', 'reconciliation', '--required')
        _, rec_done = self.complete_task(run, rec_prep, GOOD)
        self.assertEqual(self.rt('gate', run)[0], 0)
        # Missing review.md + stripped receipt must fail receipt_ok.
        rec_dir = os.path.dirname(rec_done['entry'])
        os.unlink(os.path.join(rec_dir, 'review.md'))
        write(os.path.join(rec_dir, 'receipt.json'), {'fingerprint': rec_done['fingerprint']})
        self.assertEqual(self.rt('gate', run)[0], 1)
        # Re-pass reconciliation, then fail non-required code review and reset via rerun/new context.
        _, rec_prep2 = self.rt('review', run, '--kind', 'reconciliation', '--required', '--rerun')
        self.complete_task(run, rec_prep2, GOOD)
        self.assertEqual(self.rt('gate', run)[0], 0)
        _, code_prep = self.rt('review', run, '--kind', 'code')
        self.complete_task(run, code_prep, FAIL)
        self.assertEqual(self.rt('gate', run)[0], 1)
        _, code_rerun = self.rt('review', run, '--kind', 'code', '--rerun')
        self.assertTrue(code_rerun.get('prior_failed'))
        self.assertEqual(self.rt('gate', run)[0], 1, 'pending rerun of failed review must stay blocked')
        self.rt('unavailable', run, '--task-id', code_rerun['id'], '--reason', 'stopped')
        self.assertEqual(self.rt('gate', run)[0], 1, 'unavailable rerun of failed review must stay blocked')
        # Passing the rerun clears the failure.
        _, code_pass_prep = self.rt('review', run, '--kind', 'code', '--rerun')
        self.complete_task(run, code_pass_prep, GOOD)
        self.assertEqual(self.rt('gate', run)[0], 0)

    def test_prompt_file_refused_as_output_and_newlines_rejected(self):
        run = self.start('ds-consolidate')
        _, prep = self.rt('plan', run, '--context', self.handoff())
        code, refused = self.rt('record', run, '--task-id', prep['id'], '--output', prep['prompt_path'], '--by', 'p1')
        self.assertEqual(code, 1)
        self.assertIn('prompt.md', refused['error'])
        code, bad_by = self.rt('record', run, '--task-id', prep['id'], '--output', prep['output_path'], '--by', 'a\nb')
        self.assertEqual(code, 1)
        self.assertIn('newlines', bad_by['error'])

    def test_tree_change_during_review_discards_result_and_blocks(self):
        run = self.start('ds-ui-overhaul')
        _, prep = self.rt('review', run, '--kind', 'code', '--base', self.base, '--required')
        write(os.path.join(self.repo, 'app.js'), 'export const a = 99;\n')
        _, rec = self.complete_task(run, prep, GOOD)
        self.assertEqual(rec['status'], 'unavailable')
        self.assertTrue(rec['tree_changed'])
        self.assertEqual(self.rt('gate', run)[0], 1)

    def test_rerun_without_required_never_downgrades_and_newer_context_blocks(self):
        run = self.start('ds-ui-overhaul')
        _, prep = self.rt('review', run, '--kind', 'code', '--required')
        self.complete_task(run, prep, GOOD)
        self.assertEqual(self.rt('gate', run)[0], 0)
        _, prep2 = self.rt('review', run, '--kind', 'code', '--rerun')  # forgot --required
        self.assertTrue(prep2['required'])
        self.rt('unavailable', run, '--task-id', prep2['id'], '--reason', 'failed')
        self.assertEqual(self.rt('gate', run)[0], 1)

        run2 = self.start('ds-consolidate')
        _, p1 = self.rt('review', run2, '--kind', 'reconciliation', '--required', '--context', self.handoff('ledger A\n'))
        self.complete_task(run2, p1, GOOD)
        _, p2 = self.rt('review', run2, '--kind', 'reconciliation', '--required', '--context', self.handoff('ledger B\n'))
        self.rt('unavailable', run2, '--task-id', p2['id'], '--reason', 'failed')
        self.assertEqual(self.rt('gate', run2)[0], 1)

    def test_base_is_bound_to_the_run(self):
        run = self.start('ds-ui-overhaul')
        self.commit('app.js', 'export const a = 5;\n')
        code, out = self.rt('review', run, '--kind', 'code', '--base', 'HEAD')
        self.assertEqual(code, 1)
        self.assertIn('differs from the run base', out['error'])

    def test_removed_flags_and_probe_are_gone(self):
        run = self.start('ds-consolidate')
        for argv in (
            ('probe',),
            ('review', run, '--kind', 'code', '--high'),
            ('review', run, '--kind', 'code', '--session-harness', 'x'),
        ):
            with self.subTest(argv):
                with self.assertRaises(SystemExit) as raised:
                    rt.main(list(argv))
                self.assertEqual(raised.exception.code, 2)


class RequiredMarkerTests(TaskCase):

    def test_concurrent_mark_required_preserves_all_entries(self):
        run = self.start('ds-ui-overhaul')
        kinds = ('code', 'ui-ux', 'accessibility')
        errors = []

        def mark(kind):
            try:
                rt.mark_required(run, kind, 'candidate')
            except Exception as exc:  # surfaced below; threads must not hide failures
                errors.append(exc)

        threads = [threading.Thread(target=mark, args=(kind,)) for kind in kinds]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(rt.read_required(run),
                         [['accessibility', 'candidate'], ['code', 'candidate'], ['ui-ux', 'candidate']],
                         'distinct concurrent requirements must all survive; sorted for determinism')

        # Gate enforces every marker: all three are missing before any review runs.
        code, gate = self.rt('gate', run)
        self.assertEqual(code, 1)
        joined = ' '.join(gate['problems'])
        for kind in kinds:
            self.assertIn('%s:candidate' % kind, joined)

        # Satisfy only the code review; the other two still block.
        _, prep = self.rt('review', run, '--kind', 'code', '--base', self.base)
        _, entry = self.complete_task(run, prep, GOOD)
        self.assertEqual(entry['status'], 'completed')
        code, gate = self.rt('gate', run)
        self.assertEqual(code, 1)
        joined = ' '.join(gate['problems'])
        self.assertNotIn('code:candidate', joined)
        self.assertIn('ui-ux:candidate', joined)
        self.assertIn('accessibility:candidate', joined)

        # Legacy required.json is still read (and deduplicated against marker files) and enforced.
        legacy_run = self.start('ds-ui-overhaul')
        write(os.path.join(legacy_run, 'required.json'), [['code', 'candidate'], ['code', 'candidate']])
        rt.mark_required(legacy_run, 'code', 'candidate')
        self.assertEqual(rt.read_required(legacy_run), [['code', 'candidate']])
        code, gate = self.rt('gate', legacy_run)
        self.assertEqual(code, 1)
        self.assertIn('code:candidate', ' '.join(gate['problems']))


class GitInventoryParallelTests(TaskCase):

    def test_git_inventory_parallel_is_deterministic(self):
        sh(['git', 'checkout', '-q', '-b', 'feature'], self.repo)
        self.commit('feature.js', 'UNIQUE-FEATURE-LINE\n', 'feature work')
        sh(['git', 'checkout', '-q', '-b', 'feature-two'], self.repo)
        self.commit('feature-two.js', 'UNIQUE-FEATURE-TWO-LINE\n', 'second feature')
        sh(['git', 'checkout', '-q', 'main'], self.repo)
        write(os.path.join(self.repo, 'app.js'), 'STASHED-LINE\n')
        sh(['git', 'stash', 'push', '-q', '-m', 'wip'], self.repo)
        clone = os.path.join(self.tmp, 'clone')
        sh(['git', 'clone', '-q', self.repo, clone], self.tmp)
        write(os.path.join(clone, 'clone-only.js'), 'UNIQUE-CLONE-LINE\n')
        sh(['git', 'add', '-A'], clone)
        sh(['git', 'commit', '-qm', 'clone-only'], clone)
        first_wt = os.path.join(self.tmp, 'wt-one')
        second_wt = os.path.join(self.tmp, 'wt-two')
        sh(['git', 'worktree', 'add', '-q', '--detach', first_wt], self.repo)
        sh(['git', 'worktree', 'add', '-q', '--detach', second_wt], self.repo)
        write(os.path.join(first_wt, 'app.js'), 'WORKTREE-ONE-EDIT\n')
        write(os.path.join(second_wt, 'app.js'), 'WORKTREE-TWO-EDIT\n')

        calls = []

        def runner(argv, **kwargs):
            calls.append(argv)
            time.sleep(0.01)  # makes the PR lookup overlap local inspection
            return {'rc': 0, 'stdout': '[]', 'stderr': '', 'error': None}

        first = rt.git_inventory(self.repo, 'main', [clone], True, runner=runner)
        second = rt.git_inventory(self.repo, 'main', [clone], True, runner=runner)
        self.assertEqual(first, second, 'concurrent inspection must stay byte-identical')
        self.assertEqual(len(calls), 2, 'one PR lookup per inventory call')
        for marker in ('## open PRs', '## location %s' % clone, 'UNIQUE-FEATURE-LINE',
                       'UNIQUE-FEATURE-TWO-LINE', 'STASHED-LINE', 'UNIQUE-CLONE-LINE',
                       'WORKTREE-ONE-EDIT', 'WORKTREE-TWO-EDIT',
                       'refs/heads/feature ahead=1 unique=1'):
            self.assertIn(marker, first)

        # The gate hashes exactly this inventory; a completed review of the same tree must pass.
        run = self.start('ds-consolidate')
        ledger = self.handoff('feature: proven in main\n')
        code, prep = self.rt('review', run, '--kind', 'reconciliation', '--base', self.base,
                             '--context', ledger, '--location', clone, '--required')
        self.assertEqual(code, 0, prep)
        _, entry = self.complete_task(run, prep, GOOD)
        self.assertEqual(entry['status'], 'completed')
        code, gate = self.rt('gate', run)
        self.assertEqual((code, gate['ok']), (0, True), gate)


class SkillSpecificEvidenceTests(TaskCase):

    def test_git_inventory_requests_pr_author_and_head_oid(self):
        calls = []

        def runner(argv, **kwargs):
            calls.append(argv)
            return {'rc': 0, 'stdout': '[]', 'stderr': '', 'error': None}

        inventory = rt.git_inventory(self.repo, 'main', [], True, runner=runner)
        self.assertIn('## open PRs', inventory)
        pr_calls = [argv for argv in calls if argv[:3] == ['gh', 'pr', 'list']]
        self.assertEqual(len(pr_calls), 1)
        fields = pr_calls[0][pr_calls[0].index('--json') + 1].split(',')
        self.assertIn('author', fields)
        self.assertIn('headRefOid', fields)
        self.assertIn('baseRefName', fields)
        self.assertIn('isCrossRepository', fields)

    def test_consolidate_skill_guards_remote_pr_and_merge_commit_safety(self):
        with open(os.path.join(SKILLS, 'ds-consolidate', 'SKILL.md'), encoding='utf-8') as handle:
            text = handle.read()
        for required in (
            'git log --merges --cc --format= -p',
            'pull/<n>/head',
            '--force-with-lease=refs/heads/<branch>:<verified-sha> origin :refs/heads/<branch>',
            'baseRefName',
            'origin/<DEFAULT_BRANCH>',
        ):
            self.assertIn(required, text)
        reconciliation = rt.load_profile('ds-consolidate')['review_kinds']['reconciliation']['focus']
        self.assertIn('baseRefName', reconciliation)
        self.assertIn('cross-repo/fork PRs', reconciliation)

    def test_non_media_manifest_path_never_affects_reuse(self):
        run = self.start('ds-ui-overhaul')
        shot = os.path.join(self.tmp, 'evidence', 'desktop.png')
        write(shot, 'PNGDATA')
        secret = os.path.join(self.tmp, 'proj', '.dev.vars')
        write(secret, 'API_TOKEN=SECRET-TOKEN-VALUE\n')
        manifest = os.path.join(self.tmp, 'rendered-reuse.md')
        write(manifest, 'desktop 1440x900: %s\nbuilt with env from %s\n' % (shot, secret))
        _, prep = self.rt('review', run, '--kind', 'ui-ux', '--base', self.base,
                          '--rendered-evidence', manifest, '--required')
        _, entry = self.complete_task(run, prep, GOOD)
        self.assertEqual(entry['status'], 'completed')
        write(secret, 'API_TOKEN=ROTATED-TOKEN-VALUE\n')  # a non-media path must not touch the candidate hash
        _, again = self.rt('review', run, '--kind', 'ui-ux', '--base', self.base,
                           '--rendered-evidence', manifest)
        self.assertTrue(again.get('reused'))
        self.assertEqual(again['status'], 'completed')

    def test_frontend_profile_requires_lighthouse_and_rendered_evidence(self):
        rules = rt.load_profile('ds-ui-overhaul')['rules']
        self.assertTrue(any('Lighthouse 13' in rule for rule in rules), rules)
        run = self.start('ds-ui-overhaul')
        for kind in ('ui-ux', 'accessibility'):
            code, out = self.rt('review', run, '--kind', kind, '--base', self.base)
            self.assertEqual(code, 1)
            self.assertIn('--rendered-evidence', out['error'])

        shot = os.path.join(self.tmp, 'evidence', 'mobile.png')
        write(shot, 'PNGDATA')
        secret = os.path.join(self.tmp, 'proj', '.dev.vars')
        write(secret, 'API_TOKEN=SECRET-TOKEN-VALUE\n')
        manifest = os.path.join(self.tmp, 'rendered.md')
        write(manifest, 'mobile 390x844: %s\nmissing: /nonexistent/x.png\nbuilt with env from %s\n' % (shot, secret))

        _, prep = self.rt('review', run, '--kind', 'ui-ux', '--base', self.base,
                          '--rendered-evidence', manifest, '--required')
        _, entry = self.complete_task(run, prep, GOOD)
        self.assertEqual((entry['status'], entry['rendered_evidence']), ('completed', 'manifest'))
        task_dir = os.path.dirname(entry['entry'])
        self.assertEqual(os.listdir(os.path.join(task_dir, 'rendered-files')), ['01-mobile.png'])
        with open(os.path.join(task_dir, 'prompt.md'), encoding='utf-8') as handle:
            prompt = handle.read()
        self.assertIn('Rendered/browser evidence manifest', prompt)
        self.assertIn('never claim that check happened', prompt)

        write(shot, 'NEW-SCREENSHOT')  # new screenshot invalidates reuse
        _, prep_new = self.rt('review', run, '--kind', 'ui-ux', '--base', self.base,
                              '--rendered-evidence', manifest)
        self.assertFalse(prep_new.get('reused'))
        self.assertEqual(prep_new['status'], 'pending')

        _, prep_no = self.rt('review', run, '--kind', 'accessibility', '--base', self.base,
                             '--no-rendered-evidence', 'no browser in this sandbox')
        _, acc = self.complete_task(run, prep_no, GOOD)
        self.assertEqual(acc['rendered_evidence'], 'none: no browser in this sandbox')
        with open(os.path.join(os.path.dirname(acc['entry']), 'rendered.txt'), encoding='utf-8') as handle:
            self.assertIn('Visual verification did not happen', handle.read())

    def test_consolidate_git_inventory_uncut_and_gate_detects_drift(self):
        sh(['git', 'checkout', '-q', '-b', 'feature'], self.repo)
        self.commit('feature.js', 'UNIQUE-PATCH-LINE\n', 'feature work')
        sh(['git', 'checkout', '-q', 'main'], self.repo)
        write(os.path.join(self.repo, 'app.js'), 'STASHED-LINE\n')
        sh(['git', 'stash', 'push', '-q', '-m', 'wip'], self.repo)
        clone = os.path.join(self.tmp, 'clone')
        sh(['git', 'clone', '-q', self.repo, clone], self.tmp)
        wt = os.path.join(self.tmp, 'wt')
        sh(['git', 'worktree', 'add', '-q', '--detach', wt], self.repo)
        write(os.path.join(wt, 'app.js'), 'WORKTREE-EDIT\n')

        run = self.start('ds-consolidate')
        ledger = self.handoff('feature: proven in main\nstash@{0}: proven in main\n')
        code, prep = self.rt('review', run, '--kind', 'reconciliation', '--base', self.base,
                             '--context', ledger, '--location', clone, '--required')
        self.assertEqual(code, 0, prep)
        self.assertIn(os.path.realpath(wt), prep['read_dirs'])
        self.assertIn(os.path.realpath(clone), prep['read_dirs'])
        with open(os.path.join(os.path.dirname(prep['entry']), 'git-inventory.md'), encoding='utf-8') as handle:
            inventory = handle.read()
        for marker in ('refs/heads/feature ahead=1 unique=1', 'UNIQUE-PATCH-LINE', 'STASHED-LINE',
                       'WORKTREE-EDIT', '## location %s' % clone):
            self.assertIn(marker, inventory)
        self.assertNotIn('truncated', inventory)

        code, entry = self.complete_task(run, prep, GOOD)
        self.assertEqual((code, entry['status']), (0, 'completed'))
        self.assertEqual(self.rt('gate', run)[0], 0)

        sh(['git', 'branch', 'late-branch', 'feature'], self.repo)
        code, gate = self.rt('gate', run)
        self.assertEqual(code, 1)
        self.assertIn('changed since the review', ' '.join(gate['problems']))


class DepsUpgradeSpecTests(TempCase):
    """Agent Skill spec checks ported from the retired admin validator (no installer code)."""

    SKILL = 'ds-deps-upgrade'
    SCRIPTS = ('scripts/depup.py', 'scripts/task_protocol.py', 'scripts/review_task.py')

    def skill_dir(self):
        return os.path.join(SKILLS, self.SKILL)

    def read(self, rel):
        with open(os.path.join(self.skill_dir(), rel), encoding='utf-8') as handle:
            return handle.read()

    @staticmethod
    def frontmatter(text):
        parts = text.split('---\n', 2)
        return parts[1] if len(parts) >= 3 and text.startswith('---\n') else None

    def test_frontmatter_license_and_explicit_only(self):
        text = self.read('SKILL.md')
        front = self.frontmatter(text)
        self.assertIsNotNone(front, 'SKILL.md needs YAML frontmatter')
        self.assertIn('name: %s\n' % self.SKILL, front + '\n')
        self.assertIn('license: MIT\n', front + '\n')
        self.assertIn('disable-model-invocation: true\n', front + '\n')
        self.assertIn('description:', front)
        description = re.search(r'^description:\s*(.+)$', front, re.M)
        self.assertIsNotNone(description)
        self.assertTrue(description.group(1).strip())
        self.assertLessEqual(len(description.group(1).strip()), 1024)

    def test_body_is_concise(self):
        text = self.read('SKILL.md')
        front = self.frontmatter(text)
        self.assertIsNotNone(front)
        body = text.split('---\n', 2)[2]
        self.assertLessEqual(len(body.splitlines()), 500)

    def test_internal_markdown_links_exist_and_do_not_escape(self):
        root = os.path.realpath(self.skill_dir())
        for rel in ('SKILL.md', 'README.md', 'references/workflow.md', 'references/safety.md',
                    'references/verification.md', 'references/report-schema.md',
                    'references/fresh-context-tasks.md', 'references/parallelism.md',
                    'references/javascript.md', 'references/ecosystems.md'):
            text = self.read(rel)
            for target in re.findall(r'\[[^\]]*\]\(([^)]+)\)', text):
                target = target.strip().split('#', 1)[0].split('"', 1)[0].strip()
                if not target or re.match(r'^(?:[a-z][a-z0-9+.-]*:|#)', target, re.I):
                    continue
                resolved = os.path.realpath(os.path.join(os.path.dirname(os.path.join(root, rel)), target))
                self.assertTrue(resolved == root or resolved.startswith(root + os.sep),
                                '%s escapes the skill: %s' % (rel, target))
                self.assertTrue(os.path.exists(resolved), '%s has a broken link: %s' % (rel, target))

    def test_documentation_and_major_migration_rules(self):
        skill = self.read('SKILL.md')
        workflow = self.read('references/workflow.md')
        safety = self.read('references/safety.md')

        # Frontmatter and the all-stable default align with the research contract.
        front = self.frontmatter(skill)
        self.assertIn('official documentation', front)
        self.assertIn('migration', front)
        self.assertIn('official migration guides/sources are verified', skill)

        # One authoritative non-negotiable rule (section 2) owns both requirements.
        rules = skill.split('## 2. Non-negotiable rules', 1)[1].split('## 3.', 1)[0]
        self.assertIn('Official documentation and major migration guides', rules)
        rule = re.sub(r'\s+', ' ', rules.split('Official documentation and major migration guides', 1)[1]).lower()
        for phrase in ('latest official documentation for every dependency being upgraded',
                       'official migration guides and migration sources',
                       'every major', 'cannot be found or verified', 'hold any major upgrade'):
            self.assertIn(phrase, rule)

        # The old "non-trivial target" loophole is gone everywhere.
        self.assertNotIn('non-trivial target', skill)
        self.assertNotIn('non-trivial target', workflow)

        # Research step 6 covers every target and holds unverified majors.
        self.assertIn('explicit source-gap note for non-major targets', skill)
        self.assertIn('is marked held', skill)

        # Offline degradation never mutates a major or high-risk item without source research.
        offline = skill.split('- No network:', 1)[1].split('- No write access:', 1)[0]
        self.assertIn('Never mutate a major upgrade or a high-risk item', offline)
        self.assertIn('never guess from memory', offline)

        research = re.sub(r'\s+', ' ', workflow.split('## 4. `research`', 1)[1].split('## 5. `plan`', 1)[0]).lower()
        for phrase in ('every dependency being upgraded', 'patch', 'minor', 'major',
                       'prerelease', 'deprecated', 'unknown', 'official documentation',
                       'official migration guides and migration sources', 'every major',
                       'hold any major upgrade'):
            self.assertIn(phrase, research)

        plan = re.sub(r'\s+', ' ', workflow.split('## 5. `plan`', 1)[1].split('## 6. `worktree`', 1)[0]).lower()
        self.assertIn('official documentation links', plan)
        self.assertIn('official migration guide/source links', plan)

        batch = re.sub(r'\s+', ' ', workflow.split('## 7. `batch-N`', 1)[1].split('## 8. `verify`', 1)[0]).lower()
        self.assertIn('researched latest official documentation', batch)
        self.assertIn('official migration guide/sources', batch)

        # Official docs and migration guides stay untrusted data for prompt-injection defense.
        untrusted = re.sub(r'\s+', ' ', safety.split('## Untrusted content', 1)[1].split('\n## ', 1)[0]).lower()
        self.assertIn('official documentation', untrusted)
        self.assertIn('migration guides', untrusted)
        self.assertIn('**data**', untrusted)

    def test_no_symlinks_inside_the_skill(self):
        root = self.skill_dir()
        for dirpath, dirnames, filenames in os.walk(root):
            for name in dirnames + filenames:
                self.assertFalse(os.path.islink(os.path.join(dirpath, name)),
                                 'symlink inside the skill: %s' % os.path.join(dirpath, name))

    def test_scripts_compile_cleanly(self):
        for rel in self.SCRIPTS:
            path = os.path.join(self.skill_dir(), rel)
            py_compile.compile(path, cfile=os.path.join(self.tmp, os.path.basename(rel) + 'c'), doraise=True)


if __name__ == '__main__':
    unittest.main()
