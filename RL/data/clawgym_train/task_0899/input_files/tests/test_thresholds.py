import json

def test_produce_threshold_is_seven_celsius():
    with open('config/thresholds.json', 'r', encoding='utf-8') as f:
        cfg = json.load(f)
    assert 'produce' in cfg, 'missing produce section in thresholds.json'
    assert 'max_celsius' in cfg['produce'], 'missing max_celsius in produce config'
    assert cfg['produce']['max_celsius'] == 7.0, 'max_celsius must be exactly 7.0°C for chilled produce'
