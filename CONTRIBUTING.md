# Contributing

Thanks for helping improve AI Plugin Marketplace. Use GitHub Issues for public
bug reports and feature proposals before large changes so scope can be agreed
early. Do not include customer SOW content, credentials, private repository
details, or other sensitive material in an issue or fixture.

## Development setup

Install Python 3.12 and uv 0.11.7 or a compatible release, then run:

```text
uv sync --project plugins/ai-sow --locked
```

Keep each plugin self-contained. A plugin must not depend on files above its
own installed directory. Add tests before an
implementation change and keep manifests, contract versions, docs, and release
notes aligned.

## Required checks

```text
uv run --project plugins/ai-sow --locked python -m unittest discover -s tests -v
uv run --project plugins/ai-sow --locked python scripts/validate_repository.py
uv run --project plugins/ai-sow --locked pytest -c plugins/ai-sow/pyproject.toml plugins/ai-sow/skills -q
uv run --project plugins/ai-sow --locked python plugins/ai-sow/tests/support/smoke_plugin.py --copy-plugin
```

Run all checks locally before opening a pull request. Pull requests should
explain the problem, the chosen boundary, user-visible behavior, testing, and
any privacy or compatibility impact. Small, focused commits are preferred.

The smoke command copies only the plugin package into an independent temporary
directory, creates user projects outside that directory, runs setup and all five
owner validators, and generates a workbook. Its final JSON report includes the
temporary work directory for inspection.

By contributing, you agree that your contribution is licensed under Apache
License 2.0.
