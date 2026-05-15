Project preferences and scope notes

1) Focus and narrative
- Disease: Parkinson's disease with emphasis on substantia nigra and basal ganglia circuitry.
- Mechanism: Mitochondrial quality control / mitophagy centered on the PINK1–Parkin axis, but include receptor-mediated mitophagy (BNIP3/BNIP3L/FUNDC1), cargo adapters (OPTN, NDP52/CALCOCO2, TAX1BP1), and deubiquitinases (USP30).
- Scientific goal: Causal genes and pathways via MR, then cellular localization in single-cell data to nominate key cell types and states. A translational shortlist (3–6 genes) suitable for external bulk validation and basic ROC/nomogram if justified.

2) Pattern guidance
- Comfortable with a Pattern A (Mechanism Gene-Set Driven) primary design.
- Open to a Pattern B (Key-Cell Driven) complement: differential abundance and pseudobulk DEG within dopaminergic neurons; check microglia and astrocytes for inflammatory-mitochondrial crosstalk.

3) Data and constraints
- Public data only; no wet-lab validation in scope.
- Outcome GWAS: prioritize meta-analyses (e.g., Nalls 2019 PD meta-analysis) plus FinnGen PD endpoints for replication.
- Instruments: eQTLGen (blood) and GTEx v8 (brain—substantia nigra if available; otherwise cortex/putamen), PsychENCODE for brain eQTL. Consider pQTL (UKB-PPP Olink, deCODE) for proteins where available.
- scRNA/snRNA: prefer human substantia nigra single-nucleus datasets with case/control (examples seen in GEO/CellxGene; accept cross-cohort integration if necessary).

4) Methods preferences
- Include IVW, Weighted Median, MR-Egger, heterogeneity, pleiotropy, Steiger directionality in the core MR.
- If power is sufficient, include colocalization (coloc) and/or SMR+HEIDI for top loci.
- In scRNA, include QC, annotation, module scoring (AUCell/UCell), DEG, GSVA, and at least one trajectory or pseudotime analysis in dopaminergic neurons.
- Communication analysis (CellChat/NicheNet) acceptable as an Advanced addition.

5) Deliverables and timeline
- Target tier: Advanced; competitive but feasible with public data.
- Timeline: 8–10 weeks preferred, with a Minimal Executable Version in 2–4 weeks for internal review.
- Figures: Use a standard figure set with an explicit workflow schematic (Fig 1), causal MR summary (Fig 5), and scRNA localization.

6) Risks and guardrails
- Be explicit on correlation-level versus causal-level evidence — avoid implying DEG/pathway results are causal.
- Include a self-critical risk review and fallback plan (e.g., broaden gene set, relax instrument p-threshold, move to pQTL).