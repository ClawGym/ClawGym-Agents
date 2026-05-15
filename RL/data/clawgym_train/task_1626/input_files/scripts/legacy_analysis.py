DATA = []

# Legacy script: quick-and-dirty forum post parsing and printing.
# Issues (non-exhaustive): global state, manual CSV parsing, no type casting,
# prints only, non-deterministic ordering assumptions, no file outputs.

def load_posts(path="input/posts.csv"):
    f = open(path, "r")  # intentionally not using context manager in legacy code
    lines = f.read().splitlines()
    if not lines:
        return []
    header = lines[0].split(",")
    rows = []
    for line in lines[1:]:
        if not line.strip():
            continue
        parts = line.split(",")
        if len(parts) < 9:
            # naive skip
            continue
        rec = {
            "id": parts[0],
            "date": parts[1],
            "author": parts[2],
            "title": parts[3],
            "tags": parts[4],
            "upvotes": parts[5],  # left as string
            "replies": parts[6],  # left as string
            "accepted": parts[7],  # left as string
            "content": ",".join(parts[8:])
        }
        rows.append(rec)
    # use global DATA (legacy smell)
    global DATA
    DATA = rows
    return DATA


def tag_counts():
    counts = {}
    for rec in DATA:
        tags = rec.get("tags", "")
        for t in tags.split(";"):
            if not t:
                continue
            if t not in counts:
                counts[t] = 0
            counts[t] = counts[t] + 1
    print("TAG COUNTS", counts)


def top_posts_naive(n=3):
    # sorts strings; '50' > '6' lexicographically ok sometimes but wrong generally
    sorted_posts = sorted(DATA, key=lambda r: r.get("upvotes", "0"), reverse=True)
    print("Top", n, "posts (any year, naive):")
    for p in sorted_posts[:n]:
        print(p.get("id"), p.get("upvotes"), p.get("title"))


def main():
    load_posts()
    top_posts_naive(3)
    tag_counts()
    # No file outputs in legacy version


if __name__ == "__main__":
    main()
