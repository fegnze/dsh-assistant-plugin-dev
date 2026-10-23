"""Create a registered plugin skeleton; the caller Agent then implements and delivers it."""
import json
from pathlib import Path
import re

import npm_name
import openspec_workflow
import settings

NAME = re.compile(r'dsh-[a-z0-9]+(?:-[a-z0-9]+)*')
DSH_VERSION = '0.2.1-rc.2'


def files(name, owner, description, npm_package=None):
    """Return a scaffold whose runtime identity remains the project slug.

    npm_package is deliberately separate from name: directory, repository, routes,
    OpenSpec targets and bundle ids use the unscoped slug, while npm-facing metadata
    may use the configured scope.
    """
    npm_package = npm_package or name
    route = f'/{name}/api'
    repo = f'https://github.com/{owner}/{name}'
    package = {
        'name': npm_package, 'version': '0.1.0', 'license': 'MIT', 'author': owner, 'icon': './icon.svg',
        'keywords': ['dsh-plugin', 'deepseek-harness'],
        'repository': {'type': 'git', 'url': f'git+{repo}.git'},
        'homepage': f'{repo}#readme', 'bugs': {'url': f'{repo}/issues'},
        'publishConfig': {'access': 'public', 'registry': 'https://registry.npmjs.org/'},
        'type': 'module', 'description': description,
        'exports': {'.': './src/host.mjs', './client': './src/client.js', './package.json': './package.json',
                    './locale/*.json': './locale/*.json', './icon': './icon.svg'},
        'files': ['src', 'locale', 'icon.svg', 'cordis.patch.yml', 'README.md', 'docs/zh.md'],
        'peerDependencies': {'@deepseek-ai/dsh-app-boot': DSH_VERSION},
        'peerDependenciesMeta': {'@deepseek-ai/dsh-app-boot': {'optional': True}},
        'engines': {'node': '>=22', 'dsh': DSH_VERSION},
        'dsh': {'manifestVersion': 1, 'bundle': {'patch': './cordis.patch.yml'},
                'client': {'platform': 'web', 'inject': ['@deepseek-ai/dsh-client-ui-slots']}},
        'scripts': {'test': 'node --test test/*.test.mjs'},
    }
    return {
        'package.json': json.dumps(package, ensure_ascii=False, indent=2) + '\n',
        'cordis.patch.yml': f'- insert:\n    - id: {name}\n      name: {json.dumps(npm_package)}\n',
        '.gitignore': 'node_modules/\n*.tgz\n.DS_Store\n',
        'LICENSE': LICENSE.replace('{owner}', owner),
        'README.md': f'# {name}\n\nEnglish | [中文](<docs/zh.md>)\n\n{description}\n\n'
                     f'Community DSH desktop plugin, compatible with DSH {DSH_VERSION}.\n',
        'docs/zh.md': f'# {name}\n\n[English](<../README.md>) | 中文\n\n{description}\n\n'
                      f'社区 DSH desktop 插件，兼容 DSH {DSH_VERSION}。\n',
        'src/host.mjs': HOST.replace('{route}', route).replace('{name}', name),
        'src/client.js': CLIENT.replace('{name}', npm_package),
        'test/host.test.mjs': TEST.replace('{name}', name),
        '.github/workflows/publish.yml': WORKFLOW,
        'locale/en.json': json.dumps({'meta': {'title': name, 'description': description}}, ensure_ascii=False) + '\n',
        'locale/zh.json': json.dumps({'meta': {'title': name, 'description': description}}, ensure_ascii=False) + '\n',
    }


def create(workspace, config_path, name, owner, description):
    if not NAME.fullmatch(name):
        raise ValueError('Plugin name must use dsh-* lower-kebab naming')
    if not description or '\n' in description or len(description) > 200:
        raise ValueError('Description must be one line of at most 200 characters')
    observed = settings.read(config_path)
    config = observed['config']
    if settings.validate(config_path, config)['workspace'] != str(workspace.resolve()):
        raise ValueError('Configuration workspace changed; preview again')
    target = workspace / 'dsh-plugins' / name
    if (workspace / 'dsh-plugins').is_symlink() or target.is_symlink():
        raise ValueError('Project directories must not be symlinks')
    if name in config['projects'] or target.exists():
        raise ValueError('Project already registered or directory exists')
    change_name = f'{name}-first-delivery'
    root = workspace / 'openspec'
    change = root / 'changes' / change_name
    # Check before creating either the plugin or workflow assets. Native new
    # change also refuses collisions, including a concurrent creation.
    if change.exists() or change.is_symlink():
        raise ValueError(f'OpenSpec change already exists: {change_name}')
    if root.is_symlink() or (root / 'changes').is_symlink():
        raise ValueError('Workspace OpenSpec root and changes must not be symlinks')
    # Creating a new project requires an unused public npm name, regardless of
    # who owns any existing package. Fail before any workflow or file writes.
    npm_account = config.get('npmAccount', owner)
    npm_package = f'@{npm_account}/{name}'
    npm_name.require_available(npm_package)
    openspec_workflow.initialize(workspace, 'PROJECT')
    openspec_workflow.require_local_root(workspace)
    openspec_workflow.run(workspace, ['new', 'change', change_name])
    # Retain the schema and all other metadata selected by the native CLI.
    metadata = change / '.openspec.yaml'
    with metadata.open('a') as stream:
        stream.write('\naffected_areas: ' + json.dumps([f'dsh-plugins/{name}']) + '\n')
    (change / 'proposal.md').write_text(
        f'## Why\n交付 {name}：{description}\n\n## What Changes\n'
        f'目标：`dsh-plugins/{name}`。实施前补充具体功能与验收场景。\n\n'
        '## Capabilities\n\n### New Capabilities\n实施前填写真实新能力及路径，通过原生 specs 指令生成对应 delta。\n\n'
        '### Modified Capabilities\n如修改既有要求，使用主 specs 的准确路径与完整 requirement；无规范变化才设置 skip_specs。\n\n## Impact\n'
        '明确交付范围：本地使用、源码同步或发布；仅按主人授权包含相应任务。'
        '若范围包含首次公开交付，列全独立仓库建立与核验、提交推送、npm 发布及核验；授权未满足保留待办，不自动认证。\n\n'
        '## Acceptance\n实现功能、适用测试与真实宿主验收；核对独立仓库、远端提交和导出树、npm 精确版本与包字节。'
        '由原生 OPSX 控制流程与归档；归档后修改新建小提案，不重开归档，不默认重复首发任务。\n')
    (change / 'tasks.md').write_text(
        f'## 首次交付：{name}\n\n目标：`dsh-plugins/{name}`。\n\n'
        '由原生 OPSX 推进，以下为交付任务而非固定命令顺序；guide 查询规范，inspect 提供工程事实，复用仍有效的上下文。\n\n'
        '- [ ] 明确功能与验收，按需查询 guide / inspect，使用 remote / registry / npm-bootstrap-plan 核实身份与授权需求\n'
        '- [ ] 通过原生 instructions specs/design 完成真实行为 delta 与适用设计；确认 status artifactPaths.specs 与 apply contextFiles 可发现 delta，不伪造无变化规范或空设计\n'
        '- [ ] 按真实 DSH Inspect 实现功能，完成图标与双语文档\n'
        '- [ ] 审查脚本后运行 validate，并完成适用 Host/UI 验收，说明未覆盖项\n'
        '- [ ] 使用 commit-plan / commit 保存工程，单独提交注册配置与工作区 OpenSpec\n'
        '- [ ] 获准公开后 create-repo，核验独立仓库归属与权限；使用 sync-plan / sync 推送，核对远端 SHA 与导出树\n'
        '- [ ] 按会话确认规则执行 npm-bootstrap-plan / npm-bootstrap、release / release-resume，核验 npm 精确版本与真实包字节；未获授权保留待办\n')
    for rel, text in files(name, owner, description, npm_package).items():
        path = target / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    config['projects'][name] = {'path': f'dsh-plugins/{name}', 'repository': f'{owner}/{name}'}
    # A concurrent configuration edit is never overwritten. A failed save leaves
    # the generated project visible for explicit recovery rather than deleting it.
    settings.save(config_path, observed['revision'], config)
    return {'project': name, 'path': str(target), 'next': [
        'Draw icon.svg per 插件图标视觉规范（必读）; inspect reports it missing until then.',
        f'Review workspace openspec/changes/{change_name} proposal/specs/design/tasks through native OPSX. Fill Capabilities, read native instructions, and verify delta discovery in status/apply before implementation. No skip_design marker exists; do not invent empty designs. After archive, create a new small change for later work; never reopen the archive or repeat first delivery by default.',
        'Implement src/ against the live DSH Inspect contracts; replace the placeholder README/docs.',
        'Commit the config.json registration separately; devkit commit only covers the plugin directory.',
        'Use devkit tools as needed by the proposal: validate, commit-plan/commit, create-repo, sync-plan/sync, npm-bootstrap-plan/npm-bootstrap, release/release-resume; pending authorization remains unfinished work.']}


LICENSE = '''MIT License

Copyright (c) 2026 {owner}

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
'''

HOST = '''/** Host half. Read live contracts through DSH Inspect before adding services. */
export const inject = ['webServer'];

const ROUTE = '{route}';
const HEADER = 'x-{name}';

/** Loopback, same-origin, custom-header-gated request check. */
export function trusted(req) {
  if (!['127.0.0.1', '::1', '::ffff:127.0.0.1'].includes(req.socket?.remoteAddress)) return false;
  try {
    const host = new URL(`http://${req.headers.host}`);
    return ['127.0.0.1', 'localhost', '[::1]'].includes(host.hostname)
      && (!req.headers.origin || new URL(req.headers.origin).host === host.host)
      && (!req.headers['sec-fetch-site'] || req.headers['sec-fetch-site'] === 'same-origin')
      && req.headers[HEADER] === '1';
  } catch {
    return false;
  }
}

export function apply(ctx) {
  ctx.effect(() => ctx.webServer.register({ kind: 'exact', path: ROUTE, handler: async (req, res) => {
    res.setHeader('Content-Type', 'application/json; charset=utf-8');
    res.setHeader('Cache-Control', 'no-store');
    if (!trusted(req)) { res.statusCode = 403; res.end('{}'); return; }
    res.end('{}');
  } }));
}
'''

CLIENT = '''window.__ModuleLoader__.load({ id: '{name}', factory: require => {
  const React = require('react');
  function apply(ctx) {
    // Register Slot occupants here; inspect live Slot trees before choosing ids and priorities.
    void React; void ctx;
  }
  return { inject: ['slots'], apply };
} });
'''

TEST = '''import { test } from 'node:test';
import assert from 'node:assert/strict';
import { trusted } from '../src/host.mjs';

const req = (headers, remoteAddress = '127.0.0.1') => ({ socket: { remoteAddress }, headers });

test('host route accepts only loopback same-origin requests with the plugin header', () => {
  assert.equal(trusted(req({ host: '127.0.0.1:19387', 'x-{name}': '1' })), true);
  assert.equal(trusted(req({ host: '127.0.0.1:19387' })), false);
  assert.equal(trusted(req({ host: '127.0.0.1:19387', 'x-{name}': '1' }, '10.0.0.2')), false);
});
'''

WORKFLOW = '''name: Publish npm
on:
  workflow_dispatch:
    inputs:
      expected_sha:
        description: Reviewed commit SHA
        required: true
        type: string
      dry_run:
        description: Validate without publishing
        type: boolean
        default: true
permissions:
  contents: read
concurrency:
  group: npm-publish
  cancel-in-progress: false
jobs:
  publish:
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    permissions:
      contents: read
      id-token: write
    steps:
      - name: Verify reviewed commit
        env:
          EXPECTED_SHA: ${{ inputs.expected_sha }}
        run: test "$GITHUB_SHA" = "$EXPECTED_SHA"
      - uses: actions/checkout@v4
        with:
          persist-credentials: false
      - uses: actions/setup-node@v4
        with:
          node-version: '24'
          registry-url: https://registry.npmjs.org
      - run: npm install --global npm@11.11.0
      - run: npm test
      - run: for f in src/*.js src/*.mjs; do node --check "$f"; done
      - name: Check package payload
        run: npm pack --dry-run --ignore-scripts
      - name: Publish with OIDC provenance
        if: inputs.dry_run == false
        run: npm publish --access public --provenance --ignore-scripts
'''
