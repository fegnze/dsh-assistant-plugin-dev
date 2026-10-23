import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import publication as p


class PublicationTest(unittest.TestCase):
    def test_run_id_rejects_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):
                p.store(Path(temp), '../escape', {})

    def test_completed_is_not_published(self):
        run = {'repository': {'full_name': 'owner/dsh-test'}, 'head_sha': 'abc',
               'path': '.github/workflows/publish.yml', 'html_url': 'https://github.com/run',
               'status': 'completed', 'conclusion': 'success'}
        with tempfile.TemporaryDirectory() as temp, patch.object(p, 'gh', return_value=json.dumps(run)):
            result = p.observe(Path(temp), 'owner/dsh-test', '12', Path(temp), 'abc')
            self.assertFalse(result['publicationVerified'])
            self.assertEqual(json.loads((Path(temp) / '12.json').read_text()), result)
            with self.assertRaisesRegex(ValueError, 'commit'):
                p.observe(Path(temp), 'owner/dsh-test', '12', Path(temp), 'different')

    def test_resume_pending_never_republishes(self):
        state = {'workflow': '.github/workflows/publish.yml', 'status': 'in_progress'}
        with patch.object(p, 'observe', return_value=state), patch.object(p, 'gh') as gh:
            result = p.resume(Path('.'), {}, {'workflow': 'publish.yml'}, {'repository': 'owner/dsh-test'}, Path('.'), '12', 'abc')
            self.assertEqual(result['status'], 'in_progress')
            gh.assert_not_called()

    def test_resume_verifies_success(self):
        state = {'workflow': '.github/workflows/publish.yml', 'status': 'completed', 'conclusion': 'success'}
        with tempfile.TemporaryDirectory() as temp, patch.object(p, 'observe', return_value=state), patch.object(p, 'local_tree', return_value=({}, 'tree')), patch.object(p, 'gh', return_value=json.dumps({'tree': {'sha': 'tree'}})), patch.object(p, 'verify', return_value={'status': 'published'}), patch.object(p, 'compare', return_value={'status': 'identical'}):
            result = p.resume(Path(temp), {'name': 'dsh-test', 'version': '1.0.0'}, {'workflow': 'publish.yml', 'registry': 'https://registry.npmjs.org'}, {'repository': 'owner/dsh-test'}, Path(temp), '12', 'abc')
            self.assertTrue(result['publicationVerified'])
            self.assertEqual(result['status'], 'verified')
            self.assertEqual(json.loads((Path(temp) / '12.json').read_text()), result)

    def test_resume_wrong_workflow(self):
        with patch.object(p, 'observe', return_value={'workflow': 'other'}):
            with self.assertRaisesRegex(ValueError, 'workflow'):
                p.resume(Path('.'), {}, {'workflow': 'publish.yml'}, {'repository': 'owner/dsh-test'}, Path('.'), '12', 'abc')

    def test_wrong_repo(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(p, 'gh', return_value=json.dumps({'repository': {'full_name': 'evil/other'}})):
            with self.assertRaisesRegex(ValueError, 'repository'):
                p.observe(Path(temp), 'owner/dsh-test', '12', Path(temp))
