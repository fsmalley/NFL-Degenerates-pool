# V2.13.1.7.2.3 — Draft LAR Team-Code Normalization Fix

- Fixes Los Angeles Rams results not being recognized when upstream game data uses `LA` while Draft rosters use `LAR`.
- Applies the existing `normalize_schedule_team()` alias mapping when building Draft team result colors and weekly/completed game counts.
- Normalizes away/home team codes before future game rows are stored, so `LA` is persisted as `LAR` going forward.
- No schema, salary, roster, ranking-rule, or member-account changes.
