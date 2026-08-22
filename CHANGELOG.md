# Changelog

All notable user-visible changes are documented here.

## 0.1.0-beta.1 - 2026-08-22

- Prepare AI SOW as the first public beta of the self-contained marketplace plugin.
- Introduce the strict SOW 1.3 eight-entity contract and Effective Start model.
- Separate BUSINESS and TECHNICAL Epic/Feature ownership, move technical intake
  to As-Is, and estimate one atomic Task per row without a multiplicative count field.
- Replace Story types and legacy Task domain/activity/mode multipliers with a
  12-family, 36-base-unit catalog. Estimate each Task from its configured base
  unit/work-mode effort and per-unit S/M/L standard; drive SIT from the one
  integration Task linked to each Integration and UAT from the Story flag.
- Consolidate the base-unit catalog and three work-mode effort values into one
  review-friendly worksheet, and move S/M/L complexity coefficients into the
  project parameter table.
- Publish the maintainable v1.3 Markdown standard, generated XLSX example, and
  byte-identical bundled template copies.
- Add installation-safe Skill commands derived from the loaded `SKILL.md` path.
- Add deterministic setup, validation, and workbook-generation test coverage.
- Default user-facing Skill instructions and business free text to Simplified
  Chinese while preserving machine contracts, enums, IDs, paths, hashes, and
  byte-identical XLSX templates.
- Record macOS as verified for the tested repository, local installation,
  standalone plugin copy, and Brownfield workflow; record Windows 11 as provisional until the published
  physical-machine checklist has evidence. Windows CI and synthetic portability
  tests are not described as real Windows 11 acceptance.
