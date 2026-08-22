# AI Plugin Marketplace

An open-source Codex plugin marketplace for practical, reviewable AI workflows.
The first plugin, AI SOW, turns requirements and system context into a
traceable statement-of-work workbook.

## Plugins

| Plugin | Version | Purpose |
| --- | --- | --- |
| [AI SOW](plugins/ai-sow/README.md) | 0.1.0-beta.1 | Analyze scope, reconcile the current state, estimate delivery work, and generate a reviewable XLSX. |

## Platform validation

| Platform | Status | Evidence boundary |
| --- | --- | --- |
| macOS | Verified | Repository suites, local Codex marketplace installation, execution from the installed plugin directory, and a large Brownfield workflow were exercised on a physical Mac. |
| Linux | CI-covered | GitHub-hosted CI exercises the repository and plugin suites; no desktop Excel acceptance is claimed. |
| Windows 11 | Provisional | Portable branches and Windows CI are present, but physical-machine acceptance is still pending. |

CI and synthetic tests do not count as physical Windows 11 validation. See the
[Windows 11 validation status](docs/windows-11-validation.md) for the open risks,
the real-machine checklist, and the evidence required before changing the status.

## Install

Prerequisites: Codex, Python 3.12, Git, and
[uv](https://docs.astral.sh/uv/) 0.11.7 or a compatible release.

```text
codex plugin marketplace add InspireChina/ai-plugin-marketplace
codex plugin add ai-sow@ai-plugin-marketplace
codex plugin list
```

For local development, clone the repository and register the checkout instead:

```text
git clone https://github.com/InspireChina/ai-plugin-marketplace.git
codex plugin marketplace add /absolute/path/to/ai-plugin-marketplace
codex plugin add ai-sow@ai-plugin-marketplace
```

## Update

Refresh the Git marketplace snapshot, then reinstall the plugin so Codex uses
the refreshed installed package:

```text
codex plugin marketplace upgrade ai-plugin-marketplace
codex plugin remove ai-sow@ai-plugin-marketplace
codex plugin add ai-sow@ai-plugin-marketplace
```

For a marketplace registered from a local checkout, pull the checkout first;
`marketplace upgrade` refreshes configured Git marketplaces.

## Uninstall

Remove the plugin before removing its marketplace registration:

```text
codex plugin remove ai-sow@ai-plugin-marketplace
codex plugin marketplace remove ai-plugin-marketplace
```

## Repository layout

```text
.agents/plugins/marketplace.json  Marketplace catalog
plugins/ai-sow/                   Self-contained plugin package
scripts/                          Repository and package smoke checks
tests/                            Marketplace-level tests
.github/                          Contribution templates and CI
```

The plugin package owns its runtime dependencies and does not read files from
the marketplace root at run time. It therefore remains runnable from its
installed plugin directory.

The public [marketplace architecture](docs/architecture/ai-plugin-marketplace-design.md)
records package boundaries and release decisions. Execution checklists and
machine-local plans are intentionally excluded from the public tree. The Windows
11 checklist is public because it defines a release-support boundary rather than
an internal execution plan.

## Develop

```text
uv sync --project plugins/ai-sow --locked
uv run --project plugins/ai-sow --locked python -m unittest discover -s tests -v
uv run --project plugins/ai-sow --locked python scripts/validate_repository.py
uv run --project plugins/ai-sow --locked pytest -c plugins/ai-sow/pyproject.toml plugins/ai-sow/skills -q
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the complete validation workflow.

## Add another plugin

1. Create `plugins/<stable-plugin-name>/.codex-plugin/plugin.json`.
2. Keep all runtime code, dependencies, assets, documentation, and tests under
   that plugin directory.
3. Add one local-source entry to `.agents/plugins/marketplace.json`.
4. Extend the repository validator and tests for the new package.
5. Document the plugin and add its release notes before opening a pull request.

## License

Licensed under [Apache License 2.0](LICENSE). Project-authored templates,
examples, and documents are distributed under the same license; dependency
licenses remain their own. See [NOTICE](NOTICE).
