import os
import json
import yaml
import pandas as pd

# Baseline v1 scoring: min-max normalize selected features, weighted sum, threshold, write scores
# Note: Does not support negative feature direction or metrics.json yet.

CONFIG_PATH = os.path.join('config', 'matching.yaml')
INPUT_PATH = os.path.join('input', 'pair_features.csv')
OUTPUT_DIR = os.path.join('output')
SCORES_PATH = os.path.join(OUTPUT_DIR, 'scores.csv')


def load_config(path: str):
    with open(path, 'r') as f:
        return yaml.safe_load(f)


def minmax_normalize(df: pd.DataFrame, cols):
    norm = {}
    for c in cols:
        col = df[c].astype(float)
        mn = col.min()
        mx = col.max()
        # Avoid division by zero
        if mx == mn:
            norm[c] = pd.Series([0.0] * len(df), index=df.index)
        else:
            norm[c] = (col - mn) / (mx - mn)
    return pd.DataFrame(norm)


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    cfg = load_config(CONFIG_PATH)
    weights = cfg.get('weights', {})
    threshold = float(cfg.get('score_threshold', 0.5))

    if not weights:
        raise ValueError('No weights defined in config/matching.yaml')

    df = pd.read_csv(INPUT_PATH)
    feature_cols = list(weights.keys())
    norm_df = minmax_normalize(df, feature_cols)

    # Weighted sum of normalized features
    score = 0
    for feat, w in weights.items():
        score = score + (float(w) * norm_df[feat])

    out = pd.DataFrame({
        'pair_id': df['pair_id'],
        'person_a_id': df['person_a_id'],
        'person_b_id': df['person_b_id'],
        'compatibility_score': score.round(4),
        'predicted_match': (score >= threshold).astype(int),
        'matched_label': df['matched_label']
    })

    out.to_csv(SCORES_PATH, index=False)
    print(f'Wrote {SCORES_PATH} with {len(out)} rows')


if __name__ == '__main__':
    main()
