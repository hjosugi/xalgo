# Changelog

## 0.1.1 — 2026-07-30

### Added

- Hypothetical VQV duration-threshold sweep with explicit probability and
  weight assumptions.
- Repeated video snapshot analysis with credential-column rejection,
  observational growth splits, and input/tool provenance hashes.

### Changed

- URL scoring can apply the upstream strict video-duration eligibility gate
  through `--vqv-min-duration-ms`.
- Missing video duration is treated conservatively when a threshold hypothesis
  is supplied, with the unpublished production values called out explicitly.

## 0.1.0 — 2026-07-29

Initial research release.

### Added

- Public-count score proxy with explicit 2023/2026 preset limitations.
- FxTwitter, VxTwitter and syndication fallback plus backend reliability audit.
- Upstream commit/merged-PR tracker with ranking and Grox policy categories.
- Reviewed 25-case tracking corpus with precision/recall regression metrics.
- Python AST and Rust structural change extraction for weights, actions and formulas.
- Phoenix artifact/README/action-head contract audit with drift baseline.
- Anonymous viewer-feed snapshot evaluation with rank metrics and provenance hashes.
- Author Diversity and negative-signal sensitivity analysis tools.
- Model, algorithm, validation and experiment documentation.

### Fixed

- VxTwitter requests no longer use a stale fixed-username route.
- Duplicate notifications are suppressed when a merged PR and its merge commit
  appear in the same upstream tracking window.
