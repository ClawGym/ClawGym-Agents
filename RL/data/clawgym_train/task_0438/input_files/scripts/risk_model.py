import os
import json
import math
import yaml
import pandas as pd

CONFIG_PATH = os.path.join('config', 'model.yaml')


def load_config(path: str):
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def compute_derived_metrics(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    # Derived metrics per specification
    df['loss_rate'] = df['forest_loss_ha_last3yrs'] / df['forest_area_ha']
    df['fire_density'] = df['fire_incidents_last12mo'] / df['area_km2']
    df['road_density'] = df['road_km'] / df['area_km2']
    # 1 km^2 = 100 ha
    df['forest_cover_ratio'] = df['forest_area_ha'] / (df['area_km2'] * 100.0)
    return df


def min_max_normalize(series: pd.Series) -> pd.Series:
    smin, smax = float(series.min()), float(series.max())
    if math.isclose(smin, smax):
        return pd.Series([0.0] * len(series), index=series.index)
    return (series - smin) / (smax - smin)


def compute_risk_scores(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """
    Implement the required normalization and weighted risk scoring:
    - Normalize each derived metric using directions from cfg['metrics'].
    - Compute risk_score as sum(weight_i * normalized_metric_i).
    - Tie-break by higher loss_rate, then higher fire_density.
    - Round normalized metrics and risk_score to cfg['round_decimals'].
    """
    metrics = cfg['metrics']
    dec = int(cfg.get('round_decimals', 4))

    # TODO: Replace the placeholder implementation below with the full logic described above.
    # START TODO
    # Normalize per metric and direction
    norm_cols = {}
    for m_name, m_info in metrics.items():
        direction = m_info.get('direction', 'higher_is_risk')
        base = df[m_name]
        norm = min_max_normalize(base)
        if direction == 'higher_is_risk':
            norm_val = norm
        elif direction == 'lower_is_risk':
            norm_val = 1.0 - norm
        else:
            raise ValueError(f"Unknown direction for {m_name}: {direction}")
        norm_cols[f'normalized_{m_name}'] = norm_val.round(dec)

    for col, series in norm_cols.items():
        df[col] = series

    # Weighted sum
    risk = 0.0
    for m_name, m_info in metrics.items():
        w = float(m_info.get('weight', 0.0))
        risk = risk + w * df[f'normalized_{m_name}']
    df['risk_score'] = risk.round(dec)

    # Ranking with tie-breakers
    df = df.sort_values(by=['risk_score', 'loss_rate', 'fire_density'], ascending=[False, False, False]).reset_index(drop=True)
    df['rank'] = range(1, len(df) + 1)
    # END TODO

    return df


def write_outputs(df: pd.DataFrame, cfg: dict):
    out_csv = cfg['output']['risk_scores_csv']
    out_json = cfg['output']['flags_json']
    os.makedirs(os.path.dirname(out_csv), exist_ok=True)
    os.makedirs(os.path.dirname(out_json), exist_ok=True)

    # Select required columns if present
    required_cols = [
        'municipality_id', 'name',
        'loss_rate', 'fire_density', 'road_density', 'forest_cover_ratio',
        'normalized_loss_rate', 'normalized_fire_density', 'normalized_road_density', 'normalized_forest_cover_ratio',
        'risk_score', 'rank'
    ]
    cols = [c for c in required_cols if c in df.columns]
    df[cols].to_csv(out_csv, index=False)

    threshold = float(cfg.get('high_risk_threshold', 0.6))
    flags = {}
    for _, row in df.iterrows():
        flags[str(int(row['municipality_id']))] = {
            'risk_score': float(row['risk_score']),
            'high_risk': bool(row['risk_score'] >= threshold)
        }
    with open(out_json, 'w', encoding='utf-8') as f:
        json.dump(flags, f, indent=2)


def draft_email(top_df: pd.DataFrame, cfg: dict) -> str:
    dec = int(cfg.get('round_decimals', 4))
    lines = []
    lines.append('Subject: Preliminary rainforest risk prioritization for early support')
    lines.append('')
    lines.append('Dear UNDP country office team,')
    lines.append('')
    # Brief method summary (to be concise but clear)
    lines.append('We applied a transparent, reproducible risk-scoring approach using four indicators: recent forest loss (loss_rate), fire incidence density, road density, and forest cover ratio. Each was min–max normalized; directions were set so higher implies greater risk except forest cover (lower implies higher risk). We then computed a weighted sum based on the configuration to rank municipalities.')
    lines.append('')
    lines.append('Top 3 municipalities:')
    for _, row in top_df.iterrows():
        lines.append(f"- {row['name']} (ID {int(row['municipality_id'])}): risk_score={float(row['risk_score']):.{dec}f}")
    lines.append('')
    # Generic sustainable actions placeholders
    lines.append('Recommended next steps include community-based fire management and targeted restoration incentives aligned with local livelihoods, alongside safeguards for road planning to reduce fragmentation.')
    lines.append('')
    lines.append('Please let me know if you would like the full dataset, assumptions, or to adjust weights in the configuration for scenario testing.')
    lines.append('')
    lines.append('Best regards,')
    lines.append('')
    lines.append('Rainforest Research Team')
    return '\n'.join(lines)


def main():
    cfg = load_config(CONFIG_PATH)
    df = pd.read_csv(os.path.join('input', 'municipal_indicators.csv'))
    df = compute_derived_metrics(df)
    df = compute_risk_scores(df, cfg)
    write_outputs(df, cfg)

    # Email draft
    k = int(cfg.get('top_k', 3))
    top_df = df.nsmallest(k=0, columns=['rank'])  # placeholder to keep shape
    top_df = df.sort_values('rank').head(k)
    email_text = draft_email(top_df, cfg)
    email_path = cfg['output']['email_path']
    os.makedirs(os.path.dirname(email_path), exist_ok=True)
    with open(email_path, 'w', encoding='utf-8') as f:
        f.write(email_text)


if __name__ == '__main__':
    main()
