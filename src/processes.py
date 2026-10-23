"""Explicit executable resolution for the short-lived Python CLI (no shell strings)."""
import contextvars
import os
from pathlib import Path
import shutil
import subprocess as _subprocess

_EXECUTABLES = contextvars.ContextVar('executables', default={})
ALLOWED = {'git', 'node', 'npm', 'gh', 'openspec', 'tar'}


def configure(executables=None):
    value = executables or {}
    if not isinstance(value, dict) or set(value) - ALLOWED:
        raise ValueError('Unsupported executable configuration')
    for key, command in value.items():
        if not isinstance(command, str) or not command or '\x00' in command:
            raise ValueError('Executable must be a path or command name')
        if ('/' in command or '\\' in command) and not Path(command).is_absolute():
            raise ValueError('Executable paths must be absolute')
    _EXECUTABLES.set(dict(value))


def resolve(command):
    command = _EXECUTABLES.get().get(command, command)
    found = shutil.which(command)
    if not found:
        raise ValueError('Required executable unavailable: ' + Path(command).name)
    return str(Path(found).resolve())


def argv(args):
    if not isinstance(args, (list, tuple)) or not args:
        raise ValueError('Expected executable argument list')
    first = resolve(args[0]) if args[0] in ALLOWED else args[0]
    return [first, *args[1:]]


class ProcessAdapter:
    def run(self, args, **kwargs):
        if kwargs.get('shell'):
            raise ValueError('Shell command strings are not supported')
        return _subprocess.run(argv(args), **kwargs)

    def Popen(self, args, **kwargs):
        if kwargs.get('shell'):
            raise ValueError('Shell command strings are not supported')
        return _subprocess.Popen(argv(args), **kwargs)

    def __getattr__(self, key):
        return getattr(_subprocess, key)


subprocess = ProcessAdapter()
