from scripts.build_digest import build_html


def test_build_html_basic():
    rows = [
        {"date": "2026-04-12", "headline": "Export volumes rise", "summary": "Quarterly exports increased by 3%."},
        {"date": "2026-04-13", "headline": "New trade policy update", "summary": "Policy brief released to members."},
    ]
    html = build_html(rows)
    assert '<h1>Weekly Market Digest</h1>' in html
    assert html.count('<li>') == 2
    assert 'Export volumes rise' in html
