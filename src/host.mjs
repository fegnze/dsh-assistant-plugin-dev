import z from '@deepseek-ai/schemastery';
import { resources, createRunner } from './host-runner.mjs';
import { tools } from './host-tools.mjs';

export const name = 'dsh-assistant-plugin-dev';
export const inject = ['dshAssistants', 'subprocess', 'fs', 'sandboxPolicy'];
export const Config = z.object({
  pythonExecutable: z.string().default(''),
  configPath: z.string().default(''),
  stateDir: z.string().default(''),
});

export async function definition(ctx, config, signal) {
  const assets = await resources(ctx, signal);
  let checkedAssets = assets, readinessCache;
  const manifest = {
    schemaVersion: 1, id: 'plugin-development', name: '插件开发',
    description: '原生 OpenSpec、插件工程检查与可核验交付',
    package: { name: assets.packageJson.name, version: assets.packageJson.version, contentDigest: assets.digest },
    requires: { agentPreset: 'cordis' },
    capabilities: [
      { id: 'local-development', title: '本地开发', description: '工程创建、检查、测试与精确版本/提交' },
      { id: 'publication', title: '发布交付', description: '显式授权后同步、发布及恢复核验；认证为手动入口' },
    ],
  };
  return {
    manifest,
    async check({ agent, signal: checkSignal } = {}) {
      if (!config.pythonExecutable || !config.configPath || !config.stateDir) {
        return { status: 'configuration-required', issues: [{ code: 'CONFIGURATION_REQUIRED',
          message: 'Configure an explicit Python executable and external configuration/recovery-state paths.',
          remediation: 'Use the official Settings configuration-file entry or install a private configuration override bundle; see docs/host-configuration.md. Never put personal data in the assistant package.' }] };
      }
      const runner = createRunner(ctx, config, checkSignal);
      try {
        checkedAssets = await resources(ctx, checkSignal, checkedAssets);
        if (checkedAssets.digest !== manifest.package.contentDigest) {
          return { status: 'incompatible', issues: [{ code: 'RESOURCE_DRIFT', message: 'Package resources changed; reload the package and use a new exact binding.' }] };
        }
        const fs = ctx.get('fs');
        const target = await fs.resolve(config.configPath, { signal: checkSignal });
        const info = await fs.stat(target, checkSignal);
        if (!info || info.type !== 'file' || info.size > 1024 * 1024) throw new Error('Invalid external configuration');
        const policy = ctx.get('sandboxPolicy').resolve(agent ? { session: agent.session } : {});
        const cacheKey = JSON.stringify([target.targetKey, info.version, info.size, policy.mode, policy.workspaceRoot]);
        if (readinessCache?.key === cacheKey && Date.now() < readinessCache.until) return readinessCache.value;
        const result = await runner.run(['readiness', 'local'], { agent, signal: checkSignal, timeoutMs: 90000 });
        const issues = result.issues.map(issue => ({ code: issue.code, message: issue.message, ...(issue.capability ? { capability: issue.capability } : {}) }));
        if (result.status !== 'ready') return { status: 'unavailable', issues };
        const value = { status: 'ready', issues: [{ code: 'PUBLICATION_NOT_CHECKED', capability: 'publication',
          message: 'GitHub credentials, npm ownership and publication authorization are checked per operation, not by local readiness.' }] };
        readinessCache = { key: cacheKey, until: Date.now() + 60000, value };
        return value;
      } catch {
        return { status: 'unavailable', issues: [{ code: 'LOCAL_PREREQUISITES_UNAVAILABLE',
          message: 'Cannot verify configured local runtime, configuration or sandbox. Run the documented CLI readiness command for details.',
          remediation: 'Check Python>=3.10, PyYAML>=6,<7, Node>=22, npm, git and native OpenSpec 1.8.0; no dependency is installed automatically.' }] };
      } finally { await runner.dispose(); }
    },
    async mount({ ctx: agentCtx, agent, signal: mountSignal }) {
      const off = [];
      const runner = createRunner(agentCtx, config, mountSignal);
      let disposing;
      function dispose() {
        if (disposing) return disposing;
        disposing = (async () => {
          const errors = [];
          try { await runner.dispose(); } catch (error) { errors.push(error); }
          // Process-provider failure must not leave model-facing contributions
          // behind. Preserve reverse cleanup order and attempt every disposer.
          for (const release of off.splice(0).reverse()) {
            try { await release(); } catch (error) { errors.push(error); }
          }
          if (errors.length) throw new AggregateError(errors, 'Assistant cleanup failed');
        })();
        return disposing;
      }
      try {
        if (mountSignal.aborted) throw new Error('Assistant mount cancelled');
        if ((await resources(agentCtx, mountSignal, checkedAssets)).digest !== manifest.package.contentDigest) throw new Error('Package resources changed');
        const sections = await assets.read('prompts/bound.md');
        const content = await assets.read('skills/dsh-plugin-development.md');
        if (mountSignal.aborted) throw new Error('Assistant mount cancelled');
        const toolService = agentCtx.get('tools'), skillService = agentCtx.get('skills'), promptService = agentCtx.get('systemPrompt');
        if (!toolService || !skillService || !promptService) throw new Error('Scoped tools, skills or systemPrompt service unavailable');
        for (const tool of tools(runner, agent)) off.push(toolService.register(tool));
        off.push(skillService.register({ name: 'dsh-plugin-development',
          description: '开发、维护、验证与交付 DSH 插件；使用原生 OPSX 与包内领域工具。',
          whenToUse: 'When developing, validating or delivering a DSH plugin in this assistant-bound session.',
          source: 'runtime', provider: assets.packageJson.name,
          resourceBase: { kind: 'directory', path: assets.rootPath + '/skills' }, content,
          invocation: { modelInvocable: true, userInvocable: true } }));
        off.push(promptService.section({ name: 'dsh-plugin-development-assistant', order: 170, text: sections }));
        if (mountSignal.aborted) throw new Error('Assistant mount cancelled');
        return { dispose };
      } catch (error) { await dispose(); throw error; }
    },
  };
}

export async function apply(ctx, config = {}) {
  const controller = new AbortController();
  ctx.effect(() => () => controller.abort());
  const value = await definition(ctx, config, controller.signal);
  if (controller.signal.aborted) return;
  // The base owns both package and Agent cleanup. This registration creates no process host.
  ctx.dshAssistants.register(ctx, value);
}
