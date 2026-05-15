# Cumulative Moving Average (CMA) for One-Step-Ahead Forecasting on Univariate Series

Authors: Dana Rhodes (Applied Statistics Lab), Ibrahim Khan (Data Systems Group)

Abstract:
We study the cumulative moving average (CMA) as a baseline forecaster for univariate time series. For each time step t ≥ 2, CMA predicts the next value y_t using the arithmetic mean of all prior observations y_1..y_{t-1}. We evaluate CMA with a one-step-ahead protocol on a finite sequence, reporting mean squared error (MSE) over t = 2..N. Despite its simplicity, CMA provides a competitive sanity check and serves as a reproducible baseline for rapid iteration.

Problem Definition:
Given a univariate sequence {y_t}_{t=1}^N, generate one-step-ahead predictions \hat{y}_t for t = 2..N and assess accuracy via MSE.

Algorithm (CMA):
- Initialization: For t = 1, no prediction is scored (optionally set \hat{y}_1 = y_1 but exclude from evaluation).
- For each t = 2..N:
  - Compute the cumulative mean of observed past values:
    \hat{y}_t = (1 / (t - 1)) * sum_{i=1}^{t-1} y_i
- Output the sequence of predictions {\hat{y}_t}_{t=2}^N.

Evaluation Protocol:
- One-step-ahead evaluation on the same series: for each t = 2..N, compute squared error e_t^2 = (y_t - \hat{y}_t)^2.
- Report mean squared error:
  MSE = (1 / (N - 1)) * sum_{t=2}^N (y_t - \hat{y}_t)^2.
- No data shuffling or lookahead is permitted; each prediction uses only prior observations in temporal order.

Hyperparameters and Notes:
- No tunable hyperparameters are required for CMA.
- Deterministic given the input sequence, enabling exact reproducibility.