"""End-of-move history (no Qt needed)."""
from pymodaq_plugins_keyboardjog.core.history import MoveHistory, series_key

XY = ['X', 'Y']
GROUPS = [XY, ['Z']]


def test_pair_points_are_recorded_once_both_values_are_known():
    h = MoveHistory()
    assert h.record('X', 1.0, GROUPS, now=1) == set()             # Y unknown yet
    h.set_settled('Y', 5.0)
    assert h.record('X', 2.0, GROUPS, now=2) == {series_key(XY)}
    # the point before the move is added: the path starts where the stage was
    assert h.points(XY) == [[2, 1.0, 5.0], [2, 2.0, 5.0]]
    h.record('Y', 6.0, GROUPS, now=3)
    assert h.points(XY)[-1] == [3, 2.0, 6.0] and len(h.points(XY)) == 3
    h.record('Y', 6.0, GROUPS, now=4)                             # no move: no new point
    assert len(h.points(XY)) == 3
    assert h.points(['Z']) == []


def test_single_actuator_and_max_points():
    h = MoveHistory(max_points=5)
    for i in range(10):
        h.record('Z', float(i), GROUPS, now=i)
    assert [p[1] for p in h.points(['Z'])] == [5.0, 6.0, 7.0, 8.0, 9.0]


def test_set_settled_keeps_the_first_known_value():
    h = MoveHistory()
    h.set_settled('Z', 1.0)
    h.set_settled('Z', 3.0)                                       # live values while moving: ignored
    h.record('Z', 4.0, GROUPS, now=1)
    assert [p[1] for p in h.points(['Z'])] == [1.0, 4.0]


def test_save_load_clear(tmp_path):
    path = tmp_path / 'KeyboardJog' / 'history.json'
    h = MoveHistory(path)
    h.set_settled('Y', 0.0)
    h.record('X', 1.0, GROUPS, now=1)
    h.record('Z', 3.0, GROUPS, now=2)
    h.save()
    again = MoveHistory(path)
    assert again.points(XY) == h.points(XY) and again.points(['Z']) == [[2, 3.0]]
    assert again.clear(XY) == 1
    again.save()
    assert MoveHistory(path).points(XY) == []
    path.write_text('not json', encoding='utf-8')
    assert MoveHistory(path).series == {}                         # unreadable file: empty history, no crash
