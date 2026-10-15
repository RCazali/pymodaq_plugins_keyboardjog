"""Abstract actions produced by the input sources and applied by the motion controller.

An input source (the keyboard today, a gamepad later) only translates its events into these actions, so that a
new source can be added without touching the motion controller.
"""
from __future__ import annotations

from dataclasses import dataclass

from qtpy import QtCore


@dataclass(frozen=True)
class MoveAction:
    """Move ``actuator`` by one step in ``direction`` (+1 or -1). ``group`` is the index of the binding"""
    actuator: str
    direction: int
    group: int = -1


class InputSource(QtCore.QObject):
    """Base class of the input sources: the signals the motion controller listens to

    * ``move_pressed`` / ``move_released``: a move action starts / stops being requested (key pressed / released)
    * ``select_requested``: select the group of this number (1 = first group of the main view)
    * ``step_scale_requested``: +1 to multiply the step sizes by the step factor, -1 to divide them
    * ``multiplier_changed``: temporary multiplier of the step while it is held (continuous mode: Shift / Ctrl)
    * ``reset_requested``: forget every held action (focus lost...)
    """
    move_pressed = QtCore.Signal(object)
    move_released = QtCore.Signal(object)
    select_requested = QtCore.Signal(int)
    step_scale_requested = QtCore.Signal(int)
    multiplier_changed = QtCore.Signal(float)
    reset_requested = QtCore.Signal()
