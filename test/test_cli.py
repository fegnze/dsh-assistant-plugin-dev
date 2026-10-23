"""One-shot CLI contracts against external, disposable configuration only."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE / 'src'))
import cli
import processes


class CliTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.workspace = self.root / 'workspace'
        self.project = self.workspace / 'dsh-plugins/dsh-example'
        self.project.mkdir(parents=True)
        (self.project / 'docs').mkdir()
        (self.project / 'README.md').write_text('# Example\n[中文](./docs/zh.md)\n')
        (self.project / 'docs/zh.md').write_text('# 示例\n[English](../README.md)\n')
        (self.project / 'icon.svg').write_text('<svg/>')
        self.package = {
            'name': '@owner/dsh-example', 'version': '0.1.0',
            'repository': 'https://github.com/owner/dsh-example',
            'dsh': {'bundle': {'patch': './cordis.patch.yml'}},
            'icon': './icon.svg', 'files': ['icon.svg', 'README.md', 'docs/zh.md'],
            'exports': {'./package.json': './package.json'},
        }
        (self.project / 'package.json').write_text(json.dumps(self.package))
        self.config_path = self.root / 'configuration/projects.json'
        self.config_path.parent.mkdir()
        self.value = {
            'schemaVersion': 1, 'workspace': '../workspace', 'githubOwner': 'owner',
            'npmAccount': 'owner', 'registry': 'https://registry.npmjs.org/',
            'branch': 'main', 'workflow': 'publish.yml',
            'projects': {'dsh-example': {
                'path': 'dsh-plugins/dsh-example', 'repository': 'owner/dsh-example'}},
        }
        self.save_config()
        self.state = self.root / 'state'
        cli.configure(self.config_path, self.state)
        self.addCleanup(processes.configure)

    def save_config(self):
        self.config_path.write_text(json.dumps(self.value))

    def command(self, *arguments):
        out = io.StringIO()
        argv = ['cli.py', '--config', str(self.config_path), '--state-dir', str(self.state), *arguments]
        with patch.object(sys, 'argv', argv), redirect_stdout(out):
            cli.main()
        return json.loads(out.getvalue())

    def test_external_configuration_is_anchored_to_its_file(self):
        config = cli.config()
        self.assertEqual(config['workspace'], str(self.workspace))
        self.assertTrue(Path(config['workspace']).is_absolute())
        config, path, entry = cli.project('dsh-example')
        self.assertEqual(path, self.project)
        self.assertEqual(entry, self.value['projects']['dsh-example'])
        self.assertEqual(json.loads(self.config_path.read_text())['workspace'], '../workspace')

    def test_projects_use_only_explicit_registration(self):
        unregistered = self.workspace / 'dsh-plugins/dsh-unregistered'
        unregistered.mkdir()
        (unregistered / 'package.json').write_text('{}')
        self.assertEqual(cli.invoke('projects', {}), {'projects': ['dsh-example']})
        self.assertEqual(self.command('projects'), {'projects': ['dsh-example']})
        with self.assertRaises(ValueError):
            cli.project('dsh-unregistered')

    def test_guide_points_only_to_packaged_resources(self):
        guide = cli.invoke('guide', {})
        for key in ('documentation', 'cli'):
            resource = Path(guide[key]).resolve()
            self.assertTrue(resource.is_relative_to(PACKAGE))
            self.assertTrue(resource.is_file())
        text = Path(guide['documentation']).read_text()
        self.assertTrue(guide['requiredReading'])
        for section in guide['requiredReading']:
            self.assertIn(f'## {section}\n', text)
        self.assertNotIn('MySpace', json.dumps(guide.get('delivery', {})))
        self.assertNotIn('Butler/tools/', text)

    def test_help_returns_guide_without_configuration(self):
        for argv in ([], ['--help'], ['-h'], ['help']):
            with self.subTest(argv=argv):
                out = io.StringIO()
                with patch.object(sys, 'argv', ['cli.py', *argv]), redirect_stdout(out):
                    cli.main()
                self.assertIn('tools', json.loads(out.getvalue()))
                self.assertNotIn('flow', json.loads(out.getvalue()))

    def test_unknown_and_escaping_projects_are_rejected(self):
        with self.assertRaises(ValueError):
            cli.project('../other')
        for path in ('..', '../outside', '.'):
            with self.subTest(path=path):
                self.value['projects']['dsh-example']['path'] = path
                self.save_config()
                with self.assertRaises(ValueError):
                    cli.project('dsh-example')

    def test_symlink_escape_is_rejected(self):
        outside = self.root / 'outside'
        outside.mkdir()
        (outside / 'package.json').write_text('{}')
        (self.workspace / 'escaped').symlink_to(outside, target_is_directory=True)
        self.value['projects']['dsh-example']['path'] = 'escaped'
        self.save_config()
        with self.assertRaises(ValueError):
            cli.project('dsh-example')

    def test_private_registration_is_not_publishable(self):
        (self.project / 'package.json').write_text(json.dumps({**self.package, 'private': True}))
        with patch.object(cli, 'command', return_value=''):
            result = cli.inspect('dsh-example')
        self.assertEqual(result['issues'], ['Private package cannot publish'])

    def test_query_dispatch_rejects_mutations_and_invalid_arguments(self):
        for name, args in (('publish', {}), ('plan', {'project': 'dsh-example'}),
                           ('inspect', {}), ('projects', {'extra': True}),
                           ('version_plan', {'project': 1})):
            with self.subTest(name=name, args=args), self.assertRaises(ValueError):
                cli.invoke(name, args)

    def test_no_parallel_delivery_plan(self):
        guide = cli.invoke('guide', {})
        self.assertNotIn('phases', guide['openspec'])
        self.assertIn('Native OpenSpec OPSX', guide['openspec']['workflowOwner'])
        self.assertIn('no devkit archive wrapper', guide['openspec']['commands'])
        self.assertFalse(hasattr(cli, 'rpc'))
        self.assertFalse(hasattr(cli, 'TOOLS'))

    def test_inspect_retains_publisher_guidance(self):
        with patch.object(cli, 'command', return_value=''):
            result = self.command('inspect', 'dsh-example')
        self.assertEqual(result['issues'], [])
        self.assertEqual(result['guidance']['trustedPublisher']['owner'], 'owner')
        self.assertEqual(result['guidance']['trustedPublisher']['repository'], 'dsh-example')
        self.assertNotIn('steps', result)
        self.assertNotIn('planId', result)

    def test_release_resume_uses_external_state(self):
        sha = 'a' * 40
        with patch('publication.resume', return_value={'status': 'in_progress'}) as resume:
            self.assertEqual(self.command('release-resume', 'dsh-example', '7', sha),
                             {'status': 'in_progress'})
        state = Path(resume.call_args.args[4]).resolve()
        self.assertTrue(state.is_relative_to(self.state))
        self.assertFalse(state.is_relative_to(PACKAGE))
        self.assertEqual(resume.call_args.args[-2:], ('7', sha))

    def test_fresh_process_requires_explicit_config_for_projects(self):
        result = subprocess.run([sys.executable, '-B', str(PACKAGE / 'src/cli.py'), 'projects'],
                                cwd=self.root, capture_output=True, text=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('config', (result.stderr + result.stdout).lower())
        self.assertFalse((PACKAGE / 'config.json').exists())

    def test_fresh_process_runs_from_unrelated_directory(self):
        # Use the same approved interpreter; -B keeps the unpacked package immutable.
        result = subprocess.run(
            [sys.executable, '-B', str(PACKAGE / 'src/cli.py'),
             '--config', str(self.config_path), '--state-dir', str(self.state), 'projects'],
            cwd=self.root, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {'projects': ['dsh-example']})


if __name__ == '__main__':
    unittest.main()
