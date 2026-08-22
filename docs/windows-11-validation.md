# Windows 11 validation status

Windows 11 support is **Provisional** for AI Plugin Marketplace 0.1.0-beta.1. The
repository has Windows CI and synthetic tests for selected portable branches,
but it has not yet completed the checklist below on a physical Windows 11
machine. CI and synthetic tests are useful regression signals; neither is an
acceptance result for NTFS, Codex Desktop, or Microsoft Excel Desktop.

This page is the public support boundary and the evidence plan for the first
physical-machine run. A checked item needs an attached evidence record; editing
the checkbox alone is not sufficient.

## What current automation proves

- GitHub Actions runs the root repository tests and the complete plugin pytest
  suite on `windows-latest`.
- Synthetic tests exercise Windows-specific decisions such as `PATH`
  separation, `.cmd Git shim` discovery, the portable validation-report writer,
  and reparse-point attribute rejection.
- macOS tests exercise real POSIX symlinks and race substitutions. They do not
  create an NTFS junction or native Windows reparse point.

These tests validate branch logic under controlled inputs. They do not prove
that the same branches interact correctly with Windows filesystem, process,
permission, path, Codex installation, or Excel behavior.

## Open risks and questions

| Area | Status before physical test | Required resolution |
| --- | --- | --- |
| NTFS indirection | Unconfirmed | Create directory symlinks, an NTFS junction, and other accessible reparse point forms. Confirm that `.ai-sow/validation` and report targets outside the project are rejected without modifying the external target. |
| Report-write race | Unconfirmed | Exercise a concurrent check/write/rename race against both the validation directory and report file. Confirm the report is either safely written or rejected, never redirected outside the project, and leaves no truncated or zero-byte prior report. |
| Windows paths | Unconfirmed | Run from a project path containing non-ASCII characters and spaces. Separately exercise a long path and record whether Windows long-path support was enabled. |
| Git discovery | Synthetic only | Confirm that a real Git for Windows installation and a controlled `.cmd Git shim` are both found and invoked with the expected optional-lock environment setting. |
| Toolchain and installed plugin | Unconfirmed | Confirm Python 3.12, `uv`, Codex marketplace registration, plugin installation, installed plugin directory discovery, and pytest execution from the installed plugin rather than the source checkout. |
| Codex workflow | Unconfirmed | Run setup, the five validators, and generate-sow from an empty project through the installed plugin directory; confirm all seven Skills resolve from that directory. |
| Excel result | Unconfirmed | Open the generated workbook in Microsoft Excel Desktop, use F9 to calculate and then request a full calculation, save it, and inspect cached formula values and formula errors. |
| Developer features | Unconfirmed | Repeat the filesystem cases with Developer Mode recorded and with ordinary symbolic-link permissions; document cases that require elevation or cannot be created. |

The report-write implementation includes defensive identity and reparse-point
checks. Until the native NTFS and concurrency cases above run, those controls
remain unverified on Windows rather than being advertised as resolved Windows
compatibility.

## Physical Windows 11 acceptance checklist

Use a disposable Windows user profile or VM snapshot. Do not reuse customer
data. Store command transcripts and hashes in the evidence record.

- [ ] Record the Windows edition, build, architecture, filesystem, shell,
  Python, `uv`, Git, Codex, and Excel versions; record Developer Mode,
  long-path policy, and symbolic-link permissions.
- [ ] Clone the repository to a normal path and run the root tests, repository
  validator, locked dependency sync, and complete plugin pytest suite.
- [ ] Repeat the root and plugin checks from a non-ASCII path containing spaces.
- [ ] If long-path support is enabled, repeat from a path longer than 260
  characters. If it is disabled, record the expected failure boundary instead
  of changing policy silently.
- [ ] Execute the real Git for Windows path and the controlled `.cmd Git shim`
  path; capture the resolved executable and command result.
- [ ] Create the supported directory symlink, NTFS junction, and reparse point
  cases for `.ai-sow/validation` and each report target. Confirm all external
  targets remain byte-identical.
- [ ] Exercise a concurrent check/write/rename race for the validation directory
  and existing report. Confirm no external write, no truncation, and no
  zero-byte residue after rejection.
- [ ] Register the checkout with `codex plugin marketplace add`, install AI SOW,
  and record the registration command/output plus `codex plugin list` output.
- [ ] Locate the installed plugin directory without using source paths; run locked pytest
  and the repository-provided standalone-copy smoke checks against it.
- [ ] In a fresh project, run setup, then the five validators in workflow order:
  analyze-requirement, analyze-as-is, generate-design, generate-story, and
  generate-task. Run generate-sow last. Confirm generated contracts, validation
  reports, package manifest, and workbook exist at their documented paths.
- [ ] Start a new Codex session and confirm all seven installed Skills are
  discoverable and operate from the installed plugin directory.
- [ ] Open the final workbook in Microsoft Excel Desktop, press F9 to exercise
  ordinary calculation, then invoke Calculate Full (for example, Ctrl+Alt+F9),
  save, reopen, and inspect cached formula values. Record the count and locations
  of any formula errors.
- [ ] Re-run the complete suites after Excel acceptance and archive the final
  GitHub Actions run alongside the physical-machine evidence.

## Evidence record

Create one dated Markdown record under `docs/validation/windows-11/` when the
physical run happens. It must include:

- commit SHA and clean-worktree status;
- hardware or VM description and every version/policy value listed above;
- exact commands, exit codes, test counts, and links to the matching GitHub
  Actions run;
- hashes for the three source templates, the installed-plugin template, and the
  final workbook;
- filesystem-case results, including the link or reparse type and whether
  elevation was used;
- Excel recalculation/save evidence and the cached formula-error scan;
- each failed or skipped checklist item, its owner, and the follow-up issue.

Windows 11 can move from **Provisional** to **Verified** only after every
applicable checklist item passes on a physical Windows 11 environment and the
evidence record is reviewed. Any skipped item must remain visible as a support
limitation.
