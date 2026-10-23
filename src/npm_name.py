"""Public, credential-free npm name preflight for new projects."""
import http.client
import urllib.parse


REGISTRY_HOST = 'registry.npmjs.org'
TIMEOUT_SECONDS = 10
UNAVAILABLE = 'Cannot verify npm package name availability; check network access and retry create.'
OCCUPIED = 'npm package name is already occupied; choose a different plugin name.'


def require_available(name):
    # A fresh direct HTTPS connection ignores npm config, credentials, proxies,
    # global urllib openers and redirects. Status alone suffices; never read or
    # expose registry metadata (including owners) or remote error details.
    connection = http.client.HTTPSConnection(REGISTRY_HOST, timeout=TIMEOUT_SECONDS)
    try:
        connection.request('GET', '/' + urllib.parse.quote(name, safe=''),
                           headers={'Accept': 'application/json'})
        response = connection.getresponse()
        status = response.status
        response.close()
    except (OSError, http.client.HTTPException):
        raise ValueError(UNAVAILABLE) from None
    finally:
        connection.close()
    if status == 404:
        return
    if status == 200:
        raise ValueError(OCCUPIED)
    raise ValueError(UNAVAILABLE)
