import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { definition, Config } from '../src/host.mjs';
import { createRunner, resources, HOST_ROOT } from '../src/host-runner.mjs';
import { operationArgv, tools } from '../src/host-tools.mjs';

function localFs() {
  const resolve = async p => ({ targetKey: path.resolve(p), displayPath: path.resolve(p) });
  return { resolve, processPath: t => t.displayPath, processPathFromHostPath: p => p,
    contains: (root, t) => t.targetKey === root.targetKey || t.targetKey.startsWith(root.targetKey + path.sep),
    async stat(t) { try { const s = await fs.stat(t.displayPath); return { type: s.isFile() ? 'file' : s.isDirectory() ? 'directory' : 'other', version: `${s.ino}:${s.ctimeMs}:${s.mtimeMs}:${s.size}`, size: s.size }; } catch (e) { if (e.code === 'ENOENT') return; throw e; } },
    async listDir(t) { return Promise.all((await fs.readdir(t.displayPath)).sort().map(async name => ({ name, target: await resolve(path.join(t.displayPath, name)) }))); },
    readText: t => fs.readFile(t.displayPath, 'utf8'),
    async readBytes(t, signal, max) { const value = await fs.readFile(t.displayPath); if (value.length > max) throw Error('size'); return value; },
  };
}
async function fixture(t, options = {}) {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'dsh-assistant-host-'));
  t.after(async () => { assert(root.startsWith(os.tmpdir()) && path.basename(root).startsWith('dsh-assistant-host-')); await fs.rm(root, { recursive: true, force: true }); });
  const configPath = path.join(root, 'config.json');
  await fs.writeFile(configPath, JSON.stringify({ schemaVersion: 1, workspace: root, githubOwner: 'owner', npmAccount: 'owner', branch: 'main', workflow: 'publish.yml', registry: 'https://registry.npmjs.org/', projects: {} }));
  const config = { pythonExecutable: '/configured/python', configPath, stateDir: path.join(root, 'releases') };
  const calls = [], requests = [], confined = [], releases = [], registrations = { tools: [], skills: [], prompts: [] };
  const ctx = { get: name => ctx[name], fs: localFs(),
    sandboxPolicy: { resolve: ({ mode } = {}) => ({ mode: mode || options.mode || 'danger-full-access', workspaceRoot: root }) },
    sandbox: { async confine(argv, policy) { confined.push(policy); return { argv, enforcement: options.enforcement || 'full' }; } },
    approval: { async request(req) { requests.push(req); if (options.onApproval) await options.onApproval(); return options.approval || 'allowed-once'; } },
    subprocess: { async resolveExecutable(value) { return value; }, spawn(spec) {
      calls.push(spec);
      const value = options.result || { status: 'ready', issues: [], projects: [] };
      return { done: options.done || Promise.resolve({ exitCode: options.exitCode ?? 0, signal: null }),
        collected: { stdout: { readFrom: () => ({ text: options.text ?? JSON.stringify(value), lossy: !!options.lossy }) } },
        terminate() { releases.push('terminate'); options.onTerminate?.(); }, async waitForExit() { releases.push('wait'); if (options.failWait) throw Error('provider observation failed'); return true; } };
    } },
    tools: { register(value) { registrations.tools.push(value); return () => releases.push(value.name); } },
    skills: { register(value) { registrations.skills.push(value); if (options.failSkill) throw Error('skill failed'); return () => releases.push(value.name); } },
    systemPrompt: { section(value) { registrations.prompts.push(value); return () => releases.push(value.name); } },
  };
  return { ctx, config, root, calls, requests, confined, releases, registrations, agent: { id: 'session', session: {} } };
}

test('manifest contains all resource bytes and fixed native preset; check is local and cached', async t => {
  const f = await fixture(t);
  const value = await definition(f.ctx, f.config);
  assert.equal(value.manifest.requires.agentPreset, 'cordis');
  assert.match(value.manifest.package.contentDigest, /^[0-9a-f]{64}$/);
  assert.equal(value.manifest.package.name, '@fegnze/dsh-assistant-plugin-dev');
  assert.equal((await value.check({ agent: f.agent })).status, 'ready');
  assert.equal((await value.check({ agent: f.agent })).issues[0].code, 'PUBLICATION_NOT_CHECKED');
  assert.equal(f.calls.length, 1);
  assert.deepEqual(f.calls[0].argv.slice(-2), ['readiness', 'local']);
  assert.equal(f.requests.length, 0);
  await fs.appendFile(f.config.configPath, ' ');
  await value.check({ agent: f.agent });
  assert.equal(f.calls.length, 2);
});

test('unconfigured package lists but refuses readiness without spawning', async t => {
  const f = await fixture(t); const value = await definition(f.ctx, {});
  const readiness = await value.check();
  assert.equal(readiness.status, 'configuration-required'); assert.equal(f.calls.length, 0);
  assert.match(readiness.issues[0].remediation, /configuration-file entry/);
  assert.match(readiness.issues[0].remediation, /private configuration override bundle/);
  assert.doesNotMatch(readiness.issues[0].remediation, /configuration form/);
  assert.equal(Config({}).pythonExecutable, '');
});

test('mount scopes tools, skill and prompt; disposal is idempotent', async t => {
  const f = await fixture(t); const value = await definition(f.ctx, f.config);
  const lease = await value.mount({ ctx: f.ctx, agent: f.agent, signal: new AbortController().signal });
  assert.deepEqual(f.registrations.tools.map(x => x.name), ['dsh_dev_query', 'dsh_dev_operate']);
  assert.equal(f.registrations.skills.length, 1); assert.equal(f.registrations.prompts.length, 1);
  await lease.dispose(); const count = f.releases.length; await lease.dispose(); assert.equal(f.releases.length, count);
});

test('partial scoped mount failure unwinds prior tools', async t => {
  const f = await fixture(t, { failSkill: true }); const value = await definition(f.ctx, f.config);
  await assert.rejects(value.mount({ ctx: f.ctx, agent: f.agent, signal: new AbortController().signal }), /skill failed/);
  assert.deepEqual(f.releases, ['dsh_dev_operate', 'dsh_dev_query']);
});

test('Host refuses package config and unshared execution worlds', async t => {
  const f = await fixture(t);
  await assert.rejects(createRunner(f.ctx, { ...f.config, configPath: path.join(HOST_ROOT, 'package.json') }).run(['projects']), /outside/);
  f.ctx.fs.processPathFromHostPath = () => undefined;
  await assert.rejects(createRunner(f.ctx, f.config).run(['projects']), /execution world/);
  assert.equal(f.calls.length, 0);
});

test('read-only process execution is confined; partial sandbox fails closed', async t => {
  const f = await fixture(t, { mode: 'read-only' }); await createRunner(f.ctx, f.config).run(['projects'], { agent: f.agent });
  assert.equal(f.confined.length, 1); assert.equal(f.requests.length, 0); assert.equal(f.calls[0].stdio.stdin, 'ignore');
  assert(f.calls[0].argv.includes('--config-revision')); assert.equal(f.calls[0].env.PYTHONDONTWRITEBYTECODE, '1');
  assert.deepEqual(f.releases, ['terminate', 'wait']);
  const bad = await fixture(t, { mode: 'read-only', enforcement: 'partial' });
  await assert.rejects(createRunner(bad.ctx, bad.config).run(['projects']), /Complete process sandbox/); assert.equal(bad.calls.length, 0);
});

test('side effects require real one-shot approval and fail closed for never', async t => {
  const f = await fixture(t, { mode: 'read-only', approval: 'rejected' });
  await assert.rejects(createRunner(f.ctx, f.config).run(['validate', 'dsh-example'], { agent: f.agent, effect: 'execute-scripts' }), /not approved/);
  assert.equal(f.calls.length, 0); assert.equal(f.requests.length, 1);
});

test('full access never implies public export or publication consent', async t => {
  for (const effect of ['public-export', 'publish']) {
    const f = await fixture(t, { approval: 'rejected' });
    await assert.rejects(createRunner(f.ctx, f.config).run(['release', 'dsh-example'], { agent: f.agent, effect }), /not approved/);
    assert.equal(f.calls.length, 0); assert.equal(f.requests.length, 1);
  }
});

test('config changes during approval cannot retarget an authorized command', async t => {
  let f; f = await fixture(t, { mode: 'read-only', onApproval: () => fs.appendFile(f.config.configPath, ' ') });
  await assert.rejects(createRunner(f.ctx, f.config).run(['validate', 'dsh-example'], { agent: f.agent, effect: 'execute-scripts' }), /changed during authorization/);
  assert.equal(f.calls.length, 0);
});

test('invalid/truncated/nonzero output cannot leak diagnostics or succeed', async t => {
  for (const options of [{ lossy: true }, { text: 'not-json secret' }, { exitCode: 1 }]) {
    const f = await fixture(t, options);
    await assert.rejects(createRunner(f.ctx, f.config).run(['projects']), error => !error.message.includes('secret'));
    assert.deepEqual(f.releases, ['terminate', 'wait']);
  }
});

test('disposal terminates and drains an active managed child', async t => {
  let resolve; const done = new Promise(r => { resolve = r; });
  const f = await fixture(t, { done, onTerminate: () => resolve({ exitCode: null, signal: 'SIGTERM' }) });
  const runner = createRunner(f.ctx, f.config);
  const pending = runner.run(['projects']);
  while (!f.calls.length) await new Promise(r => setImmediate(r));
  const rejection = assert.rejects(pending, /cancelled/); await runner.dispose(); await rejection;
  await assert.rejects(runner.run(['projects']), /disposed/);
});

test('provider drain failure is reported without retaining stale handles', async t => {
  const f = await fixture(t, { failWait: true });
  const runner = createRunner(f.ctx, f.config);
  await assert.rejects(runner.run(['projects']), /Managed process cleanup failed/);
  assert.deepEqual(f.releases, ['terminate', 'wait']);
  await runner.dispose();
  assert.deepEqual(f.releases, ['terminate', 'wait']);
});

test('operation schemas reject arbitrary execution, extra flags and auth bootstrap', () => {
  for (const value of [{ action: 'npm-bootstrap', project: 'dsh-example' }, { action: 'validate', project: 'dsh-example', confirmed: true }, { action: 'commit', project: '../outside', baseline: 'a'.repeat(64), subject: 'x' }]) {
    assert.throws(() => operationArgv(value));
  }
  assert.deepEqual(operationArgv({ action: 'commit', project: 'dsh-example', baseline: 'a'.repeat(64), subject: 'reviewed' }), ['commit', 'dsh-example', 'a'.repeat(64), 'reviewed', '--allow-git-hooks']);
  assert.deepEqual(operationArgv({ action: 'sync', project: 'dsh-example', baseline: 'a'.repeat(64), remote: 'empty' }), ['sync', 'dsh-example', 'a'.repeat(64), 'empty', '--approve-export']);
});

test('query cannot accept mutation action and recovery is state-writing', async () => {
  const calls = []; const definitions = tools({ run: async (...args) => { calls.push(args); return {}; } }, {});
  await assert.rejects(definitions[0].execute({ action: 'release', project: 'dsh-example' }, {}));
  await definitions[1].execute({ action: 'release-resume', project: 'dsh-example', runId: '123', commit: 'a'.repeat(40) }, {});
  assert.equal(calls[0][1].effect, 'state-write');
});
