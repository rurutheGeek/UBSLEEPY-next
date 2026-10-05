# -*- coding: utf-8 -*-
# tests/test_guild_settings.py
# ギルドごとの設定の解決（DB → config.json の既定値）。
from bot_module import guild_settings, save

PROD_GUILD = 222222222222222222
PROD_QUIZ = 100000000000000008
DEV_GUILD = 111111111111111111
DEV_QUIZ = 100000000000000017


def test_channel_id_prefers_db(monkeypatch):
    monkeypatch.setattr(save, "get_guild_setting", lambda guild_id, key: 999)
    assert guild_settings.channel_id(PROD_GUILD, "QUIZ_CHANNEL_ID") == 999


def test_channel_id_falls_back_to_config(monkeypatch):
    monkeypatch.setattr(save, "get_guild_setting", lambda guild_id, key: None)
    assert guild_settings.channel_id(PROD_GUILD, "QUIZ_CHANNEL_ID") == PROD_QUIZ
    assert guild_settings.channel_id(DEV_GUILD, "QUIZ_CHANNEL_ID") == DEV_QUIZ


def test_channel_id_unknown_guild_is_zero(monkeypatch):
    monkeypatch.setattr(save, "get_guild_setting", lambda guild_id, key: None)
    assert guild_settings.channel_id(12345, "QUIZ_CHANNEL_ID") == 0
