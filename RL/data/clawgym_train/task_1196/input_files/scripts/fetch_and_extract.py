import json
import sys
import pathlib

# TODO: add any imports you need (e.g., yaml, requests, bs4)


def load_settings(path: str):
    """Load YAML settings and return a dict."""
    # TODO: implement YAML loading
    raise NotImplementedError("Implement YAML loading from config/settings.yaml")


def fetch_html(domain: str, rfc_id: int) -> str:
    """Download HTML for the canonical RFC page on the given domain using the RFC identifier.
    Must target the RFC Editor domain and retrieve the HTML page for the RFC number from config.
    Return the HTML as a string.
    """
    # TODO: implement network fetch without hardcoding page text
    raise NotImplementedError("Implement RFC HTML download")


def extract_headings(html: str):
    """Parse HTML and return (title, headings_list) where title is the document title and
    headings_list are texts from h1/h2/h3 in document order."""
    # TODO: implement using an HTML parser
    raise NotImplementedError("Implement HTML parsing and heading extraction")


def write_json(path: pathlib.Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def run(settings_path: str = "config/settings.yaml"):
    settings = load_settings(settings_path)
    html = fetch_html(settings["target"]["domain"], int(settings["target"]["id"]))
    title, headings = extract_headings(html)
    out_name = f"rfc{settings['target']['id']}_headings.json"
    out_path = pathlib.Path(settings["output_dir"]) / out_name
    payload = {
        "title": title,
        "headings": headings,
        "source": {
            "domain": settings["target"]["domain"],
            "id": int(settings["target"]["id"]),
        },
    }
    write_json(out_path, payload)
    print(str(out_path))


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "config/settings.yaml")
