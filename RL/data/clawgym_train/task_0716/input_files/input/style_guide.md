Sector Rotation Briefing — Style Guide

Purpose
- Provide a clear, risk-aware synthesis of AI-generated multi-analyst signals for the 11 SPDR sector ETFs.
- Help readers quickly identify which sectors exhibit strengthening or weakening momentum and why.
- Maintain transparency about data gaps and the speculative nature of sector rotation signals.

Required Sections and Order (use these exact headings)
1) Executive Summary
2) Rotation Gradient
3) Sector-by-Sector Notes
4) Methodology & Limitations
5) Risk Disclaimer
6) Monitoring Plan

Tone and Writing Rules
- Professional, concise, and neutral. Avoid hype or certainty language.
- Be explicit about uncertainty. Use phrases like “appears,” “signals suggest,” and “could.”
- Do not fabricate numbers. If any field is missing (e.g., prediction_accuracy or active_predictions), call it out plainly.
- Prefer short paragraphs, clear bullet points, and concrete references to the signal fields.

Data and Ranking Rules
- Work with the 11 SPDR sector ETFs: XLK, XLF, XLE, XLV, XLI, XLC, XLY, XLP, XLB, XLRE, XLU.
- Sector name mapping:
  - XLK: Technology
  - XLF: Financials
  - XLE: Energy
  - XLV: Healthcare
  - XLI: Industrials
  - XLC: Communication Services
  - XLY: Consumer Discretionary
  - XLP: Consumer Staples
  - XLB: Materials
  - XLRE: Real Estate
  - XLU: Utilities
- Compute cw_bullish_score for each sector as: (bullish / total_analysts) * avg_confidence. Round to 4 decimals.
- Top and bottom rankings:
  - Identify the top 3 and bottom 3 sectors by cw_bullish_score in the Executive Summary.
  - If ties occur, include all tied sectors and state that ties are present.
- Avoid overstating precision. Treat avg_confidence and cw_bullish_score as directional indicators, not exact forecasts.

Section-by-Section Guidance

Executive Summary
- 1–2 paragraphs plus bullets.
- Include:
  - A one-sentence snapshot of current rotation (e.g., “Signals tilt toward cyclical sectors; defensives mixed.”).
  - A bullet list naming the top 3 sectors by cw_bullish_score with scores in parentheses (rounded to 4 decimals).
  - A bullet list naming the bottom 3 sectors by cw_bullish_score with scores in parentheses.
- Include a brief caveat noting the signals are AI-generated and may be revised intraday.

Rotation Gradient
- 1–2 paragraphs explaining where momentum appears to be flowing (e.g., from defensives to cyclicals, or from energy to tech).
- Support with qualitative references to:
  - Relative bullish/bearish counts,
  - Avg_confidence,
  - Any notable clustering in analyst perspectives.
- If gradient is ambiguous, state this, and suggest likely drivers (e.g., macro data, earnings season) without asserting certainty.

Sector-by-Sector Notes
- Organize as a list, one subsection per sector, ideally in rank order by cw_bullish_score (highest to lowest):
  - Header format: “Ticker — Sector Name”
  - Include:
    - Consensus snapshot: bullish, bearish, neutral, total_analysts, avg_confidence (0.0–1.0).
    - At least one analyst perspective:
      - Use the perspectives[] array; summarize one stance and confidence. If perspectives[] is missing, state “No analyst perspectives available in the latest snapshot.”
    - At least one active prediction:
      - Use active_predictions[]; briefly state direction (up/down), target %, and deadline if present. If missing, state “No active predictions provided.”
    - Optional: prediction_accuracy if provided (0.0–1.0). If absent, note the gap.
  - Keep each sector note to 4–7 bullet points or a compact paragraph plus bullets.
- Do not invent missing fields; explicitly label gaps.

Methodology & Limitations
- Explain how signals were obtained (e.g., curl GET to public endpoint for each ticker).
- Describe how cw_bullish_score was calculated: (bullish/total_analysts) * avg_confidence, rounded to 4 decimals.
- Note that signals update multiple times daily and are not real-time quotes.
- Limitations to include:
  - AI-generated analysis can be inconsistent or delayed.
  - Incomplete fields (e.g., missing prediction_accuracy, missing active_predictions) reduce certainty.
  - Sector rotation is inherently speculative; sentiment can reverse quickly.
  - Potential survivorship or selection bias in analyst perspectives.
  - Internet/API availability and transient errors.

Risk Disclaimer
- Must explicitly include the phrases “AI-generated” and “not financial advice.”
- Clarify that readers should not rely solely on these signals for investment decisions and should consider independent verification and personal risk tolerance.

Monitoring Plan
- Define an update cadence (e.g., poll endpoints 2–3 times per day during market hours).
- Outline steps to verify or challenge signals:
  - Cross-check with price/volume trends for the sector ETF.
  - Compare with macro and earnings calendars.
  - Track realized outcomes versus active_predictions over time.
- Specify triggers for reassessment (e.g., large divergences in perspectives, sudden changes in consensus, significant macro events).

Formatting and Length
- Target overall report length: ~1,000–1,800 words.
- Use clear headings and subheadings matching the Required Sections.
- Numeric formatting:
  - avg_confidence and prediction_accuracy: show as decimals between 0.0 and 1.0 when cited.
  - cw_bullish_score: show to 4 decimals for ranking clarity.
- Include all 11 sectors somewhere in the document (either by ticker or sector name).

Phrasing Examples (adapt to actual data)
- “Technology (XLK) leads the rotation by cw_bullish_score, supported by more bullish analysts and higher average confidence versus peers.”
- “Communication Services (XLC) shows mixed sentiment; perspectives are split and active predictions are limited, increasing uncertainty.”
- “Utilities (XLU) ranks in the bottom cohort by cw_bullish_score; several analysts are defensive, and no active predictions were available.”

Compliance Checklist (author must ensure)
- All six required sections are present with exact headings.
- Top 3 and bottom 3 sectors by cw_bullish_score are named in the Executive Summary.
- Each sector note references at least one perspective and one active prediction when available; missing fields are called out explicitly.
- The phrases “AI-generated” and “not financial advice” appear in the Risk Disclaimer.
- The Monitoring Plan includes both cadence and verification steps.