# Contributing

Contributions are welcome. Please read this short guide before opening a PR.

## Reporting issues

Open a GitHub issue with:
- A clear description of the problem
- The `bw` CLI version (`bw --version`)
- Python version (`python --version`)
- Relevant log output (set `LOG_LEVEL=DEBUG` in `.env`) — redact any personal data

## Pull requests

1. Fork the repo and create a branch from `main`
2. Keep changes focused — one concern per PR
3. Run the test suite before submitting: `python -m pytest tests/`
4. If you add a new config option, update `.env.example` and `docs/setup.md`
5. Do not include real credentials, vault exports, or personal data in any commit

## Scope

This project intentionally has no external dependencies beyond `python-dotenv` and
`requests`. PRs that add heavy frameworks or new required dependencies are unlikely
to be merged.

## Code style

- Python 3.9+, standard `black` formatting preferred
- Type hints on all public functions
- No commented-out code

## Security

If you find a security issue, please **do not open a public issue**. Contact the
maintainer directly via GitHub.
