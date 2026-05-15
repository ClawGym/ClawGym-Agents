import json
from src.event_parser import parse_events


def test_parse_events_basic():
    events = parse_events('input/events_raw.html')
    assert isinstance(events, list)
    assert len(events) == 2
    titles = [e['title'] for e in events]
    assert 'CreatorCon LA' in titles
    # Slug check
    assert any(e['id'] == 'creatorcon-la' for e in events)
    # Meet&Stream Austin details
    ms = next(e for e in events if e['title'].startswith('Meet&Stream'))
    assert ms['date'] == '2026-07-15'
    assert ms['creators'] == ['GamerJay']


def test_sorted_by_date():
    events = parse_events('input/events_raw.html')
    dates = [e['date'] for e in events]
    assert dates == sorted(dates)
