import csv
import json
import re
import sys
from pathlib import Path
from typing import List, Dict, Optional, Tuple


def safe_read_text(p: Path) -> Optional[str]:
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return None


def safe_load_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def safe_read_csv_with_header(p: Path) -> Tuple[Optional[List[str]], Optional[List[Dict[str, str]]]]:
    try:
        with p.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames[:] if reader.fieldnames is not None else None
            rows = [dict(row) for row in reader] if header is not None else []
            return header, rows
    except Exception:
        return None, None


def _strip_parenthetical(text: str) -> str:
    base = text.split("(", 1)[0].strip().lower()
    return base


def _collapse_spaces(s: str) -> str:
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"\s+([.,;:!?])", r"\1", s)
    return s.strip()


def compute_concise_description(description: str, max_len: int = 180) -> str:
    fillers = ["really", "super", "actually", "just", "basically"]
    text = description.replace("\n", " ")
    pattern = r"\b(" + "|".join(map(re.escape, fillers)) + r")\b"
    text = re.sub(pattern, "", text, flags=re.IGNORECASE)
    text = _collapse_spaces(text)
    if len(text) <= max_len:
        return text
    cutoff = text[:max_len]
    if " " in cutoff:
        cutoff = cutoff[: cutoff.rfind(" ")]
    return cutoff.strip()


def parse_recipe_file(path: Path) -> Optional[Dict]:
    content = safe_read_text(path)
    if content is None:
        return None
    lines = [ln.rstrip("\r") for ln in content.splitlines()]
    data = {
        "file_name": path.name,
        "title": None,
        "category": None,
        "prep_minutes": None,
        "cook_minutes": None,
        "servings": None,
        "description": "",
        "ingredients": [],
    }
    in_description = False
    in_ingredients = False

    for line in lines:
        if re.match(r"^\s*Title:\s*", line):
            data["title"] = line.split(":", 1)[1].strip()
            in_description = False
            in_ingredients = False
            continue
        if re.match(r"^\s*Category:\s*", line):
            data["category"] = line.split(":", 1)[1].strip()
            in_description = False
            in_ingredients = False
            continue
        if re.match(r"^\s*Prep Time:\s*", line):
            m = re.search(r"(\d+)", line)
            if m:
                data["prep_minutes"] = int(m.group(1))
            in_description = False
            in_ingredients = False
            continue
        if re.match(r"^\s*Cook Time:\s*", line):
            m = re.search(r"(\d+)", line)
            if m:
                data["cook_minutes"] = int(m.group(1))
            in_description = False
            in_ingredients = False
            continue
        if re.match(r"^\s*Servings:\s*", line):
            m = re.search(r"(\d+)", line)
            if m:
                data["servings"] = int(m.group(1))
            in_description = False
            in_ingredients = False
            continue
        if re.match(r"^\s*Description:\s*$", line):
            in_description = True
            in_ingredients = False
            continue
        if re.match(r"^\s*Ingredients:\s*$", line):
            in_description = False
            in_ingredients = True
            continue
        if re.match(r"^\s*Directions:\s*$", line):
            in_description = False
            in_ingredients = False
            continue

        if in_description:
            if line.strip() == "":
                continue
            data["description"] += (line.strip() + " ")
            continue

        if in_ingredients:
            if line.strip().startswith("-"):
                bullet = line.strip()
                bullet = re.sub(r"^-+\s*", "", bullet)
                data["ingredients"].append(bullet)
                continue
            if re.match(r"^\s*\w.+:\s*$", line):
                in_ingredients = False
                continue

    data["description"] = data["description"].strip()
    required_fields = ["title", "category", "prep_minutes", "cook_minutes", "servings", "description"]
    if any(data.get(f) in (None, "") for f in required_fields):
        return None
    return data


def compute_expected_from_inputs(inputs_dir: Path) -> List[Dict]:
    recipes = []
    for p in sorted((inputs_dir / "input" / "recipes").glob("*.txt")):
        parsed = parse_recipe_file(p)
        if not parsed:
            continue
        concise = compute_concise_description(parsed["description"])
        total_minutes = (parsed["prep_minutes"] or 0) + (parsed["cook_minutes"] or 0)
        rec = {
            "file_name": parsed["file_name"],
            "title": parsed["title"],
            "category": parsed["category"],
            "prep_minutes": parsed["prep_minutes"],
            "cook_minutes": parsed["cook_minutes"],
            "total_minutes": total_minutes,
            "servings": parsed["servings"],
            "ingredients_count": len(parsed["ingredients"]),
            "concise_description": concise,
            "ingredients": parsed["ingredients"],
        }
        recipes.append(rec)
    return recipes


def check_index_csv(workspace: Path, expected: List[Dict]) -> Dict[str, float]:
    scores = {
        "recipes_index_exists": 0.0,
        "recipes_index_header": 0.0,
        "recipes_index_rows_cover_inputs": 0.0,
        "recipes_index_banana_row_correct": 0.0,
        "recipes_index_tacos_row_correct": 0.0,
    }
    index_path = workspace / "output" / "recipes_index.csv"
    if not index_path.exists():
        return scores
    scores["recipes_index_exists"] = 1.0
    header, rows = safe_read_csv_with_header(index_path)
    if header is None or rows is None:
        return scores

    expected_header = [
        "file_name",
        "title",
        "category",
        "prep_minutes",
        "cook_minutes",
        "total_minutes",
        "servings",
        "ingredients_count",
        "concise_description",
    ]
    if header == expected_header:
        scores["recipes_index_header"] = 1.0

    by_file = {}
    for row in rows:
        if "file_name" in row:
            by_file[row["file_name"]] = row

    if len(rows) == len(expected):
        scores["recipes_index_rows_cover_inputs"] = 1.0

    def row_matches(exp: Dict, row: Dict) -> bool:
        try:
            return (
                row.get("file_name", "").strip() == exp["file_name"]
                and row.get("title", "").strip() == exp["title"]
                and row.get("category", "").strip() == exp["category"]
                and int(row.get("prep_minutes", "").strip()) == exp["prep_minutes"]
                and int(row.get("cook_minutes", "").strip()) == exp["cook_minutes"]
                and int(row.get("total_minutes", "").strip()) == exp["total_minutes"]
                and int(row.get("servings", "").strip()) == exp["servings"]
                and int(row.get("ingredients_count", "").strip()) == exp["ingredients_count"]
                and row.get("concise_description", "").strip() == exp["concise_description"]
            )
        except Exception:
            return False

    banana = next((e for e in expected if e["file_name"] == "Banana_Bread.txt"), None)
    tacos = next((e for e in expected if e["file_name"] == "Weeknight_Chicken_Tacos.txt"), None)

    if banana and banana["file_name"] in by_file:
        if row_matches(banana, by_file[banana["file_name"]]):
            scores["recipes_index_banana_row_correct"] = 1.0
    if tacos and tacos["file_name"] in by_file:
        if row_matches(tacos, by_file[tacos["file_name"]]):
            scores["recipes_index_tacos_row_correct"] = 1.0

    return scores


def compute_expected_stats(expected_recipes: List[Dict]) -> Dict:
    recipe_count = len(expected_recipes)
    if recipe_count == 0:
        return {
            "recipe_count": 0,
            "avg_prep_minutes": 0.0,
            "avg_total_minutes": 0.0,
            "counts_by_category": {},
            "unique_ingredients_count": 0,
        }
    total_prep = sum(r["prep_minutes"] for r in expected_recipes)
    total_total = sum(r["total_minutes"] for r in expected_recipes)
    avg_prep = round(total_prep / recipe_count, 1)
    avg_total = round(total_total / recipe_count, 1)
    counts_by_category: Dict[str, int] = {}
    unique_ings = set()
    for r in expected_recipes:
        cat = r["category"]
        counts_by_category[cat] = counts_by_category.get(cat, 0) + 1
        for ing in r["ingredients"]:
            norm = _strip_parenthetical(ing)
            if norm:
                unique_ings.add(norm)
    return {
        "recipe_count": recipe_count,
        "avg_prep_minutes": avg_prep,
        "avg_total_minutes": avg_total,
        "counts_by_category": counts_by_category,
        "unique_ingredients_count": len(unique_ings),
    }


def check_stats_json(workspace: Path, expected_stats: Dict) -> Dict[str, float]:
    scores = {
        "stats_exists": 0.0,
        "stats_values_correct": 0.0,
    }
    stats_path = workspace / "output" / "stats.json"
    if not stats_path.exists():
        return scores
    scores["stats_exists"] = 1.0
    stats = safe_load_json(stats_path)
    if not isinstance(stats, dict):
        return scores
    try:
        cond = (
            stats.get("recipe_count") == expected_stats["recipe_count"]
            and abs(float(stats.get("avg_prep_minutes")) - expected_stats["avg_prep_minutes"]) < 1e-6
            and abs(float(stats.get("avg_total_minutes")) - expected_stats["avg_total_minutes"]) < 1e-6
            and isinstance(stats.get("counts_by_category"), dict)
            and stats.get("counts_by_category") == expected_stats["counts_by_category"]
            and int(stats.get("unique_ingredients_count")) == expected_stats["unique_ingredients_count"]
        )
        if cond:
            scores["stats_values_correct"] = 1.0
    except Exception:
        pass
    return scores


def check_digest(workspace: Path, expected_recipes: List[Dict], expected_stats: Dict) -> Dict[str, float]:
    scores = {
        "digest_exists": 0.0,
        "digest_first_line_correct": 0.0,
        "digest_recipe_lines_correct": 0.0,
        "digest_final_line_correct": 0.0,
    }
    digest_path = workspace / "output" / "messages" / "new_recipe_digest.txt"
    if not digest_path.exists():
        return scores
    scores["digest_exists"] = 1.0
    text = safe_read_text(digest_path)
    if text is None:
        return scores
    lines = [ln.rstrip("\r") for ln in text.splitlines()]
    if len(lines) < 3:
        return scores

    expected_new_count = len(expected_recipes)
    first_line = f"New recipes added: {expected_new_count}"
    if lines[0].strip() == first_line:
        scores["digest_first_line_correct"] = 1.0

    recipe_lines = lines[1:-1]
    expected_titles_to_desc = {r["title"]: r["concise_description"] for r in expected_recipes}
    if len(recipe_lines) == expected_new_count:
        ok_count = 0
        for ln in recipe_lines:
            if not ln.startswith("- "):
                continue
            parts = ln[2:].split(" — ")
            if len(parts) != 2:
                continue
            title = parts[0].strip()
            desc = parts[1].strip()
            if title in expected_titles_to_desc and desc == expected_titles_to_desc[title]:
                ok_count += 1
        if ok_count == expected_new_count:
            scores["digest_recipe_lines_correct"] = 1.0

    final_line = lines[-1].strip()
    m = re.match(r"^Top category:\s*(.+)\s*\|\s*Avg total time:\s*([0-9]+(?:\.[0-9]+)?)\s*min$", final_line)
    if m:
        cat = m.group(1).strip()
        avg_str = m.group(2).strip()
        try:
            avg_val = float(avg_str)
        except Exception:
            avg_val = None
        counts = expected_stats.get("counts_by_category", {})
        if counts:
            max_count = max(counts.values())
            allowed_cats = {k for k, v in counts.items() if v == max_count}
        else:
            allowed_cats = set()
        exp_avg_total = expected_stats.get("avg_total_minutes", 0.0)
        exp_int = int(round(exp_avg_total))
        cat_ok = cat in allowed_cats if allowed_cats else True
        avg_ok = avg_val is not None and int(round(avg_val)) == exp_int
        if cat_ok and avg_ok:
            scores["digest_final_line_correct"] = 1.0

    return scores


def check_state_file(workspace: Path, expected_recipes: List[Dict]) -> Dict[str, float]:
    scores = {
        "state_exists": 0.0,
        "state_contains_processed_entries": 0.0,
    }
    state_path = workspace / "output" / "state" / "processed_files.json"
    if not state_path.exists():
        return scores
    scores["state_exists"] = 1.0
    data = safe_load_json(state_path)
    if data is None:
        return scores
    expected_files = {r["file_name"] for r in expected_recipes}
    found_files = set()
    try:
        if isinstance(data, dict):
            for k, v in data.items():
                if isinstance(k, str) and isinstance(v, str) and v.strip() != "":
                    if k in expected_files:
                        found_files.add(k)
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    fn = item.get("file_name") or item.get("file")
                    hv = item.get("hash") or item.get("content_hash")
                    if isinstance(fn, str) and isinstance(hv, str) and fn in expected_files and hv.strip() != "":
                        found_files.add(fn)
    except Exception:
        pass
    if found_files == expected_files and len(found_files) > 0:
        scores["state_contains_processed_entries"] = 1.0
    return scores


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "recipes_index_exists": 0.0,
        "recipes_index_header": 0.0,
        "recipes_index_rows_cover_inputs": 0.0,
        "recipes_index_banana_row_correct": 0.0,
        "recipes_index_tacos_row_correct": 0.0,
        "stats_exists": 0.0,
        "stats_values_correct": 0.0,
        "digest_exists": 0.0,
        "digest_first_line_correct": 0.0,
        "digest_recipe_lines_correct": 0.0,
        "digest_final_line_correct": 0.0,
        "state_exists": 0.0,
        "state_contains_processed_entries": 0.0,
    }

    expected_recipes = compute_expected_from_inputs(workspace)

    index_scores = check_index_csv(workspace, expected_recipes)
    scores.update(index_scores)

    expected_stats = compute_expected_stats(expected_recipes)
    stats_scores = check_stats_json(workspace, expected_stats)
    scores.update(stats_scores)

    digest_scores = check_digest(workspace, expected_recipes, expected_stats)
    scores.update(digest_scores)

    state_scores = check_state_file(workspace, expected_recipes)
    scores.update(state_scores)

    return scores


def main() -> None:
    workspace_path = sys.argv[1] if len(sys.argv) > 1 else "."
    result = grade([], workspace_path)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()