# CLI reference

Prefix every command with the selected interpreter and immutable package entry:

```sh
"$PYTHON" -B /absolute/package/src/cli.py --config /absolute/user/config.json --state-dir /absolute/user/releases COMMAND
```

`guide` needs no configuration. `readiness [local|all|COMMAND]` only checks installed prerequisites; it does not install or authenticate. `all` explicitly reports authorization as not checked. External operations independently check gh authorization at execution. Config/state paths must remain outside the package; state cannot be within a publishable project. An optional `--config-revision SHA256` fences configuration readback for Host-authorized calls.

| Command | Meaning / effects |
|---|---|
| `projects`, `inspect PROJECT` | Registered projects; identity/docs/Git/OpenSpec structure; no project scripts |
| `registry PROJECT`, `remote PROJECT` | Exact npm metadata / actual GitHub account, repository, push permission |
| `version-plan PROJECT`, `commit-plan PROJECT`, `sync-plan PROJECT` | Exact content/mode/HEAD and remote preflight; not permission |
| `create NAME DESCRIPTION` | Registry404 prerequisite, project skeleton, external registration, workspace OpenSpec first-delivery artifacts |
| `openspec PROJECT init` | Explicit domain resource initialization, preserving existing roots |
| `openspec PROJECT new change NAME --json` | Official OpenSpec new change plus target metadata; no second workflow |
| `validate PROJECT --allow-project-scripts` | Targeted strict native OpenSpec validation, npm test and pack dry-run/payload audit |
| `version-bump PROJECT BASELINE` | Exact-baseline plain-semver patch bump; leaves initial/already-bumped version intact |
| `commit PROJECT BASELINE SUBJECT --allow-git-hooks` | Exact project commit; runs hooks; refuses existing staging and changed baseline |
| `create-repo PROJECT --approve-public` | Explicit public GitHub repository creation; checks actual account |
| `sync PROJECT BASELINE REMOTE_SHA --approve-export` | Reviewed tree export; remote SHA or `empty`; no force push |
| `npm-bootstrap-plan PROJECT` | Registry/trust setup preview with exact browser confirmations; opens nothing |
| `npm-bootstrap PROJECT --approve-publish --owner-confirmed` | **Manual CLI only**, after explicit immediate owner confirmation; installed npm≥11.21.1; temporary credentials, PTY sign-in/2FA, no automatic authentication retry |
| `release PROJECT REMOTE_SHA --approve-publish` | Persist intent before dispatch, existing-byte no-op, bounded run/registry reconciliation |
| `release-status PROJECT RUN_ID` | Query and persist one existing Actions run; never dispatch |
| `release-resume PROJECT RUN_ID EXPECTED_SHA` | Reconcile exact identity/tree/registry/payload; persist evidence, never dispatch |
| `settings-read` | External config and revision |
| `settings-save REVISION JSON_FILE` | Validated atomic revision-fenced config replacement |
| `migration-preview OLD_CONFIG OLD_RELEASES` | Read-only source hashes/proposed absolute-workspace config; does not migrate or delete |

Flags express operation intent, **not** authorization. Use the invoking Agent's real execution permission/approval; ask the owner before required browser authentication, public export or publication unless the exact scope is already authorized. Never infer authorization from this document, installed package, assistant selection or a task checkbox.

Native OPSX `instructions`, `status`, spec synchronization and `archive` run directly in the configured workspace. This adapter never wraps archive. Follow the current native schema DAG; package templates are guidance rather than a second lifecycle.

## Verification categories

Python suite: isolated fixtures, real temporary Git repositories, POSIX PTY/process termination and native OpenSpec (skipped if absent). Publication/network calls are simulated. Real npm README normalization is opt-in via `DSH_TEST_NPM_ROOT`; do not call a skip a pass. Node tests cover manifest, scoped resources, process policy and lifecycle with controlled doubles; these do not substitute for real desktop acceptance.
