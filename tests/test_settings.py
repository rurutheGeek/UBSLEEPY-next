# -*- coding: utf-8 -*-
# tests/test_settings.py
import pytest

from bot_module.settings import SettingsError, get_settings, load_settings

DEFAULT = "document/default_config.json"
PROD_GUILD = 1067125843647791114
DEV_GUILD = 1140787268370583634


def test_load_defaults():
    settings = load_settings(config_path=DEFAULT, debug=False)
    assert settings.debug_mode is False
    assert settings.ids.developer_user_id == 563436616811675658
    assert settings.ids.guild_ids == [DEV_GUILD, PROD_GUILD]


def test_production_guild_is_selected():
    settings = load_settings(config_path=DEFAULT, debug=False)
    assert settings.guild.quiz_channel_id == 1094729583187722300
    assert settings.guild.dairy_channel_id == 1082026583109419018


def test_debug_uses_developer_guild():
    settings = load_settings(config_path=DEFAULT, debug=True)
    assert settings.guild.quiz_channel_id == 1162900525503754270
    assert settings.guild.dairy_channel_id == 1235888298988273715


def test_paths_and_link():
    settings = load_settings(config_path=DEFAULT, debug=False)
    assert settings.paths.pokedex == "resource/pokemon_database.csv"
    assert settings.paths.systemlog == "save/output_cache.txt"
    assert settings.ex_source_link.startswith("https://")


def test_quiz_dicts():
    settings = load_settings(config_path=DEFAULT, debug=False)
    assert settings.quizname_dict["種族値クイズ"] == "bq"
    assert settings.base_stats_dict["S"] == "すばやさ"
    assert settings.default_filter_dict == {"進化段階": ["最終進化", "進化しない"]}


def test_missing_config_falls_back_to_default():
    settings = load_settings(config_path="tests/no-such-config.json", default_path=DEFAULT)
    assert settings.ids.developer_user_id == 563436616811675658


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
    assert config.BQ_FILTER_DICT is config.DEFAULT_FILTER_DICT