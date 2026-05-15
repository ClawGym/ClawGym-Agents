#!/usr/bin/env python3
import argparse
import pandas as pd
# BUG: missing import os


def main():
    parser = argparse.ArgumentParser(description="Generate weekly summary and top posts for potato content.")
    parser.add_argument("input_csv")
    parser.add_argument("output_dir")
    args = parser.parse_args()

    df = pd.read_csv(args.input_csv)

    # BUG: fails on commas and blanks
    df["views"] = df["views"].astype(int)
    df["likes"] = df["likes"].fillna(0).astype(int)
    df["comments"] = df["comments"].fillna(0).astype(int)

    # BUG: missing parentheses changes operator precedence
    df["engagement_rate"] = df["likes"] + df["comments"] / df["views"]

    summary = (
        df.groupby("recipe_type")
          .agg({"views": "sum", "likes": "sum", "comments": "sum", "engagement_rate": "mean"})
          .reset_index()
          .rename(columns={
              "views": "total_views",
              "likes": "total_likes",
              "comments": "total_comments",
              "engagement_rate": "avg_engagement_rate"
          })
    )

    # BUG: os not imported; wrong column referenced below
    summary.to_csv(os.path.join(args.output_dir, "weekly_summary.csv"), index=False)

    top_posts = (
        df.sort_values("engagement", ascending=False)
          .head(3)[["post_id","title","recipe_type","engagement_rate","views","likes","comments"]]
    )
    top_posts.to_csv(os.path.join(args.output_dir, "top_posts.csv"), index=False)


if __name__ == "__main__":
    main()
