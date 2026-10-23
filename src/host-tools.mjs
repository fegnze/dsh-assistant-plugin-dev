const string = description => ({ type: 'string', description });
const object = (properties, required = []) => ({ type: 'object', properties, required, additionalProperties: false });
const action = (name, properties = {}, required = []) => object({ action: { type: 'string', const: name }, ...properties }, ['action', ...required]);
// Flat object input keeps native function-call adapters portable. Execute still
// enforces each selected action's exact required and forbidden fields below.
const wireSchema = alternatives => object({
  ...Object.assign({}, ...alternatives.map(row => row.properties)),
  action: { type: 'string', enum: alternatives.map(row => row.properties.action.const),
    description: 'Supply only fields for the selected action. Required: ' + alternatives.map(row =>
      row.properties.action.const + '(' + row.required.filter(key => key !== 'action').join(', ') + ')').join('; ') + '. readiness additionally accepts optional operation.' },
}, ['action']);
const project = { project: string('Exact registered project short name.') };
const baseline = { baseline: string('Exact baseline from the matching plan.') };
const sha = { commit: string('Exact reviewed remote commit SHA.') };
export const QUERY_ACTIONS = ['guide', 'projects', 'inspect', 'registry', 'remote', 'version-plan', 'commit-plan', 'sync-plan', 'npm-bootstrap-plan', 'readiness'];
export const EFFECTS = Object.freeze({ create: 'workspace-write', validate: 'execute-scripts', 'version-bump': 'workspace-write',
  commit: 'execute-hooks', 'create-repo': 'public-export', sync: 'public-export', release: 'publish',
  'release-status': 'state-write', 'release-resume': 'state-write', 'openspec-init': 'workspace-write', 'openspec-new': 'workspace-write' });
const QUERY_CASES = { oneOf: [action('guide'), action('projects'),
  ...QUERY_ACTIONS.filter(x => !['guide', 'projects', 'readiness'].includes(x)).map(name => action(name, project, ['project'])),
  action('readiness', { operation: { type: 'string', enum: ['all', 'local', ...QUERY_ACTIONS.filter(x => x !== 'readiness'), ...Object.keys(EFFECTS).filter(x => !x.startsWith('openspec-')), 'openspec', 'npm-bootstrap'] } }),
] };
const OPERATE_CASES = { oneOf: [
  action('create', { name: string('New dsh-* project name.'), description: string('One-line project description.') }, ['name', 'description']),
  action('validate', project, ['project']),
  action('version-bump', { ...project, ...baseline }, ['project', 'baseline']),
  action('commit', { ...project, ...baseline, subject: string('Single-line exact-scope commit subject.') }, ['project', 'baseline', 'subject']),
  action('create-repo', project, ['project']),
  action('sync', { ...project, ...baseline, remote: string('Exact remote SHA, or the literal string "empty" for a reviewed empty repository (not an empty string).') }, ['project', 'baseline', 'remote']),
  action('release', { ...project, ...sha }, ['project', 'commit']),
  action('release-status', { ...project, runId: string('Exact existing GitHub Actions numeric run ID.') }, ['project', 'runId']),
  action('release-resume', { ...project, runId: string('Exact existing GitHub Actions numeric run ID.'), ...sha }, ['project', 'runId', 'commit']),
  action('openspec-init', project, ['project']),
  action('openspec-new', { ...project, change: string('New lower-kebab change name bound to this project.') }, ['project', 'change']),
] };
export const QUERY_SCHEMA = wireSchema(QUERY_CASES.oneOf);
export const OPERATE_SCHEMA = wireSchema(OPERATE_CASES.oneOf);

function validate(schema, value) {
  const alternatives = schema.oneOf || [schema];
  const match = alternatives.find(row => row.properties.action.const === value?.action);
  if (!match || !value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Invalid action');
  for (const key of Object.keys(value)) if (!(key in match.properties)) throw new Error('Unexpected argument');
  for (const key of match.required) if (!(key in value)) throw new Error('Missing argument: ' + key);
  for (const [key, item] of Object.entries(value)) {
    const rule = match.properties[key];
    if (typeof item !== 'string' || !item.length || item.length > 1000 || /[\0\r\n]/.test(item)) throw new Error('Invalid argument: ' + key);
    if (rule.enum && !rule.enum.includes(item)) throw new Error('Unsupported argument: ' + key);
  }
  if (value.project && !/^dsh-[a-z0-9]+(?:-[a-z0-9]+)*$/.test(value.project)) throw new Error('Invalid project');
  if (value.name && !/^dsh-[a-z0-9]+(?:-[a-z0-9]+)*$/.test(value.name)) throw new Error('Invalid project name');
  if (value.baseline && !/^[a-f0-9]{64}$/.test(value.baseline)) throw new Error('Invalid baseline');
  if (value.commit && !/^[a-f0-9]{40}$/.test(value.commit)) throw new Error('Invalid commit');
  if (value.remote && value.remote !== 'empty' && !/^[a-f0-9]{40}$/.test(value.remote)) throw new Error('Invalid remote');
  if (value.runId && !/^\d+$/.test(value.runId)) throw new Error('Invalid run ID');
  if (value.change && !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(value.change)) throw new Error('Invalid change name');
  return value;
}
export function operationArgv(value) {
  const a = validate(OPERATE_CASES, value);
  switch (a.action) {
    case 'create': return ['create', a.name, a.description];
    case 'validate': return ['validate', a.project, '--allow-project-scripts'];
    case 'version-bump': return ['version-bump', a.project, a.baseline];
    case 'commit': return ['commit', a.project, a.baseline, a.subject, '--allow-git-hooks'];
    case 'create-repo': return ['create-repo', a.project, '--approve-public'];
    case 'sync': return ['sync', a.project, a.baseline, a.remote, '--approve-export'];
    case 'release': return ['release', a.project, a.commit, '--approve-publish'];
    case 'release-status': return ['release-status', a.project, a.runId];
    case 'release-resume': return ['release-resume', a.project, a.runId, a.commit];
    case 'openspec-init': return ['openspec', a.project, 'init'];
    case 'openspec-new': return ['openspec', a.project, 'new', 'change', a.change, '--json'];
  }
}
const output = { schema: { type: 'object', additionalProperties: true }, render: (_args, value) => [{ type: 'text', text: JSON.stringify(value, null, 2) }] };
export function tools(runner, agent) {
  return [{ name: 'dsh_dev_query', description: 'Inspect registered plugin projects, prerequisites and exact delivery plans. Queries never grant script, export or publication permission.', parameters: QUERY_SCHEMA,
    output, timeoutMs: 120000, isConcurrencySafe: () => false,
    async execute(value, exec) {
      const a = validate(QUERY_CASES, value);
      const args = [a.action, ...(a.project ? [a.project] : []), ...(a.operation ? [a.operation] : [])];
      return runner.run(args, { agent, signal: exec.signal, callId: exec.callId });
    },
  }, { name: 'dsh_dev_operate', description: 'Run one baseline-bound plugin development operation. Validation executes project scripts; commits execute hooks; synchronization exports source; release publishes; release recovery writes durable state. Authentication is not started by this tool.', parameters: OPERATE_SCHEMA,
    output, timeoutMs: 1500000, isConcurrencySafe: () => false,
    async execute(value, exec) {
      const args = operationArgv(value);
      return runner.run(args, { agent, signal: exec.signal, effect: EFFECTS[value.action], toolName: 'dsh_dev_operate', callId: exec.callId, timeoutMs: 1400000 });
    },
  }];
}
