# DVB-Nexus

## Agent skills

### Issue tracker

Issues live in GitHub Issues (`BingChaoLiu/DVB-Nexus`), managed via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Default five canonical triage labels (label strings equal to role names). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context layout: root `CONTEXT.md` + `docs/adr/`. See `docs/agents/domain.md`.

### Spec consistency check

After editing anything under `docs/spec/` (front-matter, package indexes, `REGISTRY.md`), run `python -I tools/check_specs.py`; CI runs the same check on push.

### Windows shell

Git Bash + native Windows Python path/heredoc/encoding pitfalls: see `docs/agents/windows-shell.md`.
