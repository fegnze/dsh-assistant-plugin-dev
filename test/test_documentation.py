import json
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import documentation as docs
import cli
import publication
import validation

PACKAGE = Path(__file__).resolve().parents[1]


class DocumentationTest(unittest.TestCase):
    def test_packaged_templates_describe_scope_and_explicit_authorization(self):
        template = (PACKAGE / 'templates/openspec/schemas/dsh-devkit/templates/tasks.md').read_text()
        context = (PACKAGE / 'templates/openspec/config.yaml').read_text()
        for token in ('version-plan', 'version-bump', 'sync-plan', 'release', '包字节', '授权'):
            self.assertIn(token, template)
        self.assertIn('原生 OPSX', context)
        self.assertIn('范围', template)
        for obsolete in ('MySpace', 'Butler/tools/', '/Users/', '默认公开'):
            self.assertNotIn(obsolete, template + context)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name).resolve()
        self.root = self.workspace / 'dsh-test'
        self.root.mkdir()
        self.addCleanup(patch.stopall)
        patch('openspec_workflow.check', return_value={'checked': True}).start()
        self.english = '# Test\n[简体中文](./docs/zh.md)\n\nEnglish instructions.\n'
        self.chinese = '# 测试\n[English](../README.md)\n\n中文说明。\n'
        (self.root / 'docs').mkdir()
        (self.root / 'package.json').write_text('{}')
        (self.root / 'README.md').write_text(self.english)
        (self.root / 'docs/zh.md').write_text(self.chinese)

    def packed(self, names=docs.README_FILES):
        return SimpleNamespace(returncode=0, stdout=json.dumps([{'files': [{'path': n} for n in names]}]))

    def test_valid_and_human_review(self):
        self.assertEqual(docs.issues(self.root), [])
        self.assertIn('Human review', docs.require(self.root)['review'])
        self.assertEqual(cli.invoke('guide', {})['readmePolicy']['files'], list(docs.README_FILES))

    def test_missing_each_document(self):
        read_text = Path.read_text
        for name in docs.README_FILES:
            def read(path, *args, **kwargs):
                if path == self.root / name:
                    raise FileNotFoundError
                return read_text(path, *args, **kwargs)
            with self.subTest(name=name), patch.object(Path, 'read_text', read):
                problems = docs.issues(self.root)
                self.assertEqual(len(problems), 1)
                self.assertIn(name, problems[0])
                with self.assertRaises(ValueError):
                    docs.require(self.root)

    def test_competing_root_readmes_rejected(self):
        for name in ('README.zh.md', 'README', 'readme.txt', 'ReadMe.markdown', 'README.MD'):
            with self.subTest(name=name), patch.object(Path, 'iterdir', return_value=[
                    self.root / 'README.md', self.root / name]):
                self.assertTrue(any('Competing root README' in p for p in docs.issues(self.root)))
        (self.root / 'docs' / 'README.md').write_text('Nested documentation')
        self.assertEqual(docs.issues(self.root), [])

    def test_stale_manifest_readme_fields_rejected_even_when_empty(self):
        for field in ('readme', 'readmeFilename'):
            for value in ('README.md', self.english, '', None):
                with self.subTest(field=field, value=value):
                    (self.root / 'package.json').write_text(json.dumps({field: value}))
                    with self.assertRaisesRegex(ValueError, field):
                        docs.require(self.root)

    def test_manifest_audit_fails_closed(self):
        for text in ('{', '[]'):
            with self.subTest(text=text):
                (self.root / 'package.json').write_text(text)
                with self.assertRaisesRegex(ValueError, 'package.json'):
                    docs.require(self.root)

    def test_chinese_backlink_resolves_from_docs(self):
        (self.root / 'docs/zh.md').write_text('# 中文\n[English](README.md)\n')
        with self.assertRaisesRegex(ValueError, r'must link to ../README.md'):
            docs.require(self.root)

    def test_competing_payload_readme_rejected(self):
        with self.assertRaisesRegex(ValueError, 'npm payload has competing'):
            docs.require(self.root, {*docs.README_FILES, 'readme.txt'})

    @unittest.skipUnless(shutil.which('node') and shutil.which('npm'),
                         'node and npm unavailable: real npm pack inventory not verified')
    def test_actual_npm_inventory(self):
        package = {'name': 'dsh-test', 'version': '1.0.0', 'files': list(docs.README_FILES)}
        (self.root / 'package.json').write_text(json.dumps(package))
        self.assertTrue(set(docs.README_FILES).issubset({row['path'] for row in docs.audit_pack(self.root)}))

    def test_missing_mutual_links(self):
        for name, original in [('README.md', self.english), ('docs/zh.md', self.chinese)]:
            with self.subTest(name=name):
                (self.root / name).write_text('# Documentation\nNo link\n')
                self.assertTrue(any(name + ' must link' in issue for issue in docs.issues(self.root)))
                (self.root / name).write_text(original)

    def test_link_must_be_top_navigation_not_example(self):
        for text in ['\n' * 10 + self.english, '<!--\n' + self.english + '\n-->',
                     '```md\n' + self.english + '```', '# Test\ndocs/zh.md',
                     '# Test\n![中文](docs/zh.md)']:
            with self.subTest(text=text):
                (self.root / 'README.md').write_text(text)
                self.assertTrue(docs.issues(self.root))

    def test_inspect_reports_documentation_without_packing(self):
        (self.root / 'package.json').write_text(json.dumps({'name': 'dsh-test', 'version': '1',
            'repository': 'https://github.com/owner/dsh-test', 'files': ['README.md'],
            'dsh': {'bundle': {'patch': 'patch.json'}}}))
        (self.root / 'docs/zh.md').write_text('')
        with patch.object(cli, 'project', return_value=({'workflow': 'publish.yml', 'workspace': str(self.workspace)}, self.root,
                         {'repository': 'owner/dsh-test'})), patch.object(cli, 'command', return_value=''), \
                patch('documentation.subprocess.run') as run:
            result = cli.inspect('dsh-test')
        self.assertTrue(any('docs/zh.md' in issue for issue in result['issues']))
        self.assertFalse(result['payloadChecked'])
        run.assert_not_called()

    def test_pack_exclusions_rejected(self):
        for missing in docs.README_FILES:
            with self.subTest(missing=missing), patch('documentation.subprocess.run',
                    return_value=self.packed([n for n in docs.README_FILES if n != missing])):
                with self.assertRaisesRegex(ValueError, 'npm payload missing'):
                    docs.audit_pack(self.root)

    def test_validate_checks_structure_before_scripts(self):
        (self.root / 'docs/zh.md').write_text('No backlink')
        with patch('validation.subprocess.run') as run:
            with self.assertRaisesRegex(ValueError, 'Validation failed'):
                validation.validate(self.root, self.workspace)
        run.assert_not_called()

    def test_validate_rejects_excluded_chinese_readme(self):
        with patch('validation.subprocess.run', side_effect=[SimpleNamespace(returncode=0),
                    self.packed(['README.md'])]):
            with self.assertRaisesRegex(ValueError, 'Validation failed'):
                validation.validate(self.root, self.workspace)

    def test_validate_bilingual_payload(self):
        with patch('validation.subprocess.run', side_effect=[SimpleNamespace(returncode=0), self.packed()]):
            result = validation.validate(self.root, self.workspace)
        self.assertEqual(result['status'], 'validated')
        self.assertEqual(set(result['payload']['sha256ByPath']), set(docs.README_FILES))

    def test_release_blocks_docs_or_payload_before_registry_and_dispatch(self):
        plan = {'action': 'unchanged', 'remote': {'commit': 'abc', 'canPush': True}}
        config = {'branch': 'main', 'githubOwner': 'owner', 'registry': 'https://registry.npmjs.org'}
        for invalid_docs in (False, True):
            with self.subTest(invalid_docs=invalid_docs):
                if invalid_docs:
                    (self.root / 'docs/zh.md').write_text('No backlink')
                with patch.object(publication, 'sync_plan', return_value=plan), \
                        patch.object(publication, 'verify') as verify, patch.object(publication, 'gh') as gh, \
                        patch('documentation.subprocess.run', return_value=self.packed(['README.md'])):
                    with self.assertRaises(ValueError):
                        publication.release(self.root, {'name': 'dsh-test', 'version': '1'}, config,
                                            {'repository': 'owner/dsh-test'}, self.root / '.state', 'abc')
                    verify.assert_not_called()
                    gh.assert_not_called()
                    self.assertFalse((self.root / '.state').exists())
