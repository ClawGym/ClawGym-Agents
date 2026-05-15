import json
import re
import sys
from pathlib import Path
from xml.etree import ElementTree as ET


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def file_exists(path: Path) -> bool:
    try:
        return path.exists() and path.is_file()
    except Exception:
        return False


def count_words(text: str) -> int:
    words = re.findall(r"\b\w+\b", text)
    return len(words)


def parse_svg_fonts(svg_paths) -> set:
    fonts = set()
    for p in svg_paths:
        try:
            text = read_text(p)
            if not text:
                continue
            try:
                root = ET.fromstring(text)
                for elem in root.iter():
                    ff = elem.attrib.get("font-family")
                    if ff:
                        fonts.add(ff.strip())
            except Exception:
                for m in re.finditer(r'font-family="([^"]+)"', text):
                    fonts.add(m.group(1).strip())
        except Exception:
            continue
    return fonts


def parse_makefile_targets(text: str) -> dict:
    lines = text.splitlines()
    targets = {}
    i = 0
    target_pattern = re.compile(r"^([A-Za-z0-9_.-]+)\s*:(.*)$")
    while i < len(lines):
        line = lines[i]
        m = target_pattern.match(line)
        if m:
            name = m.group(1)
            deps_str = m.group(2).strip()
            deps = [d for d in re.split(r"\s+", deps_str) if d] if deps_str else []
            recipe = []
            i += 1
            while i < len(lines):
                nxt = lines[i]
                if target_pattern.match(nxt):
                    break
                recipe.append(nxt)
                i += 1
            targets[name] = {"deps": deps, "recipe": recipe}
            continue
        i += 1
    return targets


def extract_inkscape_flags_from_recipe(recipe_lines: list) -> list:
    flags = set()
    combined = " ".join(line.strip() for line in recipe_lines)
    if "inkscape" not in combined:
        return []
    for m in re.finditer(r"(--[A-Za-z0-9-]+(?:=[^\s]+)?)", combined):
        flags.add(m.group(1))
    for m in re.finditer(r"(\s-[a-zA-Z])\b", combined):
        flags.add(m.group(1).strip())
    if re.search(r"-d\s+300\b", combined):
        flags.add("-d 300")
    return sorted(flags)


def section_bullets(text: str, section_title: str) -> list:
    lines = text.splitlines()
    idx = -1
    for i, ln in enumerate(lines):
        if section_title.lower() in ln.lower():
            idx = i
            break
    bullets = []
    if idx == -1:
        for ln in lines:
            if ln.strip().startswith("-") or ln.strip().startswith("*"):
                bullets.append(ln.strip())
        return bullets
    for j in range(idx + 1, len(lines)):
        ln = lines[j]
        if ln.strip() == "":
            break
        if ln.strip().startswith("-") or ln.strip().startswith("*"):
            bullets.append(ln.strip())
    if not bullets:
        for j in range(idx + 1, len(lines)):
            ln = lines[j]
            if ln.strip().startswith("-") or ln.strip().startswith("*"):
                bullets.append(ln.strip())
    return bullets


def gather_sources_bullets(report_text: str) -> list:
    bullets = []
    for title in ["Sources consulted", "Sources"]:
        bullets.extend(section_bullets(report_text, title))
    seen = set()
    unique = []
    for b in bullets:
        if b not in seen:
            seen.add(b)
            unique.append(b)
    return unique


def grade(transcript: list, workspace_path: str) -> dict:
    workspace = Path(workspace_path)
    scores = {
        "dockerfile_exists": 0.0,
        "dockerfile_from_ubuntu_22_04": 0.0,
        "dockerfile_installs_inkscape_apt": 0.0,
        "compose_exists": 0.0,
        "compose_service_name_cover_proofs": 0.0,
        "compose_mounts_in_and_out": 0.0,
        "compose_working_dir_work": 0.0,
        "makefile_exists": 0.0,
        "makefile_targets_present": 0.0,
        "makefile_build_uses_docker_compose": 0.0,
        "makefile_png_inkscape_300dpi_and_paths": 0.0,
        "makefile_pdf_inkscape_and_paths": 0.0,
        "makefile_all_runs_png_and_pdf": 0.0,
        "makefile_clean_removes_out_proofs": 0.0,
        "report_exists": 0.0,
        "report_fonts_listed": 0.0,
        "report_dockerfile_explained": 0.0,
        "report_cli_flags_listed": 0.0,
        "report_sources_at_least_two_and_includes_inkscape": 0.0,
        "report_no_urls_in_sources": 0.0,
        "email_polished_exists": 0.0,
        "email_under_180_words": 0.0,
        "email_instructions_build_then_make_all": 0.0,
        "email_mentions_outputs_and_paths": 0.0,
    }

    dockerfile_path = workspace / "docker" / "Dockerfile"
    compose_path = workspace / "docker-compose.yml"
    makefile_path = workspace / "Makefile"
    report_path = workspace / "out" / "REPORT.md"
    email_path = workspace / "out" / "email_polished.txt"

    svg_dir = workspace / "input" / "assets" / "svgs"
    svg_paths = []
    if svg_dir.exists():
        for p in svg_dir.glob("*.svg"):
            svg_paths.append(p)

    dockerfile_text = ""
    if file_exists(dockerfile_path):
        scores["dockerfile_exists"] = 1.0
        dockerfile_text = read_text(dockerfile_path)
        if re.search(r"^\s*from\s+ubuntu:22\.04\b", dockerfile_text, flags=re.IGNORECASE | re.MULTILINE):
            scores["dockerfile_from_ubuntu_22_04"] = 1.0
        dlow = dockerfile_text.lower()
        if ("inkscape" in dlow) and ("apt" in dlow) and ("install" in dlow):
            scores["dockerfile_installs_inkscape_apt"] = 1.0

    compose_text = ""
    if file_exists(compose_path):
        scores["compose_exists"] = 1.0
        compose_text = read_text(compose_path)
        clow = compose_text.lower()
        if "services" in clow and re.search(r"cover-proofs\s*:", compose_text):
            scores["compose_service_name_cover_proofs"] = 1.0
        has_in = ("./input/assets/svgs" in compose_text) and ("/work/in" in compose_text)
        has_out = (("./out" in compose_text) and ("/work/out" in compose_text))
        if has_in and has_out:
            scores["compose_mounts_in_and_out"] = 1.0
        if re.search(r"working_dir\s*:\s*/work\b", compose_text):
            scores["compose_working_dir_work"] = 1.0

    makefile_text = ""
    targets = {}
    if file_exists(makefile_path):
        scores["makefile_exists"] = 1.0
        makefile_text = read_text(makefile_path)
        targets = parse_makefile_targets(makefile_text)
        required_targets = {"build", "png", "pdf", "all", "clean"}
        if required_targets.issubset(set(targets.keys())):
            scores["makefile_targets_present"] = 1.0

        if "build" in targets:
            recipe = "\n".join(targets["build"]["recipe"]).lower()
            if ("docker compose build" in recipe) or ("docker-compose build" in recipe):
                scores["makefile_build_uses_docker_compose"] = 1.0

        if "png" in targets:
            recipe_lines = targets["png"]["recipe"]
            png_recipe = "\n".join(recipe_lines)
            png_low = png_recipe.lower()
            has_docker_run = (("docker compose run" in png_low) or ("docker-compose run" in png_low)) and ("--rm" in png_low) and ("cover-proofs" in png_low)
            has_inkscape = "inkscape" in png_low
            has_300dpi = ("-d 300" in png_recipe) or ("--export-dpi=300" in png_recipe)
            writes_png_dir = ("out/proofs/png" in png_recipe) or ("/work/out/proofs/png" in png_recipe)
            uses_input_dir = ("/work/in" in png_recipe) or ("input/assets/svgs" in png_recipe) or ("*.svg" in png_recipe)
            has_png_flag = ("--export-type=png" in png_recipe) or (".png" in png_recipe)
            if has_docker_run and has_inkscape and has_300dpi and writes_png_dir and uses_input_dir and has_png_flag:
                scores["makefile_png_inkscape_300dpi_and_paths"] = 1.0

        if "pdf" in targets:
            recipe_lines = targets["pdf"]["recipe"]
            pdf_recipe = "\n".join(recipe_lines)
            pdf_low = pdf_recipe.lower()
            has_docker_run = (("docker compose run" in pdf_low) or ("docker-compose run" in pdf_low)) and ("--rm" in pdf_low) and ("cover-proofs" in pdf_low)
            has_inkscape = "inkscape" in pdf_low
            writes_pdf_dir = ("out/proofs/pdf" in pdf_recipe) or ("/work/out/proofs/pdf" in pdf_recipe)
            uses_input_dir = ("/work/in" in pdf_recipe) or ("input/assets/svgs" in pdf_recipe) or ("*.svg" in pdf_recipe)
            has_pdf_flag = ("--export-type=pdf" in pdf_recipe) or (".pdf" in pdf_recipe)
            if has_docker_run and has_inkscape and writes_pdf_dir and uses_input_dir and has_pdf_flag:
                scores["makefile_pdf_inkscape_and_paths"] = 1.0

        if "all" in targets:
            deps = set(targets["all"]["deps"])
            recipe_text = "\n".join(targets["all"]["recipe"]).lower()
            if ({"png", "pdf"}.issubset(deps)) or (("make png" in recipe_text and "make pdf" in recipe_text) or ("$(MAKE) png" in recipe_text and "$(MAKE) pdf" in recipe_text)):
                scores["makefile_all_runs_png_and_pdf"] = 1.0

        if "clean" in targets:
            crecipe = "\n".join(targets["clean"]["recipe"])
            if ("out/proofs" in crecipe) or ("/work/out/proofs" in crecipe):
                if re.search(r"rm\s+-rf\b", crecipe) or "rm -r" in crecipe:
                    scores["makefile_clean_removes_out_proofs"] = 1.0

    report_text = ""
    if file_exists(report_path):
        scores["report_exists"] = 1.0
        report_text = read_text(report_path)
        rlow = report_text.lower()

        expected_fonts = parse_svg_fonts(svg_paths)
        if expected_fonts:
            all_present = True
            for ff in expected_fonts:
                if ff.lower() not in rlow:
                    all_present = False
                    break
            if all_present:
                scores["report_fonts_listed"] = 1.0

        if ("dockerfile" in rlow or "image" in rlow) and ("ubuntu" in rlow and ("22.04" in report_text or "22" in report_text)) and ("inkscape" in rlow) and ("apt" in rlow):
            scores["report_dockerfile_explained"] = 1.0

        make_flags = set()
        if "png" in targets:
            for f in extract_inkscape_flags_from_recipe(targets["png"]["recipe"]):
                make_flags.add(f)
        if "pdf" in targets:
            for f in extract_inkscape_flags_from_recipe(targets["pdf"]["recipe"]):
                make_flags.add(f)
        if make_flags:
            if all(f in report_text for f in make_flags):
                scores["report_cli_flags_listed"] = 1.0

        bullets = gather_sources_bullets(report_text)
        bullets = [b for b in bullets if b.strip("-* ").strip() != ""]
        if len(bullets) >= 2 and any("inkscape" in b.lower() for b in bullets):
            scores["report_sources_at_least_two_and_includes_inkscape"] = 1.0
        if bullets and all(("http" not in b.lower() and "www." not in b.lower()) for b in bullets):
            scores["report_no_urls_in_sources"] = 1.0

    if file_exists(email_path):
        scores["email_polished_exists"] = 1.0
        email_text = read_text(email_path)
        wc = count_words(email_text)
        if wc <= 180:
            scores["email_under_180_words"] = 1.0
        elow = email_text.lower()
        mentions_make_build = ("make build" in elow) or ("docker compose build" in elow) or ("docker-compose build" in elow)
        mentions_make_all = ("make all" in elow)
        if mentions_make_build and mentions_make_all:
            scores["email_instructions_build_then_make_all"] = 1.0
        mentions_outputs = ("png" in elow and "pdf" in elow)
        mentions_paths = ("out/proofs" in email_text) or ("out/proofs/png" in email_text) or ("out/proofs/pdf" in email_text)
        if mentions_outputs and mentions_paths:
            scores["email_mentions_outputs_and_paths"] = 1.0

    return scores


def main() -> None:
    workspace = "."
    if len(sys.argv) > 1:
        workspace = sys.argv[1]
    result = grade([], workspace)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()