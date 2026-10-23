"""Read-only GitHub preflight, exact remote tree comparison, guided authorization."""
import json
from processes import ProcessAdapter, resolve
subprocess = ProcessAdapter()
import re
from delivery import git, snapshot


def local_tree(path):
    state = snapshot(path)
    if state['dirty']:
        raise ValueError('Commit project changes before synchronization')
    prefix = state['prefix']
    tree = git(path, 'rev-parse', 'HEAD^{tree}' if prefix == '.' else 'HEAD:' + prefix).decode().strip()
    return state, tree


def sync_plan(path, repository, branch, owner):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', branch):
        raise ValueError('Unsupported repository or branch')
    state, tree = local_tree(path)
    remote = inspect_remote(path, repository, branch, owner)
    action = 'initial_export' if remote['commit'] is None else 'unchanged' if tree == remote['tree'] else 'review_required'
    return {'localBaseline': state['baseline'], 'localTree': tree, 'remote': remote, 'action': action}


def sync_apply(path, repository, branch, owner, baseline, remote_sha):
    plan = sync_plan(path, repository, branch, owner)
    if plan['localBaseline'] != baseline or (plan['remote']['commit'] or 'empty') != remote_sha:
        raise ValueError('Synchronization baseline changed')
    if not plan['remote']['canPush']:
        raise ValueError('GitHub push permission required')
    if plan['remote']['commit'] is None:
        return _initial_push(path, repository, branch, baseline)
    if plan['action'] == 'unchanged':
        return {'status': 'unchanged', 'commit': remote_sha}
    # A clean export is built on the observed remote commit, preserving its history.
    # Never force-push; concurrent remote updates are rejected by Git.
    url = 'https://github.com/' + repository + '.git'
    auth = auth_arguments()
    git(path, *auth, 'fetch', '--no-tags', url, branch)
    fetched = git(path, 'rev-parse', 'FETCH_HEAD').decode().strip()
    if fetched != remote_sha:
        raise ValueError('Remote changed while fetching')
    current, tree = local_tree(path)
    if current['baseline'] != baseline:
        raise ValueError('Local baseline changed while fetching')
    commit = git(path, 'commit-tree', tree, '-p', remote_sha, '-m', '[chore] ' + path.name + ': 同步已审查工程').decode().strip()
    git(path, *auth, 'push', url, commit + ':refs/heads/' + branch)
    return {'status': 'pushed', 'commit': commit, 'tree': tree}


def auth_arguments():
    # Git's credential helper contract executes a shell; quote only the resolved executable.
    import shlex
    return ['-c', 'credential.helper=', '-c', 'credential.helper=!' + shlex.quote(resolve('gh')) + ' auth git-credential']


def _initial_push(path, repository, branch, baseline):
    # Empty repository: the export becomes the root commit. Pushing to a branch that does not
    # exist cannot overwrite history; a concurrent first push makes this one fail.
    current, tree = local_tree(path)
    if current['baseline'] != baseline:
        raise ValueError('Local baseline changed')
    commit = git(path, 'commit-tree', tree, '-m', '[chore] ' + path.name + ': 初始导出已审查工程').decode().strip()
    git(path, *auth_arguments(), 'push', 'https://github.com/' + repository + '.git', commit + ':refs/heads/' + branch)
    return {'status': 'pushed', 'commit': commit, 'tree': tree, 'initial': True}


def create_repository(path, repository, owner, description, homepage):
    if repository.split('/')[0] != owner:
        raise ValueError('Repository owner differs from configured owner')
    if json.loads(gh(['api', 'user'], path))['login'] != owner:
        raise ValueError('gh account differs from configured owner')
    found = subprocess.run(['gh', 'api', 'repos/' + repository], cwd=path, capture_output=True, text=True, timeout=60)
    if found.returncode == 0:
        if json.loads(found.stdout)['full_name'].lower() != repository.lower():
            raise ValueError('Repository name redirects elsewhere; review before creating')
        return {'status': 'exists', 'repository': repository}
    if '"status":"404"' not in found.stdout.replace(' ', ''):
        raise ValueError('GitHub lookup failed; check gh login')
    # Empty public repository: the first sync supplies the root commit.
    gh(['repo', 'create', repository, '--public', '--description', description, '--homepage', homepage], path)
    return {'status': 'created', 'repository': repository}


def gh(args, path):
    result = subprocess.run(['gh', *args], cwd=path, capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise ValueError('GitHub operation failed; check gh login and repository permissions')
    return result.stdout.strip()


def inspect_remote(path, repository, branch, owner):
    if repository.split('/')[0] != owner:
        raise ValueError('Repository owner differs from configured owner')
    user = json.loads(gh(['api', 'user'], path))['login']
    repo = json.loads(gh(['api', 'repos/' + repository], path))
    if repo['full_name'].lower() != repository.lower():
        raise ValueError('Repository redirected; review configured target')
    base = {'account': user, 'repository': repository, 'branch': branch,
            'canPush': repo.get('permissions', {}).get('push', False)}
    if _empty(path, repository):
        return {**base, 'commit': None, 'tree': None, 'empty': True}
    commit = json.loads(gh(['api', f'repos/{repository}/commits/{branch}'], path))
    return {**base, 'commit': commit['sha'], 'tree': commit['commit']['tree']['sha']}


def _empty(path, repository):
    # GitHub answers 409 "Git Repository is empty" for repositories without commits.
    r = subprocess.run(['gh', 'api', f'repos/{repository}/commits?per_page=1'], cwd=path,
                       capture_output=True, text=True, timeout=60)
    return r.returncode != 0 and 'Git Repository is empty' in r.stdout
