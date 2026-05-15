import pandas as pd
from pathlib import Path

# NOTE: This script is currently broken; please debug it so it runs end-to-end.
# Expected high-level steps:
# 1) Load empathy scores (CSV), participant->session mapping (CSV), and sessions (HTML table).
# 2) Join to derive group label per participant from sessions HTML (condition column).
# 3) Compute per-participant delta and group-level summary.
# 4) Save outputs into output/ as CSV/JSON. (Currently paths/columns are incorrect.)

DATA_DIR = Path("inputs")  # BUG: wrong directory name (should be data)
OUTPUT_DIR = Path("outputs")  # BUG: wrong directory name (should be output)


def load_data():
    # BUGS to fix: wrong paths and wrong table selection/column names.
    scores = pd.read_csv(DATA_DIR / "empathy_scores.csv")
    sessions_map = pd.read_csv(DATA_DIR / "participant_sessions.csv")
    tables = pd.read_html(str(DATA_DIR / "drama_sessions.html"))
    sessions = tables[0]  # BUG: the first table is a legend, not the sessions table
    # BUG: wrong column names expected here; will cause KeyError
    sessions = sessions.rename(columns={"SessionID": "session_id", "Condition": "group"})
    return scores, sessions_map, sessions


def prepare(scores: pd.DataFrame, sessions_map: pd.DataFrame, sessions: pd.DataFrame) -> pd.DataFrame:
    # BUGS to fix: merge keys/column names; wrong score columns; ensure group column exists.
    df = scores.merge(sessions_map, on="participantId")  # BUG: scores uses participant_id
    df = df.merge(sessions, on="session_id", how="left")
    # BUG: wrong column names for score difference
    df["delta"] = df["post"] - df["pre"]
    return df


def summarize(df: pd.DataFrame) -> pd.DataFrame:
    # BUGS to fix: aggregation columns must match corrected names
    summary = df.groupby("group").agg(
        n=("participantId", "count"),
        mean_pre=("pre", "mean"),
        mean_post=("post", "mean"),
        mean_delta=("delta", "mean")
    ).reset_index()
    return summary


def main():
    scores, sessions_map, sessions = load_data()
    df = prepare(scores, sessions_map, sessions)
    summary = summarize(df)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    summary.to_csv(OUTPUT_DIR / "group_summary.csv", index=False)
    # Also save participant deltas
    df[["participantId", "delta"]].to_csv(OUTPUT_DIR / "participant_deltas.csv", index=False)


if __name__ == "__main__":
    main()
