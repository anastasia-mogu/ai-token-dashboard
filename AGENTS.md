# AI Token Dashboard Agent Rules

This repository is the public code repository for AI Token Dashboard. It contains application code, scripts, documentation, safety checks, and fictional example data only.

## Absolute Public Repository Boundary

Never add, generate, stage, commit, or preserve real user data in this repository. This rule is mandatory and has no exceptions.

Forbidden in this repository:

- `data.js`
- `data/` and any `data/设备-*.json` or real device JSON
- `.project-hash-seed`
- `.project-aliases.json`
- `config.local.json`
- real device names, real local project names, private project aliases, company identifiers, credentials, API keys, tokens, local absolute paths, or private GitHub repository URLs

If a task appears to require real data, stop and use the private data repository instead. Do not create temporary real-data files here. Do not copy real data here for testing. Do not relax `.gitignore` or safety checks to allow real data.

## Repository Role

- Implement UI, dashboard behavior, scanner logic, update/open scripts, public documentation, tests, and public safety checks here.
- Keep `data.example.js` fictional and clearly marked as example data.
- The optional private data repository is normally located at sibling path `../ai-token-dashboard-data`.
- Users may override the private data repository with `AI_TOKEN_DATA_REPO` or ignored local `config.local.json`.

## Working With the Data Repository

When a task is unclear, first inspect this repository and the optional sibling private data repository status, then decide where changes belong.

Default routing:

- Feature, UI, chart, scan logic, script, and public documentation changes belong here.
- Real device data, shared private seed, and local project-name mappings belong only in the private data repository or ignored local files.
- If a data schema or scan metric changes, update code here first, then instruct the user to rescan and update the private data repository separately.

Before finalizing changes here, run the public safety check when possible:

```bash
python3 scripts/check-public-safety.py
```
