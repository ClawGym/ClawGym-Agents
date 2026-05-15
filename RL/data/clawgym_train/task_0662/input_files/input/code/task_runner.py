"""
task_runner.py — baseline utility to be improved via iterative code evolution.

Public functions (do not change signatures):
- normalize_path(path: str) -> str
- expand_env(template: str, env: dict) -> str
- parse_task_line(line: str) -> dict
- safe_int(value, default: int = 0) -> int

Notes:
- Intentional limitations/bugs exist to enable iterative improvement.
- Tests are provided in input/tests/tests.json.
"""

from typing import Dict, List, Any
import re


__all__ = [
    "normalize_path",
    "expand_env",
    "parse_task_line",
    "safe_int",
]


def normalize_path(path: str) -> str:
    """
    Naively normalize a filesystem-like path to forward slashes and collapse duplicates.
    Intentional limitations:
      - Does not resolve '.' or '..' segments
      - Leaves relative leading './' in place except for a simple leading cleanup
      - Does not handle trailing '/.' cleanup
    """
    if path is None:
        return ""
    s = str(path)

    # Convert backslashes to forward slashes
    s = s.replace("\\", "/")

    # Collapse repeated slashes
    s = re.sub(r"/{2,}", "/", s)

    # Strip a single leading "./"
    if s.startswith("./"):
        s = s[2:]

    # Leave '.' and '..' segments as-is (intentional baseline limitation)
    return s


_VAR_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def expand_env(template: str, env: Dict[str, Any]) -> str:
    """
    Expand ${VAR} occurrences using values in env.
    Intentional limitations:
      - Missing variables are left untouched (e.g., ${HOME} remains if not in env)
      - Does NOT support default syntax like ${VAR:-default}
    """
    if template is None:
        return ""

    def repl(match: re.Match) -> str:
        var = match.group(1)
        if var in env:
            return str(env[var])
        # Leave placeholder intact if not found
        return match.group(0)

    return _VAR_PATTERN.sub(repl, template)


def parse_task_line(line: str) -> Dict[str, Any]:
    """
    Parse a semicolon-delimited 'key=value' line into a dict.
    Example: 'action=echo; msg=hello; count=2; enabled=true'
    Intentional limitations:
      - Splits on every ';' (does NOT handle escaped semicolons)
      - Numbers recognized only if all digits (no float coercion)
      - Empty values become empty strings (ok), but whitespace handling is basic
    """
    result: Dict[str, Any] = {}
    if not line:
        return result

    parts = line.split(";")  # naive split, will break on escaped '\;'
    for raw in parts:
        seg = raw.strip()
        if not seg:
            continue
        if "=" not in seg:
            # Skip malformed segments silently
            continue
        k, v = seg.split("=", 1)
        key = k.strip()
        val = v.strip()

        # Basic coercion
        low = val.lower()
        if low == "true":
            coerced: Any = True
        elif low == "false":
            coerced = False
        elif val.isdigit():  # does not handle floats (intentional baseline limitation)
            try:
                coerced = int(val)
            except Exception:
                coerced = val
        else:
            coerced = val

        result[key] = coerced

    return result


def safe_int(value: Any, default: int = 0) -> int:
    """
    Convert value to int safely, returning default on failure.
    Intentional limitations:
      - Does not handle float-like strings (e.g., '3.0') — will fall back to default
    """
    try:
        s = str(value).strip()
        return int(s)
    except Exception:
        return int(default)


if __name__ == "__main__":
    # Lightweight manual sanity checks (not exhaustive)
    print("normalize_path examples:")
    print(normalize_path(r"C:\Temp\..\folder//file.txt"))
    print(normalize_path("./a//b/../c/."))
    print("expand_env examples:")
    print(expand_env("Hello ${NAME}", {"NAME": "World"}))
    print(expand_env("Path: ${HOME}/bin", {}))
    print("parse_task_line example:")
    print(parse_task_line("action=echo; msg=hi; count=2; enabled=true"))
    print("safe_int examples:")
    print(safe_int(" 42 "))
    print(safe_int("3.0", 0))
    print(safe_int("abc", 7))