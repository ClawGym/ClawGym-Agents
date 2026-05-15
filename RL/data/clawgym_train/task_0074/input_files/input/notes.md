# Pilot study notes (messy)
- Goal: get a mentor-vetted plan for a small pilot on document layout analysis.
- Baseline idea: run a standard layout parser and evaluate detection (esp. tables) + robustness to handwriting.
- Constraints:
  - Time: ~2 weeks total.
  - Compute: single GPU (12GB), no long training runs.
  - Data: no new manual annotations; rely on existing labels.
- Preferences:
  - Start with a subset, but stratified if possible (by language and handwriting).
  - Reproducible pipeline (+ one script to recompute metrics).
  - Keep the plan practical and incremental.
- Open questions for mentor:
  1) Should we prioritize handwriting robustness vs. multilingual coverage first?
  2) Is it reasonable to exclude very low DPI pages in the pilot?
  3) For metrics, is table F1 sufficient for now, or include region-wise IoU?
- Deliverables I want: a short plan (sections: objectives, data summary, phased plan, risks), and a concise email to Prof. Lee summarizing next steps.
