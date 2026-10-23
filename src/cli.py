"""One command per process. User configuration and recovery state are always external."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re
import sys
from processes import subprocess
import settings

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = None
STATE_DIR = None
CONFIG_REVISION = None


def configure(config_path=None, state_dir=None):
    global CONFIG_PATH, STATE_DIR
    CONFIG_PATH = settings.external(config_path) if config_path else None
    STATE_DIR = settings.external(state_dir, 'Recovery state') if state_dir else None
    from processes import configure as executables
    executables()


def config():
    if CONFIG_PATH is None:
        raise ValueError('Explicit --config PATH is required; no workspace or account defaults')
    observed = settings.read(CONFIG_PATH)
    if CONFIG_REVISION is not None and observed['revision'] != CONFIG_REVISION:
        raise ValueError('Configuration changed since authorization; preview again')
    return settings.validate(CONFIG_PATH, observed['config'])


def state_root():
    if STATE_DIR is None:
        raise ValueError('Explicit --state-dir PATH is required for durable release evidence')
    # This is the releases directory itself, so migration preserves every existing filename/key.
    path = settings.external(STATE_DIR, 'Recovery state')
    c = config()
    for entry in c['projects'].values():
        project_path = (Path(c['workspace']) / entry['path']).resolve()
        if path == project_path or path.is_relative_to(project_path):
            raise ValueError('Recovery state must not be inside a publishable project')
    return path


def command(args, cwd):
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise ValueError(f'Command failed: {args[0]} {args[1]} (exit {result.returncode})')
    return result.stdout.strip()


def project(name):
    c = config()
    if name not in c['projects']:
        raise ValueError('Unknown registered project')
    workspace = Path(c['workspace']).resolve()
    path = (workspace / c['projects'][name]['path']).resolve()
    if not path.is_relative_to(workspace) or path == workspace:
        raise ValueError('Project escapes workspace')
    return c, path, c['projects'][name]


def inspect(name):
    c, path, entry = project(name)
    p = json.loads((path / 'package.json').read_text())
    from documentation import issues as documentation_issues, REVIEW
    issues = documentation_issues(path)
    package_name = p['name']
    if not re.fullmatch(r'dsh-[a-z0-9]+(?:-[a-z0-9]+)*', name):
        issues.append('Project directory must use dsh-* naming')
    expected_npm = f"@{c.get('npmAccount', '')}/{name}" if c.get('npmAccount') else None
    if package_name != name and (not expected_npm or package_name != expected_npm):
        issues.append('Package name must be the unscoped slug or configured scoped npm name')
    if entry['repository'].split('/')[-1] != name or path.name != name:
        issues.append('Directory and repository name must match')
    if expected_npm and package_name.startswith('@') and package_name != expected_npm:
        issues.append('Scoped package owner must match configured npm account')
    repo = p.get('repository', {})
    repo = repo.get('url', '') if isinstance(repo, dict) else repo
    if repo.removeprefix('git+').removesuffix('.git') != f"https://github.com/{entry['repository']}":
        issues.append('Repository metadata mismatch')
    if not p.get('dsh', {}).get('bundle', {}).get('patch'):
        issues.append('Missing DSH bundle patch')
    if not p.get('files'):
        issues.append('Missing npm payload allowlist')
    if p.get('private'):
        issues.append('Private package cannot publish')
    icon = p.get('icon')
    if not icon or not (path / icon).is_file() or icon.removeprefix('./') not in p.get('files', []):
        issues.append('Missing icon: declare package.json icon, add the file and list it in files')
    if (p.get('exports') or {}).get('./package.json') != './package.json':
        issues.append('exports must include "./package.json" so the host can read plugin metadata')
    from openspec_workflow import inspect as inspect_workflow
    return {'openspec': inspect_workflow(Path(c['workspace'])), 'project': name, 'name': p['name'],
            'version': p['version'], 'repository': entry['repository'],
            'head': command(['git', 'rev-parse', 'HEAD'], path),
            'dirty': bool(command(['git', 'status', '--porcelain', '--', '.'], path)),
            'workflowPresent': (path / '.github/workflows' / c['workflow']).is_file(), 'issues': issues,
            'documentationReview': REVIEW, 'payloadChecked': False,
            'guidance': {'trustedPublisher': {'provider': 'GitHub Actions', 'owner': entry['repository'].split('/')[0],
                         'repository': entry['repository'].split('/')[1], 'workflow': c['workflow'], 'environment': ''},
                         'npmSettings': f"https://www.npmjs.com/package/{p['name']}/access"}}


def guide():
    from documentation import README_FILES, REVIEW
    from readiness import REQUIRES
    return {'tools': list(REQUIRES), 'cli': str(ROOT / 'src/cli.py'), 'documentation': str(ROOT / 'docs/standards.md'),
            'requiredReading': ['OpenSpec 轻量开发流程', '插件图标视觉规范', '发布前检查', '发布结果与故障恢复'],
            'openspec': {'testedVersion': '1.8.0', 'workflowOwner': 'Native OpenSpec OPSX is the only workflow authority.',
                         'commands': 'Use native OPSX instructions/status/spec sync/archive; no devkit archive wrapper.',
                         'entry': 'Workspace from explicit user configuration. PROJECT is the plugin, not the OpenSpec root.',
                         'artifacts': 'Native proposal/specs/design/tasks DAG. skip_specs is not skip_design; artifact readiness is not acceptance.'},
            'configuration': 'Pass --config PATH and, for release evidence, --state-dir PATH before the command. Never store these inside the package.',
            'readmePolicy': {'files': list(README_FILES), 'review': REVIEW},
            'approval': 'Plans and intent flags are not permission. Use an authorized execution tool after reviewing exact scope and scripts.',
            'delivery': {'default': 'Follow the approved proposal scope, including no-release or source-only. Installation/selection grants no publication permission.',
                         'authorization': 'Ask before public export, publishing, sign-in, 2FA or rebinding unless the owner explicitly authorized that exact scope. Never retry authentication automatically.',
                         'versioning': 'Use version-plan/version-bump; preserve initial/already-increased versions. Prerelease and breaking versions need an explicit strategy.'},
            'authentication': 'Host tools never launch authentication. npm-bootstrap is explicit CLI-only, after session confirmation and reviewed flags; it uses an already installed compatible npm.',
            'limitations': ['Static checks do not establish Host/UI acceptance, translation completeness, or cryptographic provenance verification.']}


def invoke(name, args):
    name = name.replace('_', '-')
    if name == 'guide' and not args:
        return guide()
    if name == 'projects' and not args:
        return {'projects': list(config()['projects'])}
    if name in ('inspect', 'registry', 'remote', 'version-plan', 'commit-plan', 'sync-plan', 'npm-bootstrap-plan') and set(args) == {'project'} and isinstance(args['project'], str):
        c, path, entry = project(args['project'])
        if name == 'inspect':
            return inspect(args['project'])
        if name == 'version-plan':
            from versioning import plan
            return plan(path)
        if name == 'commit-plan':
            from delivery import snapshot
            return snapshot(path)
        if name == 'sync-plan':
            from github import sync_plan
            return sync_plan(path, entry['repository'], c['branch'], c['githubOwner'])
        if name == 'remote':
            from github import inspect_remote
            return inspect_remote(path, entry['repository'], c['branch'], c['githubOwner'])
        if name == 'registry':
            from registry import verify
            p = json.loads((path / 'package.json').read_text())
            return verify(p['name'], p['version'], c['registry'], entry['repository'])
        from bootstrap import preview
        return preview(path, json.loads((path / 'package.json').read_text()), c, entry)
    raise ValueError('Invalid query or arguments')


def execute(args):
    if not args or args in (['help'], ['--help'], ['-h']):
        return guide()
    name, *tail = args
    if name == 'readiness':
        from readiness import check
        if CONFIG_PATH:
            config()
        return check(tail[0] if tail else 'all')
    if name == 'migration-preview':
        from migration import preview
        if len(tail) != 2:
            raise ValueError('Usage: migration-preview OLD_CONFIG OLD_STATE_DIR')
        return preview(Path(tail[0]), Path(tail[1]))
    if name == 'guide':
        return guide()
    c = config()
    from readiness import require
    require(name)
    if name == 'settings-read':
        return settings.read(CONFIG_PATH)
    if name == 'settings-save':
        if len(tail) != 2:
            raise ValueError('Usage: settings-save REVISION JSON_FILE')
        return settings.save(CONFIG_PATH, tail[0], json.loads(Path(tail[1]).read_text()))
    if name == 'projects':
        return invoke(name, {})
    if name == 'create':
        if len(tail) != 2:
            raise ValueError('Usage: create NAME DESCRIPTION')
        from scaffold import create
        return create(Path(c['workspace']), CONFIG_PATH, *[tail[0], c['githubOwner'], tail[1]])
    if not tail:
        raise ValueError('Project is required')
    target, *options = tail
    c, path, entry = project(target)
    package = json.loads((path / 'package.json').read_text())
    if name in ('inspect', 'registry', 'remote', 'version-plan', 'commit-plan', 'sync-plan', 'npm-bootstrap-plan') and not options:
        return invoke(name, {'project': target})
    if name == 'openspec':
        from openspec_workflow import execute as native
        return native(Path(c['workspace']), target, options, target=path.relative_to(Path(c['workspace'])).as_posix())
    if name == 'version-bump' and len(options) == 1:
        from versioning import bump
        return bump(path, options[0])
    if name == 'validate' and options == ['--allow-project-scripts']:
        from validation import validate
        return validate(path, Path(c['workspace']))
    if name == 'commit' and len(options) == 3 and options[2] == '--allow-git-hooks':
        from delivery import commit
        return commit(path, options[0], options[1], co_author=c.get('coAuthor'))
    if name == 'create-repo' and options == ['--approve-public']:
        from github import create_repository
        return create_repository(path, entry['repository'], c['githubOwner'], package.get('description', ''), package.get('homepage', ''))
    if name == 'sync' and len(options) == 3 and options[2] == '--approve-export':
        from github import sync_apply
        return sync_apply(path, entry['repository'], c['branch'], c['githubOwner'], options[0], options[1])
    if name == 'release' and len(options) == 2 and options[1] == '--approve-publish':
        from publication import release
        return release(path, package, c, entry, state_root(), options[0])
    if name == 'release-status' and len(options) == 1:
        from publication import observe
        return observe(path, entry['repository'], options[0], state_root())
    if name == 'release-resume' and len(options) == 2:
        if not re.fullmatch(r'[a-f0-9]{40}', options[1]):
            raise ValueError('Expected an exact 40-character commit SHA')
        from publication import resume
        return resume(path, package, c, entry, state_root(), *options)
    if name == 'npm-bootstrap' and options == ['--approve-publish', '--owner-confirmed']:
        import webbrowser
        from bootstrap import bootstrap
        return bootstrap(path, package, c, entry, webbrowser.open, lambda text: print(text, file=sys.stderr, flush=True))
    raise ValueError('Invalid command or missing explicit intent flags; read guide and command documentation')


def main(argv=None):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--config')
    parser.add_argument('--state-dir')
    parser.add_argument('--config-revision')
    parser.add_argument('command', nargs=argparse.REMAINDER)
    raw = sys.argv[1:] if argv is None else argv
    if raw in ([], ['-h'], ['--help'], ['help']):
        print(json.dumps(guide(), ensure_ascii=False, indent=2))
        return
    options = parser.parse_args(raw)
    # Retain configured paths for direct library tests, never discover implicit files.
    if options.config is not None or options.state_dir is not None:
        configure(options.config, options.state_dir)
    global CONFIG_REVISION
    CONFIG_REVISION = options.config_revision
    result = execute(options.command)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(json.dumps({'error': type(error).__name__, 'message': str(error)[:2000]}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)
