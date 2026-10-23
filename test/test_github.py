from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import github as g


class SyncTest(unittest.TestCase):
    def test_noop_never_pushes(self):
        plan = {'localBaseline': 'base', 'action': 'unchanged', 'remote': {'commit': 'sha', 'canPush': True}}
        with patch.object(g, 'sync_plan', return_value=plan), patch.object(g, 'git') as git:
            result = g.sync_apply(Path('.'), 'owner/dsh-test', 'main', 'owner', 'base', 'sha')
            self.assertEqual(result['status'], 'unchanged')
            git.assert_not_called()

    def test_stale_baseline(self):
        plan = {'localBaseline': 'changed', 'remote': {'commit': 'sha', 'canPush': True}}
        with patch.object(g, 'sync_plan', return_value=plan), patch.object(g, 'git') as git:
            with self.assertRaisesRegex(ValueError, 'baseline'):
                g.sync_apply(Path('.'), 'owner/dsh-test', 'main', 'owner', 'base', 'sha')
            git.assert_not_called()

    def test_unsupported_branch(self):
        with self.assertRaisesRegex(ValueError, 'Unsupported'):
            g.sync_plan(Path('.'), 'owner/dsh-test', 'bad/branch', 'owner')


class InitialExportTest(unittest.TestCase):
    def test_empty_remote_plans_initial_export(self):
        remote = {'commit': None, 'tree': None, 'canPush': True, 'empty': True}
        with patch.object(g, 'local_tree', return_value=({'baseline': 'base'}, 'tree')), \
                patch.object(g, 'inspect_remote', return_value=remote):
            self.assertEqual(g.sync_plan(Path('.'), 'owner/dsh-test', 'main', 'owner')['action'], 'initial_export')

    def test_empty_remote_requires_empty_marker(self):
        plan = {'localBaseline': 'base', 'action': 'initial_export', 'remote': {'commit': None, 'canPush': True}}
        with patch.object(g, 'sync_plan', return_value=plan), patch.object(g, '_initial_push', return_value={'status': 'pushed'}) as push:
            with self.assertRaisesRegex(ValueError, 'baseline'):
                g.sync_apply(Path('.'), 'owner/dsh-test', 'main', 'owner', 'base', 'sha')
            push.assert_not_called()
            self.assertEqual(g.sync_apply(Path('.'), 'owner/dsh-test', 'main', 'owner', 'base', 'empty')['status'], 'pushed')

    def test_create_refuses_other_owner(self):
        with self.assertRaisesRegex(ValueError, 'owner'):
            g.create_repository(Path('.'), 'someone/dsh-test', 'owner', 'd', 'h')
