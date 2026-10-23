import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import openspec_workflow as w
import cli


class WorkflowFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()

    def tearDown(self):
        self.temp.cleanup()


class WorkflowTest(WorkflowFixture):
    def test_default_is_small_and_preserves_existing(self):
        state = w.initialize(self.root, 'dsh-test')
        self.assertTrue(state['managed'])
        config = self.root / 'openspec/config.yaml'
        config.write_text('schema: custom\n')
        self.assertEqual(w.initialize(self.root, 'dsh-test')['status'], 'existing')
        self.assertEqual(config.read_text(), 'schema: custom\n')
        text = (self.root / 'openspec/schemas/dsh-devkit/schema.yaml').read_text()
        import yaml
        schema = yaml.safe_load(text)
        artifacts = {a['id']: a for a in schema['artifacts']}
        self.assertEqual(set(artifacts), {'proposal', 'specs', 'design', 'tasks'})
        self.assertEqual(artifacts['specs']['generates'], 'specs/**/*.md')
        self.assertEqual(artifacts['specs']['requires'], ['proposal'])
        self.assertEqual(artifacts['design']['requires'], ['proposal'])
        self.assertEqual(artifacts['tasks']['requires'], ['specs', 'design'])
        self.assertEqual(schema['apply']['requires'], ['tasks'])

    def test_initialized_templates_match_packaged_resources(self):
        resources = Path(__file__).resolve().parents[1] / 'templates/openspec'
        self.assertEqual(w.TEMPLATES.resolve(), resources)
        expected = {path.relative_to(resources).as_posix(): path.read_text().replace('{{project}}', 'PROJECT')
                    for path in resources.rglob('*') if path.is_file()}
        self.assertTrue(expected)
        self.assertEqual(w.files(), expected)
        w.initialize(self.root, 'dsh-test')
        for rel, text in expected.items():
            self.assertEqual((self.root / 'openspec' / rel).read_text(), text, rel)

    def test_existing_symlink_never_overwritten(self):
        (self.root / 'openspec').symlink_to(self.root / 'missing')
        self.assertEqual(w.initialize(self.root, 'dsh-test')['status'], 'existing')
        self.assertFalse((self.root / 'missing').exists())

    def test_missing_is_advisory_not_automatic_migration(self):
        self.assertFalse(w.check(self.root)['checked'])
        self.assertFalse((self.root / 'openspec').exists())

    def test_archive_is_not_wrapped(self):
        w.initialize(self.root, 'dsh-test')
        self.assertFalse(hasattr(w, 'prepare_archive'))
        for args in (['archive', 'fix'], ['archive', 'fix', '--no-validate']):
            with patch.object(w, 'run') as run, patch.object(w, 'check') as check:
                with self.assertRaisesRegex(ValueError, 'native OPSX'):
                    w.execute(self.root, 'dsh-test', args)
                run.assert_not_called()
                check.assert_not_called()
        with self.assertRaisesRegex(ValueError, 'external store'):
            w.execute(self.root, 'dsh-test', ['list', '--store=other'])

    def test_cli_native_queries_do_not_inject_preflight(self):
        import io
        from contextlib import redirect_stdout
        project = self.root / 'dsh-plugins/dsh-test'
        project.mkdir(parents=True)
        (project / 'package.json').write_text('{"name":"dsh-test","version":"0.1.0"}')
        config = self.root / 'projects.json'
        config.write_text(json.dumps({
            'schemaVersion': 1, 'workspace': '.', 'githubOwner': 'owner', 'npmAccount': 'owner',
            'registry': 'https://registry.npmjs.org/', 'branch': 'main', 'workflow': 'publish.yml',
            'projects': {'dsh-test': {'path': 'dsh-plugins/dsh-test', 'repository': 'owner/dsh-test'}}}))
        for args in (['new', 'change', 'fix'], ['instructions', 'apply', '--change', 'fix'], ['instructions', '--json', '--change', 'fix', 'apply']):
            argv = ['cli.py', '--config', str(config), '--state-dir', str(self.root / 'state'),
                    'openspec', 'dsh-test', *args]
            with patch.object(cli, 'inspect', side_effect=AssertionError('unexpected inspect')), \
                    patch.object(w, 'execute', return_value={'state': 'ready'}) as execute, \
                    patch.object(sys, 'argv', argv), redirect_stdout(io.StringIO()) as out:
                cli.main()
                self.assertEqual(json.loads(out.getvalue()), {'state': 'ready'})
                self.assertEqual(execute.call_args.args[-1], args)
                self.assertEqual(execute.call_args.kwargs['target'], 'dsh-plugins/dsh-test')

    def test_templates_leave_workflow_to_opsx(self):
        templates = w.files()
        text = '\n'.join(templates.values())
        self.assertNotIn('inspect / plan', text)
        self.assertNotIn('先执行 devkit', text)
        self.assertNotIn('devkit openspec', text)
        for token in ('原生 OPSX', '不重开归档', '完整', 'create-repo', 'sync-plan / sync', 'npm-bootstrap', '包字节', '待办'):
            self.assertIn(token, text)


@unittest.skipUnless(shutil.which('openspec'), 'OpenSpec CLI unavailable: real integration not verified')
class RealOpenSpecTest(WorkflowFixture):
    def command(self, *args):
        return w.run(self.root, list(args))

    def change(self, name, skip=True):
        self.command('new', 'change', name, '--json')
        change = self.root / 'openspec/changes' / name
        (change / 'proposal.md').write_text('## Why\nFix a real issue.\n\n## What Changes\nCorrect behavior.\n\n## Impact\nLocal only.\n\n## Acceptance\nTests pass.\n')
        (change / 'tasks.md').write_text('- [x] Implement and verify\n')
        if skip:
            with (change / '.openspec.yaml').open('a') as f:
                f.write('\nskip_specs: true\n')
        return change

    def test_small_fix_and_native_archive(self):
        w.initialize(self.root, 'dsh-test')
        self.assertTrue(self.command('schema', 'validate', 'dsh-devkit', '--json')['valid'])
        self.change('small-fix')
        self.assertEqual(self.command('instructions', 'apply', '--change', 'small-fix', '--json')['state'], 'all_done')
        proof = w.check(self.root)
        self.assertTrue(proof['checked'])
        result = self.command('archive', 'small-fix', '--yes', '--json')
        self.assertEqual(result['archive']['change'], 'small-fix')
        self.assertFalse(result['archive']['specsUpdated'])
        self.assertFalse((self.root / 'openspec/changes/small-fix').exists())

    def test_feature_delta_and_first_release_guidance(self):
        w.initialize(self.root, 'dsh-test')
        change = self.change('new-feature', skip=False)
        spec = change / 'specs/feature/spec.md'
        spec.parent.mkdir(parents=True)
        spec.write_text('## ADDED Requirements\n\n### Requirement: New feature\nThe plugin SHALL expose its feature.\n\n#### Scenario: Usage\n- **WHEN** used\n- **THEN** it works\n')
        self.assertTrue(w.check(self.root)['checked'])
        apply = json.dumps(self.command('instructions', 'apply', '--change', 'new-feature', '--json'), ensure_ascii=False)
        archive = json.dumps(self.command('instructions', 'archive', '--change', 'new-feature', '--json'), ensure_ascii=False)
        for token in ['validate', 'commit-plan', 'inspect']:
            self.assertIn(token, apply)
        self.assertIn('待确认', archive)
        config = (self.root / 'openspec/config.yaml').read_text()
        for token in ['npm-bootstrap-plan', 'registry', 'remote', '授权']:
            self.assertIn(token, config)
        self.assertNotIn('{{project}}', config)

    def test_feature_delta_native_status_apply_and_sync_discovery(self):
        w.initialize(self.root, 'dsh-test')
        change = self.change('delta-lifecycle', skip=False)
        spec = change / 'specs/feature/spec.md'
        spec.parent.mkdir(parents=True)
        spec.write_text('## Purpose\n\nExpose a verifiable native feature whose specification survives discovery, apply and archive without a parallel registry.\n\n## ADDED Requirements\n\n### Requirement: Native feature\nThe plugin SHALL expose its feature.\n\n#### Scenario: Usage\n- **WHEN** used\n- **THEN** it works\n')
        (change / 'design.md').write_text('## Context\nNative service integration.\n\n## Decisions\nUse the official service rather than an independent registry.\n')
        status = self.command('status', '--change', 'delta-lifecycle', '--json')
        concrete = [str(spec)]
        # The native openspec-sync-specs workflow consumes precisely this field.
        self.assertEqual(status['artifactPaths']['specs']['existingOutputPaths'], concrete)
        self.assertEqual(status['artifactPaths']['design']['existingOutputPaths'], [str(change / 'design.md')])
        instructions = self.command('instructions', 'specs', '--change', 'delta-lifecycle', '--json')
        self.assertEqual(instructions['existingOutputPaths'], concrete)
        apply = self.command('instructions', 'apply', '--change', 'delta-lifecycle', '--json')
        self.assertEqual(apply['contextFiles']['specs'], concrete)
        self.assertEqual(apply['contextFiles']['design'], [str(change / 'design.md')])
        parsed = self.command('change', 'show', 'delta-lifecycle', '--json', '--deltas-only')
        self.assertTrue(parsed['deltas'])
        archived = self.command('archive', 'delta-lifecycle', '--yes', '--json')
        self.assertTrue(archived['archive']['specsUpdated'])
        self.assertIn('### Requirement: Native feature', (self.root / 'openspec/specs/feature/spec.md').read_text())

    def test_skip_specs_does_not_claim_design_is_skipped(self):
        w.initialize(self.root, 'dsh-test')
        change = self.change('skip-small-fix')
        status = self.command('status', '--change', 'skip-small-fix', '--json')
        artifacts = {a['id']: a for a in status['artifacts']}
        self.assertEqual(artifacts['specs']['status'], 'skipped')
        self.assertNotEqual(artifacts['design']['status'], 'skipped')
        self.assertFalse(status['isComplete'])
        self.assertEqual(status['artifactPaths']['specs']['existingOutputPaths'], [])
        self.assertFalse((change / 'specs').exists())
        specs = self.command('instructions', 'specs', '--change', 'skip-small-fix', '--json')
        self.assertTrue(specs['skipped'])
        tasks = self.command('instructions', 'tasks', '--change', 'skip-small-fix', '--json')
        self.assertFalse(next(d for d in tasks['dependencies'] if d['id'] == 'design')['done'])
        # Native apply requires only the existing tasks, not transitive dependencies.
        apply = self.command('instructions', 'apply', '--change', 'skip-small-fix', '--json')
        self.assertEqual(apply['state'], 'all_done')
        self.assertNotIn('specs', apply['contextFiles'])
        self.assertNotIn('design', apply['contextFiles'])

    def test_apply_is_blocked_before_artifacts(self):
        w.initialize(self.root, 'dsh-test')
        self.command('new', 'change', 'not-ready', '--json')
        result = self.command('instructions', 'apply', '--change', 'not-ready', '--json')
        self.assertEqual(result['state'], 'blocked')
        change = self.root / 'openspec/changes/not-ready'
        (change / 'tasks.md').write_text('- [x] Done without proposal\n')
        apply = self.command('instructions', 'apply', '--change', 'not-ready', '--json')
        self.assertEqual(apply['state'], 'all_done')
        status = self.command('status', '--change', 'not-ready', '--json')
        self.assertFalse(status['isComplete'])  # apply's direct gate is not full DAG completion

    def test_scoped_validation_and_new_change_after_native_archive(self):
        w.initialize(self.root, 'PROJECT')
        self.command('new', 'change', 'other-unfinished', '--json')
        first = self.root / 'openspec/changes/other-unfinished'
        w.bind_target(self.root, 'other-unfinished', 'dsh-plugins/dsh-other')
        self.change('local-fix')
        w.bind_target(self.root, 'local-fix', 'dsh-plugins/dsh-test')
        proof = w.check(self.root, target='dsh-plugins/dsh-test')
        self.assertEqual(proof['validatedChanges'], ['local-fix'])
        result = self.command('archive', 'local-fix', '--yes', '--json')
        self.assertEqual(result['archive']['change'], 'local-fix')
        archived = list((self.root / 'openspec/changes/archive').glob('*local-fix'))
        self.assertEqual(len(archived), 1)
        original = (archived[0] / 'tasks.md').read_bytes()
        self.change('follow-up')
        w.bind_target(self.root, 'follow-up', 'dsh-plugins/dsh-test')
        self.assertEqual(w.check(self.root, target='dsh-plugins/dsh-test')['validatedChanges'], ['follow-up'])
        self.assertEqual((archived[0] / 'tasks.md').read_bytes(), original)
        self.assertTrue(first.is_dir())

    def test_binding_and_exact_target_scope(self):
        w.initialize(self.root, 'PROJECT')
        result = w.execute(self.root, 'dsh-a', ['new', 'change', 'a-fix', '--json'], target='dsh-plugins/dsh-a')
        self.assertEqual(result['workspaceRoot'], str(self.root))
        self.assertEqual(w.metadata(self.root, 'a-fix')['affected_areas'], ['dsh-plugins/dsh-a'])
        with self.assertRaisesRegex(ValueError, 'must bind only'):
            w.require_target(self.root, 'a-fix', 'dsh-plugins/dsh-b')
        self.command('new', 'change', 'unassigned', '--json')
        with self.assertRaisesRegex(ValueError, 'must bind only'):
            w.require_target(self.root, 'unassigned', 'dsh-plugins/dsh-a')
        with (self.root / 'openspec/changes/unassigned/.openspec.yaml').open('a') as f:
            f.write('affected_areas: [dsh-plugins/dsh-a, dsh-plugins/dsh-b]\n')
        with self.assertRaisesRegex(ValueError, 'must bind only'):
            w.require_target(self.root, 'unassigned', 'dsh-plugins/dsh-a')

    def test_external_symlink_cannot_be_operated(self):
        other = self.root / 'outside'
        other.mkdir()
        w.initialize(other, 'dsh-other')
        registered = self.root / 'registered'
        registered.mkdir()
        (registered / 'openspec').symlink_to(other / 'openspec')
        with self.assertRaisesRegex(ValueError, 'symlink'):
            w.execute(registered, 'dsh-test', ['new', 'change', 'escape'])
        self.assertFalse((other / 'openspec/changes/escape').exists())


if __name__ == '__main__':
    unittest.main()
