import json
import os
import re
import sys
from typing import Any, Dict, List

def read_json(path: str) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)

def extract_banned_words(constraints: Any) -> List[str]:
    # Expect a JSON with banned words/phrases. Common keys: banned_words, banned, forbidden_words
    if isinstance(constraints, list):
        # If file itself is a list of strings
        return [w for w in constraints if isinstance(w, str) and w.strip()]
    if isinstance(constraints, dict):
        for key in ["banned_words", "banned", "forbidden_words", "blocked_words", "prohibited"]:
            val = constraints.get(key)
            if isinstance(val, list):
                return [w for w in val if isinstance(w, str) and w.strip()]
    return []

def main() -> None:
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks: Dict[str, bool] = {
        "episodes_expected_files_present": False,
        "episodes_sections_ok": False,
        "episodes_contains_scene_table": False,
        "episodes_no_banned_words": False,
        "reviews_valid": False,
        "pipeline_state_valid": False,
        "graph_characters_valid": False,
        "graph_hooks_structure_valid": False,
        "graph_hooks_resolution_rules_valid": False,
        "overview_valid": False,
    }

    # Load spec for N and theme
    story_spec_path = os.path.join(input_dir, "story_spec.json")
    spec = read_json(story_spec_path)
    theme = None
    N = None
    if isinstance(spec, dict):
        theme = spec.get("theme")
        t_ep = spec.get("target_episodes")
        if isinstance(t_ep, int) and t_ep > 0:
            N = t_ep

    # If we cannot read N, dependent checks cannot pass
    # Load constraints for banned words
    constraints_path = os.path.join(input_dir, "constraints.json")
    constraints = read_json(constraints_path)
    banned_words = extract_banned_words(constraints)

    # Episodes checks
    episodes_dir = os.path.join(output_dir, "episodes")
    expected_episode_files: List[str] = []
    if isinstance(N, int) and N > 0:
        expected_episode_files = [os.path.join(episodes_dir, f"episode_{i}.md") for i in range(1, N + 1)]
        # Check presence and no extras
        if os.path.isdir(episodes_dir):
            actual_md_files = sorted(
                [os.path.join(episodes_dir, f) for f in os.listdir(episodes_dir) if f.endswith(".md")]
            )
            # Exactly expected set (no gaps, no extras)
            if set(actual_md_files) == set(expected_episode_files):
                checks["episodes_expected_files_present"] = True

        # Verify required headers and non-empty
        if checks["episodes_expected_files_present"]:
            all_have_sections = True
            scene_table_present_any = False
            banned_ok = True
            for i in range(1, N + 1):
                ep_path = os.path.join(episodes_dir, f"episode_{i}.md")
                content = read_text(ep_path)
                if not content.strip():
                    all_have_sections = False
                    banned_ok = False  # cannot verify; do not award
                    continue
                # Required headers
                required_headers = [
                    f"## Episode {i}:",
                    "### Plot Summary",
                    "### Complete Content",
                    "### Character Updates",
                    "### Hook Handling",
                    "### Emotional Curve",
                ]
                for header in required_headers:
                    if header not in content:
                        all_have_sections = False
                        break

                # Scene table header with 'Scene' and '|' in a line (case-insensitive)
                if not scene_table_present_any:
                    for line in content.splitlines():
                        if ("|" in line) and ("scene" in line.lower()):
                            scene_table_present_any = True
                            break

                # Banned words scan only if we have a non-empty banned list
                if banned_words:
                    lower = content.lower()
                    for w in banned_words:
                        if w and w.strip() and w.lower() in lower:
                            banned_ok = False
                            break
                    if not banned_ok:
                        # No need to continue checking banned words for this file
                        pass
                else:
                    # Avoid vacuous pass if no banned words provided
                    banned_ok = False

            if all_have_sections:
                checks["episodes_sections_ok"] = True
            if scene_table_present_any:
                checks["episodes_contains_scene_table"] = True
            if banned_ok:
                checks["episodes_no_banned_words"] = True

    # Reviews validation
    reviews_dir = os.path.join(output_dir, "reviews")
    if isinstance(N, int) and N > 0 and os.path.isdir(reviews_dir):
        reviews_ok = True
        required_check_keys = [
            "Plot Coherence",
            "Character Consistency",
            "Hook Handling",
            "Pacing Control",
            "Emotional Curve",
            "Innovation",
        ]
        for i in range(1, N + 1):
            review_path = os.path.join(reviews_dir, f"episode_{i}_review.json")
            data = read_json(review_path)
            if not isinstance(data, dict):
                reviews_ok = False
                break
            # passed and score
            if data.get("passed") is not True:
                reviews_ok = False
                break
            score = data.get("score")
            if not is_number(score) or score < 7:
                reviews_ok = False
                break
            checks_obj = data.get("checks")
            if not isinstance(checks_obj, dict):
                reviews_ok = False
                break
            if set(checks_obj.keys()) != set(required_check_keys):
                reviews_ok = False
                break
            # Each check has numeric score and non-empty comment
            for k in required_check_keys:
                v = checks_obj.get(k)
                if not isinstance(v, dict):
                    reviews_ok = False
                    break
                cs = v.get("score")
                cc = v.get("comment")
                if not is_number(cs):
                    reviews_ok = False
                    break
                if not isinstance(cc, str) or not cc.strip():
                    reviews_ok = False
                    break
            if not reviews_ok:
                break
            # suggestions array and summary string
            suggestions = data.get("suggestions")
            summary = data.get("summary")
            if not isinstance(suggestions, list):
                reviews_ok = False
                break
            if not isinstance(summary, str):
                reviews_ok = False
                break
        if reviews_ok:
            checks["reviews_valid"] = True

    # Pipeline state
    pipeline_state_path = os.path.join(output_dir, "pipeline_state.json")
    ps = read_json(pipeline_state_path)
    if isinstance(ps, dict) and isinstance(N, int) and N > 0:
        valid = True
        # pipeline_id
        if not isinstance(ps.get("pipeline_id"), str) or not ps.get("pipeline_id").strip():
            valid = False
        # theme matches
        if theme is not None and ps.get("theme") != theme:
            valid = False
        # target_episodes, current_episode, status
        if ps.get("target_episodes") != N:
            valid = False
        if ps.get("current_episode") != N:
            valid = False
        if ps.get("status") != "completed":
            valid = False
        # approvals
        approvals = ps.get("approvals")
        if not (isinstance(approvals, list) and len(approvals) == N and all(a is True for a in approvals)):
            valid = False
        # ai_reviews
        ai_reviews = ps.get("ai_reviews")
        if not (isinstance(ai_reviews, list) and len(ai_reviews) == N):
            valid = False
        else:
            for item in ai_reviews:
                if not isinstance(item, dict):
                    valid = False
                    break
                sc = item.get("score")
                if not is_number(sc) or sc < 7:
                    valid = False
                    break
        # last_output
        last_output = ps.get("last_output")
        if not isinstance(last_output, dict):
            valid = False
        else:
            if last_output.get("episode") != N:
                valid = False
            summ = last_output.get("summary")
            if not isinstance(summ, str) or not summ.strip():
                valid = False
        if valid:
            checks["pipeline_state_valid"] = True

    # Graph validation
    graph_path = os.path.join(output_dir, "graph.json")
    graph = read_json(graph_path)
    characters_ok = False
    hooks_ok = False
    hooks_rules_ok = False
    if isinstance(graph, dict) and isinstance(N, int) and N > 0:
        # Characters
        chars = graph.get("characters")
        if isinstance(chars, list) and len(chars) >= 2:
            ch_valid = True
            for ch in chars:
                if not isinstance(ch, dict):
                    ch_valid = False
                    break
                name = ch.get("name")
                traits = ch.get("traits")
                if not isinstance(name, str) or not name.strip():
                    ch_valid = False
                    break
                if not (isinstance(traits, list) and len([t for t in traits if isinstance(t, str) and t.strip()]) >= 2):
                    ch_valid = False
                    break
            if ch_valid:
                characters_ok = True

        # Hooks structure
        hooks = graph.get("hooks")
        if isinstance(hooks, list) and len(hooks) >= 3:
            id_set = set()
            allowed_types = {"Mystery", "Foreshadowing", "Conflict", "Secret", "Enigma", "Crisis"}
            base_structure_ok = True
            open_count = 0
            resolved_in_values = []
            for h in hooks:
                if not isinstance(h, dict):
                    base_structure_ok = False
                    break
                hid = h.get("id")
                htype = h.get("type")
                desc = h.get("description")
                created_in = h.get("created_in")
                status = h.get("status")
                if not (isinstance(hid, str) and re.fullmatch(r"H-\d{3}", hid or "")):
                    base_structure_ok = False
                    break
                if hid in id_set:
                    base_structure_ok = False
                    break
                id_set.add(hid)
                if htype not in allowed_types:
                    base_structure_ok = False
                    break
                if not isinstance(desc, str) or not desc.strip():
                    base_structure_ok = False
                    break
                if not isinstance(created_in, int):
                    base_structure_ok = False
                    break
                if status not in ("open", "resolved"):
                    base_structure_ok = False
                    break
                if status == "resolved":
                    ri = h.get("resolved_in")
                    if not isinstance(ri, int):
                        base_structure_ok = False
                        break
                    resolved_in_values.append(ri)
                else:
                    open_count += 1
            if base_structure_ok:
                hooks_ok = True
            # Rules: at least one hook resolved_in == N; open_count <= 3
            if base_structure_ok and (N in resolved_in_values) and (open_count <= 3):
                hooks_rules_ok = True

    if characters_ok:
        checks["graph_characters_valid"] = True
    if hooks_ok:
        checks["graph_hooks_structure_valid"] = True
    if hooks_rules_ok:
        checks["graph_hooks_resolution_rules_valid"] = True

    # Overview check
    overview_path = os.path.join(output_dir, "story_overview.json")
    overview = read_json(overview_path)
    if isinstance(overview, dict) and isinstance(N, int) and N > 0:
        ov_ok = True
        summary = overview.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            ov_ok = False
        episodes_arr = overview.get("episodes")
        if not (isinstance(episodes_arr, list) and len(episodes_arr) == N):
            ov_ok = False
        else:
            for item in episodes_arr:
                if not isinstance(item, dict):
                    ov_ok = False
                    break
                title = item.get("title")
                key_events = item.get("key_events")
                if not isinstance(title, str) or not title.strip():
                    ov_ok = False
                    break
                if not (isinstance(key_events, list) and len(key_events) >= 2 and all(isinstance(k, str) for k in key_events)):
                    ov_ok = False
                    break
        o = overview.get("open_hooks_count")
        r = overview.get("resolved_hooks_count")
        if not (is_number(o) and is_number(r)):
            ov_ok = False
        if ov_ok:
            checks["overview_valid"] = True

    # Compute reward as fraction of passed deterministic checks that depend on outputs
    scored_keys = [
        "episodes_expected_files_present",
        "episodes_sections_ok",
        "episodes_contains_scene_table",
        "episodes_no_banned_words",
        "reviews_valid",
        "pipeline_state_valid",
        "graph_characters_valid",
        "graph_hooks_structure_valid",
        "graph_hooks_resolution_rules_valid",
        "overview_valid",
    ]
    passed = sum(1 for k in scored_keys if checks.get(k, False))
    total = len(scored_keys)

    # Baseline: if output dir missing or no expected artifacts, reward should be 0.0
    if not os.path.isdir(output_dir):
        reward = 0.0
    else:
        reward = (passed / total) if total > 0 else 0.0

    # Print JSON result; reward first
    result = {"reward": round(reward, 6)}
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()