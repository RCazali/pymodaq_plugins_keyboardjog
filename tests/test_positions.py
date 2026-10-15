"""Saved positions (no Qt needed)."""
import pytest

from pymodaq_plugins_keyboardjog.core.positions import PositionStore

XY = ['X', 'Y']


def test_save_replace_delete(tmp_path):
    path = tmp_path / 'KeyboardJog' / 'positions.json'
    store = PositionStore(path)
    store.save(XY, 'HA', [1.0, 2.0], now=1)
    store.save(XY, 'Pump max', [3.0, 4.0], now=2)
    store.save(['Z'], 'HA', [5.0], now=3)                 # same name, other group: independent
    store.save(XY, 'HA', [1.5, 2.5], now=4)               # same name, same group: replaced (and last)
    assert store.names(XY) == ['Pump max', 'HA'] and store.get(XY, 'HA').values == [1.5, 2.5]
    again = PositionStore(path)                           # written at once
    assert again.names(XY) == ['Pump max', 'HA'] and again.get(['Z'], 'HA').values == [5.0]
    again.delete(XY, 'Pump max')
    assert PositionStore(path).names(XY) == ['HA']


def test_invalid_positions_are_refused(tmp_path):
    store = PositionStore(tmp_path / 'positions.json')
    with pytest.raises(ValueError):
        store.save(XY, '  ', [1.0, 2.0])
    with pytest.raises(ValueError):
        store.save(XY, 'HA', [1.0, None])
    with pytest.raises(ValueError):
        store.save(XY, 'HA', [1.0])
    (tmp_path / 'bad.json').write_text('{"positions": {"X|Y": [{"name": "ok", "values": [1, 2]}, {"oops": 1}]}}',
                                       encoding='utf-8')
    assert PositionStore(tmp_path / 'bad.json').names(XY) == ['ok']      # malformed entry skipped, no crash
