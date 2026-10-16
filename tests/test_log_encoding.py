# -*- coding: utf-8 -*-
import logging

from pymodaq_plugins_keyboardjog.core.log_encoding import ensure_utf8_log_files


def test_micro_sign_written_to_log_file(tmp_path, capsys):
    path = tmp_path / 'test.log'
    logger = logging.getLogger('kbjog_test_log_encoding')
    logger.setLevel(logging.DEBUG)
    handler = logging.FileHandler(path, encoding='cp1252')
    logger.addHandler(handler)
    try:
        assert ensure_utf8_log_files(logger.name) == 1
        logger.debug('target_value value is <DataActuator (-299.1 μm)>')
        handler.flush()
        assert 'Logging error' not in capsys.readouterr().err
        assert 'μm' in path.read_text(encoding='utf-8')
        assert ensure_utf8_log_files(logger.name) == 0  # already UTF-8
    finally:
        logger.removeHandler(handler)
        handler.close()
