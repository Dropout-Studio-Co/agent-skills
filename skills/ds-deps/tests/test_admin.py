import contextlib
import io
import os
import shutil
import unittest

from tests.support import SKILL_DIR, TempCase, admin, write


def copy_skill(home):
    dest = os.path.join(home, '.agents', 'skills', 'ds-deps')
    shutil.copytree(SKILL_DIR, dest, ignore=shutil.ignore_patterns('__pycache__', '.DS_Store'))
    return dest


class AdminTests(TempCase):
    def run_admin(self, *argv):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = admin.main(list(argv) + ['--home', self.home, '--no-reconcile'])
        return code, buffer.getvalue()

    def setUp(self):
        super().setUp()
        self.home = os.path.join(self.tmp, 'home')
        self.canonical = copy_skill(self.home)
        self.link = os.path.join(self.home, '.claude', 'skills', 'ds-deps')

    def test_canonical_skill_is_spec_valid(self):
        self.assertEqual(admin.validate_skill(SKILL_DIR), [])

    def test_spec_violations_detected(self):
        bad = os.path.join(self.tmp, 'Bad--Name')
        write(os.path.join(bad, 'SKILL.md'), '---\nname: Bad--Name\ndescription: ""\nmetadata:\n  n: 1\n---\n'
                                             'see [x](../outside.md) and [y](references/missing.md)\n')
        problems = ' | '.join(admin.validate_skill(bad))
        for expected in ('name must be', 'description must be', 'escapes the skill', 'broken reference'):
            self.assertIn(expected, problems)
        nofm = os.path.join(self.tmp, 'nofm')
        write(os.path.join(nofm, 'SKILL.md'), '# no frontmatter')
        self.assertIn('frontmatter', admin.validate_skill(nofm)[0])

    def test_install_idempotent_and_doctor(self):
        code, out = self.run_admin('install')
        self.assertEqual(code, 0, out)
        self.assertEqual(os.readlink(self.link), os.path.join('..', '..', '.agents', 'skills', 'ds-deps'))
        self.assertEqual(os.path.realpath(self.link), os.path.realpath(self.canonical))
        code, out = self.run_admin('install')
        self.assertEqual(code, 0)
        self.assertIn('present (ok)', out)
        manifest = admin.load_manifest(admin.Paths(self.home))
        self.assertEqual(len(manifest['owned_links']), 1)
        code, out = self.run_admin('doctor')
        self.assertEqual(code, 0, out)
        self.assertIn('doctor: OK', out)

    def test_collision_refused(self):
        write(os.path.join(self.link, 'SKILL.md'), '---\nname: ds-deps\ndescription: other\n---\n')
        code, out = self.run_admin('install')
        self.assertEqual(code, 3)
        self.assertTrue(os.path.isfile(os.path.join(self.link, 'SKILL.md')), 'foreign skill must survive')
        code, out = self.run_admin('doctor')
        self.assertEqual(code, 1)
        self.assertIn('conflicts', out)

    def test_conflicting_definition_under_other_name_detected(self):
        write(os.path.join(self.home, '.config', 'opencode', 'skills', 'deps', 'SKILL.md'),
              '---\nname: ds-deps\ndescription: shadow\n---\n')
        self.run_admin('install')
        code, out = self.run_admin('doctor')
        self.assertEqual(code, 1)
        self.assertIn('opencode: no conflicting definition', out)

    def test_uninstall_removes_only_owned(self):
        self.run_admin('install')
        unrelated = os.path.join(self.home, '.claude', 'skills', 'other')
        os.symlink('../../.agents/skills/other', unrelated)
        code, out = self.run_admin('uninstall')
        self.assertEqual(code, 0)
        self.assertFalse(os.path.lexists(self.link))
        self.assertTrue(os.path.lexists(unrelated))
        self.assertTrue(os.path.isdir(self.canonical), 'canonical skill is kept by default')
        code, out = self.run_admin('uninstall')
        self.assertEqual(code, 0)

    def test_preexisting_and_changed_links_left_alone(self):
        os.makedirs(os.path.dirname(self.link))
        os.symlink(os.path.join('..', '..', '.agents', 'skills', 'ds-deps'), self.link)
        self.run_admin('install')
        self.run_admin('uninstall')
        self.assertTrue(os.path.lexists(self.link), 'a link the installer did not create is never removed')
        os.unlink(self.link)
        self.run_admin('install')
        os.unlink(self.link)
        os.symlink(self.canonical, self.link)  # user repointed it (absolute)
        code, out = self.run_admin('uninstall')
        self.assertTrue(os.path.lexists(self.link))
        self.assertIn('changed since install', out)

    def test_doctor_checks_only_active_harnesses(self):
        self.assertEqual(set(admin.DEFAULT_ROOTS), {'claude', 'opencode'})
        self.assertEqual(set(admin.HARNESS_BINARIES), {'claude', 'opencode'})
        agents = os.path.join(self.canonical, 'agents')
        if os.path.isdir(agents):
            shutil.rmtree(agents)
        self.run_admin('install')
        code, out = self.run_admin('doctor')
        self.assertEqual(code, 0, out)
        self.assertIn('doctor: OK', out)
        self.assertNotIn('codex', out)
        self.assertNotIn('openai', out)
        self.assertNotIn('pi discovery', out)

    def test_missing_explicit_only_flag_fails_doctor(self):
        skill_md = os.path.join(self.canonical, 'SKILL.md')
        with open(skill_md, encoding='utf-8') as handle:
            text = handle.read()
        write(skill_md, text.replace('disable-model-invocation: true\n', ''))
        self.run_admin('install')
        code, out = self.run_admin('doctor')
        self.assertEqual(code, 1)
        self.assertIn('FAIL explicit-only flag', out)

    def test_doctor_passes_without_claude_when_claude_not_installed(self):
        old_which = admin.shutil.which
        admin.shutil.which = lambda name: None if name == 'claude' else old_which(name)
        try:
            code, out = self.run_admin('doctor')
            self.assertEqual(code, 0, out)
            self.assertIn('WARN claude per-skill link', out)
        finally:
            admin.shutil.which = old_which

    def test_doctor_reads_integrations_manifest_roots(self):
        write(os.path.join(self.home, '.agents', 'integrations.json'),
              {'harnesses': {'newagent': {'skill_roots': ['~/.newagent/skills']}}})
        self.run_admin('install')
        code, out = self.run_admin('doctor')
        self.assertIn('newagent discovery', out)


if __name__ == '__main__':
    unittest.main()
