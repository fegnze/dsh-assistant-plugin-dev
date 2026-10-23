"""Local, deterministic version decisions; no scripts, network or delivery orchestration."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile

from delivery import git, snapshot


VERSION = re.compile(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', re.ASCII)


def _version(value):
    if not isinstance(value, str) or not VERSION.fullmatch(value):
        raise ValueError('Version requires an explicit decision: only plain x.y.z can be inferred')
    return tuple(int(part) for part in value.split('.'))


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate manifest key requires manual review')
        result[key] = value
    return result


def _manifest(raw):
    package = json.loads(raw.decode('utf-8'), object_pairs_hook=_pairs)
    if not isinstance(package, dict):
        raise ValueError('Manifest must be a JSON object')
    _version(package.get('version'))
    return package


def _read(path):
    manifest = path / 'package.json'
    # Do not follow a substituted symlink, including one created after snapshot.
    fd = os.open(manifest, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ValueError('Manifest must be a regular file')
        raw = stream.read()
    return raw, info


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _decision(path, state, raw):
    current = _manifest(raw)['version']
    manifest_path = '/'.join(part for part in (state['prefix'], 'package.json') if part)
    # ls-tree distinguishes an absent manifest from a failed git operation.
    repo = Path(git(path, 'rev-parse', '--show-toplevel').decode().strip())
    exists = git(repo, 'ls-tree', '-z', state['head'], '--', manifest_path)
    previous = _manifest(git(repo, 'show', state['head'] + ':' + manifest_path))['version'] if exists else None
    if previous is None:
        status, target = 'initial_version', current
    elif _version(current) > _version(previous):
        status, target = 'already_bumped', current
    elif _version(current) < _version(previous):
        raise ValueError('Manifest version is below HEAD; explicit decision required')
    elif not state['dirty']:
        status, target = 'unchanged', current
    else:
        major, minor, patch = _version(current)
        status, target = 'bump_required', f'{major}.{minor}.{patch + 1}'
    return {**state, 'status': status, 'currentVersion': current, 'headVersion': previous,
            'targetVersion': target, 'strategy': 'patch'}


def plan(path):
    """Read-only plan bound to the same content/mode/HEAD baseline as commit-plan."""
    path = Path(path).resolve()
    before = snapshot(path)
    raw, info = _read(path)
    result = _decision(path, before, raw)
    if snapshot(path) != before or _identity((path / 'package.json').lstat()) != _identity(info):
        raise ValueError('Stale version baseline during planning')
    return result


def _replace_version(raw, target):
    """Locate the root version value without reserializing any other manifest bytes."""
    text = raw.decode('utf-8')
    decoder = json.JSONDecoder()
    pos = text.index('{') + 1
    while True:
        while text[pos].isspace() or text[pos] == ',':
            pos += 1
        if text[pos] == '}':
            break
        key, pos = decoder.raw_decode(text, pos)
        while text[pos].isspace():
            pos += 1
        pos += 1  # colon, already validated by _manifest
        while text[pos].isspace():
            pos += 1
        start = pos
        _, pos = decoder.raw_decode(text, pos)
        if key == 'version':
            return (text[:start] + json.dumps(target) + text[pos:]).encode('utf-8')
    raise ValueError('Missing manifest version')


def bump(path, baseline):
    """Apply a patch decision only to the exact reviewed baseline, under a local lock."""
    path = Path(path).resolve()
    if not isinstance(baseline, str) or not re.fullmatch(r'[a-f0-9]{64}', baseline):
        raise ValueError('Invalid version baseline')
    # Stable lock outside project payload; never unlink a lock another waiter may hold.
    git_dir = Path(git(path, 'rev-parse', '--absolute-git-dir').decode().strip())
    lock = git_dir / ('devkit-version-' + hashlib.sha256(str(path).encode()).hexdigest() + '.lock')
    fd = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'rb') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Concurrent version operation; re-plan before retry') from None
        result = plan(path)
        if result['baseline'] != baseline:
            raise ValueError('Stale version baseline')
        if result['status'] != 'bump_required':
            return result
        raw, info = _read(path)
        if _manifest(raw)['version'] != result['currentVersion'] or snapshot(path)['baseline'] != baseline:
            raise ValueError('Stale version baseline')
        updated = _replace_version(raw, result['targetVersion'])
        temporary = None
        try:
            tmp_fd, temporary = tempfile.mkstemp(prefix='.devkit-version-', dir=git_dir)
            with os.fdopen(tmp_fd, 'wb') as output:
                os.fchmod(output.fileno(), stat.S_IMODE(info.st_mode))
                output.write(updated)
                output.flush()
                os.fsync(output.fileno())
            latest, latest_info = _read(path)
            if snapshot(path)['baseline'] != baseline or latest != raw or _identity(latest_info) != _identity(info) or _identity((path / 'package.json').lstat()) != _identity(info):
                raise ValueError('Manifest changed before atomic version write')
            os.replace(temporary, path / 'package.json')
            temporary = None
        finally:
            if temporary is not None:
                # mkstemp returned this exact absolute path within the checked Git directory.
                target = Path(temporary)
                if target.parent != git_dir or not target.name.startswith('.devkit-version-'):
                    raise ValueError('Unexpected temporary manifest path')
                target.unlink()
        return {**result, 'status': 'bumped', 'previousBaseline': baseline,
                'baseline': snapshot(path)['baseline']}
