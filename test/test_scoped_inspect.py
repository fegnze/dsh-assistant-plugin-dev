import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import cli


class ScopedInspectTest(unittest.TestCase):
    def test_scoped_legacy_and_identity_rejections(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'dsh-example'
            root.mkdir()
            (root / 'icon.svg').write_text('<svg/>')
            base = {'version': '0.1.0', 'repository': 'https://github.com/fegnze/dsh-example',
                    'dsh': {'bundle': {'patch': './cordis.patch.yml'}}, 'icon': './icon.svg',
                    'files': ['icon.svg'], 'exports': {'./package.json': './package.json'}}
            config = {'npmAccount': 'fegnze', 'workspace': str(Path(directory).resolve()), 'workflow': 'publish.yml'}
            for name, valid in [('dsh-example', True), ('@fegnze/dsh-example', True),
                                ('@other/dsh-example', False), ('@fegnze/other', False),
                                ('@fegnze//dsh-example', False), ('junk', False)]:
                with self.subTest(name=name):
                    (root / 'package.json').write_text(json.dumps({**base, 'name': name}))
                    with patch('cli.project', return_value=(config, root, {'repository': 'fegnze/dsh-example'})), \
                         patch('cli.command', return_value=''), patch('documentation.issues', return_value=[]), \
                         patch('openspec_workflow.inspect', return_value={}):
                        result = cli.inspect('dsh-example')
                    self.assertEqual(not result['issues'], valid)
                    self.assertEqual(result['name'], name)
                    self.assertEqual(result['guidance']['trustedPublisher']['repository'], 'dsh-example')
            (root / 'package.json').write_text(json.dumps({**base, 'name': '@fegnze/dsh-example'}))
            with patch('cli.project', return_value=(config, root, {'repository': 'fegnze/dsh-different'})), \
                 patch('cli.command', return_value=''), patch('documentation.issues', return_value=[]), \
                 patch('openspec_workflow.inspect', return_value={}):
                self.assertIn('Directory and repository name must match', cli.inspect('dsh-example')['issues'])
