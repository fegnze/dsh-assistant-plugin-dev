"""Read-only migration inventory. Actual migration remains an owner-reviewed operation."""
import hashlib
import json
from pathlib import Path
import settings


def preview(config_path, state_dir):
    config_path, state_dir = Path(config_path).resolve(), Path(state_dir).resolve()
    raw = config_path.read_bytes()
    source = json.loads(raw)
    workspace = (config_path.parent / source['workspace']).resolve()
    proposed = {**source, 'workspace': str(workspace)}
    settings.validate(config_path, proposed)
    rows = []
    if state_dir.exists():
        if not state_dir.is_dir():
            raise ValueError('Recovery source must be a directory')
        for path in sorted(state_dir.iterdir()):
            if path.is_symlink() or not path.is_file() or path.suffix != '.json':
                raise ValueError('Unexpected recovery entry; manual review required')
            data = path.read_bytes()
            if len(data) > 1024 * 1024:
                raise ValueError('Recovery record exceeds limit')
            value = json.loads(data)
            if not isinstance(value, dict):
                raise ValueError('Invalid recovery record')
            rows.append({'name': path.name, 'sha256': hashlib.sha256(data).hexdigest(),
                         'status': value.get('status'), 'repository': value.get('repository'),
                         'commit': value.get('commit'), 'version': value.get('version')})
    return {'status': 'preview', 'sourceConfigSha256': hashlib.sha256(raw).hexdigest(),
            'proposedConfig': proposed, 'releaseRecords': rows, 'fileCount': len(rows),
            'limitations': ['No destination created. Recheck source hashes before an explicit migration.',
                           'Keep every pending dispatch intent and exact run record; never redispatch because of migration.']}
