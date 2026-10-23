"""Real npm regression evidence; opt in with DSH_TEST_NPM_ROOT=/path/to/npm.

No registry publication, project lifecycle scripts, or network access is needed.
The selected npm installation supplies both its CLI and package-json normalizer.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import documentation as docs

NPM_ROOT = os.environ.get('DSH_TEST_NPM_ROOT')


@unittest.skipUnless(NPM_ROOT, 'Set DSH_TEST_NPM_ROOT to test an actual npm installation')
class NpmReadmeSelectionTest(unittest.TestCase):
    def test_selection_and_tarball_manifest(self):
        npm = Path(NPM_ROOT).resolve()
        cli = npm / 'bin/npm-cli.js'
        normalizer = npm / 'node_modules/@npmcli/package-json'
        english = '# English\n[简体中文](./docs/zh.md)\nEnglish documentation.\n'
        chinese = '# 中文\n[English](../README.md)\n中文说明。\n'
        with tempfile.TemporaryDirectory(prefix='devkit-npm-readme-') as temporary:
            root = Path(temporary)
            for strategy in ('root-bilingual', 'explicit-readme', 'nested-zh'):
                with self.subTest(strategy=strategy):
                    project = root / strategy
                    project.mkdir()
                    zh_path = 'docs/zh.md' if strategy == 'nested-zh' else 'README.zh.md'
                    package = {'name': 'dsh-readme-selection-test', 'version': '1.0.0',
                               'files': ['README.md', zh_path]}
                    if strategy == 'explicit-readme':
                        package.update(readme=english, readmeFilename='README.md')
                    manifest = (json.dumps(package, ensure_ascii=False, indent=2) + '\n').encode()
                    (project / 'package.json').write_bytes(manifest)
                    (project / 'README.md').write_text(english, encoding='utf-8')
                    (project / zh_path).parent.mkdir(parents=True, exist_ok=True)
                    (project / zh_path).write_text(chinese, encoding='utf-8')
                    # Exactly the directory-publish manifest preparation used by npm 11.
                    script = ('const P=require(process.argv[1]);'
                              '(async()=>{const p=await P.fix(process.argv[2]);'
                              'console.log(JSON.stringify((await p.prepare()).content))})()'
                              '.catch(e=>{console.error(e);process.exitCode=1})')
                    prepared = json.loads(subprocess.run(
                        ['node', '-e', script, str(normalizer), str(project)],
                        check=True, capture_output=True, text=True, timeout=30).stdout)
                    if strategy == 'root-bilingual':
                        # npm does not promise English-first for competing root READMEs.
                        self.assertIn(prepared['readme'], (english, chinese))
                    else:
                        self.assertEqual(prepared['readme'], english)
                        self.assertEqual(prepared['readmeFilename'], 'README.md')
                    packed = json.loads(subprocess.run(
                        ['node', str(cli), 'pack', '--json', '--ignore-scripts'], cwd=project,
                        check=True, capture_output=True, text=True, timeout=60).stdout)[0]
                    self.assertEqual({f['path'] for f in packed['files']},
                                     {'package.json', 'README.md', zh_path})
                    if strategy == 'nested-zh':
                        docs.require(project, {f['path'] for f in packed['files']})
                    else:
                        with self.assertRaises(ValueError):
                            docs.require(project)
                    with tarfile.open(project / packed['filename'], 'r:gz') as archive:
                        actual = archive.extractfile('package/package.json').read()
                        self.assertEqual(actual, manifest)
                        self.assertEqual(archive.extractfile('package/README.md').read(), english.encode())
                        self.assertEqual(archive.extractfile('package/' + zh_path).read(), chinese.encode())
                    self.assertEqual('readme' in json.loads(actual), strategy == 'explicit-readme')
                    # Loopback plus --force avoids registry version lookups. The CLI's
                    # --dry-run prohibits libnpmpublish; --ignore-scripts blocks hooks.
                    subprocess.run(['node', str(cli), 'publish', '--dry-run', '--json',
                                    '--ignore-scripts', '--force', '--registry=http://127.0.0.1:9'],
                                   cwd=project, check=True, capture_output=True, timeout=60)
                    self.assertEqual((project / 'package.json').read_bytes(), manifest)
