from typing import Set

def load_approved(path: str) -> Set[str]:
    """Load approved license identifiers from a text file, one per line.
    Lines starting with '#' are ignored.
    """
    approved = set()
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            approved.add(line)
    return approved


def is_foss_license(name: str, approved: Set[str]) -> bool:
    """Return True if the given license name is considered FOSS.
    NOTE: This intentionally does NOT normalize inputs (buggy per SPEC.md).
    """
    if name is None:
        return False
    # Bug: exact match only, no trimming/case-folding/synonym mapping
    return name in approved
