import test from 'node:test';
import assert from 'node:assert/strict';
import { Context } from '@deepseek-ai/cordis';
import SystemPrompt from '@deepseek-ai/dsh-system-prompt';
import ToolRuntime from '@deepseek-ai/dsh-tools';
import SkillRegistry from '@deepseek-ai/dsh-skill';
import { createScope } from '@deepseek-ai/dsh-scope';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import { definition } from '../src/host.mjs';

const filesystem = {
  resolve: async p => ({ targetKey: path.resolve(p), displayPath: path.resolve(p) }),
  processPath: t => t.displayPath, processPathFromHostPath: p => p,
  contains: (root, t) => t.targetKey === root.targetKey || t.targetKey.startsWith(root.targetKey + path.sep),
  async stat(t) { const s = await fs.stat(t.displayPath); return { type: s.isFile() ? 'file' : s.isDirectory() ? 'directory' : 'other', version: `${s.ino}:${s.ctimeMs}:${s.size}`, size: s.size }; },
  async listDir(t) { return Promise.all((await fs.readdir(t.displayPath)).sort().map(async name => ({ name, target: await filesystem.resolve(path.join(t.displayPath, name)) }))); },
  readText: t => fs.readFile(t.displayPath, 'utf8'),
  async readBytes(t, signal, max) { const value = await fs.readFile(t.displayPath); if (value.length > max) throw Error('size'); return value; },
};

test('native Cordis validates the actual manifest mount and isolates tools, Skill and prompt', async t => {
  const ctx = new Context(); t.after(() => ctx.fiber.dispose());
  await ctx.plugin(SystemPrompt); await ctx.plugin(ToolRuntime); await ctx.plugin(SkillRegistry);
  ctx.provide('fs', filesystem);
  const a = { id: 'a', session: {} }, b = { id: 'b', session: {} };
  const scopeA = createScope(ctx, a), scopeB = createScope(ctx, b);
  t.after(async () => { await scopeA.dispose(); await scopeB.dispose(); });
  const value = await definition(ctx, {});
  const lease = await value.mount({ ctx: scopeA.ctx, agent: a, signal: new AbortController().signal });
  assert.deepEqual(ctx.tools.schemas(a).map(x => x.name).sort(), ['dsh_dev_operate', 'dsh_dev_query']);
  assert.deepEqual(ctx.tools.schemas(b), []);
  assert.equal((await ctx.skills.list({ scope: a })).some(x => x.name === 'dsh-plugin-development'), true);
  assert.deepEqual(await ctx.skills.list({ scope: b }), []);
  const skill = await ctx.skills.get('dsh-plugin-development', { scope: a });
  assert.match(skill.content, /原生 OpenSpec OPSX/);
  assert.equal(skill.invocation.modelInvocable, true);
  assert.equal((await ctx.systemPrompt.assemble({ scope: a })).sections.some(x => x.name === 'dsh-plugin-development-assistant'), true);
  assert.equal((await ctx.systemPrompt.assemble({ scope: b })).sections.some(x => x.name === 'dsh-plugin-development-assistant'), false);
  await lease.dispose(); await lease.dispose();
  assert.deepEqual(ctx.tools.schemas(a), []);
  assert.deepEqual(await ctx.skills.list({ scope: a }), []);
  assert.equal((await ctx.systemPrompt.assemble({ scope: a })).sections.some(x => x.name === 'dsh-plugin-development-assistant'), false);
});

test('native scoped contributions are all removed even when process drain rejects', async t => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'dsh-native-cleanup-'));
  t.after(async () => { assert(path.basename(root).startsWith('dsh-native-cleanup-')); await fs.rm(root, { recursive: true, force: true }); });
  const configPath = path.join(root, 'config.json'); await fs.writeFile(configPath, '{}');
  const ctx = new Context(); t.after(() => ctx.fiber.dispose());
  await ctx.plugin(SystemPrompt); await ctx.plugin(ToolRuntime); await ctx.plugin(SkillRegistry);
  ctx.provide('fs', filesystem);
  ctx.provide('sandboxPolicy', { resolve: () => ({ mode: 'danger-full-access', workspaceRoot: root }) });
  let resolveDone, spawned;
  const begun = new Promise(resolve => { spawned = resolve; });
  ctx.provide('subprocess', { resolveExecutable: async () => '/test/python', spawn() {
    const done = new Promise(resolve => { resolveDone = resolve; }); spawned();
    return { done, collected: {}, terminate() { resolveDone({ exitCode: null, signal: 'SIGTERM' }); },
      async waitForExit() { throw Error('provider observation failed'); } };
  } });
  const agent = { id: 'cleanup', session: {} }, scope = createScope(ctx, agent); t.after(() => scope.dispose());
  const value = await definition(ctx, { pythonExecutable: '/test/python', configPath });
  const lease = await value.mount({ ctx: scope.ctx, agent, signal: new AbortController().signal });
  const pending = ctx.tools.get('dsh_dev_query', agent).execute({ action: 'projects' }, { signal: new AbortController().signal });
  const rejected = assert.rejects(pending, /Managed process cleanup failed/);
  await begun;
  await assert.rejects(lease.dispose(), /Assistant cleanup failed/);
  await rejected;
  assert.deepEqual(ctx.tools.schemas(agent), []);
  assert.deepEqual(await ctx.skills.list({ scope: agent }), []);
  assert.equal((await ctx.systemPrompt.assemble({ scope: agent })).sections.some(x => x.name === 'dsh-plugin-development-assistant'), false);
  await assert.rejects(lease.dispose(), /Assistant cleanup failed/);
});
