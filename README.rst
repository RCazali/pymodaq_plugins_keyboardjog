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
  * **Main view**: one compact row per displayed actuator: name, live position with units, step size, keys.
    Every actuator bound to a key is always displayed.
  * **Pairs** on the arrow keys: Left / Right move the first actuator (- / +), Down / Up the second one.
    **Single actuators** on two keys of your choice (one for -, one for +). A key used twice is reported in the
    settings and disabled.
  * **Step size** per actuator, in its units. ``+`` multiplies the step by the step factor (10 by default), ``-``
    divides it. By default they act on every displayed actuator; the setting "+/- keys act on: last" restricts them
    to the actuators of the last binding used (shown in bold).
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
2. Open *Extensions > Keyboard Jog*.
3. Click *Settings*, then *Key bindings > Add pair (arrow keys)* and choose the X and Y actuators; or *Add single
   actuator* and type its two keys (``PgUp``, ``PgDown``, ``Home``, ``End``, ``A``, ``F2``...).
4. Set the steps (*Actuators* group, or ``+`` / ``-`` in the main view), save the setup (*New name*, *Save as*).
5. Hide the settings, click the window (green border) and move with the keys.

Keys reserved by the extension: ``+`` (and ``=``), ``-``, Shift, Ctrl, Alt and Tab.

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

Keyboard layout independence (physical keys / AZERTY-QWERTZ presets), active group selection with the number keys,
axis inversion / swap per pair, emergency stop key, software limits and maximum step, lock during scans, display
interactions (absolute position entry, mouse wheel, color while moving), position memory, gamepad support (the input
handling is already "input source -> action"), true continuous motion (needs DAQ_Move evolutions), smart default
setup on first launch.
