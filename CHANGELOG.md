# Changelog

## 0.3.0 — 2026-09-22

### Added

- The `upstream_2026_09` default preset from the 2026-09-18 Home Mixer source:
  VQV weight 0.0, dwell weight 0.05 and video-open weight 0.07, with the other
  23 public defaults unchanged. `upstream_2026_08` stays available for the
  August values.
- An issue-to-code research receipt for upstream changes reported in #21–#36
  (`docs/upstream-2026-09.md`), covering weight perturbation,
  `MultiplierPreOffset`, the move of the normalization sums into
  `recompute_sums`, the removal of the dwell-regret value model gate, and the
  cold-start default changes.

### Changed

- The model-contract audit reads the September scorer (sums assigned in
  `recompute_sums`), records `multiplier_pre_offset`,
  `weight_perturbation_sigma` and `cdwell_on_impr` as optional settings, and
  adds the sign-based term split rule (unchanged since August, previously
  unrecorded) and perturbation support to the scoring contract. The baseline
  is re-recorded at `8b25829717`.
- The VQV threshold analysis reports the current published VQV weight (0.0)
  alongside the August value it still uses as the sweep hypothesis.
- The feed-weight estimator compares against the weights file's default preset
  and names it in its report.

## 0.2.1 — 2026-08-26

### Added

- Privacy-safe pairwise learning-to-rank for anonymized feed snapshots, with
  deterministic author/post-disjoint held-out validation and comparison to the
  public August Home Mixer defaults.

## 0.2.0 — 2026-08-25

### Added

- A source-based August 2026 contract audit for all 26 public Home Mixer
  action defaults, ranking settings, scoring constants, Phoenix model profiles,
  and action-space dimensions.
- The `upstream_2026_08` default preset with public VQV, negative-score offset,
  author-diversity, and OON defaults shared by Python and browser scoring.
- An issue-to-code research receipt for upstream changes reported in #14–#20
  and their impact on analysis issues #1, #6, #9, #10, and #11.

### Changed

- Upstream tracking now covers the current Phoenix, Home Mixer parameter,
  SimClusters, visibility, and Grox policy trees and suppresses import/comment
  noise in issue summaries.
- The May 2026 Phoenix demo is retained as the explicitly historical
  `repo_demo` preset; it is no longer treated as the current contract.
- The reviewed tracking corpus grows from 25 to 33 May/August cases.

### Fixed

- Rust structure extraction no longer mistakes function parameters for struct
  fields.
- URL, API, and browser scoring now apply preset-specific offsets and diversity
  settings consistently.

## 0.1.4 — 2026-07-31

### Added

- Privacy-safe VQV author/topic stratification from a strict auxiliary CSV
  schema that excludes raw author identity, post text, and extra columns.
- Per-threshold within-stratum view-growth splits and explicit comparable-cell
  counts to expose sparse or one-sided anonymous groups.

### Changed

- Development and CI now use a pinned Nix flake and Go Task instead of
  virtualenv/pip bootstrap commands.

## 0.1.3 — 2026-07-30

### Added

- Fixed-cohort backend audit receipts that exclude post text, authors, URLs,
  cookies, and credentials while retaining public counts and provenance hashes.
- Repeated-snapshot aggregation with Wilson success-rate intervals, latency
  quantiles, field coverage, cohort checks, and explicit completion gates.
- A 120-post cohort and all three required time-separated reliability snapshots.
- Direct VQV view-growth analysis from repeated privacy-minimized backend audit
  receipts, including per-receipt attrition metadata.

### Fixed

- Syndication tombstone payloads no longer count as successful post fetches.

### Changed

- Public backend request timeout reduced from 12 to 5 seconds after 1,080
  attempts across three UTC hours completed with no timeout failures and a
  maximum observed latency below 1.6 seconds.

## 0.1.2 — 2026-07-30

### Added

- Deterministic full-artifact Phoenix inference receipt with an exact
  instrumentation patch, 19-column probability histograms, and provenance
  hashes.
- Standard-library probability export validator and public-count proxy
  summarizer.

### Documented

- The bundled sports corpus contains 84,564 candidates despite the upstream
  README's approximately 537K claim.
- Public count rates cannot calibrate the example Phoenix output without
  matched viewers, candidates, times, and a resolved action-head contract.

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
