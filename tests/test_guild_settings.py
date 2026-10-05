# -*- coding: utf-8 -*-
# tests/test_guild_settings.py
# ギルドごとの設定の解決（DB → config.json の既定値）。
import pytest

from bot_module import guild_settings, save


@pytest.fixture(autouse=True)
def _clear_cache():
    guild_settings.reset_cache()
    yield
    guild_settings.reset_cache()

PROD_GUILD = 222222222222222222
PROD_QUIZ = 100000000000000008
DEV_GUILD = 111111111111111111
DEV_QUIZ = 100000000000000017


def test_channel_id_prefers_db(monkeypatch):
    monkeypatch.setattr(save, "get_guild_setting", lambda guild_id, key: 999)
    assert guild_settings.setting(PROD_GUILD, "QUIZ_CHANNEL_ID") == 999


def test_channel_id_falls_back_to_config(monkeypatch):
    monkeypatch.setattr(save, "get_guild_setting", lambda guild_id, key: None)
    assert guild_settings.setting(PROD_GUILD, "QUIZ_CHANNEL_ID") == PROD_QUIZ
    assert guild_settings.setting(DEV_GUILD, "QUIZ_CHANNEL_ID") == DEV_QUIZ


def test_channel_id_unknown_guild_is_zero(monkeypatch):
    monkeypatch.setattr(save, "get_guild_setting", lambda guild_id, key: None)
    assert guild_settings.setting(12345, "QUIZ_CHANNEL_ID") == 0


def test_setting_is_cached(monkeypatch):
    calls = []

    def fake_get(guild_id, key):
        calls.append((guild_id, key))
        return 111

    monkeypatch.setattr(save, "get_guild_setting", fake_get)

    assert guild_settings.setting(1, "QUIZ_CHANNEL_ID") == 111
    assert guild_settings.setting(1, "QUIZ_CHANNEL_ID") == 111
    assert len(calls) == 1


def test_set_setting_updates_cache(monkeypatch):
    monkeypatch.setattr(save, "set_guild_setting", lambda g, k, v: True)

    assert guild_settings.set_setting(1, "QUIZ_CHANNEL_ID", 222) == 'db'
    assert guild_settings.setting(1, "QUIZ_CHANNEL_ID") == 222


def test_set_setting_without_db_is_failed(monkeypatch):
    monkeypatch.setattr(save, "set_guild_setting", lambda g, k, v: False)

    assert guild_settings.set_setting(1, "QUIZ_CHANNEL_ID", 222) == 'failed'


def test_set_setting_save_error_is_failed(monkeypatch):
    def raise_error(guild_id, key, value):
        raise save.SaveError("保存できません")

    monkeypatch.setattr(save, "set_guild_setting", raise_error)

    assert guild_settings.set_setting(1, "QUIZ_CHANNEL_ID", 222) == 'failed'
