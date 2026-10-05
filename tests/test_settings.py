# -*- coding: utf-8 -*-
# tests/test_settings.py
# 設定はプレースホルダ入りの config.json / default_config.json で動く。
import json

import pytest

from bot_module.settings import SettingsError, get_settings, load_settings

DEFAULT = "document/default_config.json"
# リポジトリの設定に入っているプレースホルダ（サーバー固有のIDは置かない）
PROD_GUILD = 222222222222222222
DEV_GUILD = 111111111111111111
DEVELOPER_USER = 111111111111111111
PROD_QUIZ = 100000000000000008
PROD_DAIRY = 100000000000000006
DEV_QUIZ = 100000000000000017
DEV_DAIRY = 100000000000000015


def test_load_defaults():
    settings = load_settings(config_path=DEFAULT, debug=False)
    assert settings.debug_mode is False
    assert settings.ids.developer_user_id == DEVELOPER_USER
    assert settings.ids.guild_ids == [DEV_GUILD, PROD_GUILD]


def test_production_guild_is_selected():
    settings = load_settings(config_path=DEFAULT, debug=False)
    assert settings.guild.quiz_channel_id == PROD_QUIZ
    assert settings.guild.dairy_channel_id == PROD_DAIRY


def test_debug_uses_developer_guild():
    settings = load_settings(config_path=DEFAULT, debug=True)
    assert settings.guild.quiz_channel_id == DEV_QUIZ
    assert settings.guild.dairy_channel_id == DEV_DAIRY


def test_default_guild_id_selects_the_guild(tmp_path):
    raw = json.loads(open(DEFAULT, encoding="utf-8").read())
    raw["DEVELOP_ID_DICT"]["DEFAULT_GUILD_ID"] = str(DEV_GUILD)
    path = tmp_path / "config.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    settings = load_settings(config_path=path, debug=False)

    assert settings.guild.quiz_channel_id == DEV_QUIZ


def test_default_guild_id_falls_back_to_the_last_guild(tmp_path):
    raw = json.loads(open(DEFAULT, encoding="utf-8").read())
    del raw["DEVELOP_ID_DICT"]["DEFAULT_GUILD_ID"]
    path = tmp_path / "config.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    settings = load_settings(config_path=path, debug=False)

    assert settings.guild.quiz_channel_id == PROD_QUIZ


def test_paths_and_link():
    settings = load_settings(config_path=DEFAULT, debug=False)
    assert settings.paths.pokedex == "resource/pokemon_database.csv"
    assert settings.paths.calldata == "save/call_cache.csv"
    assert settings.ex_source_link.startswith("https://")


def test_quiz_dicts():
    settings = load_settings(config_path=DEFAULT, debug=False)
    assert settings.quizname_dict["種族値クイズ"] == "bq"
    assert settings.base_stats_dict["S"] == "すばやさ"
    assert settings.default_filter_dict == {"進化段階": ["最終進化", "進化しない"]}


def test_missing_config_falls_back_to_default():
    settings = load_settings(config_path="tests/no-such-config.json", default_path=DEFAULT)
    assert settings.ids.developer_user_id == DEVELOPER_USER


def test_broken_config_raises_settings_error(tmp_path):
    broken = tmp_path / "config.json"
    broken.write_text("{}", encoding="utf-8")
    with pytest.raises(SettingsError):
        load_settings(config_path=broken)


def test_get_settings_returns_loaded_object():
    settings = load_settings(config_path=DEFAULT, debug=False)
    assert get_settings() is settings


def test_config_module_exposes_legacy_names():
    import bot_module.config as config

    assert config.SETTINGS.guild.quiz_channel_id == config.QUIZ_CHANNEL_ID
    assert config.SETTINGS.paths.pokedex == config.POKEDEX_PATH
    assert config.GUILD_IDS is config.SETTINGS.ids.guild_ids
    assert config.DEFAULT_FILTER_DICT == {"進化段階": ["最終進化", "進化しない"]}
