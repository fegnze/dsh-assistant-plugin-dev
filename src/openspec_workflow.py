"""Standard OpenSpec integration; no parallel workflow state or completion receipts."""
import json
import os
from pathlib import Path
import re
from processes import ProcessAdapter
subprocess = ProcessAdapter()
import yaml


def metadata(path, change):
    if not NAME.fullmatch(change):
        raise ValueError('Change must be a lower-kebab workspace-local name')
    file = path / 'openspec/changes' / change / '.openspec.yaml'
    data = yaml.safe_load(file.read_text()) or {}
    if not isinstance(data, dict):
        raise ValueError('Invalid change metadata')
    areas = data.get('affected_areas', [])
    if not isinstance(areas, list) or not all(isinstance(area, str) for area in areas):
        raise ValueError('affected_areas must be a list of workspace-relative paths')
    return data


def require_target(path, change, target):
    areas = metadata(path, change).get('affected_areas', [])
    if areas != [target]:
        raise ValueError(f'Change {change} must bind only to {target}; missing, different or multi-target scope requires explicit full-scope review')


def bind_target(path, change, target):
    data = metadata(path, change)
    data['affected_areas'] = [target]
    (path / 'openspec/changes' / change / '.openspec.yaml').write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False))

TEMPLATES = Path(__file__).resolve().parents[1] / 'templates/openspec'
NAME = re.compile(r'[a-z0-9]+(?:-[a-z0-9]+)*')


def files(project=None):
    # Shared workspace templates must never bind to the first plugin initialized.
    return {str(p.relative_to(TEMPLATES)): p.read_text().replace('{{project}}', 'PROJECT')
            for p in sorted(TEMPLATES.rglob('*')) if p.is_file()}


def initialize(path, project):
    root = path / 'openspec'
    # Existing OpenSpec belongs to its project. Adoption must not overwrite it.
    if root.exists() or root.is_symlink():
        return {**inspect(path), 'status': 'existing', 'next': 'Reuse the existing schema; merge devkit guidance only after reviewing its config.'}
    for rel, text in files(project).items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    (root / 'changes').mkdir(exist_ok=True)
    (root / 'specs').mkdir(exist_ok=True)
    return {**inspect(path), 'status': 'initialized'}


def inspect(path):
    root = path / 'openspec'
    if root.is_symlink():
        return {'status': 'external-root', 'managed': False, 'changes': [], 'next': 'Existing OpenSpec symlink preserved; use its owning workflow explicitly, not the project-local adapter.'}
    if not root.is_dir():
        return {'status': 'not-initialized', 'changes': [],
                'root': str(path), 'next': 'openspec PROJECT init (devkit CLI); initialize the configured workspace, not the plugin directory.'}
    changes = root / 'changes'
    active = sorted(p.name for p in changes.iterdir()
                    if p.is_dir() and not p.is_symlink() and p.name != 'archive' and not p.name.startswith('.')) if changes.is_dir() else []
    return {'status': 'ready', 'root': str(path), 'managed': (root / 'schemas/dsh-devkit/schema.yaml').is_file(),
            'changes': active, 'next': 'Use native OPSX to control this change; devkit supplies project tools and validation. After archive, create a new scoped change instead of reopening it.'}


def run(path, arguments):
    try:
        result = subprocess.run(['openspec', *arguments], cwd=path, capture_output=True, text=True,
                                timeout=90, env={**os.environ, 'OPENSPEC_TELEMETRY': '0'})
    except FileNotFoundError:
        raise ValueError('OpenSpec CLI unavailable; install the project-approved OpenSpec version (tested: 1.8.0).') from None
    if result.returncode:
        # Bounded CLI diagnostics, never full project command output.
        raise ValueError('OpenSpec failed: ' + (result.stderr or result.stdout)[-2000:])
    try:
        return json.loads(result.stdout)
    except ValueError:
        return {'output': result.stdout[-6000:]}


def require_local_root(path):
    if (path / 'openspec').is_symlink():
        raise ValueError('OpenSpec symlink is preserved but not operated through the project-local adapter')
    root_dir = path / 'openspec'
    for target in [root_dir, root_dir / 'changes', root_dir / 'specs', root_dir / 'changes/archive', *root_dir.rglob('*')]:
        if target.is_symlink() and not target.resolve().is_relative_to(root_dir.resolve()):
            raise ValueError('OpenSpec contains an external symlink; use its owning workflow explicitly')
    context = run(path, ['context', '--json'])
    root = context.get('root', {}).get('path')
    if not root or Path(root).resolve() != path.resolve():
        raise ValueError('OpenSpec resolves an external root; use its owning workflow explicitly')


def check(path, target=None, change=None):
    state = inspect(path)
    if state['status'] == 'not-initialized':
        return {**state, 'checked': False}  # progressive adoption, not an unrelated-project migration
    require_local_root(path)
    if state['managed']:
        run(path, ['schema', 'validate', 'dsh-devkit', '--json'])
    selected = [change] if change else state['changes']
    unassigned = []
    if target and not change:
        unassigned = [name for name in selected if not metadata(path, name).get('affected_areas')]
        selected = [name for name in selected if target in metadata(path, name).get('affected_areas', [])]
    results = {name: run(path, ['validate', name, '--type', 'change', '--strict', '--json', '--no-interactive']) for name in selected}
    return {**state, 'root': str(path), 'target': target, 'checked': True, 'validatedChanges': selected, 'unassignedChanges': unassigned, 'validation': results}


def execute(path, project, arguments, target=None):
    """One scoped adapter for native OpenSpec commands, not a second lifecycle."""
    if arguments == ['init']:
        return initialize(path, project)
    if not arguments:
        return inspect(path)
    operation = arguments[0]
    if operation == 'archive':
        raise ValueError('Archive through native OPSX; devkit does not wrap archive')
    allowed = {'new', 'status', 'instructions', 'validate', 'list', 'templates', 'schemas'}
    if operation not in allowed:
        raise ValueError('Use init, new change, status, instructions, validate, list, templates or schemas')
    if inspect(path)['status'] == 'not-initialized':
        raise ValueError(f'Initialize first: openspec {project} init (devkit CLI)')
    if operation == 'new' and (len(arguments) < 3 or arguments[1] != 'change' or not NAME.fullmatch(arguments[2])):
        raise ValueError('Use new change LOWER-KEBAB-NAME')
    if any(a.startswith('--store') for a in arguments):
        raise ValueError('Devkit OpenSpec operates only on the registered project, not an external store')
    if '--change' in arguments:
        index = arguments.index('--change') + 1
        if index >= len(arguments) or not NAME.fullmatch(arguments[index]):
            raise ValueError('Change must be a lower-kebab project-local name')
    if any(a.startswith('--change=') and not NAME.fullmatch(a.split('=', 1)[1]) for a in arguments):
        raise ValueError('Change must be a lower-kebab project-local name')
    require_local_root(path)
    result = run(path, arguments)
    if operation == 'new' and target:
        require_local_root(path)
        bind_target(path, arguments[2], target)
        result = {'target': target, 'workspaceRoot': str(path), 'result': result}
    return result
