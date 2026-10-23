"""Exact-scope commits. Caller must explicitly authorize running Git hooks."""
import hashlib
import json
import os
from pathlib import Path
from processes import ProcessAdapter
subprocess = ProcessAdapter()

# The workspace pre-commit hook admits dsh-plugins/ commits only when this marker is set.
COMMIT_MARKER = 'DSH_DEVKIT_COMMIT'


def git(path, *args, env=None):
    r = subprocess.run(['git', *args], cwd=path, capture_output=True, timeout=60, env=env)
    if r.returncode:
        raise ValueError('Git operation failed (output withheld)')
    return r.stdout


def snapshot(path):
    path = path.resolve()
    repo = Path(git(path, 'rev-parse', '--show-toplevel').decode().strip()).resolve()
    prefix = path.relative_to(repo).as_posix()
    # Refuse any existing staged change, including unrelated work.
    if git(repo, 'diff', '--cached', '--name-only', '-z'):
        raise ValueError('Index must be empty before preparing a delivery')
    names = git(path, 'ls-files', '--cached', '--others', '--exclude-standard', '-z', '--', '.').split(b'\0')
    rows = []
    for raw in sorted(set(names)):
        if not raw:
            continue
        name = raw.decode('utf-8')
        p = path / name
        if p.is_symlink():
            raise ValueError('Symlink requires manual review')
        if not p.resolve().is_relative_to(path):
            raise ValueError('File outside project')
        if p.exists() and not p.is_file():
            raise ValueError('Submodules and non-files require manual review')
        rows.append([name, hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None,
                     p.stat().st_mode & 0o777 if p.exists() else None])
    head = git(repo, 'rev-parse', 'HEAD').decode().strip()
    payload = {'head': head, 'prefix': prefix, 'files': rows}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    return {'baseline': digest, 'head': head, 'prefix': prefix, 'fileCount': len(rows),
            'dirty': bool(git(path, 'status', '--porcelain', '--', '.'))}


def commit(path, baseline, message, workspace=None, *, co_author=None, emit=None):
    current = snapshot(path)
    if current['baseline'] != baseline:
        raise ValueError('Stale delivery baseline')
    if not current['dirty']:
        return {'status': 'unchanged', 'commit': current['head']}
    if not message or len(message) > 500 or '\n' in message:
        raise ValueError('Invalid commit subject')
    from observer import Observation
    if co_author is not None and (not isinstance(co_author, str) or not co_author or '\n' in co_author or '\r' in co_author):
        raise ValueError('Invalid configured co-author')
    wf = Observation('dsh-dev-commit', '提交插件工程', ['核对基线', '提交工程'], source='cli', target=path.name, emit=emit)
    wf.start('核对基线')
    wf.end('核对基线')
    wf.start('提交工程')
    try:
        git(path, 'add', '--', '.')
        # --only prevents unrelated staged paths from being committed if another process
        # touches the index. Git hooks may execute; CLI requires explicit authorization.
        trailers = ['-m', 'Co-Authored-By: ' + co_author] if co_author else []
        git(path, 'commit', '--only', '-m', message, *trailers, '--', '.',
            env={**os.environ, COMMIT_MARKER: '1'})
        result = git(path, 'rev-parse', 'HEAD').decode().strip()
        wf.end('提交工程')
        wf.done('success')
        return {'status': 'committed', 'commit': result, 'runId': wf.run_id}
    except Exception:
        wf.end('提交工程', 'error', 'Git commit failed; inspect index before retry')
        wf.done('error', 'Commit failed')
        raise
