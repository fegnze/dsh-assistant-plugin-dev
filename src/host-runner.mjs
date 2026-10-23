import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';

export const HOST_ROOT = fileURLToPath(new URL('../', import.meta.url));
export const CLI_HOST_PATH = fileURLToPath(new URL('./cli.py', import.meta.url));
const get = (ctx, key) => ctx.get(key);
const aborted = signal => { if (signal?.aborted) throw new Error('Operation cancelled'); };

export async function resources(ctx, signal, previous) {
  const fs = get(ctx, 'fs');
  if (!fs) throw new Error('Filesystem service unavailable');
  const rootPath = fs.processPathFromHostPath(HOST_ROOT);
  if (!rootPath) throw new Error('Package is not accessible in the subprocess execution world');
  const root = await fs.resolve(rootPath, { signal });
  const rows = [], content = new Map();
  async function visit(target, rel, depth = 0) {
    if (depth > 12 || rows.length > 1000) throw new Error('Package resource inventory exceeds limits');
    const info = await fs.stat(target, signal);
    if (!info || !fs.contains(root, target)) throw new Error('Package resource is missing or external');
    if (info.type === 'directory') {
      for (const item of await fs.listDir(target, signal)) {
        if (item.name === '__pycache__' || item.name.endsWith('.pyc')) continue;
        await visit(item.target, rel + '/' + item.name, depth + 1);
      }
    } else if (info.type === 'file') {
      // Provider-owned versions, not an assumed mtime shape. This detects ordinary
      // trusted-file drift, not malicious same-user changes to the execution world.
      const version = JSON.stringify([target.targetKey, info.version, info.size]);
      const prior = previous?.content.get(rel);
      let hash;
      if (prior?.version === version) hash = prior.hash;
      else {
        const bytes = await fs.readBytes(target, signal, 2 * 1024 * 1024);
        if ((await fs.stat(target, signal))?.version !== info.version) throw new Error('Package changed while reading');
        hash = createHash('sha256').update(bytes).digest('hex');
      }
      content.set(rel, { version, hash });
      rows.push([rel, hash]);
    } else throw new Error('Unsupported package resource');
  }
  for (const rel of ['package.json', 'cordis.patch.yml', 'src', 'skills', 'prompts', 'templates', 'locale', 'docs', 'icon.svg', 'requirements.txt', 'README.md']) {
    await visit(await fs.resolve(rootPath + '/' + rel, { signal }), rel);
  }
  rows.sort(([a], [b]) => a.localeCompare(b, 'en'));
  const packageJson = JSON.parse(await fs.readText(await fs.resolve(rootPath + '/package.json', { signal }), signal));
  const read = async rel => fs.readText(await fs.resolve(rootPath + '/' + rel, { signal }), signal);
  return { rootPath, packageJson, read, content, digest: createHash('sha256').update(JSON.stringify(rows)).digest('hex') };
}

export function createRunner(ctx, config, ownedSignal) {
  const handles = new Set();
  const shutdown = new AbortController();
  let stopped = false, disposing;
  async function drain(handle) {
    const errors = [];
    try { handle.terminate(); } catch (error) { errors.push(error); }
    try {
      if (await handle.waitForExit() !== true) throw new Error('Managed process range did not exit');
    } catch (error) { errors.push(error); }
    if (errors.length) throw new AggregateError(errors, 'Managed process cleanup failed');
  }
  async function run(args, { agent, signal, effect = 'read', toolName = 'dsh_dev_query', callId, timeoutMs = 120000 } = {}) {
    if (stopped) throw new Error('Assistant has been disposed');
    const signals = [shutdown.signal, ownedSignal, signal].filter(Boolean);
    const cancellation = signals.length ? AbortSignal.any(signals) : new AbortController().signal;
    aborted(cancellation);
    const fs = get(ctx, 'fs'), subprocess = get(ctx, 'subprocess');
    const sandboxPolicy = get(ctx, 'sandboxPolicy'), sandbox = get(ctx, 'sandbox');
    if (!fs || !subprocess || !sandboxPolicy) throw new Error('Required filesystem/process/policy services unavailable');
    if (!config.pythonExecutable || !config.configPath) throw new Error('Configure explicit Python executable and external configuration path');
    const cliPath = fs.processPathFromHostPath(CLI_HOST_PATH);
    const packagePath = fs.processPathFromHostPath(HOST_ROOT);
    if (!cliPath || !packagePath) throw new Error('Package cannot be read in this execution world');
    const configTarget = await fs.resolve(config.configPath, { signal: cancellation });
    const packageTarget = await fs.resolve(packagePath, { signal: cancellation });
    if (fs.contains(packageTarget, configTarget)) throw new Error('Configuration must be outside immutable package files');
    const configRaw = await fs.readBytes(configTarget, cancellation, 1024 * 1024);
    const configRevision = createHash('sha256').update(configRaw).digest('hex');
    const configPath = fs.processPath(configTarget);
    let policy = sandboxPolicy.resolve(agent ? { session: agent.session } : {});
    if (!['read-only', 'workspace-write', 'danger-full-access'].includes(policy?.mode)) throw new Error('Sandbox policy unavailable');
    const publicEffect = effect === 'public-export' || effect === 'publish';
    if (publicEffect || (effect !== 'read' && policy.mode !== 'danger-full-access')) {
      if (!agent) throw new Error('Mutating operations require a live requesting session');
      const approval = get(ctx, 'approval');
      if (!approval) throw new Error('Approval service unavailable');
      const outcome = await approval.request({ agent, toolName, callId, signal: cancellation,
        reason: `Run ${args[0]} (${effect}) with exact arguments ${JSON.stringify(args.slice(1))}, config ${configPath} revision ${configRevision}, state ${config.stateDir || '(none)'}. This may execute scripts/hooks or export/publish source according to the named operation.` });
      if (outcome !== 'allowed-once') throw new Error('Operation not approved: ' + outcome);
      policy = sandboxPolicy.resolve({ session: agent.session, mode: 'danger-full-access' });
    }
    aborted(cancellation);
    if (createHash('sha256').update(await fs.readBytes(configTarget, cancellation, 1024 * 1024)).digest('hex') !== configRevision) {
      throw new Error('Configuration changed during authorization; preview again');
    }
    const executable = await subprocess.resolveExecutable(config.pythonExecutable, undefined, cancellation);
    let argv = [executable, '-B', cliPath, '--config', configPath, '--config-revision', configRevision];
    if (config.stateDir) {
      const state = await fs.resolve(config.stateDir, { signal: cancellation });
      if (fs.contains(packageTarget, state)) throw new Error('Recovery state must be outside package files');
      argv.push('--state-dir', fs.processPath(state));
    }
    argv.push(...args);
    let confined;
    if (policy.mode !== 'danger-full-access') {
      if (!sandbox) throw new Error('Process sandbox unavailable; refusing unconfined execution');
      confined = await sandbox.confine(argv, policy, cancellation);
      if (confined.enforcement !== 'full') throw new Error('Complete process sandbox enforcement is required');
      argv = confined.argv;
    }
    aborted(cancellation);
    const controller = new AbortController();
    const handle = subprocess.spawn({ argv, cwd: packagePath, graceMs: 1500,
      signal: AbortSignal.any([cancellation, controller.signal]),
      stdio: { stdin: 'ignore', stdout: { maxBytes: 1024 * 1024 }, stderr: { maxBytes: 16384 } },
      env: { PYTHONDONTWRITEBYTECODE: '1', GIT_OPTIONAL_LOCKS: '0', OPENSPEC_TELEMETRY: '0', npm_config_update_notifier: 'false' } });
    handles.add(handle);
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const outcome = await handle.done;
      if (stopped || cancellation.aborted || controller.signal.aborted) throw new Error('Operation cancelled or timed out; inspect target state before retry');
      if (outcome.exitCode !== 0) throw new Error('Development command failed; inspect local configuration, prerequisites and target state before retry');
      const output = handle.collected.stdout?.readFrom(0);
      if (!output || output.lossy) throw new Error('Development output unavailable or exceeded its bound');
      let value;
      try { value = JSON.parse(output.text); } catch { throw new Error('Development command returned invalid JSON'); }
      return value;
    } finally {
      clearTimeout(timer);
      // done observes the leader; waitForExit also drains the provider-managed range.
      try { await drain(handle); } finally { handles.delete(handle); }
    }
  }
  return { run, dispose() {
    if (disposing) return disposing;
    stopped = true;
    shutdown.abort();
    disposing = (async () => {
      const results = await Promise.allSettled([...handles].map(drain));
      handles.clear();
      const errors = results.filter(result => result.status === 'rejected').map(result => result.reason);
      if (errors.length) throw new AggregateError(errors, 'Managed process cleanup failed');
    })();
    return disposing;
  } };
}
