"""review_task.py: model- and harness-agnostic fresh-context tasks for consolidate and frontend-ui-ux-overhaul.

Also verifies cross-skill model/harness neutrality across every non-exception skill in the repo.
No test calls any model or external CLI.
"""
import contextlib
import io
import json
import os
import re
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

    def test_both_sibling_skills_ship_model_agnostic_profiles(self):
        for skill, kinds, plan_kinds in (
            ('consolidate', {'reconciliation', 'code'}, {'plan', 'architecture', 'consult'}),
            ('frontend-ui-ux-overhaul', {'code', 'ui-ux', 'accessibility'}, {'plan', 'architecture'}),
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
            self.assertIn('execution-protocol', text)
            self.assertIn('explicitly invoked', text)
            for forbidden in ('Opus 5.5', 'xhigh', 'routed_task.py', 'review_router.py', 'DeepSeek', '--high'):
                self.assertNotIn(forbidden, text, '%s should not contain %s' % (skill, forbidden))
        self.assertEqual(rt.load_profile('consolidate')['review_kinds']['reconciliation']['evidence'], 'git-inventory')

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
        run = self.start('consolidate')
        code, out = self.rt('review', run, '--kind', 'ui-ux', '--base', self.base)
        self.assertEqual(code, 1)
        self.assertIn('--kind must be one of', out['error'])

    def test_all_non_exception_skills_are_model_and_harness_agnostic(self):
        forbidden_re = re.compile(
            r'claude-opus|claude-sonnet|claude-haiku|\bopus 5\.5\b|claude -p|claude --bg|'
            r'claude auth|claude agents|claude attach|review_router\.py|routed_task\.py|'
            r'routing\.json|--effort|\bxhigh\b|deepseek', re.I)
        non_exception = ('consolidate', 'dependency-upgrade', 'frontend-ui-ux-overhaul',
                         'intrinsic-responsive-ui', 'review-loop', 'safe-switch', 'sync-agent-instructions')
        for skill in non_exception:
            skill_dir = os.path.join(SKILLS, skill)
            for dirpath, dirnames, filenames in os.walk(skill_dir):
                dirnames[:] = [d for d in dirnames if d not in ('__pycache__', 'tests')]
                for name in filenames:
                    if not name.endswith(('.md', '.py', '.json')):
                        continue
                    full = os.path.join(dirpath, name)
                    rel = os.path.relpath(full, SKILLS)
                    # check_instructions.py has a regex listing model names to reject user-global lines from AGENTS.md
                    if rel == 'sync-agent-instructions/scripts/check_instructions.py':
                        continue
                    with open(full, encoding='utf-8') as handle:
                        text = handle.read()
                    match = forbidden_re.search(text)
                    self.assertIsNone(match, '%s matched forbidden coupling %r' % (rel, match and match.group(0)))

        # Skills that mention execution-protocol must scope its precedence to explicit invocation.
        for skill in ('consolidate', 'dependency-upgrade', 'frontend-ui-ux-overhaul', 'review-loop', 'safe-switch'):
            with open(os.path.join(SKILLS, skill, 'SKILL.md'), encoding='utf-8') as handle:
                text = handle.read()
            self.assertIn('execution-protocol', text, skill)
            self.assertIn('explicitly invoked', text, skill)


class PlanningAndConsultTests(TaskCase):

    def test_plan_prepare_record_redacts_handoff_and_reuses(self):
        run = self.start('consolidate')
        code, prep = self.rt('plan', run, '--context', self.handoff())
        self.assertEqual((code, prep['status']), (0, 'pending'))
        self.assertTrue(prep['advisory'])
        task_dir = os.path.dirname(prep['entry'])
        with open(os.path.join(task_dir, 'prompt.md'), encoding='utf-8') as handle:
            prompt = handle.read()
        self.assertIn('authorizes nothing', prompt)
        self.assertIn('consolidate skill', prompt)
        self.assertIn('proven in main', prompt)
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
        run = self.start('frontend-ui-ux-overhaul')
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
        run = self.start('consolidate')
        code, out = self.rt('plan', run, '--context', self.handoff(), '--kind', 'consult')
        self.assertEqual(code, 1)
        self.assertIn('--subject is required for a consult task', out['error'])
        other = self.start('frontend-ui-ux-overhaul')
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
        with open(os.path.join(SKILLS, 'consolidate', 'SKILL.md'), encoding='utf-8') as handle:
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
        focus = rt.load_profile('consolidate')['plan_kinds']['consult']
        self.assertIn('batch', focus)
        self.assertIn('never treat your recommendation as proof', focus)


class ReviewGateTests(TaskCase):

    def test_gate_blocks_until_required_review_passes_on_current_candidate(self):
        run = self.start('frontend-ui-ux-overhaul')
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
        run = self.start('frontend-ui-ux-overhaul')
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

    def test_tree_change_during_review_discards_result_and_blocks(self):
        run = self.start('frontend-ui-ux-overhaul')
        _, prep = self.rt('review', run, '--kind', 'code', '--base', self.base, '--required')
        write(os.path.join(self.repo, 'app.js'), 'export const a = 99;\n')
        _, rec = self.complete_task(run, prep, GOOD)
        self.assertEqual(rec['status'], 'unavailable')
        self.assertTrue(rec['tree_changed'])
        self.assertEqual(self.rt('gate', run)[0], 1)

    def test_rerun_without_required_never_downgrades_and_newer_context_blocks(self):
        run = self.start('frontend-ui-ux-overhaul')
        _, prep = self.rt('review', run, '--kind', 'code', '--required')
        self.complete_task(run, prep, GOOD)
        self.assertEqual(self.rt('gate', run)[0], 0)
        _, prep2 = self.rt('review', run, '--kind', 'code', '--rerun')  # forgot --required
        self.assertTrue(prep2['required'])
        self.rt('unavailable', run, '--task-id', prep2['id'], '--reason', 'failed')
        self.assertEqual(self.rt('gate', run)[0], 1)

        run2 = self.start('consolidate')
        _, p1 = self.rt('review', run2, '--kind', 'reconciliation', '--required', '--context', self.handoff('ledger A\n'))
        self.complete_task(run2, p1, GOOD)
        _, p2 = self.rt('review', run2, '--kind', 'reconciliation', '--required', '--context', self.handoff('ledger B\n'))
        self.rt('unavailable', run2, '--task-id', p2['id'], '--reason', 'failed')
        self.assertEqual(self.rt('gate', run2)[0], 1)

    def test_base_is_bound_to_the_run(self):
        run = self.start('frontend-ui-ux-overhaul')
        self.commit('app.js', 'export const a = 5;\n')
        code, out = self.rt('review', run, '--kind', 'code', '--base', 'HEAD')
        self.assertEqual(code, 1)
        self.assertIn('differs from the run base', out['error'])

    def test_removed_flags_and_probe_are_gone(self):
        run = self.start('consolidate')
        for argv in (
            ('probe',),
            ('review', run, '--kind', 'code', '--high'),
            ('review', run, '--kind', 'code', '--session-harness', 'x'),
        ):
            with self.subTest(argv):
                with self.assertRaises(SystemExit) as raised:
                    rt.main(list(argv))
                self.assertEqual(raised.exception.code, 2)


class SkillSpecificEvidenceTests(TaskCase):

    def test_frontend_profile_requires_lighthouse_and_rendered_evidence(self):
        rules = rt.load_profile('frontend-ui-ux-overhaul')['rules']
        self.assertTrue(any('Lighthouse 13' in rule for rule in rules), rules)
        run = self.start('frontend-ui-ux-overhaul')
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

        run = self.start('consolidate')
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


if __name__ == '__main__':
    unittest.main()
