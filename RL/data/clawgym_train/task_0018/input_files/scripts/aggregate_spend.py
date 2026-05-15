#!/usr/bin/env python3
"""
Starter script to aggregate monthly spend features and detect simple anomalies.
Note: This script may require fixes; please run and inspect any errors.
It expects to read input transaction CSVs under input/.
"""

import json
from pathlib import Path

import pandas as pd


def main():
    input_dir = Path('input')
    output_dir = Path('output')
    output_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(input_dir.glob('transactions_*.csv'))
    if not files:
        raise FileNotFoundError("No input files found in 'input/'. Expected files named like transactions_*.csv")

    # Intentionally incorrect column names and references (to be fixed based on the actual CSV headers)
    cols = ['transaction_id', 'user_id', 'date', 'amount_usd', 'merchant_category']
    frames = []
    for f in files:
        # This will fail because 'date' and 'amount_usd' don't exist in the provided CSVs
        df = pd.read_csv(f, usecols=cols)
        frames.append(df)
    data = pd.concat(frames, ignore_index=True)

    # Intentionally wrong: using 'date' instead of the actual timestamp column
    data['date'] = pd.to_datetime(data['date'])
    data['month'] = data['date'].dt.to_period('M').astype(str)

    # Intentionally wrong: referring to 'amount_usd'
    grouped = data.groupby(['user_id', 'month'])['amount_usd'].agg(['sum', 'mean', 'count']).reset_index()
    grouped.rename(columns={'sum': 'total_amount', 'mean': 'mean_amount', 'count': 'txn_count'}, inplace=True)
    grouped.to_csv(output_dir / 'aggregates.csv', index=False)

    # Simple anomaly detection using incorrect amount column name
    duplicates = data[data.duplicated('transaction_id', keep=False)][['transaction_id', 'user_id', 'amount_usd', 'date']].to_dict('records')
    negative = data[data['amount_usd'] < 0][['transaction_id', 'user_id', 'amount_usd', 'date']].to_dict('records')
    high_value = data[data['amount_usd'] >= 3000][['transaction_id', 'user_id', 'amount_usd', 'date']].to_dict('records')

    report = {
        'duplicate_transaction_ids': duplicates,
        'negative_amounts': negative,
        'high_value_transactions': high_value
    }
    with open(output_dir / 'anomaly_report.json', 'w') as f:
        json.dump(report, f, indent=2, sort_keys=True)


if __name__ == '__main__':
    main()
