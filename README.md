# Plugin Development Assistant

English | [中文](<docs/zh.md>)

A portable DSH assistant bundle owning its Python engineering tools, native OpenSpec resources, scoped Skill and task prompts. It registers with `@fegnze/dsh-capability-manager` ≥0.2.0 <0.3.0 and requires the official **cordis** (creation) preset; it neither copies that preset nor creates a scheduler, HTTP server or MCP process.

## Install and configure

Use the official DSH plugin manager. Install a compatible capability-manager bundle first, then this package. This checkout is not evidence of a published npm package. Installation may require restart; the official application result is authoritative.

The Host plugin accepts three configuration fields:

- `pythonExecutable`: explicit interpreter path or executable name (no machine-specific default).
- `configPath`: absolute path to an external user configuration file.
- `stateDir`: absolute external directory holding durable release intent and run records. This is the **releases directory itself**, not its parent. It must not be under this package or a publishable project.

DSH 0.2.1-rc.2 does not automatically render a form from this ordinary `Config`; this package registers no configuration page. The official Settings **Open configuration file** action opens the provider-owned document in a native editor when available locally. To avoid manual profile editing, install a separate private configuration-only override bundle through the official plugin manager. Keep machine-specific paths outside this distributable package. See [Host configuration routes and portable example](<docs/host-configuration.md>).

See [configuration example](<docs/config.example.json>). Resolve `workspace` relative to the configuration file, not the package. Project paths stay within that workspace. Optional `executables` overrides git/node/npm/gh/openspec/tar by absolute paths or executable names; `coAuthor` is an optional user policy, not a bundled attribution. No account names or credentials are supplied by the package. Existing project registrations and recovery state are never discovered implicitly or copied at activation.

Select the assistant in the session input. The base handles preset compatibility, explicit binding, recovery and lifecycle. A started incompatible session needs a new session, not a copied preset. Missing configuration or local prerequisites prevents activation; an explicit selection is retained as blocked for an exact retry. Publishing is a separate capability and remains unchecked until its operation's preview; selecting the assistant grants no publication permission.

## Prerequisites

| Capability | Prerequisites |
|---|---|
| CLI | Python ≥3.10; install `requirements.txt` into the explicitly selected interpreter |
| Local development | PyYAML ≥6,<7, git, Node ≥22, npm, official OpenSpec **1.8.0** (the verified native contract) |
| GitHub queries/export/releases | gh with owner-authorized GitHub access; account, repository and push permission are rechecked |
| First publication | POSIX PTY/process groups, tar, explicitly installed npm ≥11.21.1 and owner confirmation for browser authentication |
| Version/config writes | POSIX advisory locks (`fcntl`) and atomic rename support |

No prerequisite is downloaded by readiness, activation or `npm exec`. The assistant never opens authentication pages from a Host tool. External npm/gh authorization is not implied by installed CLIs or configured account strings. Windows is not supported for lock/PTY-dependent capabilities.

## Tools and CLI

- `dsh_dev_query`: guide, projects, inspect, readiness, registry, remote and exact operation plans.
- `dsh_dev_operate`: create, validate, version bump, commit, public repository creation, export, release and recovery; also explicit native OpenSpec init/new helpers.
- `dsh-plugin-development`: scoped, on-demand Skill; no files copied into the user's Skill roots.

Ordinary mutating Host operations use the official sandbox policy and, unless already full-access, a current-turn approval. Public export and publication always need a separate current-turn approval, even in full-access mode; a refusal or `never` policy stops the operation and leaves the explicitly authorized manual CLI route. Requests bind exact arguments and the external configuration revision. No model-supplied confirmation boolean grants permission. Non-full-access reads require complete process confinement. Side effects include project scripts/hooks, caches, remote export/publication and durable state writes; release status/resume are **not** strictly read-only.

For other Agents, invoke the same one-command CLI through their authorized execution tool:

```sh
"$PYTHON" -B /absolute/package/src/cli.py --config /absolute/user/config.json --state-dir /absolute/user/releases guide
"$PYTHON" -B /absolute/package/src/cli.py --config /absolute/user/config.json readiness local
"$PYTHON" -B /absolute/package/src/cli.py --config /absolute/user/config.json projects
```

Read [command reference](<docs/commands.md>) and [domain standards](<docs/standards.md>). Intent flags are not permission credentials. Source editing remains the caller Agent's responsibility. Native OPSX owns instructions, spec sync and archive; this package has no parallel phase database or archive wrapper.

## Validation and distribution

```sh
npm test
DSH_ASSISTANT_PYTHON=/absolute/venv/bin/python npm run test:python
```

Python tests use isolated temporary projects and simulated publication. Real Git/PTY and native OpenSpec integration are separately visible in test output. The real npm README regression requires `DSH_TEST_NPM_ROOT=/absolute/npm/package`. Skipped tests are not successful verification. No tests publish or authenticate.

The package ships implementation, templates and tests, but no user config, credentials, release records, virtualenv, node_modules or caches. The original icon is MIT licensed with the package. Runtime resource SHA-256 detects drift; it is **not** a supply-chain signature or permission proof.

## Migration and limits

`migration-preview OLD_CONFIG OLD_RELEASES` reads inventory and computes hashes without writing. An owner must separately review the destination, recheck hashes, translate the old relative workspace and preserve **all** pending dispatch intents and run records. Package updates/removal leave external data alone. Do not retire an old authority until migrated tests, clean-package checks and real desktop acceptance pass.

Static validation is not Host/UI acceptance, translation review or cryptographic provenance verification. CI success differs from registry visibility and byte equality. An uncertain release must be reconciled by exact run/SHA, never blindly redispatched. First npm publication and Trusted Publisher binding do not establish real OIDC publication: verify an explicitly authorized completion version within npm's actual validation window.

The base blocks unavailable exact bindings while installed; a fully removed base has no future interception point. These tools cannot constrain arbitrary shell or external MCP usage. Recover the base/package or continue in a new session rather than claiming an impossible permanent guard.
