Use a local semantic memory system to store, search, forget, and verify.

Steps:
1) Read input/memories.json and store each of the six items. Capture returned records: id (string), text, category, importance (number), createdAt (number).
2) Read input/queries.json and for each query run a semantic search with limit=3. Record full result objects with: id, text, category, importance, createdAt, score (0..1). Sort each result list by score descending.
3) For the query "branching strategy we use", take the TOP result's id and delete that memory by id. Write that id to output/memory/deleted_id.txt (exactly one line, no extra whitespace).
4) Store a new memory with text "We now use Trunk-Based Development for branching", category "decision", importance 0.9. Save the returned record to output/memory/new_memory.json.
5) Re-run the search for "branching strategy we use" (limit=3) and record results.

Write exactly these files (and no others) under output/:
- output/memory/stored.json — JSON array of the six initially stored records (id, text, category, importance, createdAt).
- output/memory/search_initial.json — JSON object with exactly three keys:
  "branching strategy we use", "morning coffee order", "Phoenix go-live date".
  Each maps to an array (up to 3) of result objects: { id, text, category, importance, createdAt, score } sorted by descending score.
- output/memory/deleted_id.txt — contains only the deleted id (top match from the initial "branching strategy we use" results).
- output/memory/new_memory.json — the newly stored Trunk-Based record (id, text, category, importance, createdAt).
- output/memory/search_after.json — JSON object with exactly one key "branching strategy we use" mapping to up to 3 result objects (same fields), sorted by descending score.

Validation expectations:
- In search_initial.json, the top result for "branching strategy we use" must contain "GitFlow" in its text; for "morning coffee order" must contain "vanilla lattes"; for "Phoenix go-live date" must contain "2026-05-01".
- The id written to deleted_id.txt must equal the id of the top initial "branching strategy we use" result, and that id must not appear in search_after.json.
- search_after.json must include at least one result whose text contains "Trunk-Based".