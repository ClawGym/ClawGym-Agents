#!/usr/bin/env python3
import json
import os
import sys

def main():
    print("Mock Palette Tool v0.1")
    print("Working directory:", os.getcwd())
    posts_path = os.path.join("input", "forum_posts.json")
    print(f"Scanning posts from {posts_path} ...")
    with open(posts_path, "r", encoding="utf-8") as f:
        posts = json.load(f)
    print(f"Loaded {len(posts)} posts")
    # Derive simple style tags from posts
    tags = []
    for p in posts:
        pref = (p.get("style_preference") or "").strip().lower()
        if "+" in pref:
            pref = pref.split("+")[0].strip()
        if pref and pref not in tags:
            tags.append(pref)
    print("Detected style tags:", ", ".join(tags) if tags else "(none)")
    presets_path = os.path.join("input", "palette_presets.json")
    print(f"Loading palette presets from {presets_path} ...")
    # Intentionally trigger FileNotFoundError for demonstration
    with open(presets_path, "r", encoding="utf-8") as pf:
        presets = json.load(pf)
    print("Presets loaded:", len(presets))  # This will not execute
    return 0

if __name__ == "__main__":
    sys.exit(main())
