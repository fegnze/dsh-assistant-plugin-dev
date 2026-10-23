"""Track an existing Actions run durably; querying never triggers a new release."""
import json
import os
from pathlib import Path
import re
import tempfile
from github import gh, sync_plan, local_tree


def resume(path, package, c, entry, root, run_id, expected_sha):
    """Reconcile one explicit run; never dispatch or change a version."""
    state = observe(path, entry['repository'], run_id, root, expected_sha)
    if state['workflow'] != '.github/workflows/' + c['workflow']:
        raise ValueError('Run workflow mismatch')
    if state['status'] != 'completed':
        return state
    if state['conclusion'] != 'success':
        return {**state, 'status': 'failed', 'guidance': 'Review Actions logs and authorization; no automatic redispatch.'}
    _, tree = local_tree(path)
    commit = json.loads(gh(['api', f"repos/{entry['repository']}/git/commits/{expected_sha}"], path))
    if commit['tree']['sha'] != tree:
        raise ValueError('Current source differs from the release run; restore reviewed source before reconciliation')
    registry = verify(package['name'], package['version'], c['registry'], entry['repository'])
    if registry['status'] != 'published':
        state['status'] = 'waiting_registry'
    else:
        state['payload'] = compare(path, package['name'], package['version'])
        state['publicationVerified'] = True
        state['status'] = 'verified'
        state['version'] = package['version']
    store(root, run_id, state)
    return state

from registry import verify
from payload import compare
from documentation import audit_pack


def release(path, package, c, entry, root, expected_sha):
    plan = sync_plan(path, entry['repository'], c['branch'], c['githubOwner'])
    if plan['action'] != 'unchanged' or plan['remote']['commit'] != expected_sha:
        raise ValueError('Synchronize and review the exact remote commit first')
    if not plan['remote']['canPush']:
        raise ValueError('Repository write permission required')
    if c['registry'].rstrip('/') != 'https://registry.npmjs.org':
        raise ValueError('Release currently supports official npm registry only')
    audit_pack(path)
    published = verify(package['name'], package['version'], c['registry'], entry['repository'])
    if published['status'] == 'published':
        proof = compare(path, package['name'], package['version'])
        return {'status': 'already_published', 'payload': proof, 'commit': expected_sha}
    workflow = path / '.github/workflows' / c['workflow']
    text = workflow.read_text()
    fence = 'test "$GITHUB_SHA" = "$EXPECTED_SHA"'
    if 'EXPECTED_SHA: ${{ inputs.expected_sha }}' not in text:
        raise ValueError('Workflow must bind expected_sha through environment, not shell interpolation')
    publish_position = text.find('npm publish')
    if fence not in text or publish_position < 0 or text.index(fence) > publish_position:
        raise ValueError('Workflow needs exact expected_sha fence before publishing; review workflow first')
    # Exclusive durable intent prevents automatic re-dispatch after crash or timeout.
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    import hashlib
    key = hashlib.sha256((entry['repository'] + ':' + package['version']).encode()).hexdigest()
    intent = root / (key + '.json')
    try:
        fd = os.open(intent, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return {'status': 'reconcile_required', 'intent': key,
                'guidance': 'Inspect GitHub workflow runs; never blindly retry a dispatch.'}
    with os.fdopen(fd, 'w') as stream:
        json.dump({'repository': entry['repository'], 'version': package['version'],
                   'commit': expected_sha, 'status': 'dispatch_intent'}, stream)
        stream.flush()
        os.fsync(stream.fileno())
    # Branch refs can race: workflow must fence expected_sha before any publish.
    since = _now_iso()
    gh(['workflow', 'run', c['workflow'], '--repo', entry['repository'], '--ref', c['branch'],
        '-f', 'expected_sha=' + expected_sha, '-f', 'dry_run=false'], path)
    dispatched = {'status': 'dispatched', 'intent': key, 'commit': expected_sha}
    run_id = find_run(path, entry['repository'], c['workflow'], expected_sha, since)
    if run_id is None:
        return {**dispatched, 'guidance': 'Run not found yet; find it in GitHub Actions and use release-resume. Do not redispatch.'}
    return {**dispatched, **watch(path, package, c, entry, root, run_id, expected_sha)}


def _now_iso():
    import datetime
    return (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=30)).strftime('%Y-%m-%dT%H:%M:%SZ')


def find_run(path, repository, workflow, sha, since, attempts=12, pause=5, sleep=None):
    """Identify the dispatched run by workflow, event, commit and creation time."""
    import time
    sleep = sleep or time.sleep
    for _ in range(attempts):
        runs = json.loads(gh(['api', f'repos/{repository}/actions/workflows/{workflow}/runs'
                                     f'?event=workflow_dispatch&head_sha={sha}&created=%3E%3D{since}'], path))['workflow_runs']
        if len(runs) == 1:
            return str(runs[0]['id'])
        if len(runs) > 1:
            raise ValueError('Several matching runs; reconcile manually with release-resume')
        sleep(pause)
    return None


def watch(path, package, c, entry, root, run_id, expected_sha, timeout=1200, pause=15, sleep=None):
    """Poll one known run to completion, then wait boundedly for the registry; never redispatches."""
    import time
    sleep, deadline = sleep or time.sleep, time.monotonic() + timeout
    while True:
        state = resume(path, package, c, entry, root, run_id, expected_sha)
        if state['status'] in ('verified', 'failed') or time.monotonic() > deadline:
            return state
        sleep(pause)


def store(root, run_id, value):
    if not re.fullmatch(r'[0-9]+', str(run_id)):
        raise ValueError('Invalid run id')
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(dir=root)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, ensure_ascii=False)
        os.replace(tmp, root / (str(run_id) + '.json'))
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def observe(path, repository, run_id, state_root, expected_sha=None):
    if not re.fullmatch(r'[0-9]+', str(run_id)):
        raise ValueError('Invalid run id')
    run = json.loads(gh(['api', f'repos/{repository}/actions/runs/{run_id}'], path))
    if run['repository']['full_name'].lower() != repository.lower():
        raise ValueError('Run repository mismatch')
    if expected_sha and run['head_sha'] != expected_sha:
        raise ValueError('Run commit mismatch')
    result = {'runId': str(run_id), 'repository': repository, 'commit': run['head_sha'],
              'workflow': run['path'], 'url': run['html_url'], 'status': run['status'],
              'conclusion': run.get('conclusion'), 'publicationVerified': False}
    store(state_root, run_id, result)
    return result
