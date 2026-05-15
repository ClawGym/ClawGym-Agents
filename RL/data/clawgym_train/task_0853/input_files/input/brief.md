# Mini Literature Review Brief
Transformer Architectures for Univariate and Multivariate Time Series Forecasting in Business Applications

Version: 1.0  
Language: English  
Target length: 1,200–1,600 words

## Scope and Audience
This review targets data science leads, applied machine learning practitioners, and analytics researchers working on business forecasting problems such as:
- Demand planning and sales forecasting (retail, e-commerce, supply chain)
- Energy load and renewables generation forecasting (utilities, grid operators)
- Traffic flow and mobility forecasting (transportation, ride-hailing, logistics)

Focus specifically on transformer-based architectures for time series forecasting in both univariate and multivariate settings. Include practical considerations relevant to enterprise environments (data availability/quality, compute constraints, latency/throughput, interpretability, maintenance).

## Inclusion Criteria
- Academic sources only (peer-reviewed journals, conference proceedings, dissertations, official preprints on recognized repositories like arXiv, PMLR, AAAI, NeurIPS, IJF, OpenReview).
- Methods or studies that introduce, adapt, or evaluate transformer-style architectures for time series forecasting; include strong baselines (e.g., DeepAR, N-BEATS) for context and comparison.
- Application relevance to business contexts (demand, energy, traffic) via datasets, case studies, or general-purpose benchmarks commonly used in these domains (e.g., Electricity, Traffic, Exchange, Weather, ETT, M4/M5).
- Publication years primarily 2019–2024 unless seminal.

## Exclusion Criteria
- Non-academic sources (blogs, news, Wikipedia).
- Papers focused solely on anomaly detection, representation learning without forecasting, or unrelated sequence tasks (e.g., pure language modeling) unless directly adapted for forecasting.
- Domain studies without time series forecasting outcomes or methodology.

## Key Definitions and Assumptions
- Univariate vs. Multivariate: single target series vs. multiple interdependent series; consider exogenous covariates and static features as part of multivariate contexts when appropriate.
- Forecasting horizons (suggested ranges; tailor discussion to business context as needed):
  - Short-term: up to 24 steps (e.g., hourly/day-ahead)
  - Medium-term: 24–168 steps (multi-day to weekly)
  - Long-term: >168 steps (multi-week to seasonal)
- Data characteristics: stationary vs. non-stationary; presence of strong seasonality/trend; intermittent demand; missing values; regime shifts.
- Business metrics and evaluation: sMAPE, MAPE/WAPE, MAE/RMSE, pinball loss for quantiles, service level/stock-out risk.

## Guiding Questions
1. When and why do transformer architectures outperform strong baselines (e.g., DeepAR, N-BEATS) in business forecasting?
2. Which architectural choices matter most (e.g., sparse attention, decomposition/auto-correlation, frequency-domain modeling, exponential smoothing priors, static/context gating)?
3. How do models handle horizon length (short/medium/long), exogenous covariates, and cross-series dependencies?
4. What are the computational implications (training/inference complexity, memory footprint) and how do efficient transformer variants mitigate O(L^2) attention costs?
5. How do non-stationarity and seasonality affect model performance and which approaches (decomposition, frequency modeling, smoothing) are effective?
6. What interpretability/diagnostics are available (e.g., variable importance, attention analysis) and how does this inform business decision-making and governance?
7. What deployment considerations arise (cold-start, drift monitoring, backtesting protocols, rolling-origin evaluation, latency SLAs)?
8. What open challenges persist (data sparsity, irregular sampling, probabilistic calibration, cross-domain transfer, scaling to thousands of series, robustness)?

## Required Deliverable Structure
- Sections (H2): Introduction; Methodology (search and selection); Thematic Synthesis; Comparative Analysis; Open Challenges & Research Gaps; Conclusion; References.
- Use only sources listed in input/allowed_sources.csv. Cite at least five distinct sources.
- Numbered in-text citations [1], [2], … starting from [1], contiguous and used consistently.
- References section: each entry must include authors, year, title, venue, and URL exactly as they appear in input/allowed_sources.csv. One reference per citation number; no extras.
- Include one Markdown table in Comparative Analysis with at least four models (e.g., TFT, Informer, Autoformer, FEDformer, ETSformer) covering: key idea, computational complexity, strengths, limitations, reported datasets/benchmarks.
- Include one Mermaid diagram that maps models to forecasting horizons (short/medium/long) and data characteristics (univariate vs. multivariate; stationary vs. non-stationary). The diagram should be concise and align with the discussion.

## Methodology (for your Methodology section)
- Selection: restrict to the curated list in input/allowed_sources.csv. Justify selection by relevance to transformer architectures (and key baselines) and to business applications.
- Extraction: note model class, data setting, attention strategy (full/sparse/frequency/auto-correlation), decomposition, probabilistic outputs, interpretability, datasets, and performance highlights as reported by the source.
- Synthesis: group findings by architectural themes (e.g., efficiency, decomposition/frequency modeling, interpretability, probabilistic forecasting, cross-series scaling).

## Comparative Table Guidance
Include at least four models; suggested attributes:
- Model; Key idea; Attention/Complexity; Strengths (business-relevant); Limitations/Assumptions; Reported datasets/benchmarks.
Candidates: Temporal Fusion Transformers (TFT), Informer, Autoformer, FEDformer, ETSformer, plus baselines DeepAR and N-BEATS for context (the table must include ≥4 models; baselines can appear in text or table as needed).

## Mermaid Diagram Guidance
Create a high-level mapping (example categories; adapt based on sources):
- Nodes for forecasting horizons: short, medium, long.
- Nodes for data characteristics: univariate, multivariate, stationary, non-stationary.
- Connect models to the most appropriate nodes (e.g., TFT → medium/long; multivariate; non-stationary; Informer/FEDformer/Autoformer → long; multivariate; seasonal/non-stationary; ETSformer → seasonal/non-stationary).
Ensure the diagram text is concise and readable.

## Practical Implications to Address
- Data readiness: handling missingness, calendar/event features, holiday effects; normalization and per-series scaling.
- Model selection heuristics: when to favor TFT vs. Informer/Autoformer/FEDformer/ETSformer; when baselines (DeepAR, N-BEATS) may suffice or excel.
- Training regimes: rolling-origin evaluation, cross-validation by time, horizon-wise loss design, probabilistic calibration.
- Compute considerations: sequence length vs. memory; batching thousands of series; mixed precision; efficient attention variants for long horizons.
- Interpretability and governance: variable importance (TFT), attention inspection limits, feature attributions, change management.
- Deployment: monitoring drift, re-training cadence, champion–challenger setups, latency budgets for real-time vs. batch.

Note: You must only cite sources present in input/allowed_sources.csv and produce a citations mapping at output/citations_used.csv with headers: citation_number,id.