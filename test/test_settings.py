import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import settings
import processes


class SettingsTest(unittest.TestCase):
    def setUp(self):
        self.addCleanup(processes.configure)

    def test_relative_workspace_and_optional_configuration(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            config = root / 'configuration/projects.json'
            config.parent.mkdir()
            workspace = root / 'workspace'
            workspace.mkdir()
            value = {'schemaVersion': 1, 'workspace': '../workspace',
                     'githubOwner': 'owner', 'npmAccount': 'owner',
                     'registry': 'https://registry.npmjs.org/', 'branch': 'main',
                     'workflow': 'publish.yml', 'projects': {},
                     'coAuthor': 'Test <test@example.invalid>',
                     'executables': {'git': str(Path(sys.executable).resolve())}}
            normalized = settings.validate(config, value)
            self.assertEqual(normalized['workspace'], str(workspace))
            self.assertEqual(value['workspace'], '../workspace')
            self.assertEqual(normalized['coAuthor'], value['coAuthor'])

    def test_package_local_or_symlink_config_is_rejected_before_read(self):
        package = Path(__file__).resolve().parents[1]
        with patch.object(Path, 'read_bytes') as read:
            with self.assertRaises(ValueError):
                settings.read(package / 'config.json')
        read.assert_not_called()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / 'actual.json'
            target.write_text('{}')
            link = root / 'config.json'
            link.symlink_to(target)
            with self.assertRaises(ValueError):
                settings.read(link)

    def test_save_and_stale(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'config.json'
            value = {'schemaVersion': 1, 'workspace': '.', 'githubOwner': 'owner', 'npmAccount': 'owner', 'registry': 'https://registry.npmjs.org/', 'branch': 'main', 'workflow': 'publish.yml', 'projects': {}}
            path.write_text(json.dumps(value))
            old = settings.read(path)
            value['branch'] = 'release'
            updated = settings.save(path, old['revision'], value)
            self.assertEqual(updated['config']['branch'], 'release')
            with self.assertRaises(ValueError):
                settings.save(path, old['revision'], value)

    def test_invalid_workspace(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'config.json'
            value = {'schemaVersion': 1, 'workspace': 'missing', 'githubOwner': 'owner', 'npmAccount': 'owner', 'registry': 'https://registry.npmjs.org/', 'branch': 'main', 'workflow': 'publish.yml', 'projects': {}}
            with self.assertRaises(ValueError):
                settings.save(path, 'old', value)
