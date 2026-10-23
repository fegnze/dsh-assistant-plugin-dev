"""Executable overrides stay explicit and argv-based, without download fallbacks."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import processes as p


class ProcessesTest(unittest.TestCase):
    def setUp(self):
        p.configure()
        self.addCleanup(p.configure)

    def test_run_uses_configured_executable_and_preserves_arguments(self):
        executable = str(Path(sys.executable).resolve())
        p.configure({'git': executable})
        with patch.object(p._subprocess, 'run') as run:
            p.subprocess.run(['git', 'status', '--', 'file with spaces'], cwd='.', timeout=3)
        run.assert_called_once_with([executable, 'status', '--', 'file with spaces'], cwd='.', timeout=3)

    def test_popen_uses_configured_executable(self):
        executable = str(Path(sys.executable).resolve())
        p.configure({'npm': executable})
        with patch.object(p._subprocess, 'Popen') as popen:
            p.subprocess.Popen(['npm', 'login'], stdin=10)
        popen.assert_called_once_with([executable, 'login'], stdin=10)

    def test_default_resolution_has_no_implicit_install_fallback(self):
        with patch.object(p.shutil, 'which', return_value=None), patch.object(p._subprocess, 'run') as run:
            with self.assertRaisesRegex(ValueError, 'unavailable'):
                p.subprocess.run(['openspec', '--version'])
        run.assert_not_called()

    def test_shell_strings_are_rejected(self):
        with patch.object(p._subprocess, 'run') as run, patch.object(p._subprocess, 'Popen') as popen:
            with self.assertRaises(ValueError):
                p.subprocess.run('echo unsafe', shell=True)
            with self.assertRaises(ValueError):
                p.subprocess.Popen('echo unsafe', shell=True)
        run.assert_not_called()
        popen.assert_not_called()

    def test_invalid_configuration_and_empty_argv_are_rejected(self):
        for value in ({'unknown': 'tool'}, {'git': './git'}, {'git': ''}, {'npm': ['npm']}, {'git': 'bad\x00path'}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                p.configure(value)
        for args in ([], (), 'git status'):
            with self.subTest(args=args), self.assertRaises(ValueError):
                p.argv(args)


if __name__ == '__main__':
    unittest.main()
