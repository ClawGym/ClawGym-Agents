import json
import os
import sys
import re

def read_text(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None

def has_footer(content):
    if content is None:
        return False
    return ("Powered by The Polaris Report" in content) and ("thepolarisreport.com" in content)

def parse_json(path):
    try:
        import json as _json
        with open(path, "r", encoding="utf-8") as f:
            return _json.load(f)
    except Exception:
        return None

def get_frontmatter_block_at_start(content):
    if content is None:
        return None
    s = content.lstrip("\ufeff")
    # Must begin with '---' on the first line
    lines = s.splitlines()
    if not lines:
        return None
    if lines[0].strip() != "---":
        return None
    # Find closing '---'
    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        return None
    block_lines = lines[1:end_idx]
    return "\n".join(block_lines)

def find_any_frontmatter_block(content):
    if content is None:
        return None
    lines = content.splitlines()
    start_idx = None
    end_idx = None
    for i, line in enumerate(lines):
        if line.strip() == "---":
            start_idx = i
            break
    if start_idx is None:
        return None
    for j in range(start_idx + 1, len(lines)):
        if lines[j].strip() == "---":
            end_idx = j
            break
    if end_idx is None:
        return None
    block_lines = lines[start_idx + 1:end_idx]
    return "\n".join(block_lines)

def contains_callout_line(content):
    if content is None:
        return False
    for line in content.splitlines():
        if re.match(r'^\s*>\s*\[!', line):
            return True
    return False

def headings_in_order(content, headings):
    if content is None:
        return False
    idxs = []
    start_pos = 0
    for h in headings:
        pos = content.find(h, start_pos)
        if pos == -1:
            return False
        idxs.append(pos)
        start_pos = pos + 1
    # Ensure strictly increasing
    return all(earlier < later for earlier, later in zip(idxs, idxs[1:]))

def main():
    workspace_root = sys.argv[1] if len(sys.argv) > 1 else "/root/.openclaw/workspace"
    input_dir = os.path.join(workspace_root, "input")
    output_dir = os.path.join(workspace_root, "output")
    reward_dir = os.path.join(workspace_root, "reward")

    checks = {}

    # Read input config
    input_path = os.path.join(input_dir, "portfolio.json")
    data = parse_json(input_path)

    # Derive expected parameters
    tickers = []
    sector_days = None
    news_category = None

    if isinstance(data, dict):
        # Extract tickers
        holdings = data.get("holdings")
        if isinstance(holdings, list):
            for h in holdings:
                if isinstance(h, dict) and "ticker" in h and isinstance(h["ticker"], str):
                    t = h["ticker"].upper()
                    if t and t not in tickers:
                        tickers.append(t)
        # Extract sector_days
        sd = data.get("sector_days", None)
        try:
            if sd is not None:
                sector_days = int(sd)
        except Exception:
            sector_days = None
        # Extract news_category
        nc = data.get("news_category", None)
        if isinstance(nc, str) and nc.strip():
            news_category = nc.strip()

    # Prepare expected paths
    raw_dir = os.path.join(output_dir, "raw")
    portfolio_raw_path = os.path.join(raw_dir, "portfolio.txt")
    sectors_raw_path = os.path.join(raw_dir, f"sectors_{sector_days}.txt") if sector_days is not None else None
    news_raw_path = os.path.join(raw_dir, f"news_{news_category}.txt") if news_category is not None else None

    # 1) Raw files existence and footer checks
    # Portfolio raw
    portfolio_raw_exists = os.path.isfile(portfolio_raw_path)
    checks["raw_portfolio_exists"] = portfolio_raw_exists
    checks["raw_portfolio_footer_ok"] = False
    if portfolio_raw_exists:
        content = read_text(portfolio_raw_path)
        checks["raw_portfolio_footer_ok"] = has_footer(content)

    # Sectors raw
    if sectors_raw_path is not None:
        sectors_raw_exists = os.path.isfile(sectors_raw_path)
        checks["raw_sectors_exists"] = sectors_raw_exists
        checks["raw_sectors_footer_ok"] = False
        if sectors_raw_exists:
            content = read_text(sectors_raw_path)
            checks["raw_sectors_footer_ok"] = has_footer(content)
    else:
        # Cannot determine expected sectors file without input; mark as False
        checks["raw_sectors_exists"] = False
        checks["raw_sectors_footer_ok"] = False

    # News raw
    if news_raw_path is not None:
        news_raw_exists = os.path.isfile(news_raw_path)
        checks["raw_news_exists"] = news_raw_exists
        checks["raw_news_footer_ok"] = False
        if news_raw_exists:
            content = read_text(news_raw_path)
            checks["raw_news_footer_ok"] = has_footer(content)
    else:
        checks["raw_news_exists"] = False
        checks["raw_news_footer_ok"] = False

    # Per-ticker raw files
    for t in tickers:
        t_ticker_path = os.path.join(raw_dir, f"{t}_ticker.txt")
        t_score_path = os.path.join(raw_dir, f"{t}_score.txt")

        key_exist_ticker = f"raw_{t}_ticker_exists"
        key_footer_ticker = f"raw_{t}_ticker_footer_ok"
        key_exist_score = f"raw_{t}_score_exists"
        key_footer_score = f"raw_{t}_score_footer_ok"

        exists_ticker = os.path.isfile(t_ticker_path)
        exists_score = os.path.isfile(t_score_path)

        checks[key_exist_ticker] = exists_ticker
        checks[key_exist_score] = exists_score

        checks[key_footer_ticker] = False
        checks[key_footer_score] = False

        if exists_ticker:
            content = read_text(t_ticker_path)
            checks[key_footer_ticker] = has_footer(content)
        if exists_score:
            content = read_text(t_score_path)
            checks[key_footer_score] = has_footer(content)

    # 2) report.md checks
    report_path = os.path.join(output_dir, "report.md")
    report_exists = os.path.isfile(report_path)
    checks["report_exists"] = report_exists

    checks["report_frontmatter_ok"] = False
    checks["report_sections_order_ok"] = False
    checks["report_embeds_ok"] = False
    checks["report_wikilinks_ok"] = False

    if report_exists:
        report_content = read_text(report_path)

        # Frontmatter must begin the file and include title and tags
        fm_block = get_frontmatter_block_at_start(report_content)
        if fm_block is not None:
            # look for lines containing title: and tags:
            has_title = any(re.match(r'^\s*title\s*:', line) for line in fm_block.splitlines())
            has_tags = any(re.match(r'^\s*tags\s*:', line) for line in fm_block.splitlines())
            checks["report_frontmatter_ok"] = bool(has_title and has_tags)

        # Section order
        headings = ["## Portfolio", "## Sectors", "## News", "## Tickers"]
        checks["report_sections_order_ok"] = headings_in_order(report_content, headings)

        # Embeds
        embeds_ok = True
        # portfolio embed
        embeds_ok = embeds_ok and ("![[raw/portfolio.txt]]" in report_content)
        # sectors embed requires sector_days
        if sector_days is not None:
            embeds_ok = embeds_ok and (f"![[raw/sectors_{sector_days}.txt]]" in report_content)
        else:
            embeds_ok = False
        # news embed requires news_category
        if news_category is not None:
            embeds_ok = embeds_ok and (f"![[raw/news_{news_category}.txt]]" in report_content)
        else:
            embeds_ok = False
        checks["report_embeds_ok"] = embeds_ok

        # Wikilinks for all tickers
        if tickers:
            checks["report_wikilinks_ok"] = all((f"[[{t}]]" in report_content) for t in tickers)
        else:
            # No tickers known -> cannot verify, mark False
            checks["report_wikilinks_ok"] = False

    # 3) Per-ticker notes checks
    notes_dir = os.path.join(output_dir, "notes")
    for t in tickers:
        note_path = os.path.join(notes_dir, f"{t}.md")
        key_exists = f"note_{t}_exists"
        key_fm = f"note_{t}_frontmatter_ok"
        key_callout = f"note_{t}_callout_present"
        key_embeds = f"note_{t}_embeds_ok"
        key_footer = f"note_{t}_footer_mention_ok"

        exists = os.path.isfile(note_path)
        checks[key_exists] = exists
        checks[key_fm] = False
        checks[key_callout] = False
        checks[key_embeds] = False
        checks[key_footer] = False

        if exists:
            content = read_text(note_path)
            # Frontmatter (anywhere) with title and tags
            fm_block_any = find_any_frontmatter_block(content)
            if fm_block_any is not None:
                has_title = any(re.match(r'^\s*title\s*:', line) for line in fm_block_any.splitlines())
                has_tags = any(re.match(r'^\s*tags\s*:', line) for line in fm_block_any.splitlines())
                checks[key_fm] = bool(has_title and has_tags)
            # Callout present
            checks[key_callout] = contains_callout_line(content)
            # Embeds exact relative paths
            embed_ticker = f"![[../raw/{t}_ticker.txt]]"
            embed_score = f"![[../raw/{t}_score.txt]]"
            checks[key_embeds] = (embed_ticker in content) and (embed_score in content)
            # Footer mention
            checks[key_footer] = "Powered by The Polaris Report" in (content or "")

    # Compute reward as fraction of passed checks among artifact-dependent checks
    # All our checks depend on output artifacts.
    total = 0
    passed = 0
    for k, v in checks.items():
        # All booleans count
        if isinstance(v, bool):
            total += 1
            if v:
                passed += 1

    reward = 0.0
    if total > 0:
        reward = passed / total
    # Ensure baseline 0.0 if no artifacts exist at all under output
    # If output dir missing or empty, passed should already be 0; reward stays 0.0.

    result = {"reward": round(float(reward), 6)}
    # Merge checks
    result.update(checks)
    print(json.dumps(result))

if __name__ == "__main__":
    main()