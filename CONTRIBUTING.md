# Contributing to StarGate

## Workflow: PRs only + Friday release day

**All work goes through pull requests. Direct commits to `main` are
forbidden.**

- Branch from `main` for every change: `pr/<topic>` (e.g.
  `pr/partner-visibility`)
- Open a PR — the agent never merges its own PRs; the user reviews the
  diff and merges (GitHub blocks self-approval; no branch protection
  requires it — the review is reading the PR, not an approval click)
- PRs may merge any day; that's how the week's work lands
- Small related changes can share a PR; unrelated changes get separate PRs
- PR titles follow the commit-message style: what + why, honest limits in
  the body

**Fridays are release day.**

- Production deployments (builds + rollout to the `stargate` namespace on
  infra01) happen **only on Fridays**, unless explicitly approved as an
  out-of-band hotfix (live incident)
- When finishing work on a non-Friday: PR opened, tests green, note
  "ready for Friday release"
- Never start a build or `oc rollout` on another weekday without asking
- Post-release: run `scripts/confluence_sync.py` so the Confluence mirror
  refreshes

**Config changes are not releases** (see
[docs/config-management.md](docs/config-management.md)): API keys, env
vars, and credentials change via `oc set env` / ConfigMap any day, with a
log note.

## Testing

Every PR runs the full suite before merge:

```bash
make test                # Unit tests (SQLite in-memory, no Postgres needed)
cd frontend && npm test  # Frontend tests
```

Integration tests (`make test-integration`) require PostgreSQL.

## Notes

- `AGENTS.md` is deliberately gitignored — it holds local agent
  instructions. Repo-wide working rules live here.
- The repo is the source of truth; Confluence mirrors it and refreshes on
  release.
