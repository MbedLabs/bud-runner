# Changelog

All notable changes to `bud_runner` will be documented in this file.

## [1.0.3] — 2026-08-16

### Added
- Run work queued by the backend for this station
- Upload run artifacts with `--artifact`
- Send the report and remaining files a run leaves behind

### Fixed
- Completed run claims are acknowledged idempotently

### Changed
- Version aligned with `budtestlibrary` 1.0.3, which adds an optional `addr`
  target address to `FlashEvent.flash()` and `FlashEvent.execute()`

## [1.0.2] — 2026-07-22

### Changed
- Package licensing wording now explicitly confirms that `bud_runner` remains free and open source under `AGPL-3.0-only`, including for commercial use subject to AGPL compliance
- Bud and Bloom application licensing is clearly separated from the `bud_runner` package licence
- Contributor terms now guarantee that Accepted Contributions remain publicly available under `AGPL-3.0-only`
- Pull requests now include an explicit CLA acceptance declaration

### Fixed
- README relative-link validation allows `#`-prefixed anchor links supported by PyPI

## [1.0.1] — 2026-07-19

### Changed
- Hardened `.gitignore` with key/cert patterns for public release
- Removed internal hostname from CI workflow step name
- Added PR template for contribution guidelines

## [1.0.0.post2] — 2026-06-28

### Changed
- Package version advanced to `1.0.0.post2` for final public metadata and documentation corrections
- Project URLs now point to `embedlabs.net`
- PyPI README no longer relies on private-repository file links for service deployment guidance

## [1.0.0.post1] — 2026-06-28

### Changed
- Package version advanced to `1.0.0.post1` for a documentation-only PyPI metadata correction
- Package author metadata now credits Amine El Omari
- README now includes creator credit for the published project page

## [1.0.0] — 2026-06-28

### Added
- Stable open-source release packaging for `bud_runner`
- Release metadata regression coverage for version, licence metadata, and changelog presence

### Changed
- Package version advanced to `1.0.0`
- Packaging metadata now uses a PEP 621-compatible licence table
- Release classifier moved from beta to production/stable
