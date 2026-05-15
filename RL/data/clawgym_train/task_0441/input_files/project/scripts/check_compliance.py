#!/usr/bin/env python3
import argparse
import json
import os
import re
import sys


def eprint(line: str) -> None:
    sys.stderr.write(line + "\n")


def main():
    parser = argparse.ArgumentParser(description="Check image license and attribution compliance in blog posts.")
    parser.add_argument("--posts", required=True, help="Path to directory containing .md posts")
    parser.add_argument("--metadata", required=True, help="Path to assets metadata JSON")
    parser.add_argument("--rules", required=True, help="Path to compliance rules JSON")
    args = parser.parse_args()

    # Load metadata
    try:
        with open(args.metadata, "r", encoding="utf-8") as f:
            metadata = json.load(f)
    except Exception as ex:
        eprint(f"ERROR,METADATA_LOAD,{args.metadata},-,-,Failed to load metadata: {type(ex).__name__}")
        sys.exit(2)

    # Load rules
    try:
        with open(args.rules, "r", encoding="utf-8") as f:
            rules = json.load(f)
    except Exception as ex:
        eprint(f"ERROR,RULES_LOAD,{args.rules},-,-,Failed to load rules: {type(ex).__name__}")
        sys.exit(2)

    allowed = set(rules.get("allowed_licenses", []))
    require_attr = set(rules.get("require_attribution_for", []))

    had_error = False

    # Walk posts
    for root, _dirs, files in os.walk(args.posts):
        for name in files:
            if not name.endswith(".md"):
                continue
            post_path = os.path.normpath(os.path.join(root, name))
            try:
                with open(post_path, "r", encoding="utf-8") as f:
                    text = f.read()
            except Exception as ex:
                eprint(f"ERROR,POST_READ,{post_path},-,-,Failed to read post: {type(ex).__name__}")
                had_error = True
                continue

            image_ids = re.findall(r"\[image:id=([A-Za-z0-9_\-]+)\]", text)
            has_attribution = bool(re.search(r"^Attribution:\s*.+", text, flags=re.MULTILINE))

            for img_id in image_ids:
                if img_id not in metadata:
                    eprint(f"ERROR,UNKNOWN_IMAGE_ID,{post_path},{img_id},-,Image id not found in metadata")
                    had_error = True
                    continue
                lic = str(metadata[img_id].get("license", "")).strip()
                if lic not in allowed:
                    print(f"WARNING,DISALLOWED_LICENSE,{post_path},{img_id},{lic},License not permitted by rules")
                if lic in require_attr and not has_attribution:
                    print(f"WARNING,MISSING_ATTRIBUTION,{post_path},{img_id},{lic},Attribution required for license but none found")

    if had_error:
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
