from pathlib import Path
import json
import tempfile
import sys
import unittest
from unittest.mock import patch, MagicMock
import urllib.request
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import bootstrap as b
import publication as p

C = {'githubOwner': 'o', 'npmAccount': 'o', 'registry': 'https://registry.npmjs.org/', 'branch': 'main', 'workflow': 'publish.yml'}
E = {'repository': 'o/dsh-x'}


class NpmRunnerTest(unittest.TestCase):
    def test_uses_installed_npm_without_download_wrapper(self):
        self.assertEqual(b.NPM, [])

    def run_npm(self, script, code=0):
        """Run b.npm against a real child on a real PTY that prints `script`."""
        opened = []
        command = [sys.executable, '-B', '-c', f'import sys; sys.stdout.write({script!r}); sys.stdout.flush(); sys.exit({code})']
        real = b.subprocess.Popen
        with patch.object(b, 'NPM', []), patch.object(b, 'subprocess', wraps=b.subprocess) as sp:
            sp.Popen = lambda cmd, **kw: real(command, **kw)
            try:
                out = b.npm(['login'], Path('.'), Path('rc'), C['registry'], opened.append, lambda _: None, timeout=30)
            except ValueError as error:
                return opened, error
        return opened, out

    def test_child_sees_a_terminal(self):
        command = [sys.executable, '-B', '-c', 'import sys; print(sys.stdin.isatty() and sys.stdout.isatty())']
        real = b.subprocess.Popen
        with patch.object(b, 'NPM', []), patch.object(b, 'subprocess', wraps=b.subprocess) as sp:
            sp.Popen = lambda cmd, **kw: real(command, **kw)
            self.assertIn('True', b.npm(['x'], Path('.'), Path('rc'), C['registry'], print, print, timeout=30))

    def test_opens_auth_pages_once_and_redacts_tokens(self):
        url = 'https://www.npmjs.com/login?next=/login/cli/abc'
        opened, _ = self.run_npm(f'Login at:\n{url}\n{url}\n')
        self.assertEqual(opened, [url])
        opened, error = self.run_npm('token npm_' + 'a' * 30 + '\n', code=1)
        self.assertIsInstance(error, ValueError)
        self.assertNotIn('npm_aaaa', str(error))

    def test_ignores_non_auth_links(self):
        opened, _ = self.run_npm('see https://www.npmjs.com/package/x\n')
        self.assertEqual(opened, [])


class BootstrapTest(unittest.TestCase):
    SHA = 'a' * 40
    STAGE = '0f1e2d3c-4b5a-6978-8a9b-0c1d2e3f4a5b'

    def run_bootstrap(self, registry='absent', account='o', pending=(), trusted=False, approve_errors=(), trust_error=None):
        calls, errors = [], list(approve_errors)
        def npm(args, cwd, userconfig, *rest, **kw):
            calls.append(' '.join(args[:2]))
            if args[0] == 'login':
                userconfig.write_text('//registry.npmjs.org/:_authToken=secret\n')
            if args[0] == 'whoami':
                return account + '\n'
            if args[:2] == ['stage', 'publish']:
                self.staged = json.loads((cwd / 'package.json').read_text())
                return f'+ dsh-x@1.0.0 staged as {self.STAGE}\n'
            if args[:2] == ['stage', 'list']:
                return json.dumps(list(pending))
            if args[:2] == ['stage', 'view']:
                return json.dumps({'id': self.STAGE, 'status': self.statuses.pop(0)})
            if args[:2] == ['stage', 'approve'] and errors:
                raise ValueError(errors.pop(0))
            if args[:2] == ['trust', 'github']:
                self.assertIn('--allow-publish', args)
                if trust_error:
                    raise ValueError(trust_error)
            if args[:2] == ['trust', 'list']:
                ok = trusted or 'trust github' in calls
                return json.dumps([{'repository': 'o/dsh-x', 'file': 'publish.yml'}] if ok else [])
            return ''
        def export(path, tree, target):
            self.assertEqual(tree, 'tree-id')
            target.mkdir()
            (target / 'package.json').write_text(json.dumps({'name': 'dsh-x', 'version': '1.0.0'}))
        logout = MagicMock()
        plan = {'action': 'unchanged', 'localTree': 'tree-id', 'remote': {'commit': self.SHA}}
        with patch('github.sync_plan', return_value=plan), patch.object(b, 'prepare_export', side_effect=export), \
                patch.object(b, 'state', return_value=registry), patch.object(b, 'npm', side_effect=npm), \
                patch.object(b, '_shasum', return_value='sum'), patch.object(b.subprocess, 'run', logout):
            result = b.bootstrap(Path('.'), {'name': 'dsh-x', 'version': '1.0.0'}, C, E, lambda _: None, lambda _: None,
                                 sleep=lambda _: None)
        return result, calls, logout

    def setUp(self):
        self.statuses = ['reviewing', 'ready']

    def test_stages_exact_tree_waits_review_approves_binds_and_logs_out(self):
        result, calls, logout = self.run_bootstrap()
        self.assertEqual(result['status'], 'published_package')
        self.assertEqual(result['trustedPublisher'], 'pending_validation')
        self.assertEqual(result['steps'], ['login', 'staged', 'approved', 'trusted_publisher_bound'])
        for guidance in ('real OIDC publish', 'within 2 days', 'explicit owner authorization',
                         'never auto-bump', 'already_published', 'dry-run', 'no provenance'):
            self.assertIn(guidance, result['next'])
        self.assertNotIn('trust list', calls)
        self.assertEqual(calls, ['login --auth-type=web', 'whoami', 'stage list', 'stage publish', 'stage view', 'stage view',
                                 'stage approve', 'trust github'])
        auth = [c for c in calls if c.split()[0] in ('login', 'trust') or c == 'stage approve']
        self.assertEqual(len(auth), len(b.confirmations('absent')))
        self.assertEqual(self.staged['version'], '1.0.0')
        self.assertIn('logout', logout.call_args[0][0])

    def test_resumes_existing_stage_without_restaging(self):
        row = {'id': self.STAGE, 'packageName': 'dsh-x', 'version': '1.0.0', 'shasum': 'sum'}
        _, calls, _ = self.run_bootstrap(registry='placeholder', pending=[row])
        self.assertNotIn('stage publish', calls)
        self.assertIn('stage approve', calls)

    def test_public_404_still_resumes_private_stage(self):
        row = {'id': self.STAGE, 'packageName': 'dsh-x', 'version': '1.0.0', 'shasum': 'sum'}
        _, calls, _ = self.run_bootstrap(registry='absent', pending=[row])
        self.assertIn('stage list', calls)
        self.assertNotIn('stage publish', calls)
        self.assertIn('stage approve', calls)

    def test_refuses_stage_with_different_bytes(self):
        row = {'id': self.STAGE, 'packageName': 'dsh-x', 'version': '1.0.0', 'shasum': 'other'}
        with self.assertRaisesRegex(ValueError, 'differs'):
            self.run_bootstrap(registry='placeholder', pending=[row])

    def test_published_only_binds_trust_and_still_needs_validation(self):
        result, calls, _ = self.run_bootstrap(registry='published', trusted=True)
        self.assertEqual(calls, ['login --auth-type=web', 'whoami', 'trust github'])
        self.assertEqual(len(b.confirmations('published')), 2)
        self.assertEqual(result['status'], 'published_package')
        self.assertEqual(result['trustedPublisher'], 'pending_validation')
        self.assertEqual(result['steps'], ['login', 'trusted_publisher_bound'])

    def test_existing_binding_is_not_validation_or_a_fresh_deadline(self):
        result, calls, _ = self.run_bootstrap(registry='published', trust_error='Trust already exists')
        self.assertEqual(result['trustedPublisher'], 'pending_validation')
        self.assertIn('an existing binding may have less time', result['next'])
        self.assertEqual(calls.count('trust github'), 1)

    def test_trust_failure_does_not_report_pending_success(self):
        with self.assertRaisesRegex(ValueError, 'E403.*ask the owner'):
            self.run_bootstrap(registry='published', trust_error='E403 forbidden')

    def test_approval_is_never_retried(self):
        with self.assertRaisesRegex(ValueError, 'ask the owner'):
            self.run_bootstrap(approve_errors=["can't be approved yet because automated review hasn't finished"])
        self.statuses = ['reviewing', 'ready']
        with self.assertRaisesRegex(ValueError, 'E403'):
            self.run_bootstrap(approve_errors=['E403 forbidden'])

    def test_preview_opens_nothing(self):
        with patch('github.sync_plan', return_value={'action': 'unchanged', 'remote': {'commit': self.SHA}}), \
                patch.object(b, 'state', return_value='published'), patch.object(b, 'npm') as npm:
            r = b.preview(Path('.'), {'name': 'dsh-x', 'version': '1.0.0'}, C, E)
        npm.assert_not_called()
        self.assertEqual((r['status'], len(r['confirmations'])), ('ready', 2))

    def test_state_encodes_scoped_package_name(self):
        response = MagicMock()
        response.read.return_value = b'{"versions": {"1.0.0": {}}}'
        response.__enter__.return_value = response
        with patch('urllib.request.urlopen', return_value=response) as opened:
            self.assertEqual(b.state('@o/dsh-x', '1.0.0', 'https://registry.npmjs.org/'), 'published')
        self.assertEqual(opened.call_args.args[0], 'https://registry.npmjs.org/%40o%2Fdsh-x')

    def test_existing_releases_never_sign_in(self):
        result, calls, _ = self.run_bootstrap(registry='other')
        self.assertEqual((result['status'], calls), ('exists', []))

    def test_wrong_account_stops_before_publish(self):
        with self.assertRaisesRegex(ValueError, 'expected o'):
            self.run_bootstrap(account='someone')

    def test_stage_id_must_be_unique(self):
        self.assertEqual(b.find_stage(f'id {self.STAGE.upper()}', self.STAGE), self.STAGE)
        with self.assertRaises(ValueError):
            b.find_stage('nothing')
        with self.assertRaises(ValueError):
            b.find_stage(self.STAGE, '11111111-2222-3333-4444-555555555555')

    def test_prepare_export_runs_project_test_and_checks_generated_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'out'
            manifest = {'name': 'dsh-x', 'version': '1.0.0',
                        'scripts': {'test': 'npm test'},
                        'exports': {'.': './lib/client.js', './package.json': './package.json'}}
            def make_export(path, tree, destination):
                destination.mkdir()
                (destination / 'package.json').write_text(json.dumps(manifest))
            calls = []
            def run(args, **kwargs):
                calls.append(args)
                if args[-2:] == ['npm', 'test']:
                    (target / 'lib').mkdir()
                    (target / 'lib/client.js').write_text('generated')
                    return MagicMock(returncode=0, stdout='', stderr='')
                return MagicMock(returncode=0, stdout=json.dumps([{'files': [
                    {'path': 'package.json'}, {'path': 'lib/client.js'}]}]), stderr='')
            with patch.object(b, 'export', side_effect=make_export), patch.object(b, 'NPM', []), \
                    patch.object(b.subprocess, 'run', side_effect=run):
                packed = b.prepare_export(Path('.'), 'tree-id', target)
            self.assertIn('lib/client.js', packed)
            self.assertEqual(calls[0][-2:], ['npm', 'test'])

    def test_prepare_export_installs_locked_dependencies_without_scripts(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'out'
            def make_export(path, tree, destination):
                destination.mkdir()
                (destination / 'package.json').write_text(json.dumps({
                    'scripts': {'test': 'node --test'}, 'dependencies': {'zod': '4.4.3'}}))
                (destination / 'package-lock.json').write_text('{}')
            calls = []
            def run(args, **kwargs):
                calls.append(args)
                return MagicMock(returncode=0, stdout='[{"files": []}]', stderr='')
            with patch.object(b, 'export', side_effect=make_export), patch.object(b, 'NPM', []), \
                    patch.object(b.subprocess, 'run', side_effect=run):
                b.prepare_export(Path('.'), 'tree', target)
            self.assertEqual(calls[0], ['npm', 'ci', '--ignore-scripts'])
            self.assertEqual(calls[1], ['npm', 'test'])

    def test_prepare_export_rejects_missing_required_export_before_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'out'
            manifest = {'name': 'dsh-x', 'version': '1.0.0',
                        'scripts': {'test': 'npm test'},
                        'exports': {'.': './lib/client.js'}}
            def make_export(path, tree, destination):
                destination.mkdir()
                (destination / 'package.json').write_text(json.dumps(manifest))
            def run(args, **kwargs):
                return MagicMock(returncode=0, stdout=json.dumps([{'files': [
                    {'path': 'package.json'}]}]), stderr='')
            with patch.object(b, 'export', side_effect=make_export), patch.object(b, 'NPM', []), \
                    patch.object(b.subprocess, 'run', side_effect=run):
                with self.assertRaisesRegex(ValueError, 'missing required export'):
                    b.prepare_export(Path('.'), 'tree-id', target)

    def test_export_uses_committed_tree_not_working_tree(self):
        import subprocess, tempfile
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / 'r'
            (repo / 'pkg').mkdir(parents=True)
            git = lambda *a: subprocess.run(['git', *a], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()
            git('init', '-q'); git('config', 'user.email', 't@x.invalid'); git('config', 'user.name', 'T')
            (repo / 'pkg/f').write_text('committed')
            git('add', '.'); git('commit', '-qm', 'c')
            tree = git('rev-parse', 'HEAD:pkg')
            (repo / 'pkg/f').write_text('dirty')
            b.export(repo / 'pkg', tree, Path(tmp) / 'out')
            self.assertEqual((Path(tmp) / 'out/f').read_text(), 'committed')


class NpmTimeoutTest(unittest.TestCase):
    def test_denied_group_signal_falls_back_to_owned_child(self):
        proc = MagicMock(pid=123)
        proc.poll.return_value = None
        with patch.object(b.subprocess, 'Popen', return_value=proc), \
                patch('os.killpg', side_effect=PermissionError('denied')), \
                patch.object(b.time, 'monotonic', side_effect=[0, 2]):
            with self.assertRaisesRegex(ValueError, 'timed out'):
                b.npm(['x'], Path('.'), Path('rc'), C['registry'], print, print, timeout=1)
        proc.kill.assert_called_once_with()
        proc.wait.assert_called_once_with()

    def test_timeout_kills_process_group(self):
        import os, time as t
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        marker = Path(temporary.name) / 'pid'
        code = f"import subprocess,sys,time; p=subprocess.Popen([sys.executable,'-B','-c','import time; time.sleep(60)']); open({str(marker)!r},'w').write(str(p.pid)); time.sleep(60)"
        real = b.subprocess.Popen
        with patch.object(b, 'NPM', []), patch.object(b, 'subprocess', wraps=b.subprocess) as sp:
            sp.Popen = lambda cmd, **kw: real([sys.executable, '-B', '-c', code], **kw)
            with self.assertRaisesRegex(ValueError, 'timed out'):
                b.npm(['x'], Path('.'), Path('rc'), C['registry'], print, print, timeout=2)
        t.sleep(0.5)
        import subprocess
        alive = subprocess.run(['ps', '-o', 'stat=', '-p', marker.read_text()], capture_output=True, text=True).stdout.strip()
        self.assertIn(alive[:1], ('', 'Z'))  # gone, or a zombie awaiting init; never still running


class FollowRunTest(unittest.TestCase):
    def test_find_run_requires_single_match(self):
        with patch.object(p, 'gh', return_value=json.dumps({'workflow_runs': [{'id': 7}]})):
            self.assertEqual(p.find_run(Path('.'), 'o/dsh-x', 'publish.yml', 'sha', 't', sleep=lambda _: None), '7')
        with patch.object(p, 'gh', return_value=json.dumps({'workflow_runs': [{'id': 7}, {'id': 8}]})):
            with self.assertRaises(ValueError):
                p.find_run(Path('.'), 'o/dsh-x', 'publish.yml', 'sha', 't', sleep=lambda _: None)
        with patch.object(p, 'gh', return_value=json.dumps({'workflow_runs': []})):
            self.assertIsNone(p.find_run(Path('.'), 'o/dsh-x', 'publish.yml', 'sha', 't', attempts=2, sleep=lambda _: None))

    def test_watch_polls_until_verified(self):
        states = iter([{'status': 'in_progress'}, {'status': 'waiting_registry'}, {'status': 'verified'}])
        with patch.object(p, 'resume', side_effect=lambda *a: next(states)):
            self.assertEqual(p.watch(Path('.'), {}, C, E, Path('.'), '7', 'sha', sleep=lambda _: None)['status'], 'verified')


if __name__ == '__main__':
    unittest.main()
