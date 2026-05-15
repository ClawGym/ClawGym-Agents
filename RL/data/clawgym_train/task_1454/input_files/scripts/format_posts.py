import sys
import pandas as pd

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python scripts/format_posts.py <input_csv> <output_csv>")
        sys.exit(2)
    inp, outp = sys.argv[1], sys.argv[2]
    df = pd.read_csv(inp)
    # Expects a precomputed column named 'engagement_score'
    df = df.sort_values("engagement_score", ascending=False)
    df.head(5).to_csv(outp, index=False)
    print("Wrote", outp)
