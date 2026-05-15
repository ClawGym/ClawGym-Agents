import os
import json
from fastapi.testclient import TestClient
from app.main import app


def test_gigs_endpoint_serves_expected_shape():
    os.environ["GIGS_FILE"] = "data/gigs.json"
    client = TestClient(app)
    r = client.get("/gigs")
    assert r.status_code == 200
    payload = r.json()
    assert "count" in payload and "gigs" in payload
    assert isinstance(payload["count"], int)
    assert isinstance(payload["gigs"], list)
    assert payload["count"] == len(payload["gigs"]) 
    for item in payload["gigs"]:
        assert set(["date", "venue", "city", "songs_count"]).issubset(item.keys())
        assert isinstance(item["songs_count"], int)


def test_extracted_json_matches_html_counts():
    # Cross-validate the extracted data against the HTML source
    from bs4 import BeautifulSoup

    with open("data/gigs.html", "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")

    gig_divs = soup.select(".gig")
    total_song_items = 0
    for g in gig_divs:
        total_song_items += len(g.select(".songs li"))

    with open("data/gigs.json", "r", encoding="utf-8") as f:
        gigs_json = json.load(f)

    assert isinstance(gigs_json, list) and len(gigs_json) == len(gig_divs)
    assert sum(g.get("songs_count", 0) for g in gigs_json) == total_song_items
