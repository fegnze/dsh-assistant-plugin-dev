"""First npm publication of a new package: guided browser sign-in, staged publish, Trusted Publisher.

Trusted Publisher can only bind an existing package. npm reserves `0.0.0-stage` for its own staged
publishing: `npm stage publish` of a package that does not exist yet creates that placeholder and
holds the real version until a maintainer approves it with 2FA. So the first release is the real,
reviewed package, packed from the exact synchronized commit, without provenance. Binding is not
validation: first delivery also needs an explicitly owner-authorized completion version actually
published through OIDC within npm's two-day validation window, not an uncertain future feature update.

Every npm credential lives in a private temporary userconfig, is never printed, and is revoked with
`npm logout` before the directory is removed. The owner only completes the browser sign-in and the
2FA approval; the tool opens those pages itself.
"""
import json
from pathlib import Path
import re
import shutil
from processes import ProcessAdapter
subprocess = ProcessAdapter()
import tempfile
import time

# Require an explicitly installed compatible npm; never download it implicitly.
# Kept as an optional argv prefix for tests/embedders; production uses configured npm.
NPM = []
# Only complete URLs: a terminator must follow, since output can split a URL across reads.
URL = re.compile(r'(https://www\.npmjs\.com/[^\s\x1b]+)[\s\x1b]')
STAGE_ID = re.compile(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}')


def npm(args, cwd, userconfig, registry, opener, say, timeout=600):
    """Run npm on a pseudo-terminal, opening every npm sign-in/2FA page it prints.

    npm waits for web 2FA (otplease) only when stdin and stdout are TTYs; on a pipe it fails with
    EOTP at once. `--browser=false` makes npm print the page instead of asking for ENTER, and this
    function opens it, so the owner only acts in the browser.
    """
    import os
    import pty
    import select
    command = [*NPM, 'npm', *args, '--registry=' + registry, '--userconfig=' + str(userconfig), '--browser=false']
    master, slave = pty.openpty()
    try:
        proc = subprocess.Popen(command, cwd=cwd, stdin=slave, stdout=slave, stderr=slave, close_fds=True,
                                start_new_session=True)
    finally:
        os.close(slave)
    buffer, opened, deadline = '', set(), time.monotonic() + timeout
    try:
        while True:
            if time.monotonic() > deadline:
                raise ValueError(f'npm {args[0]} timed out waiting for browser authentication')
            ready, _, _ = select.select([master], [], [], 1)
            if ready:
                try:
                    chunk = os.read(master, 4096).decode(errors='replace')
                except OSError:  # EIO once the child closes the terminal
                    chunk = ''
                if not chunk:
                    # EOF may precede waitpid visibility; do not kill a normally exiting npm.
                    try:
                        proc.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        pass
                    break
                buffer += chunk
                for url in URL.findall(buffer):
                    if url not in opened and ('/login' in url or '/auth' in url):
                        opened.add(url)
                        say('请在已打开的浏览器页面完成 npm 登录或二次验证')
                        opener(url)
            elif proc.poll() is not None:
                break
    finally:
        os.close(master)
        if proc.poll() is None:  # timeout or interruption: stop npm and everything it spawned
            import signal
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except PermissionError:
                # A denied group signal must not mask the original timeout/error.
                # Fall back to the owned child; this does not prove descendants stopped.
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
            proc.wait()
    text = buffer.replace('\r\n', '\n')
    if proc.wait():
        tail = re.sub(r'npm_[A-Za-z0-9]{20,}', '[token]', '\n'.join(text.strip().splitlines()[-5:]))
        raise ValueError(f'npm {args[0]} failed: {tail}')
    return text


def export(path, tree, target):
    """Write one exact git tree (never the working tree) into `target`.

    `tree` is the project tree that sync-plan proved identical to the GitHub commit.
    """
    from delivery import git
    # From a subdirectory git archive keeps only that subdirectory's slice of the tree.
    root = git(path, 'rev-parse', '--show-toplevel').decode().strip()
    archive = git(root, 'archive', '--format=tar', tree)
    target.mkdir()
    subprocess.run(['tar', '-x', '-C', str(target)], input=archive, check=True, timeout=60)


def _export_targets(value):
    """Yield concrete package paths declared by any npm exports condition."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _export_targets(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _export_targets(item)


def _pack_files(target):
    """Return npm's actual pack inventory, with lifecycle scripts disabled."""
    result = subprocess.run([*NPM, 'npm', 'pack', '--dry-run', '--json', '--ignore-scripts'],
                            cwd=target, capture_output=True, text=True, timeout=300, check=True)
    try:
        data = json.loads(result.stdout[result.stdout.find('['):])
        return {row['path'] for row in data[0]['files']}
    except (ValueError, IndexError, KeyError, TypeError) as error:
        raise ValueError('Unable to inspect exported npm package inventory') from error


def prepare_export(path, tree, target):
    """Build and inspect an exact export before it can reach npm stage publish.

    The reviewed project's own ``npm test`` is the only enabled lifecycle execution.  It runs in
    the temporary git export, so generated files never alter the checkout or the synchronized tree.
    The subsequent pack inspection is script-free and checks the actual npm inventory, including all
    manifest export targets, rather than trusting ``files`` or the filesystem alone.
    """
    export(path, tree, target)
    manifest = json.loads((target / 'package.json').read_text(encoding='utf-8'))
    test = (manifest.get('scripts') or {}).get('test')
    if not test:
        raise ValueError('Exported project must declare a test script before staging')
    env = {'npm_config_ignore_scripts': 'false', 'npm_config_update_notifier': 'false',
           'npm_config_fund': 'false'}
    import os
    run_env = os.environ.copy()
    run_env.update(env)
    if manifest.get('dependencies') or manifest.get('devDependencies'):
        if not (target / 'package-lock.json').is_file():
            raise ValueError('Exported project dependencies require package-lock.json before staging')
        installed = subprocess.run([*NPM, 'npm', 'ci', '--ignore-scripts'], cwd=target, env=run_env,
                                   capture_output=True, text=True, timeout=600)
        if installed.returncode:
            raise ValueError('Exported project dependency installation failed before staging')
    result = subprocess.run([*NPM, 'npm', 'test'], cwd=target, env=run_env,
                            capture_output=True, text=True, timeout=600)
    if result.returncode:
        raise ValueError('Exported project tests failed before staging')
    packed = _pack_files(target)
    missing = []
    for declared in _export_targets(manifest.get('exports', {})):
        if not declared.startswith('./'):
            continue
        relative = declared[2:]
        candidate = (target / relative).resolve()
        if not candidate.is_relative_to(target.resolve()):
            missing.append(declared)
            continue
        if '*' in relative:
            prefix, suffix = relative.split('*', 1)
            if not any(name.startswith(prefix) and name.endswith(suffix) for name in packed):
                missing.append(declared)
        elif relative not in packed or not (target / relative).is_file():
            missing.append(declared)
    if missing:
        raise ValueError('npm pack is missing required export(s): ' + ', '.join(sorted(set(missing))))
    return packed


def find_stage(*outputs):
    """The single stage id printed by `npm stage publish` / `npm stage list` for a brand-new package."""
    ids = {i.lower() for text in outputs for i in STAGE_ID.findall(text)}
    if len(ids) != 1:
        raise ValueError(f'Expected one staged version, found {len(ids)}; review with npm stage list')
    return ids.pop()


REVIEWING = re.compile(r'review|pending|scan|process|queue', re.I)


def staged_entries(run, name, version):
    """Staged records for exactly name@version, from `npm stage list --json`."""
    text = run(['stage', 'list', name, '--json'], timeout=120)
    start = min([i for i in (text.find('['), text.find('{')) if i != -1], default=-1)
    data = json.loads(text[start:]) if start != -1 else []
    rows = data if isinstance(data, list) else data.get('objects') or []
    return [r for r in rows if isinstance(r, dict) and r.get('packageName') == name and r.get('version') == version]


def await_review(run, stage_id, say, sleep=time.sleep, attempts=60, pause=20):
    """Wait until npm's automated review lets the staged version be approved (status no longer reviewing)."""
    for i in range(attempts):
        text = run(['stage', 'view', stage_id, '--json'], timeout=120)
        status = str(json.loads(text[text.find('{'):]).get('status', '')) if '{' in text else ''
        # Status values are not documented; an unknown or missing one falls through to approve,
        # whose 409 "automated review hasn't finished" is retried.
        if not REVIEWING.search(status):
            return status
        if i == 0:
            say(f'等待 npm 自动审核完成（当前状态 {status or "未知"}）')
        sleep(pause)
    raise ValueError('npm automated review did not finish in time; rerun npm-bootstrap later to resume')


def approve(run, stage_id):
    """Approve once. A failure is reported, never retried: each retry would ask the owner for 2FA again."""
    try:
        return run(['stage', 'approve', stage_id])
    except ValueError as error:
        if 'automated review' in str(error):
            raise ValueError('npm automated review still running; ask the owner before rerunning npm-bootstrap') from None
        raise


def state(name, version, registry):
    """'absent' (no package), 'placeholder' (only npm's 0.0.0-stage), 'published' (target version live) or 'other'."""
    import urllib.error
    import urllib.parse
    import urllib.request
    try:
        with urllib.request.urlopen(registry.rstrip('/') + '/' + urllib.parse.quote(name, safe=''), timeout=30) as response:
            versions = set(json.loads(response.read()).get('versions', {}))
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return 'absent'
        raise ValueError('npm registry lookup failed') from None
    if version in versions:
        return 'published'
    return 'placeholder' if versions <= {'0.0.0-stage'} else 'other'


def confirmations(current):
    """Browser confirmations the owner will be asked for, in order, for a given registry state."""
    steps = ['npm 登录']
    if current != 'published':
        steps.append('批准暂存版本（二次验证）')
    steps.append('绑定 Trusted Publisher（二次验证）')
    return steps


def preview(path, package, c, entry):
    """Read-only: what npm-bootstrap would do and which browser confirmations it needs. Opens nothing."""
    from github import sync_plan
    plan = sync_plan(path, entry['repository'], c['branch'], c['githubOwner'])
    name, version = package['name'], package['version']
    current = state(name, version, c['registry'])
    if current == 'other':
        return {'status': 'exists', 'package': name, 'confirmations': []}
    return {'status': 'ready' if plan['action'] == 'unchanged' else 'sync_required',
            'package': name, 'version': version, 'registry': current, 'commit': plan['remote']['commit'],
            'confirmations': confirmations(current),
            'ask': 'Ask the owner with the session ask-user tool (not trailing reply text) before running; open nothing until they agree.'}


def bootstrap(path, package, c, entry, opener, say, sleep=time.sleep):
    """Resumable: each run continues from what the registry already shows.

    Each npm call that needs the owner opens exactly one browser page; nothing is retried, so the
    owner is never asked more often than `confirmations()` announced.
    """
    from github import sync_plan
    plan = sync_plan(path, entry['repository'], c['branch'], c['githubOwner'])
    if plan['action'] != 'unchanged':
        raise ValueError('Synchronize the reviewed project to GitHub first')
    name, version, registry = package['name'], package['version'], c['registry']
    current = state(name, version, registry)
    if current == 'other':
        return {'status': 'exists', 'package': name,
                'guidance': 'Package already has releases; use release. Bind Trusted Publisher in its settings if OIDC fails.'}
    work = Path(tempfile.mkdtemp(prefix='dsh-devkit-npm-'))
    userconfig = work / 'npmrc'
    userconfig.touch(mode=0o600)
    steps = []
    run = lambda args, cwd=work, timeout=900: npm(args, cwd, userconfig, registry, opener, say, timeout)
    try:
        say('打开浏览器登录 npm')
        run(['login', '--auth-type=web'])
        account = run(['whoami'], timeout=60).strip().splitlines()[-1]
        if account != c['npmAccount']:
            raise ValueError(f'Signed in as {account}, expected {c["npmAccount"]}')
        steps.append('login')
        if current != 'published':
            pending = staged_entries(run, name, version)  # Public 404 does not imply no private stage exists.
            if len(pending) > 1:
                raise ValueError(f'Several staged {name}@{version}; reject extras with npm stage reject first')
            if pending:
                if pending[0].get('shasum') and pending[0]['shasum'] != _shasum(path, plan['localTree'], work):
                    raise ValueError('Staged tarball differs from the synchronized tree; reject it before restaging')
                stage_id = pending[0]['id']
                say(f'继续已暂存的 {name}@{version}')
            else:
                prepare_export(path, plan['localTree'], work / 'package')
                say(f'暂存发布 {name}@{version}（来自已同步提交 {plan["remote"]["commit"][:7]}）')
                staged = run(['stage', 'publish', '--access', 'public', '--ignore-scripts'], cwd=work / 'package')
                stage_id = find_stage(staged) if STAGE_ID.search(staged) else find_stage(run(['stage', 'list', name], timeout=120))
            steps.append('staged')
            await_review(run, stage_id, say, sleep)
            say('批准暂存版本，需在浏览器完成二次验证')
            approve(run, stage_id)
            steps.append('approved')
        # `npm trust list` asks for 2FA too, so it is neither a pre-check nor a read-back:
        # one confirmation binds, but only a timely real OIDC publish can validate the trust.
        say('绑定 Trusted Publisher')
        try:
            run(['trust', 'github', name, '--repository=' + entry['repository'], '--file=' + c['workflow'],
                 '--allow-publish', '--yes'])  # npm >= 11.21 requires an explicit permission; publish.yml runs npm publish
        except ValueError as error:
            if 'already' not in str(error).lower() and 'exists' not in str(error).lower():
                raise
        steps.append('trusted_publisher_bound')
        return {'status': 'published_package', 'package': name, 'version': version,
                'trustedPublisher': 'pending_validation',
                'commit': plan['remote']['commit'], 'steps': steps,
                'next': 'First delivery is incomplete: validate Trusted Publisher with a real OIDC publish '
                        'within 2 days of the new trust binding (check npm for the actual deadline; '
                        'an existing binding may have less time). Obtain explicit owner authorization '
                        'for the OIDC completion version; never auto-bump or wait for an uncertain future '
                        'feature update. Commit and synchronize that approved version, then run release '
                        'for its exact commit and verify the CI run, registry bytes and provenance. '
                        'Releasing this same version only returns already_published after byte checks; '
                        'it and dry-run do not validate OIDC. The local bootstrap publish has no provenance. '
                        'If the validation window expires, trust may expire; review npm status and seek '
                        'owner approval before any rebind or authentication retry.'}
    except (ValueError, subprocess.CalledProcessError) as error:
        raise ValueError(f'{error}; completed steps: {steps or "none"}; ask the owner before rerunning npm-bootstrap') from None
    finally:
        # Revoke the session token server-side, then remove every local trace.
        if userconfig.exists() and userconfig.stat().st_size:
            subprocess.run([*NPM, 'npm', 'logout', '--registry=' + registry, '--userconfig=' + str(userconfig)],
                           cwd=work, capture_output=True, timeout=120)
        shutil.rmtree(work, ignore_errors=True)


def _shasum(path, tree, work):
    """sha1 of the tarball npm would build from the synchronized tree, as npm reports it."""
    target = work / 'shasum'
    prepare_export(path, tree, target)
    r = subprocess.run([*NPM, 'npm', 'pack', '--dry-run', '--json', '--ignore-scripts'], cwd=target,
                       capture_output=True, text=True, timeout=300, check=True)
    return json.loads(r.stdout[r.stdout.find('['):])[0]['shasum']
