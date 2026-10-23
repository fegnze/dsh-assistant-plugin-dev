"""Read-only exact-version registry checks. Never interpret network failure as absence."""
import json
import urllib.error
import urllib.parse
import urllib.request


def verify(name, version, registry, repository):
    url = registry.rstrip('/') + '/' + urllib.parse.quote(name, safe='') + '/' + urllib.parse.quote(version, safe='')
    if not url.startswith('https://'):
        raise ValueError('Registry must use HTTPS')
    request = urllib.request.Request(url, headers={'Accept': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read(2 * 1024 * 1024 + 1)
    except urllib.error.HTTPError as exc:
        exc.close()
        if exc.code == 404:
            return {'status': 'not_visible', 'name': name, 'version': version}
        raise ValueError('Registry refused query') from None
    except urllib.error.URLError:
        raise ValueError('Registry unavailable; publication state unknown') from None
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError('Registry metadata too large')
    data = json.loads(raw)
    if data.get('name') != name or data.get('version') != version:
        raise ValueError('Registry identity mismatch')
    repo = data.get('repository', {})
    repo = repo.get('url', '') if isinstance(repo, dict) else repo
    expected = 'https://github.com/' + repository
    if repo.removeprefix('git+').removesuffix('.git') != expected:
        raise ValueError('Published repository mismatch')
    dist = data.get('dist', {})
    return {'status': 'published', 'name': name, 'version': version,
            'integrity': dist.get('integrity'), 'shasum': dist.get('shasum'),
            'provenanceAdvertised': bool(dist.get('attestations', {}).get('provenance')),
            'limitations': ['Attestation cryptography and local tarball equivalence not verified.']}
