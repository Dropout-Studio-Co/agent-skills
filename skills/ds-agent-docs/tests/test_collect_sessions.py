"""collect_sessions.py: OpenCode is read read-only from SQLite; Claude Code still works; no Gemini."""
import hashlib
import importlib.util
import json
import os
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import transcript_fixtures

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(HERE, 'scripts', 'collect_sessions.py')


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix='collect-test-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = os.path.join(self.tmp, 'home')
        self.data = os.path.join(self.tmp, 'data')
        self.claude = os.path.join(self.tmp, 'claude')
        self.root = os.path.join(self.tmp, 'repo')
        os.makedirs(self.root, exist_ok=True)
        self.env = dict(os.environ)
        self.env.update({'HOME': self.home, 'XDG_DATA_HOME': self.data, 'CLAUDE_CONFIG_DIR': self.claude})

    def run_collector(self, *extra, cwd=None):
        return subprocess.run([sys.executable, SCRIPT, '--repo', self.root, '--days', '60'] + list(extra),
                              capture_output=True, text=True, env=self.env, cwd=cwd)

    def db_path(self):
        return Path(self.data) / 'opencode' / 'opencode.db'

    def make_db(self, sessions):
        path = self.db_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path))
        conn.execute('CREATE TABLE project (id text PRIMARY KEY)')
        conn.execute("INSERT INTO project VALUES ('project-1')")
        conn.execute("CREATE TABLE session_v2 (id text PRIMARY KEY, project_id text, slug text, directory text, "
                     "parent_id text, time_created integer, time_updated integer)")
        conn.execute("CREATE TABLE session_message (id text PRIMARY KEY, session_id text, type text, seq integer, "
                     "time_created integer, time_updated integer, data text)")
        for session_id, directory, age_days, messages in sessions:
            now = int((time.time() - age_days * 86400) * 1000)
            conn.execute('INSERT INTO session_v2 VALUES (?, ?, ?, ?, ?, ?, ?)',
                         (session_id, 'project-1', session_id, directory, None, now, now))
            for seq, (kind, data) in enumerate(messages, 1):
                conn.execute('INSERT INTO session_message VALUES (?, ?, ?, ?, ?, ?, ?)',
                             ('%s-%d' % (session_id, seq), session_id, kind, seq, now, now,
                              json.dumps(data)))
        conn.commit()
        conn.close()
        return path

    def claude_fixture(self, text='hello from claude code'):
        enc = re.sub(r'[^A-Za-z0-9]', '-', str(self.root))
        directory = os.path.join(self.claude, 'projects', enc)
        os.makedirs(directory, exist_ok=True)
        with open(os.path.join(directory, 'fixture.jsonl'), 'w', encoding='utf-8') as handle:
            handle.write(json.dumps({'cwd': self.root, 'type': 'user',
                                     'message': {'role': 'user', 'content': text}}) + '\n')

    def test_opencode_session_inside_the_root_is_printed_and_redacted(self):
        self.make_db([
            ('inside-session', self.root, 0, [
                ('user', {'time': {'created': int(time.time() * 1000)},
                          'text': "don't do that again; token=SECRET-TOKEN-VALUE"}),
                ('assistant', {'time': {'created': int(time.time() * 1000)},
                               'content': [{'type': 'tool', 'name': 'bash',
                                            'state': {'status': 'error',
                                                      'input': {'command': 'ls'},
                                                      'error': {'type': 'permission.rejected',
                                                                'message': 'Permission denied: shell '
                                                                           'token=SECRET-TOKEN-VALUE'}}}]})]),
            ('outside-session', os.path.join(self.tmp, 'elsewhere'), 0, [
                ('user', {'text': 'outside message that must not appear'})]),
            ('old-session', self.root, 400, [
                ('user', {'text': 'old message that must not appear'})]),
        ])
        proc = self.run_collector()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('· opencode · inside-session', proc.stdout)
        self.assertIn('⚑', proc.stdout)
        self.assertIn('✗ error', proc.stdout)
        self.assertIn('permission.rejected: Permission denied: shell', proc.stdout)
        self.assertIn('[REDACTED]', proc.stdout)
        self.assertNotIn('outside message', proc.stdout)
        self.assertNotIn('old message', proc.stdout)

    def test_database_bytes_and_directory_are_unchanged(self):
        path = self.make_db([('inside-session', self.root, 0, [
            ('user', {'text': "don't change the database"})])])
        before_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        before_files = sorted(os.listdir(path.parent))
        proc = self.run_collector()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before_hash)
        self.assertEqual(sorted(os.listdir(path.parent)), before_files, 'no journal or shm files appear')

    def test_sessions_without_a_directory_are_skipped_even_from_inside_the_root(self):
        self.make_db([
            ('empty-dir-session', '', 0, [
                ('user', {'text': 'empty directory message must not appear'})]),
            ('null-dir-session', None, 0, [
                ('user', {'text': 'null directory message must not appear'})]),
            ('inside-session', self.root, 0, [
                ('user', {'text': 'inside message appears'})]),
        ])
        proc = self.run_collector(cwd=self.root)  # cwd equals the repo root: '' must still never match
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('inside message appears', proc.stdout)
        self.assertNotIn('empty directory message', proc.stdout)
        self.assertNotIn('null directory message', proc.stdout)

    def test_database_in_wal_mode_is_read_without_new_files(self):
        path = self.make_db([('wal-session', self.root, 0, [
            ('user', {'text': "don't change the wal database"})])])
        conn = sqlite3.connect(str(path))
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        conn.close()
        for suffix in ('-wal', '-shm'):
            leftover = Path(str(path) + suffix)
            if leftover.exists():
                leftover.unlink()
            self.assertFalse(leftover.exists(), 'the fixture starts without %s' % suffix)
        before_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        before_files = sorted(os.listdir(path.parent))
        proc = self.run_collector()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before_hash)
        self.assertEqual(sorted(os.listdir(path.parent)), before_files, 'no journal or shm files appear')

    def test_live_wal_database_with_a_writer_is_read_without_new_files(self):
        path = self.make_db([])
        writer = sqlite3.connect(str(path))
        self.addCleanup(writer.close)
        writer.execute('PRAGMA journal_mode=WAL').fetchall()
        now = int(time.time() * 1000)
        writer.execute('INSERT INTO session_v2 VALUES (?, ?, ?, ?, ?, ?, ?)',
                       ('live-session', 'project-1', 'live-session', self.root, None, now, now))
        writer.execute('INSERT INTO session_message VALUES (?, ?, ?, ?, ?, ?, ?)',
                       ('live-session-1', 'live-session', 'user', 1, now, now,
                        json.dumps({'text': "don't lose the live wal session"})))
        writer.commit()  # the writer stays open, holding -wal and -shm
        wal, shm = Path(str(path) + '-wal'), Path(str(path) + '-shm')
        self.assertTrue(wal.exists(), 'the fixture has a pending write-ahead log')
        self.assertTrue(shm.exists(), 'the writer holds the shared-memory file open')
        before_files = sorted(os.listdir(path.parent))
        proc = self.run_collector()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('· opencode · live-session', proc.stdout)
        self.assertIn('live wal session', proc.stdout)
        self.assertEqual(sorted(os.listdir(path.parent)), before_files, 'no journal or shm files appear')

    def test_wal_without_shared_memory_is_skipped_with_a_note(self):
        self.claude_fixture()
        path = self.make_db([('wal-only', self.root, 0, [
            ('user', {'text': 'wal only message must not appear'})])])
        Path(str(path) + '-wal').write_bytes(b'')
        self.assertFalse(Path(str(path) + '-shm').exists())
        before_files = sorted(os.listdir(path.parent))
        proc = self.run_collector()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('WAL', proc.stderr)
        self.assertIn('claude-code', proc.stdout)
        self.assertIn('hello from claude code', proc.stdout)
        self.assertNotIn('wal only message', proc.stdout)
        self.assertEqual(sorted(os.listdir(path.parent)), before_files)

    def test_extra_dir_files_are_filtered_by_working_directory(self):
        extra = Path(self.tmp) / 'extra'
        extra.mkdir(parents=True, exist_ok=True)
        elsewhere = os.path.join(self.tmp, 'another-repo')
        with open(extra / 'inside.jsonl', 'w', encoding='utf-8') as handle:
            handle.write(json.dumps({'cwd': self.root, 'type': 'user',
                                     'message': {'role': 'user', 'content': 'inside extra directory message'}}) + '\n')
        with open(extra / 'outside.jsonl', 'w', encoding='utf-8') as handle:
            handle.write(json.dumps({'cwd': elsewhere, 'type': 'user',
                                     'message': {'role': 'user', 'content': 'outside extra directory message'}}) + '\n')
        proc = self.run_collector('--extra-dir', str(extra))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('inside extra directory message', proc.stdout)
        self.assertNotIn('outside extra directory message', proc.stdout)

    def test_corrupt_or_missing_database_still_prints_claude_sessions(self):
        self.claude_fixture()
        path = self.db_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'this is not a sqlite database')
        proc = self.run_collector()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('OpenCode', proc.stderr)
        self.assertIn('claude-code', proc.stdout)
        self.assertIn('hello from claude code', proc.stdout)
        path.unlink()
        proc = self.run_collector()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('no OpenCode database', proc.stderr)
        self.assertIn('claude-code', proc.stdout)

    def test_gemini_store_is_ignored_and_the_source_has_no_gemini(self):
        root_hash = hashlib.sha256(str(Path(self.root).resolve()).encode()).hexdigest()
        gemini = Path(self.home) / '.gemini' / 'tmp' / root_hash
        gemini.mkdir(parents=True, exist_ok=True)
        (gemini / 'chat.json').write_text(json.dumps({'messages': [
            {'role': 'user', 'content': 'gemini-only message that must not appear'}]}), encoding='utf-8')
        proc = self.run_collector()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn('gemini-only message', proc.stdout)
        with open(SCRIPT, encoding='utf-8') as handle:
            source = handle.read()
        self.assertFalse(re.search('gemini', source, re.I))


def load_collector():
    spec = importlib.util.spec_from_file_location('collect_sessions_under_test', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CollectorCase(unittest.TestCase):
    """Shared fixture: an isolated HOME, data dir, Claude config dir and repo root."""

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix='collect-case-'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = os.path.join(self.tmp, 'home')
        self.data = os.path.join(self.tmp, 'data')
        self.claude = os.path.join(self.tmp, 'claude')
        self.root = os.path.join(self.tmp, 'repo')
        os.makedirs(self.root, exist_ok=True)
        self.env = dict(os.environ)
        self.env.update({'HOME': self.home, 'XDG_DATA_HOME': self.data,
                         'CLAUDE_CONFIG_DIR': self.claude})

    def run_collector(self, *extra, cwd=None, umask=None):
        kwargs = {}
        if umask is not None:
            kwargs['preexec_fn'] = lambda: os.umask(umask)
        return subprocess.run([sys.executable, SCRIPT, '--repo', self.root, '--days', '60']
                              + list(extra), capture_output=True, text=True, env=self.env,
                              cwd=cwd, **kwargs)

    def project_dir(self, cwd, name=None):
        encoded = name or transcript_fixtures.encode(cwd)
        directory = os.path.join(self.claude, 'projects', encoded)
        os.makedirs(directory, exist_ok=True)
        return directory

    def write_session(self, cwd, name, records, mtime=None, project_dir=None, stamp_cwd=True):
        directory = self.project_dir(cwd, project_dir)
        path = os.path.join(directory, name)
        if stamp_cwd:
            records = [dict({'cwd': cwd}, **item) for item in records]
        transcript_fixtures.write_jsonl(path, records)
        if mtime is not None:
            os.utime(path, (mtime, mtime))
        return path

    def write_raw_session(self, cwd, name, lines, mtime=None, project_dir=None):
        directory = self.project_dir(cwd, project_dir)
        path = os.path.join(directory, name)
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write('\n'.join(lines) + '\n')
        if mtime is not None:
            os.utime(path, (mtime, mtime))
        return path

    def db_path(self):
        return Path(self.data) / 'opencode' / 'opencode.db'

    def make_db(self, sessions, parent_column=True, missing=()):
        path = self.db_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path))
        conn.execute('CREATE TABLE project (id text PRIMARY KEY)')
        conn.execute("INSERT INTO project VALUES ('project-1')")
        if 'session_v2' not in missing:
            columns = ('id text PRIMARY KEY, project_id text, slug text, directory text, '
                       'fork_session_id text, ')
            if parent_column:
                columns += 'parent_id text, '
            columns += 'time_created integer, time_updated integer'
            conn.execute('CREATE TABLE session_v2 (%s)' % columns)
        if 'session_message' not in missing:
            conn.execute('CREATE TABLE session_message (id text PRIMARY KEY, session_id text, '
                         'type text, seq integer, time_created integer, time_updated integer, '
                         'data text)')
        for session_id, directory, age_days, messages in sessions:
            now = int((time.time() - age_days * 86400) * 1000)
            values = [session_id, 'project-1', session_id, directory, None]
            if parent_column:
                values.append(None)
            values.extend([now, now])
            conn.execute('INSERT INTO session_v2 VALUES (%s)'
                         % ','.join('?' * len(values)), tuple(values))
            if 'session_message' not in missing:
                for seq, (kind, data) in enumerate(messages, 1):
                    conn.execute('INSERT INTO session_message VALUES (?, ?, ?, ?, ?, ?, ?)',
                                 ('%s-%d' % (session_id, seq), session_id, kind, seq, now, now,
                                  json.dumps(data)))
        conn.commit()
        conn.close()
        return path


class GitRepoCase(CollectorCase):
    """A real git repository fixture; every git call runs in a scratch directory."""

    def git(self, cwd, *args):
        env = {k: v for k, v in os.environ.items()
               if k not in ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE', 'GIT_COMMON_DIR')}
        env.update({'GIT_AUTHOR_NAME': 'fixture', 'GIT_AUTHOR_EMAIL': 'fixture@example.test',
                    'GIT_COMMITTER_NAME': 'fixture',
                    'GIT_COMMITTER_EMAIL': 'fixture@example.test',
                    'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_SYSTEM': os.devnull})
        return subprocess.run(['git'] + list(args), cwd=cwd, capture_output=True, text=True,
                              env=env, check=True)

    def init_repo(self, path, branch='main'):
        os.makedirs(path, exist_ok=True)
        self.git(path, 'init', '-q', '-b', branch)
        with open(os.path.join(path, 'README.md'), 'w', encoding='utf-8') as handle:
            handle.write('fixture\n')
        self.git(path, 'add', '.')
        self.git(path, 'commit', '-qm', 'init')


class CollectorIdentityTests(GitRepoCase):
    """A1: sessions belong to the repo only through live worktrees sharing its common dir."""

    def setUp(self):
        super().setUp()
        self.init_repo(self.root)
        self.worktree = os.path.join(self.tmp, 'linked')
        self.git(self.root, 'worktree', 'add', '-q', '-b', 'fixture-branch', self.worktree)
        self.sub_main = os.path.join(self.root, 'docs')
        os.makedirs(self.sub_main, exist_ok=True)
        self.sub_worktree = os.path.join(self.worktree, 'src')
        os.makedirs(self.sub_worktree, exist_ok=True)
        self.nested = os.path.join(self.root, 'nested')
        self.git(self.tmp, 'clone', '-q', self.root, self.nested)
        self.deleted = os.path.join(self.tmp, 'deleted-worktree')
        self.git(self.root, 'worktree', 'add', '-q', '-b', 'gone', self.deleted)
        self.git(self.root, 'worktree', 'remove', '--force', self.deleted)
        self.sibling = os.path.join(self.tmp, 'repo-2')
        os.makedirs(self.sibling, exist_ok=True)

    def test_live_worktrees_and_subdirectories_are_included(self):
        self.write_session(self.root, 'main.jsonl',
                           [dict(transcript_fixtures.record('message from the main checkout'),
                                 cwd=self.root)])
        self.write_session(self.sub_main, 'main-sub.jsonl',
                           [dict(transcript_fixtures.record('message from a main subdirectory'),
                                 cwd=self.sub_main)])
        self.write_session(self.worktree, 'worktree.jsonl',
                           [dict(transcript_fixtures.record('message from a linked worktree'),
                                 cwd=self.worktree)])
        self.write_session(self.sub_worktree, 'worktree-sub.jsonl',
                           [dict(transcript_fixtures.record('message from a worktree subdirectory'),
                                 cwd=self.sub_worktree)])
        proc = self.run_collector()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        for text in ('message from the main checkout', 'message from a main subdirectory',
                     'message from a linked worktree', 'message from a worktree subdirectory'):
            self.assertIn(text, proc.stdout)

    def test_prefix_sibling_nested_clone_deleted_worktree_and_missing_cwd_are_excluded(self):
        self.write_session(self.sibling, 'sibling.jsonl',
                           [dict(transcript_fixtures.record('prefix sibling message'),
                                 cwd=self.sibling)],
                           project_dir=transcript_fixtures.encode(self.root) + '-2')
        self.write_session(self.nested, 'nested.jsonl',
                           [dict(transcript_fixtures.record('nested clone message'),
                                 cwd=self.nested)],
                           project_dir=transcript_fixtures.encode(self.nested))
        self.write_session(self.deleted, 'deleted.jsonl',
                           [dict(transcript_fixtures.record('deleted worktree message'),
                                 cwd=self.deleted)],
                           project_dir=transcript_fixtures.encode(self.root) + '-deleted')
        self.write_session(self.root, 'no-cwd.jsonl',
                           [transcript_fixtures.record('no cwd message')], stamp_cwd=False)
        self.write_session(self.root, 'main.jsonl',
                           [dict(transcript_fixtures.record('main checkout message'),
                                 cwd=self.root)])
        proc = self.run_collector()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('main checkout message', proc.stdout)
        for text in ('prefix sibling message', 'nested clone message',
                     'deleted worktree message', 'no cwd message'):
            self.assertNotIn(text, proc.stdout)

    def test_claude_sessions_has_no_matched_initialiser(self):
        with open(SCRIPT, encoding='utf-8') as handle:
            source = handle.read()
        self.assertNotIn('matched = True', source)


class CollectorParallelScanTests(CollectorCase):
    """B1: bounded parallel scanning keeps a deterministic order and one lookup per cwd."""

    def test_member_lookup_runs_once_per_cwd_across_threads(self):
        module = load_collector()
        sub = os.path.join(self.root, 'sub')
        os.makedirs(sub, exist_ok=True)
        calls = []
        original = module._common_dir

        def counting(path):
            calls.append(str(path))
            time.sleep(0.01)
            return '/fixture/common'

        module._common_dir = counting
        self.addCleanup(setattr, module, '_common_dir', original)
        repo = module.Repo(self.root)
        calls.clear()
        results = []
        barrier = threading.Barrier(8)

        def worker(cwd):
            barrier.wait()
            results.append(repo.member(cwd))

        threads = [threading.Thread(target=worker, args=(cwd,))
                   for cwd in [self.root, sub] * 4]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)
        self.assertEqual(len(results), 8)
        self.assertTrue(all(results))
        self.assertEqual(len(calls), 2, calls)
        self.assertEqual(sorted(calls), sorted([self.root, sub]))

    def test_equal_mtime_sessions_keep_a_deterministic_order_across_runs(self):
        now = time.time()
        names = ['delta', 'alpha', 'charlie', 'bravo', 'echo']
        for name in names:
            self.write_session(self.root, name + '.jsonl',
                               [transcript_fixtures.record('body of ' + name)], mtime=now)
        orders = []
        for index in range(3):
            evidence = os.path.join(self.tmp, 'evidence-%d.json' % index)
            proc = self.run_collector('--evidence-out', evidence)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            with open(evidence, encoding='utf-8') as handle:
                payload = json.load(handle)
            orders.append([session['id'] for session in payload['sessions']])
        expected = ['claude-code:%s.jsonl' % name for name in sorted(names)]
        self.assertEqual(orders[0], expected)
        self.assertEqual(orders[1], orders[0])
        self.assertEqual(orders[2], orders[0])


class CollectorNonGitTests(CollectorCase):
    def test_non_git_root_keeps_path_inside_matching(self):
        inside = os.path.join(self.root, 'sub')
        os.makedirs(inside, exist_ok=True)
        elsewhere = os.path.join(self.tmp, 'repo-other')
        os.makedirs(elsewhere, exist_ok=True)
        self.write_session(inside, 'inside.jsonl',
                           [dict(transcript_fixtures.record('inside non git message'),
                                 cwd=inside)])
        self.write_session(elsewhere, 'outside.jsonl',
                           [dict(transcript_fixtures.record('outside non git message'),
                                 cwd=elsewhere)],
                           project_dir=transcript_fixtures.encode(self.root) + '-other')
        proc = self.run_collector()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('inside non git message', proc.stdout)
        self.assertNotIn('outside non git message', proc.stdout)


class CollectorHumanEvidenceTests(CollectorCase):
    """A2: machine-authored records never count as human text."""

    def check_one_excluded(self, name, records):
        self.write_session(self.root, name, records)
        proc = self.run_collector()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn('machine text', proc.stdout, name)
        self.assertIn('typed message survives', proc.stdout, name)

    def test_record_level_exclusions(self):
        cases = [
            ('isMeta', {'isMeta': True}),
            ('isSidechain', {'isSidechain': True}),
            ('origin', {'origin': {'kind': 'hook'}}),
            ('entrypoint', {'entrypoint': 'sdk-cli'}),
            ('promptSource', {'promptSource': 'suggestion'}),
            ('turnOrigin', {'turnOrigin': {'kind': 'agent'}}),
            ('sessionKind', {'sessionKind': 'bg'}),
            ('isCompactSummary', {'isCompactSummary': True}),
        ]
        for name, fields in cases:
            with self.subTest(name):
                self.check_one_excluded(
                    name + '.jsonl',
                    [transcript_fixtures.record('machine text via ' + name, **fields),
                     transcript_fixtures.record('typed message survives')])

    def test_content_level_exclusions(self):
        beside_tool_result = {'type': 'user', 'message': {
            'role': 'user', 'content': [
                {'type': 'text', 'text': 'machine text beside a tool result'},
                {'type': 'tool_result', 'content': 'ok'}]}}
        self.check_one_excluded('tool-result.jsonl', [
            beside_tool_result, transcript_fixtures.record('typed message survives')])
        for name, text in [
                ('hook', 'Stop hook feedback: machine text from a hook'),
                ('continuation', 'This session is being continued from a previous machine text'),
                ('skill', 'Base directory for this skill: machine text'),
                ('handoff', '# Handoff: machine text from a handoff')]:
            with self.subTest(name):
                self.check_one_excluded(name + '.jsonl', [
                    transcript_fixtures.record(text),
                    transcript_fixtures.record('typed message survives')])


class CollectorExclusionTests(CollectorCase):
    """A2b: whole-session markers, OpenCode children and pasted spans."""

    def test_self_session_marker_excludes_the_whole_session(self):
        self.write_session(self.root, 'self.jsonl', [
            transcript_fixtures.record('<!-- backpass:self-session --> typed in self session'),
            transcript_fixtures.record('typed message survives')])
        proc = self.run_collector()
        self.assertNotIn('typed in self session', proc.stdout)
        self.assertNotIn('typed message survives', proc.stdout)

    def test_both_self_session_markers_exclude_the_whole_session(self):
        self.write_session(self.root, 'active.jsonl', [
            transcript_fixtures.record('<!-- ds-agent-docs:self-session --> active marker'),
            transcript_fixtures.record('active tail survives')])
        self.write_session(self.root, 'legacy.jsonl', [
            transcript_fixtures.record('<!-- backpass:self-session --> legacy marker'),
            transcript_fixtures.record('legacy tail survives')])
        self.write_session(self.root, 'clean.jsonl', [
            transcript_fixtures.record('clean message stays')])
        proc = self.run_collector()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        for text in ('active marker', 'active tail survives', 'legacy marker',
                     'legacy tail survives'):
            self.assertNotIn(text, proc.stdout)
        self.assertIn('clean message stays', proc.stdout)

    def test_implementer_opening_excludes_the_whole_session(self):
        self.write_session(self.root, 'implementer.jsonl', [
            transcript_fixtures.record(
                'You are the implementer for one step of a plan written by Claude Opus.'),
            transcript_fixtures.record('typed message survives')])
        proc = self.run_collector()
        self.assertNotIn('typed message survives', proc.stdout)

    def test_self_session_marker_on_the_last_line_still_excludes_the_session(self):
        self.write_session(self.root, 'late-marker.jsonl', [
            transcript_fixtures.record('typed message that must not appear'),
            transcript_fixtures.record('<!-- ds-agent-docs:self-session --> late marker')])
        self.write_session(self.root, 'clean.jsonl',
                           [transcript_fixtures.record('clean message stays')])
        proc = self.run_collector()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn('typed message that must not appear', proc.stdout)
        self.assertIn('clean message stays', proc.stdout)

    def test_opencode_child_session_is_excluded(self):
        path = self.make_db([
            ('parent-session', self.root, 0, [
                transcript_fixtures.opencode_user('parent session message')]),
            ('child-session', self.root, 0, [
                transcript_fixtures.opencode_user('child session message')]),
        ])
        conn = sqlite3.connect(str(path))
        conn.execute("UPDATE session_v2 SET parent_id='parent-session' WHERE id='child-session'")
        conn.commit()
        conn.close()
        proc = self.run_collector()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('parent session message', proc.stdout)
        self.assertNotIn('child session message', proc.stdout)

    def test_forked_opencode_sessions_share_the_fork_group(self):
        path = self.make_db([
            ('origin-session', self.root, 0, [
                transcript_fixtures.opencode_user('origin session message')]),
            ('branch-session', self.root, 0, [
                transcript_fixtures.opencode_user('branch session message')]),
        ])
        conn = sqlite3.connect(str(path))
        conn.execute("UPDATE session_v2 SET fork_session_id='origin-session' "
                     "WHERE id='branch-session'")
        conn.commit()
        conn.close()
        evidence = os.path.join(self.tmp, 'evidence.json')
        proc = self.run_collector('--evidence-out', evidence)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        with open(evidence, encoding='utf-8') as handle:
            payload = json.load(handle)
        groups = {session['id']: session['group'] for session in payload['sessions']}
        self.assertEqual(groups['opencode:branch-session'], 'origin-session')
        self.assertEqual(groups['opencode:origin-session'], 'origin-session')

    def test_pasted_spans_are_removed_and_the_rest_is_kept(self):
        self.write_session(self.root, 'pasted.jsonl', [
            transcript_fixtures.record(
                'keep before <pasted_content>hidden paste content</pasted_content> keep after')])
        proc = self.run_collector()
        self.assertIn('keep before', proc.stdout)
        self.assertIn('keep after', proc.stdout)
        self.assertNotIn('hidden paste content', proc.stdout)

    def test_unterminated_pasted_span_removes_to_the_end(self):
        self.write_session(self.root, 'unterminated.jsonl', [
            transcript_fixtures.record('visible head <pasted_content>secret tail')])
        proc = self.run_collector()
        self.assertIn('visible head', proc.stdout)
        self.assertNotIn('secret tail', proc.stdout)


class CollectorSamplingTests(CollectorCase):
    """A3: round-robin weekly sampling, interactive-first, skip, and count arithmetic."""

    def labels(self, proc):
        return [line.rsplit(' · ', 1)[-1] for line in proc.stdout.splitlines()
                if line.startswith('## ')]

    def test_round_robin_across_weekly_buckets(self):
        now = time.time()
        for age, name in [(0, 'week0-a'), (1, 'week0-b'), (8, 'week1-a'), (9, 'week1-b'),
                          (15, 'week2-a')]:
            self.write_session(self.root, name + '.jsonl',
                               [transcript_fixtures.record('body ' + name)],
                               mtime=now - age * 86400)
        proc = self.run_collector()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        labels = self.labels(proc)
        self.assertEqual(labels[:3], ['week0-a.jsonl', 'week1-a.jsonl', 'week2-a.jsonl'])
        self.assertEqual(labels[3:], ['week0-b.jsonl', 'week1-b.jsonl'])

    def test_interactive_sessions_come_before_headless_ones(self):
        now = time.time()
        self.write_session(self.root, 'headless.jsonl',
                           [transcript_fixtures.record('headless body'),
                            transcript_fixtures.record('boot', entrypoint='sdk-cli')],
                           mtime=now)
        self.write_session(self.root, 'interactive.jsonl',
                           [transcript_fixtures.record('interactive body')], mtime=now - 10)
        proc = self.run_collector()
        self.assertEqual(self.labels(proc)[0], 'interactive.jsonl')

    def test_block_too_large_for_the_budget_is_skipped(self):
        now = time.time()
        big = [transcript_fixtures.record('BIGSTART message number %d %s' % (i, 'x' * 400))
               for i in range(15)]
        self.write_session(self.root, 'big.jsonl', big, mtime=now)
        self.write_session(self.root, 'small.jsonl',
                           [transcript_fixtures.record('small message survives')],
                           mtime=now - 10)
        proc = self.run_collector('--max-chars', '1500')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('small message survives', proc.stdout)
        self.assertNotIn('BIGSTART', proc.stdout)

    def test_date_range_uses_only_the_shown_sessions(self):
        now = time.time()
        big = [transcript_fixtures.record('BIGSTART message %d %s' % (i, 'x' * 400))
               for i in range(15)]
        self.write_session(self.root, 'big.jsonl', big, mtime=now)
        self.write_session(self.root, 'small.jsonl',
                           [transcript_fixtures.record('small message survives')],
                           mtime=now - 9 * 86400)
        proc = self.run_collector('--max-chars', '1500')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('small message survives', proc.stdout)
        self.assertNotIn('BIGSTART', proc.stdout)
        match = re.search(r'(\d+) shown\. (\S+) to (\S+)\.', proc.stdout)
        self.assertIsNotNone(match, proc.stdout)
        shown, start, end = match.groups()
        self.assertEqual(shown, '1')
        self.assertEqual(start, time.strftime('%Y-%m-%d',
                                              time.localtime(now - 9 * 86400)))
        self.assertEqual(end, start)

    def test_counts_and_date_range_are_reported(self):
        now = time.time()
        self.write_session(self.root, 'interactive.jsonl',
                           [transcript_fixtures.record('interactive body')], mtime=now)
        self.write_session(self.root, 'headless.jsonl',
                           [transcript_fixtures.record('headless body'),
                            transcript_fixtures.record('boot', entrypoint='sdk-cli')],
                           mtime=now - 86400)
        self.write_session(self.root, 'excluded.jsonl',
                           [transcript_fixtures.record('assistant only', role='assistant')],
                           mtime=now - 172800)
        proc = self.run_collector()
        match = re.search(
            r'(\d+) sessions in last (\d+) days: (\d+) interactive, (\d+) headless, '
            r'(\d+) excluded, (\d+) shown\. (\S+) to (\S+)\.', proc.stdout)
        self.assertIsNotNone(match, proc.stdout)
        total, days, interactive, headless, excluded, shown, start, end = match.groups()
        self.assertEqual(int(total), 3)
        self.assertEqual(int(interactive), 1)
        self.assertEqual(int(headless), 1)
        self.assertEqual(int(excluded), 1)
        self.assertEqual(int(shown), 2)
        self.assertEqual(int(interactive) + int(headless) + int(excluded), int(total))
        self.assertEqual(start, time.strftime('%Y-%m-%d', time.localtime(now - 86400)))
        self.assertEqual(end, time.strftime('%Y-%m-%d', time.localtime(now)))


class CollectorCorrectionTests(unittest.TestCase):
    """A4: the correction marker flags the committed corrections, not the controls."""

    def test_committed_corrections_are_flagged(self):
        module = load_collector()
        flagged = [text for text in transcript_fixtures.CORRECTIONS if module.is_correction(text)]
        self.assertGreaterEqual(len(flagged), 9, flagged)

    def test_committed_non_corrections_are_not_flagged(self):
        module = load_collector()
        flagged = [text for text in transcript_fixtures.NON_CORRECTIONS
                   if module.is_correction(text)]
        self.assertLessEqual(len(flagged), 1, flagged)


class CollectorRedactionTests(CollectorCase):
    """A5: new secret kinds are redacted everywhere, including header and evidence."""

    def test_new_redaction_kinds_in_digest_and_evidence(self):
        self.root = os.path.join(self.tmp, 'Users', 'alice', 'repo')
        os.makedirs(self.root, exist_ok=True)
        email = 'alice' + '@' + 'example.test'
        jwt = '.'.join(['eyJ' + 'a' * 10, 'b' * 10, 'c' * 10])
        pem = '-----BEGIN ' + 'RSA PRIVATE KEY-----\n' + 'MIIB' + 'x' * 40 + \
              '\n-----END ' + 'RSA PRIVATE KEY-----'
        truncated = '-----BEGIN ' + 'OPENSSH PRIVATE KEY-----\n' + 'AAAAB3Nza'
        url = 'https://' + 'user' + ':' + 'pw' + '@' + 'git.example.test/repo.git'
        home = '/' + 'Users' + '/alice/private/file.txt'
        token = 'token=' + 'SECRET-TOKEN-VALUE'
        github = 'gh' + 'p_' + 'a' * 36
        self.write_session(self.root, 'secrets.jsonl', [
            transcript_fixtures.record('reach me at ' + email),
            transcript_fixtures.record('session ' + jwt),
            transcript_fixtures.record('key ' + pem),
            transcript_fixtures.record('truncated ' + truncated),
            transcript_fixtures.record('clone ' + url),
            transcript_fixtures.record('path ' + home),
            transcript_fixtures.record(token),
            transcript_fixtures.record('push ' + github),
            {'type': 'user', 'message': {'role': 'user', 'content': [
                {'type': 'tool_result', 'is_error': True,
                 'content': 'failed at %s for %s' % (home, email)}]}},
        ])
        evidence = os.path.join(self.tmp, 'evidence.json')
        proc = self.run_collector('--evidence-out', evidence)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        with open(evidence, encoding='utf-8') as handle:
            payload = json.load(handle)
        blob = proc.stdout + json.dumps(payload)
        self.assertIn('[REDACTED]', proc.stdout)
        for secret in (email, jwt, 'MIIB' + 'x' * 40, 'AAAAB3Nza', 'user:pw',
                       'SECRET-TOKEN-VALUE', 'a' * 36):
            self.assertNotIn(secret, blob)
        self.assertNotIn('alice', proc.stdout.splitlines()[0])
        self.assertNotIn('alice', blob)

    def test_secrets_regex_avoids_english_prose_and_catches_real_secrets(self):
        module = load_collector()
        prose = [
            'Keep the token budget under 5,000.',
            'Enforce a 5,000-token budget for root memory.',
            'Never commit secret files to git.',
            'Use argon2 for password hashing.',
            'See #high-risk-decision-protocol for details.',
        ]
        for line in prose:
            with self.subTest(prose=line):
                self.assertEqual(module.redact(line), line)
        secrets = [
            ('sk-' + 'x' * 20, 'x' * 20),
            ('api_key=abc123456', 'abc123456'),
            ('token: ' + 'eyJhbGciOiJIUzI1NiJ9', 'eyJhbGciOiJIUzI1NiJ9'),
            ('Authorization: Bearer ' + 'eyJhbGciOiJIUzI1NiJ9', 'eyJhbGciOiJIUzI1NiJ9'),
            ('password=supersecret1', 'supersecret1'),
        ]
        for sample, literal in secrets:
            with self.subTest(secret=sample):
                redacted = module.redact(sample)
                self.assertIn('[REDACTED]', redacted)
                self.assertNotIn(literal, redacted)


class CollectorDriftTests(CollectorCase):
    """A6: format drift thresholds, strict exit, and v1-only counting."""

    def test_drift_needs_twenty_records(self):
        nineteen = ['not json %d' % i for i in range(19)]
        self.write_raw_session(self.root, 'junk19.jsonl', nineteen)
        proc = self.run_collector()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn('FORMAT DRIFT', proc.stdout)
        self.write_raw_session(self.root, 'junk20.jsonl', ['not json 19'])
        proc = self.run_collector()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('FORMAT DRIFT: claude-code', proc.stdout)
        strict = self.run_collector('--strict')
        self.assertEqual(strict.returncode, 3, strict.stderr)

    def test_drift_when_no_well_formed_user_record(self):
        records = [json.dumps({'type': 'assistant',
                               'message': {'role': 'assistant', 'content': 'x'}})
                   for _ in range(20)]
        self.write_raw_session(self.root, 'assistant-only.jsonl', records)
        proc = self.run_collector()
        self.assertIn('FORMAT DRIFT: claude-code', proc.stdout)

    def test_blank_lines_are_not_counted_and_malformed_lines_are(self):
        typed = [json.dumps(transcript_fixtures.record('typed body %d' % i)) for i in range(10)]
        blank = ['', '   '] * 10
        self.write_raw_session(self.root, 'mixed.jsonl', typed + blank)
        proc = self.run_collector()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn('FORMAT DRIFT', proc.stdout)
        junk = ['not json %d' % i for i in range(11)]
        self.write_raw_session(self.root, 'mixed.jsonl', junk + typed + blank)
        proc = self.run_collector()
        self.assertIn('FORMAT DRIFT: claude-code', proc.stdout)

    def test_missing_table_and_missing_parent_id_are_drift(self):
        self.make_db([], missing=('session_v2',))
        proc = self.run_collector()
        self.assertIn('FORMAT DRIFT: opencode', proc.stdout)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.run_collector('--strict').returncode, 3)
        os.remove(str(self.db_path()))
        self.make_db([('inside-session', self.root, 0, [
            transcript_fixtures.opencode_user('parentless message')])], parent_column=False)
        proc = self.run_collector()
        self.assertIn('FORMAT DRIFT: opencode', proc.stdout)
        self.assertNotIn('parentless message', proc.stdout)

    def test_v1_only_sessions_are_counted_without_reading_message_or_part(self):
        path = self.make_db([('v2-session', self.root, 0, [
            transcript_fixtures.opencode_user('v2 session message')])])
        conn = sqlite3.connect(str(path))
        conn.execute('CREATE TABLE session (id text PRIMARY KEY, directory text, '
                     'time_updated integer)')
        now = int(time.time() * 1000)
        conn.execute('INSERT INTO session VALUES (?, ?, ?)', ('v1-session', self.root, now))
        conn.execute('INSERT INTO session VALUES (?, ?, ?)',
                     ('v1-old', self.root, now - 400 * 86400 * 1000))
        conn.execute('INSERT INTO session VALUES (?, ?, ?)',
                     ('v1-elsewhere', os.path.join(self.tmp, 'elsewhere'), now))
        conn.execute('CREATE VIEW message AS SELECT * FROM missing_message_table')
        conn.execute('CREATE VIEW part AS SELECT * FROM missing_part_table')
        conn.commit()
        conn.close()
        evidence = os.path.join(self.tmp, 'evidence.json')
        proc = self.run_collector('--evidence-out', evidence)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('v2 session message', proc.stdout)
        with open(evidence, encoding='utf-8') as handle:
            payload = json.load(handle)
        self.assertEqual(payload['counts']['opencode_v1_only'], 1)


class CollectorEvidenceTests(GitRepoCase):
    """A7: evidence schema, mode and path refusals."""

    def setUp(self):
        super().setUp()
        self.init_repo(self.root)

    def test_evidence_schema_and_mode_under_permissive_umask(self):
        long_text = 'long evidence message ' + 'y' * 400
        self.write_session(self.root, 'evidence.jsonl', [
            transcript_fixtures.record('short typed message'),
            transcript_fixtures.record(long_text)])
        evidence = os.path.join(self.tmp, 'evidence.json')
        proc = self.run_collector('--evidence-out', evidence, umask=0)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(stat.S_IMODE(os.stat(evidence).st_mode), 0o600)
        with open(evidence, encoding='utf-8') as handle:
            payload = json.load(handle)
        self.assertEqual(payload['version'], 1)
        self.assertRegex(payload['repo_id'], r'^[0-9a-f]{64}$')
        self.assertEqual(set(payload['counts']),
                         {'total', 'interactive', 'headless', 'excluded', 'shown',
                          'digest_shown', 'opencode_v1_only'})
        self.assertEqual(payload['counts']['shown'], 1)
        self.assertIn('date_range', payload)
        self.assertIn('drift', payload)
        session = payload['sessions'][0]
        self.assertEqual(session['id'], 'claude-code:evidence.jsonl')
        self.assertEqual(session['source'], 'claude-code')
        self.assertEqual(session['kind'], 'interactive')
        self.assertEqual(session['group'], 'evidence.jsonl')
        texts = [item['text'] for item in session['human']]
        self.assertIn(long_text, texts)
        self.assertTrue(all('correction' in item and 'msg' in item
                            for item in session['human']))
        self.assertIn('errors', session)

    def test_evidence_shown_matches_sessions_when_the_digest_truncates(self):
        for index in range(3):
            self.write_session(self.root, 'long-%d.jsonl' % index,
                               [transcript_fixtures.record(
                                   'long evidence message %d %s' % (index, 'z' * 300))])
        evidence = os.path.join(self.tmp, 'evidence.json')
        proc = self.run_collector('--evidence-out', evidence, '--max-chars', '200')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        with open(evidence, encoding='utf-8') as handle:
            payload = json.load(handle)
        self.assertEqual(len(payload['sessions']), payload['counts']['shown'])
        self.assertEqual(payload['counts']['shown'], 3)
        self.assertLess(payload['counts']['digest_shown'], payload['counts']['shown'])

    def test_evidence_path_refusals(self):
        self.write_session(self.root, 'evidence.jsonl',
                           [transcript_fixtures.record('typed message survives')])
        targets = [
            os.path.join(self.root, 'evidence.json'),
            os.path.join(self.root, '.git', 'evidence.json'),
        ]
        bridge = os.path.join(self.tmp, 'bridge')
        os.symlink(self.root, bridge)
        targets.append(os.path.join(bridge, 'evidence.json'))
        for target in targets:
            with self.subTest(target):
                proc = self.run_collector('--evidence-out', target)
                self.assertEqual(proc.returncode, 2, proc.stderr)
                self.assertFalse(os.path.lexists(target))
        existing = os.path.join(self.tmp, 'existing.json')
        with open(existing, 'w', encoding='utf-8') as handle:
            handle.write('keep me')
        proc = self.run_collector('--evidence-out', existing)
        self.assertEqual(proc.returncode, 2)
        with open(existing, encoding='utf-8') as handle:
            self.assertEqual(handle.read(), 'keep me')
        link = os.path.join(self.tmp, 'link.json')
        os.symlink(os.path.join(self.tmp, 'nowhere.json'), link)
        proc = self.run_collector('--evidence-out', link)
        self.assertEqual(proc.returncode, 2)
        self.assertTrue(os.path.islink(link))


if __name__ == '__main__':
    unittest.main()
