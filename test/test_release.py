from pathlib import Path
import sys
import json
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import publication as p


class ReleaseTest(unittest.TestCase):
    def setUp(self):
        packed = [{'files': [{'path': name} for name in ('README.md', 'docs/zh.md')]}]
        mock = patch('documentation.subprocess.run', return_value=SimpleNamespace(returncode=0, stdout=json.dumps(packed)))
        self.pack = mock.start()
        self.addCleanup(mock.stop)

    def docs(self, root):
        (root / 'docs').mkdir()
        (root / 'package.json').write_text('{}')
        (root / 'README.md').write_text('# Test\n[简体中文](./docs/zh.md)\n\nFull English documentation.\n')
        (root / 'docs/zh.md').write_text('# 测试\n[English](../README.md)\n\n完整中文文档。\n')

    def test_existing_package_never_dispatches(self):
        plan = {'action': 'unchanged', 'remote': {'commit': 'abc', 'canPush': True}}
        c = {'branch': 'main', 'githubOwner': 'owner', 'registry': 'https://registry.npmjs.org/'}
        with tempfile.TemporaryDirectory() as temp, patch.object(p, 'sync_plan', return_value=plan), patch.object(p, 'verify', return_value={'status': 'published'}), patch.object(p, 'compare', return_value={'status': 'identical'}), patch.object(p, 'gh') as gh:
            self.docs(Path(temp))
            r = p.release(Path(temp), {'name': 'dsh-test', 'version': '1.0.0'}, c, {'repository': 'owner/dsh-test'}, Path(temp), 'abc')
            self.assertEqual(r['status'], 'already_published')
            gh.assert_not_called()

    def test_dispatch_is_not_repeated(self):
        plan = {'action': 'unchanged', 'remote': {'commit': 'abc', 'canPush': True}}
        c = {'branch': 'main', 'githubOwner': 'owner', 'registry': 'https://registry.npmjs.org/', 'workflow': 'publish.yml'}
        with tempfile.TemporaryDirectory() as temp, patch.object(p, 'sync_plan', return_value=plan), patch.object(p, 'verify', return_value={'status': 'not_visible'}), patch.object(p, 'gh') as gh, \
                patch.object(p, 'find_run', return_value=None):
            root = Path(temp)
            self.docs(root)
            workflow = root / '.github/workflows/publish.yml'
            workflow.parent.mkdir(parents=True)
            workflow.write_text('EXPECTED_SHA: ${{ inputs.expected_sha }}\nrun: test "$GITHUB_SHA" = "$EXPECTED_SHA"\nrun: npm publish\n')
            args = (root, {'name': 'dsh-test', 'version': '1.0.0'}, c, {'repository': 'owner/dsh-test'}, root / '.state', 'abc')
            self.assertEqual(p.release(*args)['status'], 'dispatched')
            self.assertIn('dry_run=false', gh.call_args.args[0])
            self.assertIn('expected_sha=abc', gh.call_args.args[0])
            self.assertEqual(p.release(*args)['status'], 'reconcile_required')
            self.assertEqual(gh.call_count, 1)

    def test_dispatch_follows_found_run(self):
        plan = {'action': 'unchanged', 'remote': {'commit': 'abc', 'canPush': True}}
        c = {'branch': 'main', 'githubOwner': 'owner', 'registry': 'https://registry.npmjs.org/', 'workflow': 'publish.yml'}
        with tempfile.TemporaryDirectory() as temp, patch.object(p, 'sync_plan', return_value=plan), patch.object(p, 'verify', return_value={'status': 'not_visible'}), patch.object(p, 'gh'), \
                patch.object(p, 'find_run', return_value='9'), patch.object(p, 'watch', return_value={'status': 'verified', 'runId': '9'}) as watch:
            root = Path(temp)
            self.docs(root)
            workflow = root / '.github/workflows/publish.yml'
            workflow.parent.mkdir(parents=True)
            workflow.write_text('EXPECTED_SHA: ${{ inputs.expected_sha }}\nrun: test "$GITHUB_SHA" = "$EXPECTED_SHA"\nrun: npm publish\n')
            r = p.release(root, {'name': 'dsh-test', 'version': '1.0.0'}, c, {'repository': 'owner/dsh-test'}, root / '.state', 'abc')
            self.assertEqual((r['status'], r['runId']), ('verified', '9'))
            self.assertEqual(watch.call_args.args[5], '9')

    def test_uncertain_dispatch_keeps_intent(self):
        plan = {'action': 'unchanged', 'remote': {'commit': 'abc', 'canPush': True}}
        c = {'branch': 'main', 'githubOwner': 'owner', 'registry': 'https://registry.npmjs.org/', 'workflow': 'publish.yml'}
        with tempfile.TemporaryDirectory() as temp, patch.object(p, 'sync_plan', return_value=plan), patch.object(p, 'verify', return_value={'status': 'not_visible'}), patch.object(p, 'gh', side_effect=ValueError('timeout')) as gh:
            root = Path(temp)
            self.docs(root)
            workflow = root / '.github/workflows/publish.yml'
            workflow.parent.mkdir(parents=True)
            workflow.write_text('EXPECTED_SHA: ${{ inputs.expected_sha }}\nrun: test "$GITHUB_SHA" = "$EXPECTED_SHA"\nrun: npm publish\n')
            args = (root, {'name': 'dsh-test', 'version': '1.0.0'}, c, {'repository': 'owner/dsh-test'}, root / '.state', 'abc')
            with self.assertRaises(ValueError):
                p.release(*args)
            self.assertEqual(p.release(*args)['status'], 'reconcile_required')
            self.assertEqual(gh.call_count, 1)

    def test_missing_fence_does_not_leave_intent(self):
        plan = {'action': 'unchanged', 'remote': {'commit': 'abc', 'canPush': True}}
        c = {'branch': 'main', 'githubOwner': 'owner', 'registry': 'https://registry.npmjs.org/', 'workflow': 'publish.yml'}
        with tempfile.TemporaryDirectory() as temp, patch.object(p, 'sync_plan', return_value=plan), patch.object(p, 'verify', return_value={'status': 'not_visible'}), patch.object(p, 'gh') as gh:
            root = Path(temp)
            self.docs(root)
            workflow = root / '.github/workflows/publish.yml'
            workflow.parent.mkdir(parents=True)
            workflow.write_text('run: npm publish\n')
            with self.assertRaises(ValueError):
                p.release(root, {'name': 'dsh-test', 'version': '1.0.0'}, c, {'repository': 'owner/dsh-test'}, root / '.state', 'abc')
            self.assertFalse((root / '.state').exists())
            gh.assert_not_called()

    def test_changed_remote_refused(self):
        plan = {'action': 'unchanged', 'remote': {'commit': 'new', 'canPush': True}}
        c = {'branch': 'main', 'githubOwner': 'owner'}
        with patch.object(p, 'sync_plan', return_value=plan):
            with self.assertRaisesRegex(ValueError, 'exact'):
                p.release(Path('.'), {}, c, {'repository': 'owner/dsh-test'}, Path('.'), 'old')
