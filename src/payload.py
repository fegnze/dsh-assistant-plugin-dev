"""Compare registry tarball bytes against local publish files, without extraction."""
import base64
import hashlib
import io
import json
from processes import ProcessAdapter
subprocess = ProcessAdapter()
import tarfile
import urllib.parse
import urllib.request
from documentation import require

MAX = 32 * 1024 * 1024


def read_https(url):
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != 'https' or parsed.hostname != 'registry.npmjs.org' or parsed.username or parsed.password:
        raise ValueError('Unexpected npm endpoint')
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            raise ValueError('Registry redirect refused')
    with urllib.request.build_opener(NoRedirect).open(url, timeout=30) as response:
        data = response.read(MAX + 1)
    if len(data) > MAX:
        raise ValueError('Registry response exceeds limit')
    return data


def compare(path, name, version):
    metadata = json.loads(read_https('https://registry.npmjs.org/' + urllib.parse.quote(name, safe='') + '/' + urllib.parse.quote(version, safe='')))
    if metadata.get('name') != name or metadata.get('version') != version:
        raise ValueError('Package identity mismatch')
    dist = metadata['dist']
    data = read_https(dist['tarball'])
    integrity = 'sha512-' + base64.b64encode(hashlib.sha512(data).digest()).decode()
    if integrity != dist.get('integrity'):
        raise ValueError('Tarball integrity mismatch')
    result = subprocess.run(['npm', 'pack', '--dry-run', '--ignore-scripts', '--json'], cwd=path,
                            capture_output=True, timeout=60)
    if result.returncode:
        raise ValueError('Local pack inspection failed')
    expected = {f['path'] for f in json.loads(result.stdout)[0]['files']}
    require(path, expected)
    seen = set()
    total = 0
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
        for member in archive:
            if member.isdir():
                continue
            if not member.isfile() or not member.name.startswith('package/'):
                raise ValueError('Unexpected tar member')
            name_in_package = member.name[len('package/'):]
            if name_in_package in seen or name_in_package not in expected:
                raise ValueError('Unexpected or duplicate package file')
            total += member.size
            if total > MAX:
                raise ValueError('Expanded package exceeds limit')
            target = (path / name_in_package).resolve()
            if not target.is_relative_to(path.resolve()) or not target.is_file():
                raise ValueError('Unsafe local payload')
            if archive.extractfile(member).read() != target.read_bytes():
                raise ValueError('Published bytes differ from local payload')
            seen.add(name_in_package)
    if seen != expected:
        raise ValueError('Published file set differs')
    return {'status': 'identical', 'fileCount': len(seen), 'integrity': integrity,
            'provenanceAdvertised': bool(dist.get('attestations', {}).get('provenance'))}
