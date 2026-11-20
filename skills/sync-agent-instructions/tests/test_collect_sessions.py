"""collect_sessions.py: OpenCode is read read-only from SQLite; Claude Code still works; no Gemini."""
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

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

    def run_collector(self):
        return subprocess.run([sys.executable, SCRIPT, '--repo', self.root, '--days', '60'],
                              capture_output=True, text=True, env=self.env)

    def db_path(self):
        return Path(self.data) / 'opencode' / 'opencode.db'

    def make_db(self, sessions):
        path = self.db_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path))
        conn.execute('CREATE TABLE project (id text PRIMARY KEY)')
        conn.execute("INSERT INTO project VALUES ('project-1')")
        conn.execute("CREATE TABLE session_v2 (id text PRIMARY KEY, project_id text, slug text, directory text, "
                     "time_created integer, time_updated integer)")
        conn.execute("CREATE TABLE session_message (id text PRIMARY KEY, session_id text, type text, seq integer, "
                     "time_created integer, time_updated integer, data text)")
        for session_id, directory, age_days, messages in sessions:
            now = int((time.time() - age_days * 86400) * 1000)
            conn.execute('INSERT INTO session_v2 VALUES (?, ?, ?, ?, ?, ?)',
                         (session_id, 'project-1', session_id, directory, now, now))
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
                                                      'error': 'command failed token=SECRET-TOKEN-VALUE'}}]})]),
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


if __name__ == '__main__':
    unittest.main()
