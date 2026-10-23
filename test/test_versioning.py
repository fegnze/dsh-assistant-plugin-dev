"""Version operations use real temporary Git repositories; no network or project scripts."""
import fcntl
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SRC = Path(__file__).resolve().parents[1] / 'src'
sys.path.insert(0, str(SRC))
import versioning as v
import cli


class VersioningTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        self.project = self.repo / 'nested/dsh-test'
        self.project.mkdir(parents=True)
        v.git(self.repo, 'init')
        v.git(self.repo, 'config', 'user.email', 'test@example.invalid')
        v.git(self.repo, 'config', 'user.name', 'Test')
        self.manifest = self.project / 'package.json'
        self.manifest.write_bytes(b'{\n  "name": "dsh-test", "nested": {"version":"9.0.0"},\n  "version" : "1.2.3", "unicode": "\\u4e2d"\n}\n')
        self.manifest.chmod(0o640)
        (self.project / 'source').write_text('initial')
        (self.repo / 'outside').write_text('outside')
        (self.repo / '.gitignore').write_text('ignored\n')
        self.commit()

    def tearDown(self):
        self.tmp.cleanup()

    def commit(self):
        v.git(self.repo, 'add', '.')
        v.git(self.repo, 'commit', '-m', 'initial')

    def dirty(self):
        (self.project / 'source').write_text('changed')

    def set_version(self, version):
        p = json.loads(self.manifest.read_text())
        p['version'] = version
        self.manifest.write_text(json.dumps(p))

    def test_readonly_deterministic_plan_uses_delivery_snapshot(self):
        self.dirty()
        before = self.manifest.read_bytes()
        result = v.plan(self.project)
        self.assertEqual(result, v.plan(self.project))
        self.assertEqual(result['baseline'], v.snapshot(self.project)['baseline'])
        self.assertEqual(result['status'], 'bump_required')
        self.assertEqual(result['headVersion'], '1.2.3')
        self.assertEqual(result['targetVersion'], '1.2.4')
        self.assertEqual(self.manifest.read_bytes(), before)
        self.assertFalse(list((self.repo / '.git').glob('devkit-version-*')))

    def test_patch_changes_only_version_preserves_mode_and_does_not_repeat(self):
        self.dirty()
        before = self.manifest.read_bytes()
        result = v.bump(self.project, v.plan(self.project)['baseline'])
        self.assertEqual(result['status'], 'bumped')
        self.assertEqual(self.manifest.read_bytes(), before.replace(b'"1.2.3"', b'"1.2.4"'))
        self.assertEqual(self.manifest.stat().st_mode & 0o777, 0o640)
        self.assertEqual(result['baseline'], v.snapshot(self.project)['baseline'])
        self.assertEqual(v.bump(self.project, result['baseline'])['status'], 'already_bumped')
        self.assertFalse(v.git(self.repo, 'diff', '--cached', '--name-only'))
        self.assertEqual(v.git(self.repo, 'log', '--format=%s').decode().strip(), 'initial')

    def test_clean_ignored_and_unrelated_changes_do_not_bump(self):
        (self.project / 'ignored').write_text('ignored')
        (self.repo / 'outside').write_text('other')
        result = v.plan(self.project)
        self.assertFalse(result['dirty'])
        self.assertEqual(v.bump(self.project, result['baseline'])['status'], 'unchanged')

    def test_untracked_and_deleted_sources_count_as_changes(self):
        (self.project / 'new').write_text('new')
        self.assertEqual(v.plan(self.project)['status'], 'bump_required')
        (self.project / 'source').unlink()
        self.assertEqual(v.plan(self.project)['status'], 'bump_required')

    def test_manual_higher_version_is_retained(self):
        self.set_version('2.0.0')
        result = v.plan(self.project)
        self.assertEqual(result['status'], 'already_bumped')
        self.assertEqual(v.bump(self.project, result['baseline'])['targetVersion'], '2.0.0')

    def test_new_manifest_initial_version_retained(self):
        new = self.repo / 'new-project'
        new.mkdir()
        (new / 'package.json').write_text('{"version":"0.1.0"}')
        result = v.plan(new)
        self.assertIsNone(result['headVersion'])
        self.assertEqual(v.bump(new, result['baseline'])['status'], 'initial_version')
        self.assertEqual(result['targetVersion'], '0.1.0')

    def test_repo_root_manifest(self):
        (self.repo / 'package.json').write_text('{"version":"0.0.1"}')
        self.commit()
        (self.repo / 'outside').write_text('dirty')
        self.assertEqual(v.plan(self.repo)['targetVersion'], '0.0.2')

    def test_non_plain_versions_and_downgrades_rejected(self):
        for version in ('1.2.3-beta.1', '1.2.3+meta', '01.2.3', '1.2', 'v1.2.3', 123, '1.2.2'):
            with self.subTest(version=version):
                self.set_version(version)
                with self.assertRaises(ValueError):
                    v.plan(self.project)

    def test_head_prerelease_also_requires_decision(self):
        self.set_version('1.2.3-beta.1')
        self.commit()
        self.set_version('1.2.3')
        with self.assertRaises(ValueError):
            v.plan(self.project)

    def test_duplicate_version_rejected(self):
        self.manifest.write_text('{"version":"1.2.3","version":"1.2.4"}')
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            v.plan(self.project)

    def test_stale_content_mode_head_and_staged_changes_rejected(self):
        self.dirty()
        baseline = v.plan(self.project)['baseline']
        (self.project / 'source').write_text('raced')
        with self.assertRaisesRegex(ValueError, 'Stale'):
            v.bump(self.project, baseline)
        baseline = v.plan(self.project)['baseline']
        self.manifest.chmod(0o600)
        with self.assertRaisesRegex(ValueError, 'Stale'):
            v.bump(self.project, baseline)
        baseline = v.plan(self.project)['baseline']
        self.commit()
        with self.assertRaisesRegex(ValueError, 'Stale'):
            v.bump(self.project, baseline)
        v.git(self.repo, 'add', 'outside')
        (self.repo / 'outside').write_text('staged')
        v.git(self.repo, 'add', 'outside')
        with self.assertRaisesRegex(ValueError, 'Index'):
            v.plan(self.project)

    def test_symlink_manifest_rejected(self):
        self.manifest.unlink()
        self.manifest.symlink_to(self.repo / 'outside')
        with self.assertRaisesRegex(ValueError, 'Symlink'):
            v.plan(self.project)

    def test_concurrent_bump_lock_rejected(self):
        self.dirty()
        baseline = v.plan(self.project)['baseline']
        lock = self.repo / '.git' / ('devkit-version-' + hashlib.sha256(str(self.project.resolve()).encode()).hexdigest() + '.lock')
        with lock.open('wb') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(ValueError, 'Concurrent'):
                v.bump(self.project, baseline)

    def test_manifest_change_before_replace_not_overwritten(self):
        self.dirty()
        baseline = v.plan(self.project)['baseline']
        original = v._replace_version
        def raced(raw, target):
            result = original(raw, target)
            self.set_version('1.2.9')
            return result
        with patch.object(v, '_replace_version', side_effect=raced):
            with self.assertRaisesRegex(ValueError, 'changed'):
                v.bump(self.project, baseline)
        self.assertEqual(json.loads(self.manifest.read_text())['version'], '1.2.9')
        self.assertFalse(list((self.repo / '.git').glob('.devkit-version-*')))

    def test_source_change_before_replace_not_overwritten(self):
        self.dirty()
        baseline = v.plan(self.project)['baseline']
        before = self.manifest.read_bytes()
        original = v._replace_version
        def raced(raw, target):
            (self.project / 'source').write_text('raced')
            return original(raw, target)
        with patch.object(v, '_replace_version', side_effect=raced):
            with self.assertRaisesRegex(ValueError, 'changed'):
                v.bump(self.project, baseline)
        self.assertEqual(self.manifest.read_bytes(), before)

    def test_atomic_failure_leaves_original_and_cleans_temp(self):
        self.dirty()
        baseline = v.plan(self.project)['baseline']
        before = self.manifest.read_bytes()
        with patch.object(v.os, 'replace', side_effect=OSError('simulated')):
            with self.assertRaises(OSError):
                v.bump(self.project, baseline)
        self.assertEqual(self.manifest.read_bytes(), before)
        self.assertFalse(list((self.repo / '.git').glob('.devkit-version-*')))

    def test_cli_version_queries_and_explicit_bump(self):
        self.dirty()
        config = self.repo / 'query-config.json'
        state = self.repo / 'external-state'
        config.write_text(json.dumps({
            'schemaVersion': 1, 'workspace': '.', 'githubOwner': 'owner', 'npmAccount': 'owner',
            'registry': 'https://registry.npmjs.org/', 'branch': 'main', 'workflow': 'publish.yml',
            'projects': {'dsh-test': {'path': 'nested/dsh-test', 'repository': 'owner/dsh-test'}}}))
        cli.configure(config, state)
        self.assertEqual(cli.invoke('version_plan', {'project': 'dsh-test'})['targetVersion'], '1.2.4')
        for args in (['version-plan', 'dsh-test'], ['version-bump', 'dsh-test', v.plan(self.project)['baseline']]):
            argv = ['cli.py', '--config', str(config), '--state-dir', str(state), *args]
            with patch.object(sys, 'argv', argv), patch('builtins.print') as output:
                cli.main()
                self.assertIn(json.loads(output.call_args.args[0])['status'], ('bump_required', 'bumped'))
        self.assertEqual(json.loads(self.manifest.read_text())['version'], '1.2.4')
        self.assertFalse(v.git(self.repo, 'diff', '--cached', '--name-only'))
        self.assertEqual(v.git(self.repo, 'log', '--format=%s').decode().strip(), 'initial')
        guide = cli.invoke('guide', {})
        self.assertIn('version-plan', guide['tools'])
        self.assertIn('version-bump', guide['tools'])
        self.assertNotIn('MySpace', guide['delivery']['default'])


if __name__ == '__main__':
    unittest.main()
