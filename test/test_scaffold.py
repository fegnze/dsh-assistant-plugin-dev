import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import scaffold
from documentation import issues as documentation_issues

PACKAGE = Path(__file__).resolve().parents[1]
CONFIG = {'schemaVersion': 1, 'projects': {'dsh-a': {'path': 'dsh-plugins/dsh-a', 'repository': 'o/dsh-a'}},
          'workspace': '..', 'githubOwner': 'o', 'npmAccount': 'o',
          'registry': 'https://registry.npmjs.org/', 'branch': 'main', 'workflow': 'publish.yml'}


class ScaffoldTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.config = self.root / 'configuration/projects.json'
        self.config.parent.mkdir(parents=True)
        self.config.write_text(json.dumps(CONFIG))
        existing = self.root / 'dsh-plugins/dsh-a'
        existing.mkdir(parents=True)
        (existing / 'package.json').write_text('{"name":"@o/dsh-a","version":"0.1.0"}')
        self.native_schema = 'dsh-devkit'
        native_patch = patch('scaffold.openspec_workflow.run', side_effect=self.native_new)
        self.native = native_patch.start()
        self.addCleanup(native_patch.stop)
        # All create tests are offline, including existing successful creates.
        registry_patch = patch('npm_name.http.client.HTTPSConnection')
        self.registry = registry_patch.start()
        self.addCleanup(registry_patch.stop)
        self.registry.return_value.getresponse.return_value.status = 404

    def native_new(self, workspace, arguments):
        self.assertEqual(workspace, self.root)
        if arguments == ['context', '--json']:
            return {'root': {'path': str(workspace)}}
        self.assertEqual(arguments[:2], ['new', 'change'])
        self.assertEqual(len(arguments), 3)  # native defaults, no schema override
        change = workspace / 'openspec/changes' / arguments[2]
        change.mkdir(parents=True, exist_ok=False)
        (change / '.openspec.yaml').write_text(f'schema: {self.native_schema}\ncreated: 2026-10-20\n')
        return {'output': 'created'}

    def tearDown(self):
        self.tmp.cleanup()

    def test_creates_registered_project_that_passes_doc_gate(self):
        result = scaffold.create(self.root, self.config, 'dsh-new-thing', 'o', '示例插件')
        target = Path(result['path'])
        saved = json.loads(self.config.read_text())
        self.assertEqual(saved['projects']['dsh-new-thing'], {'path': 'dsh-plugins/dsh-new-thing', 'repository': 'o/dsh-new-thing'})
        self.assertEqual({k: v for k, v in saved.items() if k != 'projects'}, {k: v for k, v in CONFIG.items() if k != 'projects'})
        self.assertEqual(documentation_issues(target), [])
        package = json.loads((target / 'package.json').read_text())
        self.assertEqual(package['name'], '@o/dsh-new-thing')
        patch_text = (target / 'cordis.patch.yml').read_text()
        self.assertIn('id: dsh-new-thing', patch_text)
        self.assertIn('name: "@o/dsh-new-thing"', patch_text)  # YAML @ scalar must be quoted
        self.assertIn("id: '@o/dsh-new-thing'", (target / 'src/client.js').read_text())
        self.assertEqual(package['exports']['./package.json'], './package.json')
        self.assertIn('EXPECTED_SHA: ${{ inputs.expected_sha }}', (target / '.github/workflows/publish.yml').read_text())
        self.assertFalse((target / 'icon.svg').exists())  # drawn by hand per the icon standard
        self.assertFalse((target / 'openspec').exists())
        self.assertTrue((self.root / 'openspec/schemas/dsh-devkit/schema.yaml').is_file())
        change = self.root / 'openspec/changes/dsh-new-thing-first-delivery'
        metadata = (change / '.openspec.yaml').read_text()
        self.assertIn('schema: dsh-devkit\ncreated: 2026-10-20\n', metadata)
        self.assertIn('affected_areas: ["dsh-plugins/dsh-new-thing"]', metadata)
        self.assertIn('dsh-plugins/dsh-new-thing', (change / 'proposal.md').read_text())
        tasks = (change / 'tasks.md').read_text()
        self.assertIn('dsh-plugins/dsh-new-thing', tasks)
        self.assertIn('dsh-new-thing-first-delivery', ' '.join(result['next']))
        for command in ('guide', 'inspect', 'remote', 'registry', 'npm-bootstrap-plan', 'validate', 'commit-plan', 'create-repo', 'sync-plan', 'release'):
            self.assertIn(command, tasks)
        for evidence in ('独立仓库', '远端 SHA', 'npm 精确版本', '包字节', '授权'):
            self.assertIn(evidence, tasks)
        for obsolete in ('MySpace', 'Butler/tools/', '默认公开'):
            self.assertNotIn(obsolete, tasks)
        self.assertNotIn('guide / inspect / plan', tasks)
        self.assertNotIn('读取 apply', tasks)
        self.assertIn('非固定命令顺序', tasks)
        self.assertIn('新建小提案，不重开归档', (change / 'proposal.md').read_text())
        self.assertNotIn('→', ' '.join(result['next']))

    def snapshot(self):
        return {str(path.relative_to(self.root)): (
            path.read_bytes() if path.is_file() else None)
            for path in self.root.rglob('*')}

    def test_npm_preflight_failure_leaves_entire_workspace_untouched(self):
        import http.client
        for failure in (200, 401, 403, 429, 500, 302,
                        TimeoutError('secret timeout detail'),
                        OSError('secret network detail'),
                        http.client.HTTPException('secret HTTP detail')):
            with self.subTest(failure=type(failure).__name__ if isinstance(failure, Exception) else failure):
                response = self.registry.return_value.getresponse
                response.side_effect = failure if isinstance(failure, Exception) else None
                response.return_value.status = failure if isinstance(failure, int) else 404
                before = self.snapshot()
                with patch('scaffold.openspec_workflow.initialize') as initialize:
                    with self.assertRaises(ValueError) as caught:
                        scaffold.create(self.root, self.config, 'dsh-new', 'o', 'x')
                    initialize.assert_not_called()
                expected = scaffold.npm_name.OCCUPIED if failure == 200 else scaffold.npm_name.UNAVAILABLE
                self.assertEqual(str(caught.exception), expected)
                self.native.assert_not_called()
                self.assertEqual(self.snapshot(), before)

    def test_available_name_is_checked_before_workflow_mutations(self):
        original_initialize = scaffold.openspec_workflow.initialize

        def initialize(*args):
            self.registry.return_value.getresponse.assert_called_once_with()
            self.registry.return_value.close.assert_called_once_with()
            self.assertFalse((self.root / 'openspec').exists())
            return original_initialize(*args)

        with patch('scaffold.openspec_workflow.initialize', side_effect=initialize):
            scaffold.create(self.root, self.config, 'dsh-new', 'o', 'x')
        self.registry.return_value.request.assert_called_once_with(
            'GET', '/%40o%2Fdsh-new', headers={'Accept': 'application/json'})

    def test_files_contain_only_plugin_assets(self):
        self.assertFalse(any(path.startswith('openspec/') for path in scaffold.files('dsh-new', 'o', 'x')))

    def test_preserves_existing_workspace_schema_and_native_default(self):
        root = self.root / 'openspec'
        root.mkdir()
        config = root / 'config.yaml'
        original = 'schema: spec-driven\ncontext: Existing workspace context\n'
        config.write_text(original)
        self.native_schema = 'spec-driven'
        scaffold.create(self.root, self.config, 'dsh-new', 'o', 'x')
        self.assertEqual(config.read_text(), original)
        self.assertFalse((root / 'schemas/dsh-devkit').exists())
        self.assertIn('schema: spec-driven', (root / 'changes/dsh-new-first-delivery/.openspec.yaml').read_text())

    def test_change_collision_leaves_plugin_and_registry_untouched(self):
        change = self.root / 'openspec/changes/dsh-new-first-delivery'
        change.mkdir(parents=True)
        proposal = change / 'proposal.md'
        proposal.write_text('existing proposal')
        original = self.config.read_text()
        with patch('scaffold.openspec_workflow.initialize') as initialize:
            with self.assertRaisesRegex(ValueError, 'change already exists'):
                scaffold.create(self.root, self.config, 'dsh-new', 'o', 'x')
            initialize.assert_not_called()
        self.native.assert_not_called()
        self.assertEqual(proposal.read_text(), 'existing proposal')
        self.assertEqual(self.config.read_text(), original)
        self.assertFalse((self.root / 'dsh-plugins/dsh-new').exists())

    def test_native_failure_does_not_write_plugin_or_registration(self):
        self.native.side_effect = ValueError('OpenSpec CLI unavailable')
        original = self.config.read_text()
        with self.assertRaisesRegex(ValueError, 'CLI unavailable'):
            scaffold.create(self.root, self.config, 'dsh-new', 'o', 'x')
        self.assertEqual(self.config.read_text(), original)
        self.assertFalse((self.root / 'dsh-plugins/dsh-new').exists())
        self.native.assert_called_once_with(self.root, ['context', '--json'])

    def test_scaffold_tests_pass(self):
        if not shutil.which('node') or not shutil.which('npm'):
            self.skipTest('node and npm required: generated scaffold tests not verified')
        target = Path(scaffold.create(self.root, self.config, 'dsh-new-thing', 'o', 'x')['path'])
        r = subprocess.run(['npm', 'test'], cwd=target, capture_output=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout.decode()[-500:])

    def test_rejects_bad_name_duplicates_and_existing_dirs(self):
        for name in ('bad', 'dsh-A', 'dsh-a'):
            with self.assertRaises(ValueError):
                scaffold.create(self.root, self.config, name, 'o', 'x')
        (self.root / 'dsh-plugins/dsh-b').mkdir(parents=True)
        with self.assertRaises(ValueError):
            scaffold.create(self.root, self.config, 'dsh-b', 'o', 'x')


class PortableAssetsTest(unittest.TestCase):
    def test_scoped_npm_identity_does_not_change_runtime_scope(self):
        assets = scaffold.files('dsh-example', 'repository-owner', 'Example', '@package-owner/dsh-example')
        package = json.loads(assets['package.json'])
        self.assertEqual(package['name'], '@package-owner/dsh-example')
        self.assertEqual(package['repository']['url'], 'git+https://github.com/repository-owner/dsh-example.git')
        self.assertIn('id: dsh-example', assets['cordis.patch.yml'])
        self.assertIn('name: "@package-owner/dsh-example"', assets['cordis.patch.yml'])
        self.assertIn("id: '@package-owner/dsh-example'", assets['src/client.js'])
        self.assertIn('/dsh-example/api', assets['src/host.mjs'])
        self.assertIn('x-dsh-example', assets['src/host.mjs'])
        self.assertNotIn('@package-owner', assets['src/host.mjs'])

    def test_generated_assets_are_package_local_and_portable(self):
        assets = scaffold.files('dsh-example', 'owner', 'Example')
        for name, text in assets.items():
            with self.subTest(name=name):
                path = Path(name)
                self.assertFalse(path.is_absolute())
                self.assertNotIn('..', path.parts)
                for obsolete in ('MySpace', 'Butler/tools/', '/Users/', 'bin/git-hooks', 'butler_sdk'):
                    self.assertNotIn(obsolete, text)
        self.assertEqual(json.loads(assets['package.json'])['name'], 'dsh-example')
        self.assertFalse(any(name.startswith(('openspec/', '.git/hooks/', 'bin/')) for name in assets))

    def test_workflow_resources_are_bundled_not_workspace_copies(self):
        resources = PACKAGE / 'templates/openspec'
        self.assertEqual(scaffold.openspec_workflow.TEMPLATES.resolve(), resources)
        self.assertTrue((resources / 'schemas/dsh-devkit/schema.yaml').is_file())
        expected = {path.relative_to(resources).as_posix(): path.read_text().replace('{{project}}', 'PROJECT')
                    for path in resources.rglob('*') if path.is_file()}
        self.assertEqual(scaffold.openspec_workflow.files(), expected)


if __name__ == '__main__':
    unittest.main()
