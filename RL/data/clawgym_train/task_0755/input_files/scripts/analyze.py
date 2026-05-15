import json
from pathlib import Path

import pandas as pd
import yaml

# NOTE: This is a starter script. Please modify it to implement the analysis described in the task.
# Expected outputs:
# - output/contestant_summary.csv
# - output/episode_trends.json
# The script should read config/analysis.yaml for weights and episodes_include.


def load_config(cfg_path: str) -> dict:
    with open(cfg_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def ensure_dirs():
    Path('output').mkdir(parents=True, exist_ok=True)


def main():
    cfg = load_config('config/analysis.yaml')
    episodes_path = Path('input/episodes.csv')
    contestants_path = Path('input/contestants.csv')

    if not episodes_path.exists() or not contestants_path.exists():
        raise FileNotFoundError('Missing input files in input/.')

    df = pd.read_csv(episodes_path)
    contestants = pd.read_csv(contestants_path)

    # Apply episode filter from config
    include_eps = cfg.get('episodes_include', [])
    if include_eps:
        df = df[df['episode'].isin(include_eps)].copy()

    # TODO: Compute per-episode z-scores for challenge_score, photoshoot_score, public_vote
    # TODO: Compute weighted_index = challenge_w*z_challenge + photoshoot_w*z_photoshoot + vote_w*z_vote
    # TODO: Aggregate per-contestant metrics (avg_index, consistency_score, episodes_count, eliminated_in)
    # TODO: Aggregate per-episode trends (episode_mean_index, episode_std_index, bottom3)
    # TODO: Write output/contestant_summary.csv and output/episode_trends.json

    print(f"Loaded rows: {len(df)}. Implement analysis logic to produce outputs.")


if __name__ == '__main__':
    ensure_dirs()
    main()
