# Contributing to Yuizaki

Thank you for helping improve Yuizaki. The project is a local-first desktop application; contributions should preserve that boundary, keep changes reviewable, and include evidence for behavior changes.

## Before you start

Read:

- [README.md](README.md) for supported scope and installation.
- [SECURITY.md](SECURITY.md) for local trust boundaries and reporting.
- [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) before adding assets, models, fonts, or services.
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) before changing process or event contracts.

Do not commit API keys, personal data, chat history, screenshots, model weights, audio caches, databases, logs, or pytest temporary directories.

## Development setup

Windows:

```powershell
.\install.bat full
```

Linux:

```bash
./install.sh full
```

Use the project Python environment in `python/.venv`. Keep provider credentials in the ignored `python/.env` file.

## Verification

Run the smallest relevant checks first, then the full checks for cross-layer changes:

```powershell
python scripts/check_docs.py
cd electron
npm run type-check
npm run lint
npm test
npm run build
cd ..\python
.\.venv\Scripts\python.exe -m pytest -q --tb=short
.\.venv\Scripts\python.exe -m compileall -q modules app.py socket_server.py
```

Linux uses `python scripts/check_docs.py`, the equivalent npm commands, and `.venv/bin/python -m pytest -q --tb=short`.

Changes to Socket.IO events, Job envelopes, cancellation, authentication, storage deletion, restore, or resource permissions require contract tests. Hardware- or provider-dependent behavior must include a mocked deterministic test plus a clear real-device limitation.

## Pull requests

Keep one concern per pull request. Describe:

- the user-visible or operator-visible outcome;
- the files and process boundaries affected;
- tests and verification commands run;
- configuration, migration, license, or security implications;
- known limitations and follow-up work.

Do not include generated build output or local runtime state. Review the diff for secrets and third-party assets before requesting review.

## Commit style

Use concise imperative subjects with a conventional prefix when practical, for example:

- `docs: clarify local deployment boundary`
- `fix: reject stale voice events`
- `test: cover scheduler cancellation`

## Security issues

Do not open a public issue for credentials, token leakage, unauthorized tool execution, or data disclosure. Follow the private reporting guidance in [SECURITY.md](SECURITY.md).

## License

By contributing, you agree that your contribution is provided under the repository license. Third-party assets remain subject to their own licenses.
