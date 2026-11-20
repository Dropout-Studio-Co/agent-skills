"""Reviewer routing: one route (Claude Opus 5.5) and an outage blocks; no fallback.

Every CLI (claude) is mocked; no test makes a model call.
"""
import hashlib
import json
import os
import re

from tests.support import TempCase, depup, git_init, load, sh, write

rr = load('review_router_under_test', 'scripts/review_router.py')

GOOD = ('Looked at every hunk.\n%s\n{"verdict": "pass", "summary": "clean", "findings": '
        '[{"severity": "Nit", "file": "a.js", "line": 1, "summary": "naming", "scenario": "none"}]}\n%s\n'
        % (rr.RESULT_BEGIN, rr.RESULT_END))
PARTIAL_FINDING = 'Important: src/db.js:3 drops a column (partial, cut off)'
CLAUDE_HELP = '  --effort <level>    Effort level for the current session\n    (low, medium, high, xhigh, max)\n'


def ok(stdout='', stderr=''):
    return {'rc': 0, 'stdout': stdout, 'stderr': stderr, 'error': None}


def fail(stdout='', stderr='', rc=1):
    return {'rc': rc, 'stdout': stdout, 'stderr': stderr, 'error': None}


def claude_result(text, model='claude-opus-5-5', error=False, status='allowed', api_status=None):
    events = [{'type': 'system', 'subtype': 'init'},
              {'type': 'rate_limit_event', 'rate_limit_info': {'status': status, 'resetsAt': 1893456000,
                                                               'rateLimitType': 'five_hour', 'utilization': 0.4}},
              {'type': 'result', 'subtype': 'error_during_execution' if error else 'success', 'is_error': error,
               'api_error_status': api_status, 'result': text, 'modelUsage': {model: {'outputTokens': 10}}}]
    return '\n'.join(json.dumps(e) for e in events) + '\n'


class FakeHarnesses:
    """Scripted claude CLI. `reviews['claude-code']` is consumed one response per review run."""

    def __init__(self, tmp, missing=(), claude_logged_in=True, claude_help=CLAUDE_HELP, reviews=None):
        self.missing = set(missing)
        self.claude_logged_in, self.claude_help = claude_logged_in, claude_help
        self.reviews = {'claude-code': list((reviews or {}).get('claude-code', []))}
        self.calls = []
        self.cwds = []
        self.sleeps = []

    def which(self, name):
        return None if name in self.missing else '/usr/bin/' + name

    def review_calls(self):
        return [c for c in self.calls if c[:2] == ['claude', '-p']]

    def runner(self, argv, cwd=None, env=None, timeout=60):
        self.calls.append(list(argv))
        self.cwds.append(cwd)
        name = argv[0]
        if argv[1:] == ['--version']:
            return ok('%s 1.0\n' % name)
        if argv[:2] == ['claude', '--help']:
            return ok(self.claude_help)
        if argv[:3] == ['claude', 'auth', 'status']:
            return ok(json.dumps({'loggedIn': self.claude_logged_in, 'authMethod': 'claude.ai',
                                  'email': 'someone@example.invalid', 'subscriptionType': 'pro'}))
        assert name == 'claude', 'only the claude CLI may ever run'
        assert env and env.get(rr.GUARD_ENV) == '1', 'reviewers run with the recursion guard set'
        response = self.reviews['claude-code'].pop(0)
        return {k: response.get(k, d) for k, d in (('rc', 0), ('stdout', ''), ('stderr', ''), ('error', None))}


def make_router(fake, environ=None, max_retries=1):
    return rr.Router(runner=fake.runner, which=fake.which, sleep=fake.sleeps.append, environ=environ or {},
                     timeout=60, max_retries=max_retries, retry_delay=7)


class RouterCase(TempCase):
    def ctx(self, name='critical-full-diff-abc'):
        reviews_dir = os.path.join(self.tmp, 'run', name, 'reviews')
        review_dir = os.path.join(reviews_dir, name)
        os.makedirs(review_dir, exist_ok=True)
        return {'review_id': name, 'review_dir': review_dir, 'reviews_dir': reviews_dir,
                'worktree': self.tmp, 'prompt': 'PROMPT', 'redact': depup.redact_text}

    def route(self, fake, environ=None, max_retries=1, **ctx_extra):
        ctx = dict(self.ctx(ctx_extra.pop('name', 'critical-full-diff-abc')), **ctx_extra)
        return make_router(fake, environ, max_retries).route(ctx)


class RouterUnitTests(RouterCase):

    def test_only_route_is_claude_opus_5_5(self):
        self.assertEqual(rr.PREFERRED, ({'priority': 1, 'harness': 'claude-code', 'model': 'claude-opus-5-5',
                                          'display': 'Claude Opus 5.5', 'effort': 'medium'},))
        self.assertEqual(rr.HARNESS_CLI, {'claude-code': 'claude'})
        for removed in ('opencode_agent', 'symlink_escape', '_toolchain_target', 'normalize_harness',
                        'detect_harness', 'session_candidate', 'retired_route'):
            self.assertFalse(hasattr(rr, removed), removed)
        import inspect
        self.assertEqual(list(inspect.signature(rr.Router.route).parameters), ['self', 'ctx'])
        with open(rr.__file__, encoding='utf-8') as handle:
            source = handle.read()
        self.assertFalse(re.search(r'deepseek|opencode', source, re.I))

    def test_opus_available_selects_opus_with_one_call(self):
        fake = FakeHarnesses(self.tmp, reviews={'claude-code': [{'stdout': claude_result(GOOD)}]})
        evidence, selected, done = self.route(fake)
        self.assertEqual((selected['harness'], selected['model'], selected['effort']),
                         ('claude-code', 'claude-opus-5-5', 'medium'))
        self.assertEqual(len(fake.review_calls()), 1, 'exactly one reviewer call')
        argv = fake.review_calls()[0]
        self.assertEqual(argv[argv.index('--model') + 1], 'claude-opus-5-5')
        self.assertEqual(argv[argv.index('--effort') + 1], 'medium')
        self.assertEqual(argv[argv.index('--tools') + 1], 'Read,Grep,Glob', 'reviewer is read-only')
        self.assertNotIn('--fallback-model', argv)
        review_cwd = fake.cwds[fake.calls.index(argv)]
        self.assertTrue(review_cwd.startswith(self.ctx()['review_dir']), 'reviewers never run inside the repo')
        self.assertIn(self.tmp, argv[argv.index('--add-dir') + 1:], 'the worktree is granted read access')
        self.assertEqual(done[1]['verdict'], 'pass')
        self.assertEqual(evidence['candidates'][0]['usage'], 'confirmed', 'rate_limit_event confirms usage')

    def test_opus_outage_blocks_without_fallback(self):
        def assert_blocked(fake, name, max_retries=1):
            evidence, selected, done = self.route(fake, name=name, max_retries=max_retries)
            self.assertEqual(evidence.get('outcome'), 'unavailable', name)
            self.assertIsNone(selected, name)
            self.assertIsNone(done, name)
            self.assertFalse([c for c in fake.calls if c and c[0] != 'claude'], fake.calls)
            for candidate in evidence['candidates']:
                for attempt in candidate.get('attempts', []):
                    self.assertTrue(os.path.isfile(os.path.join(attempt['attempt_dir'], 'DISCARDED')), name)

        overloaded = {'stdout': claude_result('API Error: 529 overloaded', error=True, api_status=529), 'rc': 1}
        scenarios = {
            'missing-cli': FakeHarnesses(self.tmp, missing={'claude'}),
            'not-authenticated': FakeHarnesses(self.tmp, claude_logged_in=False),
            'unsupported-effort': FakeHarnesses(self.tmp, claude_help=CLAUDE_HELP.replace('medium, ', '')),
            'rejected-mid-run': FakeHarnesses(self.tmp, reviews={'claude-code': [{
                'stdout': claude_result(PARTIAL_FINDING + '\nClaude AI usage limit reached', error=True,
                                        status='rejected', api_status=429), 'rc': 1}]}),
            'transient-recurs': FakeHarnesses(self.tmp, reviews={'claude-code': [dict(overloaded), dict(overloaded)]}),
            'timeout': FakeHarnesses(self.tmp, reviews={'claude-code': [{'rc': None, 'error': 'timeout after 60s'}]}),
            'incomplete-result': FakeHarnesses(self.tmp, reviews={'claude-code': [{'stdout': 'no result block'}]}),
            'substituted-model': FakeHarnesses(self.tmp, reviews={'claude-code': [
                {'stdout': claude_result(GOOD, model='claude-sonnet-5-5')}]}),
        }
        for name, fake in scenarios.items():
            with self.subTest(name):
                assert_blocked(fake, name)
        self.assertEqual(scenarios['transient-recurs'].sleeps, [7], 'exactly one retry')
        self.assertEqual(len(scenarios['timeout'].review_calls()), 1, 'a timeout is not retried')
        # No auth method is ever accepted as a substitute for the subscription.
        api_key = FakeHarnesses(self.tmp, reviews={'claude-code': [{'stdout': claude_result(GOOD)}]})
        original = api_key.runner

        def runner(argv, cwd=None, env=None, timeout=60):
            if argv[:3] == ['claude', 'auth', 'status']:
                api_key.calls.append(list(argv))
                return ok(json.dumps({'loggedIn': True, 'authMethod': 'api_key'}))
            return original(argv, cwd=cwd, env=env, timeout=timeout)
        api_key.runner = runner
        with self.subTest('api-key-auth'):
            assert_blocked(api_key, 'api-key-auth')
        # A cached exhaustion blocks before any model call.
        cached = FakeHarnesses(self.tmp)
        router = make_router(cached)
        ctx = self.ctx('cached-exhaustion')
        router.remember(ctx['reviews_dir'], rr.PREFERRED[0], rr.EXHAUSTED, 'earlier', 'x', router.clock() + 600)
        evidence, selected, done = router.route(ctx)
        self.assertEqual((evidence.get('outcome'), selected, done), ('unavailable', None, None))
        self.assertEqual(cached.review_calls(), [])

    def test_task_effort_is_passed_exactly(self):
        for effort in ('xhigh', 'high'):
            fake = FakeHarnesses(self.tmp, reviews={'claude-code': [{'stdout': claude_result(GOOD)}]})
            evidence, selected, done = self.route(fake, effort=effort)
            argv = fake.review_calls()[0]
            self.assertEqual(argv[argv.index('--effort') + 1], effort)
            self.assertEqual(selected['effort'], effort)
        fake = FakeHarnesses(self.tmp, reviews={'claude-code': [{'stdout': claude_result(GOOD)}]})
        _, selected, _ = self.route(fake, name='default-effort')
        self.assertEqual(selected['effort'], 'medium', 'reviews default to medium')
        for bad in ('low', 'max', 'session'):
            fake = FakeHarnesses(self.tmp)
            with self.assertRaises(RuntimeError):
                self.route(fake, name='bad-effort', effort=bad)
            self.assertEqual(fake.calls, [], 'an invalid effort is refused before any CLI call')

    def test_same_single_route_from_every_harness(self):
        orders = []
        for index, environ in enumerate(({'CLAUDECODE': '1'}, {'OPENCODE': '1'}, {})):
            fake = FakeHarnesses(self.tmp, reviews={'claude-code': [{'stdout': claude_result(GOOD)}]})
            evidence, selected, done = self.route(fake, environ=environ, name='harness-%d' % index)
            orders.append(([c['priority'] for c in evidence['candidates']], selected['model'],
                           [c[0] for c in fake.review_calls()]))
        self.assertEqual(len({json.dumps(o) for o in orders}), 1, orders)
        self.assertEqual(orders[0], ([1], 'claude-opus-5-5', ['claude']))

    def test_unknown_usage_attempts_preferred_model_without_preliminary_calls(self):
        fake = FakeHarnesses(self.tmp, reviews={'claude-code': [{'stdout': claude_result(GOOD, status=None)}]})
        evidence, selected, _ = self.route(fake)
        self.assertEqual(selected['priority'], 1)
        self.assertEqual(evidence['candidates'][0]['usage'], 'unknown', 'unknown is reported, not assumed')
        self.assertEqual(len(fake.review_calls()), 1, 'no preliminary model call, only the review itself')

    def test_mid_review_exhaustion_discards_partial_and_is_cached(self):
        partial = claude_result(PARTIAL_FINDING + '\nClaude AI usage limit reached', error=True, status='rejected',
                                api_status=429)
        fake = FakeHarnesses(self.tmp, reviews={'claude-code': [{'stdout': partial, 'rc': 1}]})
        router = make_router(fake)
        ctx = self.ctx()
        evidence, selected, done = router.route(ctx)
        self.assertEqual((evidence['outcome'], selected, done), ('unavailable', None, None))
        first = evidence['candidates'][0]
        self.assertEqual(first['status'], rr.EXHAUSTED)
        self.assertEqual(first['attempts'][0]['category'], 'exhausted')
        self.assertTrue(os.path.isfile(os.path.join(first['attempts'][0]['attempt_dir'], 'DISCARDED')))
        # The exhaustion is remembered: the next review of the run makes no call.
        calls = len(fake.calls)
        router.route(ctx)
        self.assertEqual(len(fake.calls), calls, 'cached exhaustion is not re-tried')

    def test_7_transient_errors_retry_once_then_block(self):
        overloaded = {'stdout': claude_result('API Error: 529 overloaded', error=True, api_status=529), 'rc': 1}
        fake = FakeHarnesses(self.tmp, reviews={'claude-code': [overloaded, dict(overloaded)]})
        evidence, selected, done = self.route(fake)
        self.assertEqual((evidence['outcome'], selected, done), ('unavailable', None, None))
        self.assertEqual([a['category'] for a in evidence['candidates'][0]['attempts']], ['transient', 'transient'])
        self.assertEqual(fake.sleeps, [7], 'one bounded retry with backoff')
        recovered = FakeHarnesses(self.tmp, reviews={'claude-code': [dict(overloaded), {'stdout': claude_result(GOOD)}]})
        _, selected2, _ = self.route(recovered, name='recovered')
        self.assertEqual(selected2['priority'], 1, 'a transient error that clears keeps the route')
        timed_out = FakeHarnesses(self.tmp, reviews={'claude-code': [{'rc': None, 'error': 'timeout after 60s'}]})
        evidence3, selected3, _ = self.route(timed_out, name='timed-out')
        self.assertEqual((evidence3['outcome'], selected3), ('unavailable', None))
        self.assertEqual(len(evidence3['candidates'][0]['attempts']), 1, 'a timeout is not retried')

    def test_api_key_billing_is_never_used(self):
        fake = FakeHarnesses(self.tmp, reviews={'claude-code': [{'stdout': claude_result(GOOD)}]})
        original = fake.runner

        def runner(argv, cwd=None, env=None, timeout=60):
            if argv[:3] == ['claude', 'auth', 'status']:
                fake.calls.append(list(argv))
                return ok(json.dumps({'loggedIn': True, 'authMethod': 'api_key'}))
            return original(argv, cwd=cwd, env=env, timeout=timeout)
        fake.runner = runner
        router = make_router(fake, environ={'ANTHROPIC_API_KEY': 'x'})
        evidence, selected, done = router.route(self.ctx())
        self.assertEqual((evidence['outcome'], selected, done), ('unavailable', None, None))
        self.assertEqual(fake.review_calls(), [], 'API-key billing never runs a review')
        self.assertFalse([c for c in fake.calls if c and c[0] == 'opencode'])
        self.assertNotIn('ANTHROPIC_API_KEY', router.child_env('claude-code'))

    def test_nested_orchestration_refused(self):
        fake = FakeHarnesses(self.tmp)
        with self.assertRaises(RuntimeError):
            self.route(fake, environ={rr.GUARD_ENV: '1'})
        self.assertEqual(fake.calls, [])

    def test_reviewer_env_never_exposes_anthropic_credentials(self):
        router = make_router(FakeHarnesses(self.tmp), environ={
            'ANTHROPIC_API_KEY': 'a', 'ANTHROPIC_AUTH_TOKEN': 'b', 'OPENAI_API_KEY': 'keep'})
        env = router.child_env('claude-code')
        self.assertNotIn('ANTHROPIC_API_KEY', env)
        self.assertNotIn('ANTHROPIC_AUTH_TOKEN', env)
        self.assertEqual(env['OPENAI_API_KEY'], 'keep', 'other providers are untouched')

    def test_result_parsing_is_strict(self):
        self.assertIsNone(rr.parse_result('no block')[0])
        placeholder = '%s\n{"verdict": "<pass|fail>", "findings": []}\n%s' % (rr.RESULT_BEGIN, rr.RESULT_END)
        self.assertIsNone(rr.parse_result(placeholder)[0], 'the prompt template never counts as a result')
        lying = '%s\n{"verdict": "pass", "findings": [{"severity": "Important", "summary": "bug"}]}\n%s' % (
            rr.RESULT_BEGIN, rr.RESULT_END)
        self.assertEqual(rr.parse_result(lying)[0]['verdict'], 'fail')


class IntegrationCase(TempCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(setattr, depup, 'ROUTER_FACTORY', None)

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

    def use(self, fake):
        depup.ROUTER_FACTORY = lambda **kw: make_router(fake, max_retries=kw.get('max_retries', 1))


class ReviewIntegrationTests(IntegrationCase):

    def test_review_run_binds_receipt_and_reuses_completed_review(self):
        start, wt = self.upgrade_run()
        fake = FakeHarnesses(self.tmp, reviews={'claude-code': [{'stdout': claude_result(GOOD)}]})
        self.use(fake)
        code, entry = self.cli('review', 'run', start['run_ref'], '--kind', 'critical', '--required')
        self.assertEqual(code, 0, entry)
        self.assertEqual((entry['status'], entry['verdict']), ('completed', 'pass'))
        self.assertEqual(entry['selected']['model'], 'claude-opus-5-5')
        review_dir = os.path.dirname(entry['entry'])
        with open(os.path.join(review_dir, 'lockfile.diff'), encoding='utf-8') as handle:
            self.assertIn('2.0.0', handle.read(), 'the lockfile diff is reviewed in full')
        with open(os.path.join(review_dir, 'code.diff'), encoding='utf-8') as handle:
            code_diff = handle.read()
        self.assertIn('package.json', code_diff)
        self.assertNotIn('package-lock.json', code_diff)
        candidate = depup.git_state(wt)['head']
        self.assertTrue(depup.bound_evidence(start['run_dir'], entry['evidence'], entry['candidate_head'] and
                                             start['run_ref'].split('/')[1], candidate, 'critical-review',
                                             'full-diff', 'pass'))
        with open(os.path.join(review_dir, 'routing.json'), encoding='utf-8') as handle:
            routing = handle.read()
        self.assertNotIn('someone@example.invalid', routing, 'no account data in evidence')
        _, again = self.cli('review', 'run', start['run_ref'], '--kind', 'critical')
        self.assertTrue(again['reused'])
        self.assertEqual(len(fake.review_calls()), 1, 'no duplicate review of the same candidate')
        write(os.path.join(review_dir, 'review.lock'), {'pid': os.getpid()})
        code, busy = self.cli('review', 'run', start['run_ref'], '--kind', 'critical', '--rerun')
        self.assertEqual(code, 1)
        self.assertIn('already running', busy['error'])
        dead = sh(['python3', '-c', 'import os; print(os.getpid())'], self.tmp).stdout.strip()
        write(os.path.join(review_dir, 'review.lock'), {'pid': int(dead)})
        fake.reviews['claude-code'] = [{'stdout': claude_result(GOOD)}]
        code, rerun = self.cli('review', 'run', start['run_ref'], '--kind', 'critical', '--rerun')
        self.assertEqual((code, rerun['status']), (0, 'completed'), 'a dead holder\'s lock is reclaimed')

    def test_9_required_review_unavailable_prevents_pass(self):
        start, wt = self.upgrade_run()
        ref, run_dir = start['run_ref'], start['run_dir']
        self.use(FakeHarnesses(self.tmp, missing={'claude'}))
        _, sec = self.cli('review', 'run', ref, '--kind', 'security', '--subject', 'db', '--required')
        self.assertEqual(sec['status'], 'unavailable')
        self.assertTrue(sec['required'])
        self.assertIn('Claude Opus 5.5 could not complete', sec['reason'])
        self.assertIn('no fallback', sec['reason'])
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
        _, rep = self.cli('report', ref, '--input', path)
        self.assertEqual(rep['status'], 'PARTIAL', 'leaving the unavailable required review out cannot hide it')
        self.assertTrue(any('required review' in c for c in rep['corrections']), rep['corrections'])
        payload['reviews'] = [sec]
        write(path, payload)
        _, rep = self.cli('report', ref, '--input', path)
        self.assertEqual(rep['status'], 'PARTIAL')
        self.assertTrue(any('required review' in c for c in rep['corrections']), rep['corrections'])
        with open(rep['summary'], encoding='utf-8') as handle:
            self.assertIn('## Reviews', handle.read())
        # A forged "completed" entry without a candidate-bound receipt cannot unlock PASS either.
        forged = dict(sec, status='completed', verdict='pass', evidence='logs/tests.json')
        payload['reviews'] = [forged]
        write(path, payload)
        _, rep = self.cli('report', ref, '--input', path)
        self.assertEqual(rep['status'], 'PARTIAL')

    def test_review_and_planning_record_and_session_flags_are_gone(self):
        start, _ = self.upgrade_run()
        argv_list = [
            ['review', 'record', start['run_ref'], '--review-id', 'x'],
            ['planning', 'record', start['run_ref'], '--plan-id', 'x'],
            ['review', 'run', start['run_ref'], '--kind', 'critical', '--session-harness', 'x'],
        ]
        for argv in argv_list:
            with self.subTest(argv):
                with self.assertRaises(SystemExit) as raised:
                    depup.main(argv)
                self.assertEqual(raised.exception.code, 2)

    def test_probe_makes_no_model_calls(self):
        fake = FakeHarnesses(self.tmp)
        self.use(fake)
        code, out = self.cli('review', 'probe')
        self.assertEqual(code, 0)
        self.assertEqual(out['model_calls'], 0)
        self.assertEqual(fake.review_calls(), [])
        self.assertEqual([c['priority'] for c in out['candidates']], [1])


class DossierTests(IntegrationCase):
    def test_routed_independent_and_security_reviews_satisfy_a_high_risk_dossier(self):
        start, wt = self.upgrade_run()
        ref, run_dir = start['run_ref'], start['run_dir']
        fake = FakeHarnesses(self.tmp, reviews={'claude-code': [{'stdout': claude_result(GOOD)}] * 3})
        self.use(fake)
        _, ind = self.cli('review', 'run', ref, '--kind', 'independent', '--subject', 'db', '--required')
        _, sec = self.cli('review', 'run', ref, '--kind', 'security', '--subject', 'db', '--required')
        _, crit = self.cli('review', 'run', ref, '--kind', 'critical', '--required')
        self.assertEqual((ind['selected']['effort'], sec['selected']['effort'], crit['selected']['effort']),
                         ('high', 'high', 'medium'))
        self.assertNotEqual(ind['reviewer'], sec['reviewer'], 'same model, distinct fresh sessions')
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
        payload = {'status': 'PASS', 'reviews': [ind, sec, crit],
                   'verification': [{'check': 'tests', 'command': 'npm test', 'result': 'pass',
                                     'log': 'logs/tests.log', 'evidence': 'logs/tests.json'}],
                   'upgrades': [{'name': 'db', 'impact_tier': 'high', 'status': 'done'}],
                   'risks': [{'name': 'db', 'summary': 'db', 'severity': 'high', 'disposition': 'proceed',
                              'analysis': 'mapped', 'recovery': 'revert on owned branch',
                              'sources': [{'name': 'guide', 'url': 'https://example.test', 'retrieved': '2026-11-03'}],
                              'alternatives': ['stay'], 'controls': ['staged'],
                              'reviews': [{'type': 'independent', 'status': 'pass', 'evidence': ind['evidence']},
                                          {'type': 'security', 'status': 'pass', 'evidence': sec['evidence']}]}]}
        path = os.path.join(self.tmp, 'in.json')
        write(path, payload)
        _, rep = self.cli('report', ref, '--input', path)
        self.assertEqual(rep['status'], 'PASS', rep['corrections'])
