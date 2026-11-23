import hashlib
import os
import threading
import time
import unittest
from unittest import mock

from tests.support import TempCase, depup, write


def digest(path):
    with open(path, 'rb') as handle:
        return hashlib.sha256(handle.read()).hexdigest()


class AdapterFixtureTests(TempCase):
    def test_cargo_go_and_uv_outdated_adapters_preserve_lockfiles(self):
        root = os.path.join(self.tmp, 'polyglot')
        write(os.path.join(root, 'Cargo.toml'),
              '[package]\nname = "fixture-rust"\nversion = "0.1.0"\n\n'
              '[dependencies]\nserde = "1"\n')
        write(os.path.join(root, 'Cargo.lock'),
              'version = 3\n\n[[package]]\nname = "serde"\nversion = "1.0.190"\n')
        write(os.path.join(root, 'go.mod'),
              'module example.com/fixture\n\ngo 1.22\n\nrequire github.com/a/b v1.0.0\n')
        write(os.path.join(root, 'go.sum'), 'github.com/a/b v1.0.0 h1:fixture\n')
        write(os.path.join(root, 'pyproject.toml'),
              '[project]\nname = "fixture-python"\nversion = "0.1.0"\n'
              'requires-python = ">=3.10"\ndependencies = ["sample-py>=1.0"]\n')
        write(os.path.join(root, 'uv.lock'),
              'version = 1\nrequires-python = ">=3.10"\n')
        protected_files = ('Cargo.toml', 'Cargo.lock', 'go.mod', 'go.sum', 'pyproject.toml', 'uv.lock')
        before = {name: digest(os.path.join(root, name)) for name in protected_files}
        calls = []

        def fake_run(argv, **kwargs):
            calls.append((argv, kwargs))
            if argv[0] == 'cargo':
                return {'rc': 0, 'stdout': '', 'stderr':
                        '    Updating serde v1.0.190 -> v1.0.210\n', 'error': None}
            if argv[0] == 'go':
                return {'rc': 0, 'stdout':
                        '{"Path":"example.com/fixture","Main":true}\n'
                        '{"Path":"github.com/a/b","Version":"v1.0.0",'
                        '"Update":{"Version":"v1.2.0"}}\n', 'stderr': '', 'error': None}
            if argv[0] == 'uv':
                return {'rc': 0, 'stdout': '├── sample-py v1.0.0 (latest: v1.4.0)\n',
                        'stderr': '', 'error': None}
            raise AssertionError('unexpected executable: %s' % argv[0])

        with mock.patch.object(depup.shutil, 'which', side_effect=lambda name: '/fixture/' + name), \
                mock.patch.object(depup, 'run_cmd', side_effect=fake_run):
            result = depup.outdated(root, 10)

        found = {(record['ecosystem'], record['name'], record['latest'])
                 for record in result['records']}
        self.assertEqual(found, {
            ('rust', 'serde', '1.0.210'),
            ('go', 'github.com/a/b', 'v1.2.0'),
            ('python', 'sample-py', '1.4.0'),
        })
        by_executable = {argv[0]: (argv, kwargs) for argv, kwargs in calls}
        self.assertIn('--dry-run', by_executable['cargo'][0])
        self.assertEqual(by_executable['go'][1]['env_extra']['GOFLAGS'], '-mod=readonly')
        self.assertEqual(by_executable['go'][1]['env_extra']['GOTOOLCHAIN'], 'local')
        self.assertIn('--frozen', by_executable['uv'][0])
        after = {name: digest(os.path.join(root, name)) for name in protected_files}
        self.assertEqual(after, before)


class NativeQueryHazardTests(TempCase):
    def hazards(self, package_json, manager='pnpm'):
        root = os.path.join(self.tmp, 'hazards')
        os.makedirs(root, exist_ok=True)
        write(os.path.join(root, 'package.json'), package_json)
        return depup.native_query_hazards(root, root, manager, {'packageManager': package_json.get('packageManager')})

    def test_json_unicode_escaped_pnpm_settings_are_detected(self):
        hazards = self.hazards({'name': 'x', 'packageManager': 'pnpm@9.0.0',
                                '\u0063onfigDependencies': {'@scope/plugin': '1.0.0'}})
        self.assertTrue(any('configDependencies' in hazard for hazard in hazards), hazards)

        hazards = self.hazards({'name': 'x', 'packageManager': 'pnpm@9.0.0',
                                '\u006danagePackageManagerVersions': True})
        self.assertTrue(any('package-manager version downloads' in hazard for hazard in hazards), hazards)

        for key in ('global_pnpmfile', 'globalPnpmfile', 'pnpmfile'):
            hazards = self.hazards({'name': 'x', 'packageManager': 'pnpm@9.0.0', key: './hook.cjs'})
            self.assertTrue(any('pnpmfile' in hazard for hazard in hazards), (key, hazards))

    def test_invalid_package_json_fails_closed_for_pnpm(self):
        root = os.path.join(self.tmp, 'badjson')
        write(os.path.join(root, 'package.json'), '{not json')
        hazards = depup.native_query_hazards(root, root, 'pnpm', {'packageManager': 'pnpm@9.0.0'})
        self.assertTrue(any('not valid JSON' in hazard for hazard in hazards), hazards)

    def test_non_object_package_json_fails_closed_for_pnpm(self):
        root = os.path.join(self.tmp, 'listjson')
        write(os.path.join(root, 'package.json'), '[]')
        hazards = depup.native_query_hazards(root, root, 'pnpm', {'packageManager': 'pnpm@9.0.0'})
        self.assertTrue(any('is not a JSON object' in hazard for hazard in hazards), hazards)

    def test_truthy_false_and_absent_settings_are_not_hazards(self):
        for value in (False, 'false', 0, None):
            hazards = self.hazards({'name': 'x', 'packageManager': 'pnpm@9.0.0',
                                    'managePackageManagerVersions': value})
            self.assertFalse(any('package-manager version downloads' in hazard for hazard in hazards), value)
        hazards = self.hazards({'name': 'x', 'packageManager': 'pnpm@9.0.0', 'dependencies': {'a': '1.0.0'}})
        self.assertFalse(any('configDependencies' in hazard for hazard in hazards), hazards)


class OutdatedParallelTests(TempCase):
    def test_outdated_parallel_preserves_order_and_caps_registry_concurrency(self):
        root = os.path.join(self.tmp, 'parallel')
        letters = ('a', 'b', 'c', 'd')
        for index in range(4):
            write(os.path.join(root, 'project%d' % index, 'package.json'), {
                'name': 'project%d' % index, 'packageManager': 'bun@1.1.0',
                'dependencies': {'%s-dep' % letter: '^1.0.0' for letter in letters}})

        active = peak = 0
        lock = threading.Lock()

        def fake_registry(name, timeout, cwd):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.02)  # hold the slot so overlap is observable
            with lock:
                active -= 1
            return {'latest': '9.9.9', 'deprecated': False}

        with mock.patch.object(depup, '_registry_view', side_effect=fake_registry), \
                mock.patch.object(depup.shutil, 'which', return_value='/usr/bin/npm'):
            result = depup.outdated(root, 10)

        expected = [('project%d' % index, '%s-dep' % letter)
                    for index in range(4) for letter in letters]
        self.assertEqual([(record['workspace'], record['name']) for record in result['records']], expected,
                         'records stay in project then dependency order despite parallel queries')
        self.assertEqual([query['cwd'] for query in result['queries']],
                         ['project%d' % index for index in range(4)])
        self.assertLessEqual(peak, 6, 'the shared semaphore caps npm view across all projects')
        self.assertGreaterEqual(peak, 2, 'project queries must actually overlap')


class CapabilitiesTests(TempCase):
    def test_capabilities_returns_all_tools_in_order(self):
        expected = ['git', 'node', 'npm', 'pnpm', 'yarn', 'bun', 'deno', 'cargo', 'rustc', 'go', 'uv', 'python3',
                    'pip3', 'poetry', 'mvn', 'gradle', 'ruby', 'bundle', 'composer', 'php', 'dotnet', 'swift']
        seen = []

        def fake(name, args=('--version',)):
            seen.append(name)
            return {'path': '/fixture/' + name, 'version': args[0]}

        with mock.patch.object(depup, 'tool_version', side_effect=fake):
            caps = depup.capabilities()
        self.assertEqual(len(expected), 22)
        self.assertEqual(list(caps['tools']), expected, 'tool probes keep the declared order')
        self.assertEqual(sorted(seen), sorted(expected))
        self.assertEqual(caps['tools']['go'], {'path': '/fixture/go', 'version': 'version'})
        self.assertEqual(caps['tools']['git'], {'path': '/fixture/git', 'version': '--version'})


if __name__ == '__main__':
    unittest.main()
