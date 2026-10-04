# -*- coding: utf-8 -*-
# tests/test_config_file.py
import json

import bot_module.config_file as config_file


def test_update_config_changes_only_the_target(tmp_path):
    path = tmp_path / 'config.json'
    path.write_text(json.dumps({
        'GUILD_DICT': {
            '1': {'QUIZ_CHANNEL_ID': 10, 'DAIRY_CHANNEL_ID': 20},
            '2': {'QUIZ_CHANNEL_ID': 30},
        },
    }), encoding='utf-8')

    config_file.update_config(path, 1, 'QUIZ_CHANNEL_ID', 99)

    saved = json.loads(path.read_text(encoding='utf-8'))
    assert saved['GUILD_DICT']['1']['QUIZ_CHANNEL_ID'] == 99
    assert saved['GUILD_DICT']['1']['DAIRY_CHANNEL_ID'] == 20
    assert saved['GUILD_DICT']['2']['QUIZ_CHANNEL_ID'] == 30
    assert not (tmp_path / 'config.json.tmp').exists()
