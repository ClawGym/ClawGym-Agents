Title: Strategy Pivot — Mindshare-Driven Allocation Toward L2 and AI Narratives

Author: Portfolio Strategy Team
Date: 2026-04-19

Executive Summary
We propose a measured pivot of 15% of the portfolio toward assets aligned with the L2 and AI narratives, guided by mindshare momentum and confirmed by high-conviction ETF signals for entry pacing. The shift aims to capture narrative tailwinds while maintaining risk controls (max portfolio 95% 1-day VaR ≤ 3.5%, max drawdown budget ≤ 18%). We will rebalance over 4 tranches (weekly), with tactical accelerations only when signal thresholds are met.

Current Portfolio (Baseline, 100%)
- 45% BTC
- 35% ETH
- 10% SOL
- 5% DeFi basket (UNI/AAVE/MKR/GMX, equal-weight)
- 5% Stablecoin (USDC) for liquidity

Proposed Target Portfolio (100% after 4-week ramp)
- 40% BTC (−5 pp)
- 30% ETH (−5 pp)
- 18% SOL (+8 pp)
- 5% “L2 infra” basket (+3 pp): ARB/OP/MATIC/STRK, equal-weight
- 2% HYPERLIQUID (HYPE) (+2 pp)
- 3% “AI infra” basket (+3 pp): RNDR/TAO/NVML, equal-weight
- 2% RWA basket (+2 pp): ONDO/MKR (RWA sleeve), equal-weight
- 0% Stablecoin (−5 pp) — working capital covered by derivatives margin; keep 2% cash equivalent in custody operational account (not part of investable NAV)

Rationale
- Mindshare signals: Over the last 6–12 months, L2 and AI narratives have shown sustained or rising mindshare, with periodic surges accompanying product launches and fee declines. We hypothesize mindshare leads capital rotation by 2–6 weeks on average.
- Execution tailwinds: Solana ecosystem throughput and fee improvements are creating visible user growth. L2 incentives are driving TVL accretion and app launches. AI narrative has multiple catalysts (inference marketplaces, data availability, GPU-sharing).
- Risk budget: We will fund the pivot by trimming BTC and ETH, preserving blue-chip ballast while increasing exposure to higher beta segments with defined guardrails.

Return/Risk Assumptions (12-month horizon)
- BTC: Exp ret 12%, vol 55%, corr(avg) base basket 0.45
- ETH: Exp ret 15%, vol 65%, corr 0.55
- SOL: Exp ret 25%, vol 90%, corr 0.60
- L2 infra basket: Exp ret 28%, vol 95%, corr 0.62
- HYPE: Exp ret 35%, vol 120%, corr 0.50 (idiosyncratic exchange token risk)
- AI infra basket: Exp ret 30%, vol 110%, corr 0.48
- RWA basket: Exp ret 10%, vol 35%, corr 0.30

Constraints and Kill Switches
- Portfolio 95% 1-day VaR ≤ 3.5% of NAV (historical and parametric checks)
- Max drawdown budget ≤ 18%; breach triggers de-lever to baseline
- Mindshare guardrails (narratives): If a narrative’s 30-day mindshare falls ≥ 15% from its 90-day average and is below the 12-month average, freeze additional buys and rebalance back 50% of that sleeve
- Entity guardrails: If an entity’s rank drops from Top 20 to >50 for 4 consecutive weeks, halve that position
- Signals guardrails: Only accelerate tranches if both min_confidence and min_strength thresholds are met (e.g., 0.78/0.80); otherwise default to schedule

Implementation Plan
- Tranching: 4 equal tranches across weeks 1–4
- Tactical accelerations: +25% tranche size if signals flash “Strong buy” for risk-on proxies (e.g., QQQ/ARKK correlation > 0.6 to AI beta sleeve based on rolling 60-day) while narrative mindshare is “surging”
- Execution venues: Use primary CEXs with best liquidity for majors; route long tail via split orders (TWAP ~ 4h windows)
- Fees and slippage: Assume 6 bps average all-in for majors, 15 bps for long-tail per tranche
- Tooling: Kaito mindshare (weekly pull and 12m context), MoltStreet actionable signals (daily pull with configured thresholds), in-house risk engine for VaR/MDD monitoring

Budget and Costs
- Estimated total fees over 4 tranches: ~0.09% of NAV (weighted)
- Operational lift: 8 analyst-hours per week to update mindshare dashboards and signals reading; automation reduces to 3 hours by week 3

KPIs and Success Criteria (90 days)
- Hit tranche schedule with ≤ 10% deviation unless guardrails triggered
- Narrative exposure performance vs. bench (BTC/ETH blend) ≥ +250 bps over 90 days risk-adjusted
- Portfolio VaR compliance: ≤ 3.5% 95% 1-day VaR at all checkpoints
- At least two narratives classified “surging” during the holding period in ≥ 50% of weekly checks

Data and Measurement
- Mindshare data via kaito_mindshare and kaito_narrative_mindshare; switch tickers to full project names on all-zero returns (e.g., HYPE → HYPERLIQUID)
- Signals via MoltStreet actionable endpoint with thresholds from config (min_confidence, min_strength)
- Weekly report: 12m high/low/average context, current values, rank interpretation for entities, movement classification for narratives, and deltas

Risks and Mitigations
- Narrative reversal risk: Use guardrails tied to 30d vs 90d mindshare trends
- Liquidity risk in long-tail: Cap HYPE at 2% and AI/RWA sleeves at a combined 5%; stagger orders to limit slippage
- Correlation spikes in stress: Dynamic hedging via reducing beta sleeves or adding BTC/ETH on spikes (rule-based)
- If [X] fails: If mindshare leading-lag relationship fails to hold for two consecutive 4-week windows (no alpha vs bench), cease narrative tilt and revert to baseline

Go/No-Go Criteria
- GO if backtest overlay (last 12 months) shows ≥ +300 bps vs bench with VaR within budget
- REWORK if alpha < +150 bps or guardrails would have triggered > 3 times in backtest
- NO-GO if projected VaR > 3.5% at start or liquidity cost > 0.20% of NAV

Requested Decision
Approve the 15% pivot with the above constraints, tranching plan, and monitoring protocol.

Appendix: Correlation Notes
- AI infra sleeve has shown rolling 60-day correlation ~0.6–0.7 with high-beta tech proxies; monitor MoltStreet signals to avoid adding on tech risk-off days.
- L2 and SOL exposures overlap but provide diversification vs. ETH on fee and UX narratives.