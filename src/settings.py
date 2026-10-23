"""External user configuration, revision fenced; package content is immutable."""
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from contextlib import contextmanager

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REQUIRED = {'schemaVersion', 'workspace', 'githubOwner', 'npmAccount', 'registry', 'branch', 'workflow', 'projects'}
OPTIONAL = {'executables', 'coAuthor'}


def external(path, label='Configuration'):
    path = Path(path).expanduser().absolute()
    if path.is_symlink() or path.resolve().is_relative_to(PACKAGE_ROOT):
        raise ValueError(label + ' must be outside the package and not a symlink')
    return path.resolve()


def read(path):
    path = external(path)
    raw = path.read_bytes()
    return {'revision': hashlib.sha256(raw).hexdigest(), 'config': json.loads(raw)}


def validate(path, value):
    if not isinstance(value, dict) or not REQUIRED <= set(value) or set(value) - REQUIRED - OPTIONAL:
        raise ValueError('Configuration fields are invalid')
    if value['schemaVersion'] != 1 or value['registry'] != 'https://registry.npmjs.org/':
        raise ValueError('Only schema 1 and the official npm registry are supported')
    for key in ('githubOwner', 'npmAccount', 'branch'):
        if not isinstance(value[key], str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,99}', value[key]):
            raise ValueError('Invalid account or branch')
    if not isinstance(value['workflow'], str) or not re.fullmatch(r'[A-Za-z0-9_-]+\.ya?ml', value['workflow']):
        raise ValueError('Invalid workflow filename')
    if not isinstance(value['workspace'], str) or not value['workspace']:
        raise ValueError('Workspace is required')
    workspace = (Path(path).parent / value['workspace']).resolve()
    if not workspace.is_dir() or workspace.is_relative_to(PACKAGE_ROOT):
        raise ValueError('Workspace must exist outside the package')
    projects = value['projects']
    if not isinstance(projects, dict) or len(projects) > 100:
        raise ValueError('Invalid projects')
    for name, entry in projects.items():
        if not re.fullmatch(r'dsh-[a-z0-9]+(?:-[a-z0-9]+)*', name) or not isinstance(entry, dict) or set(entry) != {'path', 'repository'}:
            raise ValueError('Invalid project fields')
        if not isinstance(entry['path'], str) or not isinstance(entry['repository'], str):
            raise ValueError('Invalid project path or repository')
        target = (workspace / entry['path']).resolve()
        if target == workspace or not target.is_relative_to(workspace) or not (target / 'package.json').is_file():
            raise ValueError('Project must be within workspace and contain package.json')
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/' + re.escape(name), entry['repository']):
            raise ValueError('Repository name must match project')
    from processes import configure
    configure(value.get('executables'))
    author = value.get('coAuthor')
    if author is not None and (not isinstance(author, str) or not author or '\n' in author or '\r' in author):
        raise ValueError('Invalid co-author policy')
    return {**value, 'workspace': str(workspace)}


@contextmanager
def locked(path):
    # The stable lock is external too; never remove a lock another process may hold.
    import fcntl
    path = external(path)
    fd = os.open(str(path) + '.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'rb') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Concurrent configuration operation; re-read before retry') from None
        yield


def save(path, revision, value):
    path = external(path)
    validate(path, value)
    with locked(path):
        if read(path)['revision'] != revision:
            raise ValueError('Configuration changed; reload before saving')
        fd, tmp = tempfile.mkstemp(prefix='.assistant-config-', dir=path.parent)
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump(value, stream, ensure_ascii=False, indent=2)
                stream.write('\n')
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp, path)
        finally:
            target = Path(tmp)
            if target.exists() and target.parent == path.parent and target.name.startswith('.assistant-config-'):
                target.unlink()
        return read(path)
