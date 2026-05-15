# SPEC: License Recognition Semantics

## Function under test

is_foss_license(name: str, approved: Set[str]) -> bool

Return True if the input license name corresponds to a FOSS license in `approved`.

## Canonicalization rules (expected)

- Trim leading and trailing whitespace from `name`.
- Compare case-insensitively.
- Normalize common synonyms to canonical identifiers before checking membership. Required mappings for this demo:
  - "Apache 2.0" -> "Apache-2.0"
  - "BSD 3-Clause" -> "BSD-3-Clause"
  - "GPL v3+" -> "GPL-3.0-or-later"
  - "MIT" remains "MIT"
- After canonicalization, return True if the canonical string is in the approved set.

## Examples (expected behavior)

- Input: "MIT" -> True
- Input: "mit" -> True
- Input: "  MIT  " -> True
- Input: "Apache 2.0" -> True (canonicalizes to "Apache-2.0")
- Input: "BSD 3-Clause" -> True (canonicalizes to "BSD-3-Clause")
- Input: "GPL v3+" -> True (canonicalizes to "GPL-3.0-or-later")
- Input: "Proprietary" -> False

Note: The current implementation intentionally does not perform these normalizations; tests should assert the expected behavior above and are expected to fail until the implementation is fixed.
