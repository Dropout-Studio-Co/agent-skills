"""Fresh-context review and planning tasks for dependency-upgrade (model- and harness-agnostic).

Tests cover prompt/parser strictness, prepare/record/unavailable flows, candidate binding,
reuse, tamper/tree-change detection, high-risk distinct-reviewer dossiers, and absence of
model/harness/CLI coupling. No test calls any model or external CLI.
"""
import hashlib
import json
import os
import re
import unittest

from tests.support import TempCase, depup, git_init, load, sh, write

tp = load('task_protocol_under_test', 'scripts/task_protocol.py')

GOOD = (
    'Looked at every hunk.\n%s\n{"verdict": "pass", "summary": "clean", "findings": '
    '[{"severity": "Nit", "file": "a.js", "line": 1, "summary": "naming", "scenario": "none"}]}\n%s\n'
    % (tp.RESULT_BEGIN, tp.RESULT_END)
)
FAIL_REVIEW = (
    'Found a bug.\n%s\n{"verdict": "fail", "summary": "broken import", "findings": '
    '[{"severity": "Important", "file": "src/a.js", "line": 4, "summary": "missing export", '
    '"scenario": "runtime TypeError"}]}\n%s\n'
    % (tp.RESULT_BEGIN, tp.RESULT_END)
)
PLAN = {
    'summary': 'Upgrade a 1 -> 2 in one batch.',
    'decisions': [{'decision': 'single batch', 'rationale': 'no coupled family'}],
    'steps': [{'id': 'batch-1', 'summary': 'npm install a@2', 'checks': ['npm test']}],
    'risks': [],
    'holds': [],
}
PLAN_TEXT = 'Plan follows.\n%s\n%s\n%s\n' % (tp.PLAN_BEGIN, json.dumps(PLAN), tp.PLAN_END)


class TaskProtocolUnitTests(TempCase):

    def test_protocol_module_has_no_model_or_harness_coupling(self):
        import ast
        with open(tp.__file__, encoding='utf-8') as handle:
            source = handle.read()
        tree = ast.parse(source)
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        self.assertNotIn('subprocess', imports)
        for forbidden in ('claude-opus', 'claude -p', 'opencode', 'deepseek',
                          'ANTHROPIC_API_KEY', 'PREFERRED', 'EFFORTS', 'class Router'):
            self.assertNotIn(forbidden, source, forbidden)
        for removed in ('Router', 'PREFERRED', 'HARNESS_CLI', 'EFFORTS', 'PLAN_EFFORT', 'REVIEW_EFFORT'):
            self.assertFalse(hasattr(tp, removed), removed)

    def test_result_parsing_is_strict(self):
        self.assertIsNone(tp.parse_result('no block')[0])
        placeholder = '%s\n{"verdict": "<pass|fail>", "findings": []}\n%s' % (tp.RESULT_BEGIN, tp.RESULT_END)
        self.assertIsNone(tp.parse_result(placeholder)[0], 'the prompt template never counts as a result')
        lying = '%s\n{"verdict": "pass", "findings": [{"severity": "Important", "summary": "bug"}]}\n%s' % (
            tp.RESULT_BEGIN, tp.RESULT_END)
        parsed, problem = tp.parse_result(lying)
        self.assertIsNone(problem)
        self.assertEqual(parsed['verdict'], 'fail')
        self.assertTrue(parsed['corrections'])

    def test_plan_parser_is_strict(self):
        self.assertIsNone(tp.parse_plan_result('no block')[0])
        empty = dict(PLAN, steps=[])
        text = '%s\n%s\n%s' % (tp.PLAN_BEGIN, json.dumps(empty), tp.PLAN_END)
        self.assertIsNone(tp.parse_plan_result(text, 'plan')[0], 'a plan needs steps')
        self.assertIsNotNone(tp.parse_plan_result(text, 'architecture')[0], 'architecture needs decisions only')
        nodecision = '%s\n%s\n%s' % (tp.PLAN_BEGIN, json.dumps(dict(PLAN, decisions=[])), tp.PLAN_END)
        self.assertIsNone(tp.parse_plan_result(nodecision, 'architecture')[0])
        self.assertIsNone(tp.parse_result(PLAN_TEXT)[0], 'a plan never counts as a review result')


class DepupTaskCase(TempCase):

    def upgrade_run(self):
        root = os.path.join(self.tmp, 'repo')
        write(os.path.join(root, 'package.json'), {'name': 'r', 'dependencies': {'a': '^1.0.0'}})
        write(os.path.join(root, 'package-lock.json'), {'lockfileVersion': 3, 'packages': {'a': '1.0.0'}})
        git_init(root)
        _, start = self.cli('run', 'start', '--repo', root, '--mode', 'upgrade')
        _, worktree = self.cli('run', 'worktree', start['run_ref'])
        wt = worktree['worktree']
        write(os.path.join(wt, 'package.json'), {'name': 'r', 'dependencies': {'a': '^2.0.0'}})
        write(os.path.join(wt, 'package-lock.json'), {'lockfileVersion': 3, 'packages': {'a': '2.0.0'}})
        sh(['git', 'add', '-A'], wt)
        sh(['git', 'commit', '-q', '-m', 'deps: a 1 -> 2'], wt)
        return start, wt

    def plan_run(self):
        root = os.path.join(self.tmp, 'repo')
        write(os.path.join(root, 'package.json'), {'name': 'r', 'dependencies': {'a': '^1.0.0'}})
        git_init(root)
        _, start = self.cli('run', 'start', '--repo', root, '--mode', 'plan')
        return start, root

    def handoff(self, text='scope: all-stable\noutdated: a 1.0.0 -> 2.0.0 (major)\ntoken=SECRET-TOKEN-VALUE\n'):
        path = os.path.join(self.tmp, 'handoff.md')
        write(path, text)
        return path

    def write_out(self, path, text):
        write(path, text)
        return path


class ReviewIntegrationTests(DepupTaskCase):

    def test_prepare_record_binds_receipt_and_reuses_completed_review(self):
        start, wt = self.upgrade_run()
        code, prep = self.cli('review', 'prepare', start['run_ref'], '--kind', 'critical', '--required')
        self.assertEqual(code, 0, prep)
        self.assertEqual(prep['status'], 'pending')
        self.assertTrue(os.path.isfile(prep['prompt_path']))
        review_dir = os.path.dirname(prep['entry'])
        with open(os.path.join(review_dir, 'lockfile.diff'), encoding='utf-8') as handle:
            self.assertIn('2.0.0', handle.read(), 'the lockfile diff is reviewed in full')
        with open(os.path.join(review_dir, 'code.diff'), encoding='utf-8') as handle:
            code_diff = handle.read()
        self.assertIn('package.json', code_diff)
        self.assertNotIn('package-lock.json', code_diff)

        out_file = self.write_out(prep['output_path'], GOOD)
        code, entry = self.cli('review', 'record', start['run_ref'], '--review-id', prep['id'],
                               '--output', out_file, '--reviewer', 'fresh-subagent-1')
        self.assertEqual(code, 0, entry)
        self.assertEqual((entry['status'], entry['verdict']), ('completed', 'pass'))
        self.assertNotIn('selected', entry)
        self.assertNotIn('next', entry)
        candidate = depup.git_state(wt)['head']
        self.assertTrue(depup.bound_evidence(start['run_dir'], entry['evidence'],
                                             start['run_ref'].split('/')[1], candidate,
                                             'critical-review', 'full-diff', 'pass'))
        code, again = self.cli('review', 'prepare', start['run_ref'], '--kind', 'critical')
        self.assertEqual(code, 0)
        self.assertTrue(again['reused'])
        self.assertEqual(again['verdict'], 'pass')

    def test_worktree_change_between_prepare_and_record_discards_result(self):
        start, wt = self.upgrade_run()
        _, prep = self.cli('review', 'prepare', start['run_ref'], '--kind', 'critical', '--required')
        write(os.path.join(wt, 'extra.txt'), 'mutated\n')
        out_file = self.write_out(prep['output_path'], GOOD)
        code, entry = self.cli('review', 'record', start['run_ref'], '--review-id', prep['id'],
                               '--output', out_file, '--reviewer', 'fresh-subagent-1')
        self.assertEqual(code, 0)
        self.assertEqual(entry['status'], 'unavailable')
        self.assertTrue(entry['tree_changed'])
        self.assertIn('changed since the review was prepared', entry['reason'])

    def test_invalid_review_output_marks_unavailable(self):
        start, _ = self.upgrade_run()
        _, prep = self.cli('review', 'prepare', start['run_ref'], '--kind', 'critical', '--required')
        out_file = self.write_out(prep['output_path'], 'no valid block here')
        code, entry = self.cli('review', 'record', start['run_ref'], '--review-id', prep['id'],
                               '--output', out_file, '--reviewer', 'fresh-subagent-1')
        self.assertEqual(code, 0)
        self.assertEqual(entry['status'], 'unavailable')
        self.assertIn('output invalid', entry['reason'])

    def test_unavailable_and_pending_required_review_prevent_pass(self):
        start, wt = self.upgrade_run()
        ref, run_dir = start['run_ref'], start['run_dir']
        _, prep = self.cli('review', 'prepare', ref, '--kind', 'security', '--subject', 'db', '--required')
        with open(start['journal'], encoding='utf-8') as handle:
            run_id = json.load(handle)['run_id']
        candidate = depup.git_state(wt)['head']
        write(os.path.join(run_dir, 'logs', 'tests.log'), 'pass\n')
        digest = hashlib.sha256(b'pass\n').hexdigest()
        write(os.path.join(run_dir, 'logs', 'tests.json'), {
            'run_id': run_id, 'candidate_head': candidate, 'kind': 'verification', 'subject': 'npm test',
            'result': 'pass', 'reviewer': 'runner', 'artifact': 'logs/tests.log', 'artifact_sha256': digest})
        for step in ('baseline', 'verify', 'review'):
            self.cli('run', 'step', ref, '--id', step, '--status', 'done')
        payload = {'status': 'PASS', 'verification': [{'check': 'tests', 'command': 'npm test', 'result': 'pass',
                                                       'log': 'logs/tests.log', 'evidence': 'logs/tests.json'}]}
        path = os.path.join(self.tmp, 'in.json')
        write(path, payload)
        # Pending required review on disk blocks PASS even if omitted from input.
        _, rep = self.cli('report', ref, '--input', path)
        self.assertEqual(rep['status'], 'PARTIAL')
        self.assertTrue(any('required review' in c for c in rep['corrections']), rep['corrections'])
        # Marking unavailable also blocks PASS.
        code, unavail = self.cli('review', 'unavailable', ref, '--review-id', prep['id'],
                                 '--reason', 'harness has no fresh-context mechanism')
        self.assertEqual((code, unavail['status']), (0, 'unavailable'))
        payload['reviews'] = [unavail]
        write(path, payload)
        _, rep = self.cli('report', ref, '--input', path)
        self.assertEqual(rep['status'], 'PARTIAL')
        with open(rep['summary'], encoding='utf-8') as handle:
            summary = handle.read()
        self.assertIn('## Reviews', summary)
        self.assertIn('harness has no fresh-context mechanism', summary)
        # A forged "completed" entry without a candidate-bound receipt cannot unlock PASS either.
        forged = dict(unavail, status='completed', verdict='pass', evidence='logs/tests.json')
        payload['reviews'] = [forged]
        write(path, payload)
        _, rep = self.cli('report', ref, '--input', path)
        self.assertEqual(rep['status'], 'PARTIAL')

    def test_old_router_subcommands_are_gone(self):
        start, _ = self.upgrade_run()
        for argv in (
            ['review', 'run', start['run_ref'], '--kind', 'critical'],
            ['review', 'probe'],
            ['planning', 'run', start['run_ref'], '--context', self.handoff()],
        ):
            with self.subTest(argv):
                with self.assertRaises(SystemExit) as raised:
                    depup.main(argv)
                self.assertEqual(raised.exception.code, 2)

    def test_distinct_independent_and_security_reviews_satisfy_high_risk_dossier(self):
        start, wt = self.upgrade_run()
        ref, run_dir = start['run_ref'], start['run_dir']
        recorded = {}
        for kind, subject in (('independent', 'db'), ('security', 'db'), ('critical', None)):
            args = ['review', 'prepare', ref, '--kind', kind, '--required']
            if subject:
                args += ['--subject', subject]
            _, prep = self.cli(*args)
            out_file = self.write_out(prep['output_path'], GOOD)
            _, rec = self.cli('review', 'record', ref, '--review-id', prep['id'],
                              '--output', out_file, '--reviewer', 'session-fresh-context')
            recorded[kind] = rec
        self.assertNotEqual(recorded['independent']['reviewer'], recorded['security']['reviewer'],
                            'same session model still gets distinct fresh-context reviewer identities')
        with open(start['journal'], encoding='utf-8') as handle:
            run_id = json.load(handle)['run_id']
        candidate = depup.git_state(wt)['head']
        write(os.path.join(run_dir, 'logs', 'tests.log'), 'pass\n')
        write(os.path.join(run_dir, 'logs', 'tests.json'), {
            'run_id': run_id, 'candidate_head': candidate, 'kind': 'verification', 'subject': 'npm test',
            'result': 'pass', 'reviewer': 'runner', 'artifact': 'logs/tests.log',
            'artifact_sha256': hashlib.sha256(b'pass\n').hexdigest()})
        for step in ('baseline', 'verify', 'review'):
            self.cli('run', 'step', ref, '--id', step, '--status', 'done')
        payload = {
            'status': 'PASS',
            'reviews': [recorded['independent'], recorded['security'], recorded['critical']],
            'verification': [{'check': 'tests', 'command': 'npm test', 'result': 'pass',
                              'log': 'logs/tests.log', 'evidence': 'logs/tests.json'}],
            'upgrades': [{'name': 'db', 'impact_tier': 'high', 'status': 'done'}],
            'risks': [{
                'name': 'db', 'summary': 'db', 'severity': 'high', 'disposition': 'proceed',
                'analysis': 'mapped', 'recovery': 'revert on owned branch',
                'sources': [{'name': 'guide', 'url': 'https://example.test', 'retrieved': '2026-11-03'}],
                'alternatives': ['stay'], 'controls': ['staged'],
                'reviews': [
                    {'type': 'independent', 'status': 'pass', 'evidence': recorded['independent']['evidence']},
                    {'type': 'security', 'status': 'pass', 'evidence': recorded['security']['evidence']},
                ],
            }],
        }
        path = os.path.join(self.tmp, 'in.json')
        write(path, payload)
        _, rep = self.cli('report', ref, '--input', path)
        self.assertEqual(rep['status'], 'PASS', rep['corrections'])


class PlanningIntegrationTests(DepupTaskCase):

    def test_planning_prepare_record_redacts_handoff_and_reuses(self):
        start, root = self.plan_run()
        code, prep = self.cli('planning', 'prepare', start['run_ref'], '--context', self.handoff())
        self.assertEqual((code, prep['status']), (0, 'pending'))
        self.assertEqual(prep['target'], root)
        plan_dir = os.path.dirname(prep['entry'])
        with open(os.path.join(plan_dir, 'prompt.md'), encoding='utf-8') as handle:
            prompt = handle.read()
        self.assertIn(os.path.join(plan_dir, 'context.md'), prompt)
        self.assertIn('Do not edit or create files', prompt)
        with open(os.path.join(plan_dir, 'context.md'), encoding='utf-8') as handle:
            context = handle.read()
        self.assertIn('a 1.0.0 -> 2.0.0', context)
        self.assertNotIn('SECRET-TOKEN-VALUE', context, 'handoff is redacted')

        out_file = self.write_out(prep['output_path'], PLAN_TEXT)
        code, entry = self.cli('planning', 'record', start['run_ref'], '--plan-id', prep['id'],
                               '--output', out_file, '--planner', 'fresh-planner-1')
        self.assertEqual((code, entry['status']), (0, 'completed'))
        self.assertEqual(entry['plan']['steps'][0]['id'], 'batch-1')
        self.assertTrue(os.path.isfile(os.path.join(plan_dir, 'receipt.json')))
        self.assertTrue(depup.git_state(root)['clean'])

        _, again = self.cli('planning', 'prepare', start['run_ref'], '--context', self.handoff())
        self.assertTrue(again['reused'])

    def test_checkout_change_during_planning_is_discarded_and_reported(self):
        start, root = self.plan_run()
        _, prep = self.cli('planning', 'prepare', start['run_ref'], '--context', self.handoff())
        write(os.path.join(root, 'stray.txt'), 'x')
        out_file = self.write_out(prep['output_path'], PLAN_TEXT)
        _, entry = self.cli('planning', 'record', start['run_ref'], '--plan-id', prep['id'],
                            '--output', out_file, '--planner', 'fresh-planner-1')
        self.assertEqual(entry['status'], 'unavailable')
        self.assertTrue(entry['tree_changed'])
        self.assertNotIn('plan', entry)
        _, rep = self.cli('report', start['run_ref'])
        with open(rep['report'], encoding='utf-8') as handle:
            report = json.load(handle)
        self.assertFalse(report['rollback']['user_checkout_untouched'])
        self.assertTrue(any('user checkout changed' in c for c in rep['corrections']))

    def test_architecture_task_and_report_summary(self):
        start, wt = self.upgrade_run()
        code, refused = self.cli('planning', 'prepare', start['run_ref'], '--kind', 'architecture',
                                 '--context', self.handoff())
        self.assertEqual(code, 1)
        self.assertIn('--subject', refused['error'])
        _, prep = self.cli('planning', 'prepare', start['run_ref'], '--kind', 'architecture',
                           '--subject', 'db', '--context', self.handoff())
        out_file = self.write_out(prep['output_path'], PLAN_TEXT)
        _, arch = self.cli('planning', 'record', start['run_ref'], '--plan-id', prep['id'],
                           '--output', out_file, '--planner', 'fresh-architect')
        self.assertEqual((arch['status'], arch['target']), ('completed', wt))
        path = os.path.join(self.tmp, 'in.json')
        write(path, {'status': 'PARTIAL', 'planning': []})
        _, rep = self.cli('report', start['run_ref'], '--input', path)
        with open(rep['report'], encoding='utf-8') as handle:
            report = json.load(handle)
        self.assertEqual([p['kind'] for p in report['planning']], ['architecture'])
        with open(rep['summary'], encoding='utf-8') as handle:
            summary = handle.read()
        self.assertIn('## Architecture and planning', summary)
        self.assertIn('architecture db: completed — fresh-architect', summary)

    def test_planning_unavailable_and_dirty_tree_changes_reuse_key(self):
        start, root = self.plan_run()
        _, prep = self.cli('planning', 'prepare', start['run_ref'], '--context', self.handoff())
        code, entry = self.cli('planning', 'unavailable', start['run_ref'], '--plan-id', prep['id'],
                               '--reason', 'no fresh context available')
        self.assertEqual((code, entry['status']), (0, 'unavailable'))
        _, rep = self.cli('report', start['run_ref'])
        with open(rep['summary'], encoding='utf-8') as handle:
            summary = handle.read()
        self.assertIn('plan upgrade: unavailable — no fresh context available', summary)
        write(os.path.join(root, 'package.json'), {'name': 'r', 'dependencies': {'a': '^1.5.0'}})
        _, second = self.cli('planning', 'prepare', start['run_ref'], '--context', self.handoff())
        self.assertNotEqual(prep['id'], second['id'], 'uncommitted work changes the reuse key')


if __name__ == '__main__':
    unittest.main()
