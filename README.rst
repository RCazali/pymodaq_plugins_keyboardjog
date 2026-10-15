pymodaq_plugins_keyboardjog
###########################

.. image:: https://img.shields.io/pypi/v/pymodaq_plugins_keyboardjog.svg
   :target: https://pypi.org/project/pymodaq_plugins_keyboardjog/
   :alt: Latest Version

.. image:: https://github.com/PyMoDAQ/pymodaq_plugins_keyboardjog/actions/workflows/tests.yml/badge.svg
    :target: https://github.com/PyMoDAQ/pymodaq_plugins_keyboardjog/actions/workflows/tests.yml

**Keyboard Jog** is a PyMoDAQ Dashboard extension: a tiny, always-on-top window to move the actuators of the
Dashboard with the keyboard (arrow keys for a pair of axes, keys of your choice for single actuators), while
showing their current position. It is made for alignment work: centering a beam, finding a sample, focusing...

.. figure:: docs/keyboard_jog.png
   :alt: The Keyboard Jog window

   Green border: the window has the keyboard focus, the keys move the actuators. Red border: keys are ignored.


Authors
=======

* RCazali (romcazali@gmail.com)


Extensions
==========

* **Keyboard Jog**: move the Dashboard actuators with the keyboard

  * **Focus indicator** (main safety feature): the window border is **green** when it has the keyboard focus (the
    keys move the actuators) and **red** otherwise (every key is ignored). Click the window to activate it.
    Clicking in the settings tree also makes it red: typing a value never moves an actuator.
  * **Works without configuration**: every actuator of the Dashboard is shown with a number, the first one is
    selected. Keys **1-9** (or a click on a row) select an actuator, **W A S D** move the selection.
  * **Movement keys**: W A S D are recognized by their position on the keyboard (Windows, Linux), so they are the
    Z Q S D keys of an AZERTY keyboard (the labels follow the input language). The arrows can be used instead, or
    both (setting *Move keys*).
  * **Main view**: one compact row per displayed actuator: number, name, live position with units, step size, keys.
    The selection is marked with ▶ and its keys are shown.
  * **Named pairs**: right-click a row, *Pair 'X' with ▸ Y*, give it a name (e.g. "XY stage"): the two actuators
    get one number and are moved together, A / D the first one, S / W the second one. Right-click again to rename
    or unpair. A single actuator is moved by both A / D and S / W.
  * **Extra keys** (settings): two keys of your choice (e.g. PgDown / PgUp for a focus) that always move an
    actuator, whatever the selection. A key used twice is reported in the settings and disabled.
  * **Step size** per actuator, in its units. ``+`` multiplies the step of the selection by the step factor (10 by
    default), ``-`` divides it.
  * **Step mode** (default): one key press = one relative move of one step. Holding the key does nothing more.
  * **Continuous mode**: steps are repeated while the key is held, each one sent only once the previous move is
    done (moves are never queued), with an optional minimum interval. While held, **Shift** = step x10,
    **Ctrl** = step /10 (the stored step is unchanged).
  * **Safety**: OS auto-repeat is ignored, a key press arriving while the actuator is still moving (or moved by
    something else: a scan, its own module...) is dropped, releasing the key stops the repetition at once, and
    losing the focus clears every held key and (option, on by default) stops the actuators moved by this window.
  * **Setups**: the complete configuration (displayed actuators, bindings, steps, options, always-on-top) is
    saved / loaded / deleted by name from the settings, as XML files (PyMoDAQ parameter-tree format) in
    ``<PyMoDAQ local folder>/KeyboardJog/setups``. The last setup is reloaded at startup. A setup referring to an
    actuator that is not in the Dashboard loads anyway: that binding is skipped and a warning is shown.

All the motion goes through the ``DAQ_Move`` modules already loaded in the Dashboard, with their public API only
(``move_rel``, ``stop_motion``, ``current_value_signal``, ``move_done_signal``): no hardware access, zero
connection configuration.


Usage
=====

1. Load a Dashboard preset (PyMoDAQ 5.1) or experiment (5.2+) with actuators, initialize them.
2. Open *Extensions > Keyboard Jog*. Click the window (green border).
3. Press ``1``, ``2``... (or click a row) to select an actuator, move it with W A S D, adjust its step with
   ``+`` / ``-``.
4. Right-click a row to pair two actuators (X / Y of a stage) under one name and number.
5. Optional, in *Settings*: *Add extra keys* (e.g. ``PgDown`` / ``PgUp``), steps and displayed actuators
   (*Actuators*), movement keys, then save the setup (*New name*, *Save as*).

Keys used by the extension: W A S D (by position) and / or the arrows, ``1``-``9`` (top row or keypad; the top row
also works without Shift on an AZERTY keyboard, on Windows and Linux), ``+`` (and ``=``), ``-``, Shift, Ctrl, Alt and
Tab.

Development launch with the mock actuators of ``pymodaq_plugins_mock``::

    python -m pymodaq_plugins_keyboardjog.tools.mock_config            # writes the 'keyboard_jog_mock' preset / experiment
    python -m pymodaq_plugins_keyboardjog.extensions.keyboard_jog keyboard_jog_mock


Installation instructions
=========================

* PyMoDAQ 5.1.x or newer: tested with PyMoDAQ 5.1.10 (Python 3.11, PyQt5) and 5.3.4 (Python 3.12, PyQt6).
* Any operating system supported by PyMoDAQ (developed and tested on Windows 11).
* No driver: the extension only uses the actuators of the Dashboard.

::

    pip install pymodaq_plugins_keyboardjog

or, for development, ``pip install -e .`` in a clone of this repository, then ``pytest``.


To be discussed (not implemented)
=================================

Keyboard layout independence for the extra keys (physical keys / AZERTY-QWERTZ presets), axis inversion / swap per pair, emergency stop key, software limits and maximum step, lock during scans, display
interactions (absolute position entry, mouse wheel, color while moving), position memory, gamepad support (the input
handling is already "input source -> action"), true continuous motion (needs DAQ_Move evolutions), smart default
pairs on first launch.
