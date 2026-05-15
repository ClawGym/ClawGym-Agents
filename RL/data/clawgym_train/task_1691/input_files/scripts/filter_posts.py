import os
import json
import glob

CONFIG_PATH = "config/filter.json"
POSTS_DIR = "content/posts"
OUTPUT_DIR = "build"
OUTPUT_PATH = os.path.join(OUTPUT_DIR, "visible_posts.json")

def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def load_posts():
    posts = []
    for path in sorted(glob.glob(os.path.join(POSTS_DIR, "*.json"))):
        with open(path, "r", encoding="utf-8") as f:
            post = json.load(f)
            posts.append(post)
    return posts

def filter_posts(posts, cfg):
    # BUG: Over-aggressive exclusion by splitting tags on '-' and using substring matching
    exclude_tags = cfg.get("exclude_tags", [])
    banned_tokens = set()
    for tag in exclude_tags:
        for part in tag.split("-"):
            banned_tokens.add(part)
    visible = []
    for post in posts:
        tags = post.get("tags", [])
        # Substring match on tokens causes false positives like 'women-leaders' matching token 'women'
        if any(any(bt in t for bt in banned_tokens) for t in tags):
            continue
        visible.append(post)
    return visible

def prepare_output(posts, cfg):
    fields = cfg.get("include_fields", ["id", "title"])
    items = [{k: p.get(k) for k in fields} for p in posts]
    items.sort(key=lambda x: x.get("id"))
    return items

def main():
    cfg = load_config()
    posts = load_posts()
    visible = filter_posts(posts, cfg)
    data = prepare_output(visible, cfg)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

if __name__ == "__main__":
    main()
