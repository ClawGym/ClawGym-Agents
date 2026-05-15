# Datetime Normalization Requirements (Mixed Sources v1.2)

Purpose: Define a plan to normalize inconsistent datetime values collected from multiple systems with mixed formats, missing time zones, and ambiguous dates. This document intentionally includes conflicts to reflect real stakeholder disagreements. Your task is to design a robust, defensible normalization approach and verification plan.

Reference files you will read:
- input/spec.md (this file)
- input/sample_data.csv (example inputs with notes)

## Target Output (Primary)
- Canonical normalized field: `timestamp_utc` as an ISO 8601 UTC string in the format `YYYY-MM-DDTHH:MM:SSZ`.
- Preserve original raw string as `raw_value`.
- Optional auxiliary fields if derivable: `source_tz_name`, `source_offset`, `parse_confidence` (0.0–1.0), `disambiguation_note`.

## Important Conflicts (Intentionally Contradictory)
- TZ default:
  - Stakeholder A (Data Warehouse): Default to UTC (“Z”) for missing time zones.
  - Stakeholder B (CRM/Marketing): Default to America/New_York for CRM and Marketing sources when time zone is missing.
- DST fall-back choice:
  - Stakeholder A: Choose the first (DST) occurrence for ambiguous “01:30” during fall-back.
  - Stakeholder B (Reservations): Choose the second (post-DST, standard time) occurrence.
- Front-end analytics display:
  - Stakeholder C: UI expects local time with offset preserved.
  - Data Warehouse: Warehouse must store UTC only.

You must acknowledge these conflicts and propose a plan for consistent handling (e.g., source-specific rules + metadata that enables downstream consumers to reconstruct local-time semantics).

## Input Variants to Support
1. ISO 8601 with offset or Z:
   - Examples: `2023-08-05T14:30:00-04:00`, `2023-08-05 14:30:00Z`, `2023-12-31T24:00Z` (maps to next day `00:00:00Z`).
2. ISO week/ordinal dates:
   - Week date: `2023-W05-3` (Wednesday of week 5)
   - Ordinal date: `2023-217` (217th day of the year)
3. Named time zones:
   - `2023-04-05 16:00 Asia/Tokyo`
   - `2024-03-10 02:15 America/New_York` (may fall into a DST gap)
4. Locale-dependent numeric formats:
   - US-style: `8/5/23 2:30 PM` (MM/DD/YY)
   - EU-style: `05/08/2023 14:30` (DD/MM/YYYY)
   - Ambiguous: `03/04/05 06:07:08`
5. Textual dates:
   - `Aug 5, 2023 2:30pm`, `5 Aug 2023`
6. Relative expressions:
   - `now`, `yesterday 17:00` (resolve relative to a reference time)
7. Potentially invalid inputs:
   - `2023/13/01 12:00` (invalid month), `2023-04-31` (invalid day), leap seconds `23:59:60Z`

## Disambiguation Rules (Proposed Baseline)
- Reference time for relative expressions: `2024-02-15T12:00:00Z` (from this spec) unless the runtime supplies a different reference.
- Time zone defaults by source (when absent in the input):
  - `log`: assume `UTC`
  - `crm`, `marketing`: assume `America/New_York`
  - `web`: prefer user local time if available; if not available, assume `UTC` (conflict acknowledged)
  - `ops`, `finance`, `analytics`, `legacy`, `support`, `partner_*`: If TZ not present, assume `UTC` unless a country code or separate governance says otherwise.
- Country-/region-specific overrides (when determinable from metadata such as country code in notes):
  - If the record indicates `country_code` in {GB, FR, DE, ES, IT, NL, SE, NO, DK}, prefer day-first parsing (DD/MM/YYYY) for numeric dates.
  - If `country_code=GB` and format is ambiguous numeric, parse DD/MM/YYYY.
- Day-first vs. month-first:
  - If source in {crm, marketing} and no country code: default to US month-first.
  - If source indicates EU or `country_code` EU list above: day-first.
- Two-digit year windowing:
  - `00`–`69` => 2000–2069
  - `70`–`99` => 1970–1999
- DST anomalies:
  - Spring-forward (missing local times, e.g., `2024-03-10 02:15 America/New_York`): shift forward to the earliest valid instant per IANA rules (e.g., interpret as `03:15` local) and record `disambiguation_note`.
  - Fall-back ambiguous (`2024-11-03 01:30 America/New_York`): choose occurrence according to source:
    - For `reservations`/`ops`: choose SECOND occurrence (post-DST, standard time)
    - For others: choose FIRST occurrence unless otherwise specified
  - Always convert to UTC for storage.
- Invalid values:
  - Reject with an error flag, set `timestamp_utc` to null, and attach `disambiguation_note` explaining the failure.

## Output Constraints and Examples
- Always produce `timestamp_utc` in `YYYY-MM-DDTHH:MM:SSZ`.
- Examples:
  - `2023-08-05T14:30:00-04:00` -> `2023-08-05T18:30:00Z`
  - `2023-12-31T24:00Z` -> `2024-01-01T00:00:00Z`
  - `8/5/23 2:30 PM` (crm, assume America/New_York) -> `2023-08-05T18:30:00Z`

## Verification Requirements
- For each input row, produce:
  - `timestamp_utc` (or null if invalid)
  - `parse_confidence` (heuristic)
  - `disambiguation_note` when any default/assumption or DST rule applied
- Sampling strategy must demonstrate correctness on:
  - At least one DST gap case, one DST overlap case
  - One ordinal date, one ISO week date
  - One relative expression
  - One ambiguous numeric format with region logic

## Notes on sample_data.csv
- Columns: `id,source,raw_value,notes`
- The `notes` column may include hints like `country_code=GB` or comments about ambiguity.
- Use the reference time `2024-02-15T12:00:00Z` for relative terms unless stated otherwise.

## Known Conflicts Recap (Callouts)
- Default time zone varies by stakeholder group (UTC vs America/New_York for CRM/Marketing).
- Ambiguous fall-back “01:30” selection differs by business function (first vs second occurrence).
- UI may want local times while Warehouse requires UTC.

Document all assumptions and unresolved conflicts in your plan so downstream teams can align on a single standard.

---