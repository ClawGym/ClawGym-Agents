import json
import os
import re
import sys

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    # Files to check
    files = {
        "ig": os.path.join(output_dir, "instagram_caption.txt"),
        "wa": os.path.join(output_dir, "whatsapp_reply.txt"),
        "banner": os.path.join(output_dir, "banner.txt"),
    }

    # Patterns (case-insensitive)
    spanish_pattern = re.compile(r"\b(?:vale|bueno|gracias)\b", re.IGNORECASE)
    filler_pattern = re.compile(r"\b(?:ba|bada|ezta|badakizu|begira|bueno)\b", re.IGNORECASE)
    interj_pattern = re.compile(r"\b(?:aiba|bikain|primeran|genial|ene|ostras|oso\s+ondo)\b", re.IGNORECASE)
    zu_pattern = re.compile(r"\b(?:zu|zure)\b", re.IGNORECASE)

    # Prohibited patterns
    hi_pattern = re.compile(r"\bhi\b", re.IGNORECASE)
    egun_on_pattern = re.compile(r"egun\s+on", re.IGNORECASE)
    jakina_pattern = re.compile(r"\bjakina\b", re.IGNORECASE)

    checks = {
        "ig_exists": False,
        "ig_word_limit": False,
        "ig_has_spanish": False,
        "ig_has_filler": False,
        "ig_has_interj": False,
        "ig_has_zu_or_zure": False,
        "ig_no_prohibited": False,

        "wa_exists": False,
        "wa_word_limit": False,
        "wa_has_spanish": False,
        "wa_has_filler": False,
        "wa_has_interj": False,
        "wa_has_zu_or_zure": False,
        "wa_no_prohibited": False,

        "banner_exists": False,
        "banner_word_limit": False,
        "banner_has_spanish": False,
        "banner_has_filler": False,
        "banner_has_interj": False,
        "banner_has_zu_or_zure": False,
        "banner_no_prohibited": False,
    }

    def eval_file(prefix, path):
        # Existence and non-empty
        if not os.path.isfile(path):
            return
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception:
            return
        if content.strip() == "":
            return

        checks[f"{prefix}_exists"] = True

        # Word count <= 200
        words = content.strip().split()
        if len(words) <= 200:
            checks[f"{prefix}_word_limit"] = True

        # Spanish code-switch
        if spanish_pattern.search(content):
            checks[f"{prefix}_has_spanish"] = True

        # Filler/softener
        if filler_pattern.search(content):
            checks[f"{prefix}_has_filler"] = True

        # Expressive interjection
        if interj_pattern.search(content):
            checks[f"{prefix}_has_interj"] = True

        # Contains "zu" or "zure" as standalone
        if zu_pattern.search(content):
            checks[f"{prefix}_has_zu_or_zure"] = True

        # No prohibited markers
        if not (hi_pattern.search(content) or egun_on_pattern.search(content) or jakina_pattern.search(content)):
            checks[f"{prefix}_no_prohibited"] = True

    eval_file("ig", files["ig"])
    eval_file("wa", files["wa"])
    eval_file("banner", files["banner"])

    # Compute reward as fraction of passed checks
    bool_values = list(checks.values())
    total_checks = len(bool_values)
    passed = sum(1 for v in bool_values if v)
    reward = (passed / total_checks) if total_checks > 0 else 0.0

    # Ensure no-op baseline 0.0 when nothing exists
    if not (checks["ig_exists"] or checks["wa_exists"] or checks["banner_exists"]):
        reward = 0.0

    # Clamp reward to [0,1]
    reward = max(0.0, min(1.0, float(reward)))

    result = {"reward": reward}
    result.update(checks)

    print(json.dumps(result))

if __name__ == "__main__":
    main()