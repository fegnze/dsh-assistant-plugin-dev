"""Bounded local validation with optional observations and no publishing."""
import hashlib
import json
from pathlib import Path
from processes import ProcessAdapter
subprocess = ProcessAdapter()
import sys
from documentation import require


def validate(path, workspace, source='cli', emit=None):
    from observer import Observation
    steps = ['测试', '检查发布文件']
    wf = Observation('dsh-dev-validate', 'DSH 插件验证', steps, source=source, target=path.name, emit=emit)
    evidence = {}
    current = 0
    try:
        wf.start(steps[0])
        from openspec_workflow import check
        evidence['openspec'] = check(workspace, target=path.resolve().relative_to(workspace.resolve()).as_posix())
        evidence['documentation'] = require(path)
        result = subprocess.run(['npm', 'test'], cwd=path, capture_output=True, timeout=180)
        if result.returncode:
            raise ValueError('Project tests failed')
        evidence['tests'] = 'passed'
        wf.end(steps[0])
        current = 1
        wf.start(steps[1])
        result = subprocess.run(['npm', 'pack', '--dry-run', '--json', '--ignore-scripts'], cwd=path,
                                capture_output=True, timeout=60)
        if result.returncode:
            raise ValueError('Package audit failed')
        pack = json.loads(result.stdout)[0]
        files = pack['files']
        require(path, {row['path'] for row in files})
        hashes = {}
        for row in files:
            name = row['path']
            target = (path / name).resolve()
            if not target.is_relative_to(path.resolve()) or not target.is_file():
                raise ValueError('Payload escapes project')
            parts = Path(name).parts
            if any(p in ('.git', 'node_modules', '.npmrc', '.env') or p.startswith('.env.') for p in parts):
                raise ValueError('Forbidden payload path')
            data = target.read_bytes()
            if b'-----BEGIN PRIVATE KEY-----' in data or b'-----BEGIN RSA PRIVATE KEY-----' in data:
                raise ValueError('Private key in payload')
            hashes[name] = hashlib.sha256(data).hexdigest()
        evidence['payload'] = {'fileCount': len(files), 'sha256ByPath': hashes}
        evidence['limitations'] = ['Payload scan detects forbidden paths and private-key headers, not all credentials.',
                                    'Host and UI runtime acceptance was not performed.']
        wf.end(steps[1])
        wf.done('success')
        return {'runId': wf.run_id, 'status': 'validated', **evidence}
    except Exception:
        wf.end(steps[current], 'error', 'Validation failed; project output withheld')
        for step in steps[current + 1:]:
            wf.skip(step)
        wf.done('error', 'Validation failed')
        raise ValueError('Validation failed; inspect local project tests and package allowlist') from None
