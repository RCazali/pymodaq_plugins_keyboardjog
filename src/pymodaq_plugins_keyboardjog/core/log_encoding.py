# -*- coding: utf-8 -*-
"""
Make the PyMoDAQ log file accept any character.

pymodaq_utils opens ``pymodaq.log`` with the locale encoding (cp1252 on Windows). With the debug
level of the 5.3 default configuration, every move of an actuator in µm logs its target
('<DataActuator (-299.1 μm)>') and the 'μ' raises a "--- Logging error ---" traceback in the
console. Reopening the file handlers in UTF-8 fixes it for the whole application.
"""
import logging

UTF8 = 'utf-8'


def ensure_utf8_log_files(logger_name: str = 'pymodaq') -> int:
    """Switch the file handlers of the given logger to UTF-8, return how many were changed"""
    changed = 0
    for handler in logging.getLogger(logger_name).handlers:
        if not isinstance(handler, logging.FileHandler):
            continue
        if (handler.encoding or '').lower().replace('_', '-') in ('utf-8', 'utf8'):
            continue
        handler.acquire()
        try:
            handler.encoding = UTF8
            if handler.stream is not None:
                handler.stream.close()
                handler.stream = None  # FileHandler.emit reopens it with the new encoding
        finally:
            handler.release()
        changed += 1
    return changed
