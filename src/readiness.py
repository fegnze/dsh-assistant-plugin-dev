"""Read-only per-operation prerequisites. Never installs, signs in, or opens a browser."""
import importlib.util
import os
from pathlib import Path
import re
import sys
from processes import resolve, subprocess

REQUIRES = {
    'guide': (), 'projects': (), 'settings-read': (), 'settings-save': ('posix',), 'migration-preview': (),
    'inspect': ('git',), 'registry': ('git',), 'remote': ('gh',),
    'version-plan': ('git', 'posix'), 'version-bump': ('git', 'posix'),
    'commit-plan': ('git',), 'commit': ('git',),
    'create': ('git', 'openspec', 'yaml'), 'openspec': ('openspec', 'yaml'),
    'validate': ('node', 'npm', 'openspec', 'yaml'),
    'sync-plan': ('git', 'gh'), 'sync': ('git', 'gh'), 'create-repo': ('gh',),
    'npm-bootstrap-plan': ('git', 'gh'),
    'npm-bootstrap': ('git', 'gh', 'node', 'npm', 'tar', 'posix'),
    'release': ('git', 'gh', 'node', 'npm'),
    'release-status': ('gh',), 'release-resume': ('git', 'gh', 'node', 'npm'),
}
AUTH = {'remote', 'sync-plan', 'sync', 'create-repo', 'npm-bootstrap-plan', 'npm-bootstrap', 'release', 'release-status', 'release-resume'}


def check(operation='all', *, verify_auth=False):
    if operation not in ('all', 'local') and operation not in REQUIRES:
        raise ValueError('Unknown operation for readiness')
    operations = (REQUIRES if operation == 'all' else
                  {key: REQUIRES[key] for key in ('inspect', 'create', 'validate', 'version-plan')} if operation == 'local' else
                  {operation: REQUIRES[operation]})
    facts = {}
    for dependency in sorted({dep for deps in operations.values() for dep in deps}):
        issue = None
        try:
            if dependency == 'yaml':
                if not importlib.util.find_spec('yaml'):
                    raise ValueError('Install declared PyYAML>=6,<7 in the configured interpreter')
                import yaml
                if not (6 <= int(yaml.__version__.split('.')[0]) < 7):
                    raise ValueError('PyYAML must be >=6,<7')
                facts[dependency] = {'available': True, 'version': yaml.__version__}
                continue
            if dependency == 'posix':
                if os.name != 'posix':
                    raise ValueError('This operation requires POSIX locks and terminal/process-group support')
                facts[dependency] = {'available': True, 'version': os.name}
                continue
            executable = resolve(dependency)
            # Explicit --version only; no npm exec, credential reads or project scripts.
            result = subprocess.run([executable, '--version'], capture_output=True, text=True, timeout=10,
                                    env={**os.environ, 'OPENSPEC_TELEMETRY': '0', 'npm_config_update_notifier': 'false'})
            if result.returncode:
                raise ValueError(dependency + ' version check failed')
            text = result.stdout.strip().splitlines()[0][:120] if result.stdout.strip() else ''
            match = re.search(r'(\d+)\.(\d+)\.(\d+)', text)
            version = tuple(map(int, match.groups())) if match else None
            if dependency == 'node' and (not version or version < (22, 0, 0)):
                raise ValueError('Node >=22 is required')
            if dependency == 'openspec' and version != (1, 8, 0):
                raise ValueError('OpenSpec 1.8.0 is the verified native contract; review another version before use')
            facts[dependency] = {'available': True, 'version': text, 'path': executable}
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            facts[dependency] = {'available': False, 'issue': str(error)[:200]}
    capabilities = {}
    for name, deps in operations.items():
        issues = [{'code': 'DEPENDENCY_UNAVAILABLE', 'capability': name, 'message': facts[dep]['issue'],
                   'remediation': 'Install/configure the declared dependency explicitly; readiness never installs it.'}
                  for dep in deps if not facts[dep]['available']]
        if name == 'npm-bootstrap' and facts.get('npm', {}).get('available'):
            match = re.search(r'(\d+)\.(\d+)\.(\d+)', facts['npm']['version'])
            if not match or tuple(map(int, match.groups())) < (11, 21, 1):
                issues.append({'code': 'NPM_BOOTSTRAP_VERSION', 'capability': name, 'message': 'Bootstrap needs explicitly installed npm >=11.21.1.'})
        authorization = 'not-required'
        if name in AUTH:
            authorization = 'not-checked'
            if verify_auth and not issues:
                try:
                    result = subprocess.run(['gh', 'auth', 'status', '--hostname', 'github.com'], capture_output=True, timeout=10)
                    authorization = 'available' if result.returncode == 0 else 'unavailable'
                except (ValueError, OSError, subprocess.SubprocessError):
                    authorization = 'unavailable'
                if authorization == 'unavailable':
                    issues.append({'code': 'GITHUB_AUTH_REQUIRED', 'capability': name,
                                   'message': 'GitHub authorization is unavailable; ask the owner before sign-in.'})
            elif not issues:
                issues.append({'code': 'AUTHORIZATION_NOT_CHECKED', 'capability': name,
                               'message': 'External authorization is not checked by local readiness; preview the operation before use.'})
        capabilities[name] = {'status': 'unavailable' if issues else 'ready', 'issues': issues, 'authorization': authorization}
    issues = [issue for row in capabilities.values() for issue in row['issues']]
    if sys.version_info < (3, 10):
        issues.append({'code': 'PYTHON_VERSION', 'message': 'Python >=3.10 is required'})
    return {'status': 'ready' if not issues else 'unavailable', 'issues': issues,
            'python': {'version': '.'.join(map(str, sys.version_info[:3])), 'minimum': '3.10'},
            'dependencies': facts, 'capabilities': capabilities,
            'limitations': ['Local dependency checks do not grant project-script, public-export or publishing permission.']}


def require(operation):
    result = check(operation, verify_auth=operation in AUTH)
    if result['status'] != 'ready':
        raise ValueError('; '.join(issue['message'] for issue in result['issues']))
    return result
