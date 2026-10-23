from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import delivery as d


class DeliveryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        self.project = self.repo / 'dsh-test'
        self.project.mkdir()
        d.git(self.repo, 'init')
        d.git(self.repo, 'config', 'user.email', 'test@example.invalid')
        d.git(self.repo, 'config', 'user.name', 'Test')
        (self.project / 'a').write_text('first')
        (self.repo / 'outside').write_text('first')
        d.git(self.repo, 'add', '.')
        d.git(self.repo, 'commit', '-m', 'initial')

    def tearDown(self):
        self.tmp.cleanup()

    def test_content_changes_invalidate(self):
        before = d.snapshot(self.project)
        (self.project / 'a').write_text('second')
        after = d.snapshot(self.project)
        self.assertNotEqual(before['baseline'], after['baseline'])
        with self.assertRaisesRegex(ValueError, 'Stale'):
            d.commit(self.project, before['baseline'], 'test')

    def test_staged_work_refused(self):
        (self.repo / 'outside').write_text('other')
        d.git(self.repo, 'add', 'outside')
        with self.assertRaisesRegex(ValueError, 'Index'):
            d.snapshot(self.project)

    def test_exact_scope(self):
        (self.repo / 'outside').write_text('unrelated')
        (self.project / 'a').write_text('second')
        state = d.snapshot(self.project)
        result = d.commit(self.project, state['baseline'], '[fix] test: 范围提交')
        self.assertEqual(result['status'], 'committed')
        self.assertEqual(d.git(self.repo, 'show', '--format=', '--name-only', 'HEAD').decode().strip(), 'dsh-test/a')
        self.assertIn(b'outside', d.git(self.repo, 'status', '--porcelain'))

    def test_commit_sets_hook_marker(self):
        hook = self.repo / '.git/hooks/pre-commit'
        hook.write_text(f'#!/bin/sh\n[ "${d.COMMIT_MARKER}" = 1 ] || exit 1\n')
        hook.chmod(0o755)
        (self.project / 'a').write_text('second')
        state = d.snapshot(self.project)
        self.assertEqual(d.commit(self.project, state['baseline'], '[fix] test: 标记')['status'], 'committed')

    def test_co_author_is_optional_and_explicit(self):
        (self.project / 'a').write_text('without trailer')
        d.commit(self.project, d.snapshot(self.project)['baseline'], '[fix] test: local')
        self.assertNotIn(b'Co-Authored-By:', d.git(self.repo, 'log', '-1', '--format=%B'))
        (self.project / 'a').write_text('with trailer')
        d.commit(self.project, d.snapshot(self.project)['baseline'], '[fix] test: configured',
                 co_author='Example <example@example.invalid>')
        self.assertIn(b'Co-Authored-By: Example <example@example.invalid>',
                      d.git(self.repo, 'log', '-1', '--format=%B'))

    def test_compatibility_workspace_is_not_used_for_sdk_discovery(self):
        (self.project / 'a').write_text('second')
        result = d.commit(self.project, d.snapshot(self.project)['baseline'],
                          '[fix] test: portable', self.repo / 'nonexistent-workspace')
        self.assertEqual(result['status'], 'committed')
        self.assertFalse((self.repo / 'nonexistent-workspace').exists())

    def test_invalid_co_author_never_stages_files(self):
        (self.project / 'a').write_text('second')
        baseline = d.snapshot(self.project)['baseline']
        with self.assertRaisesRegex(ValueError, 'co-author'):
            d.commit(self.project, baseline, '[fix] test: reject', co_author='User\nInjected trailer')
        self.assertFalse(d.git(self.repo, 'diff', '--cached', '--name-only'))

    def test_symlink_refused(self):
        (self.project / 'link').symlink_to(self.repo / 'outside')
        with self.assertRaisesRegex(ValueError, 'Symlink'):
            d.snapshot(self.project)


if __name__ == '__main__':
    unittest.main()
