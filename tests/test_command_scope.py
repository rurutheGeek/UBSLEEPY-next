# -*- coding: utf-8 -*-
# tests/test_command_scope.py
# コマンドの登録先（debug=開発用ギルド、通常=グローバル）。
from discord import app_commands

import bot_module.config as cfg
from bot_module.command_scope import scoped


def _dummy():
    @app_commands.command(name="dummy", description="テスト")
    @scoped
    async def dummy(interaction):
        pass

    return dummy


def test_scoped_is_global_outside_debug(monkeypatch):
    monkeypatch.setattr(cfg, "DEBUG_MODE", False)
    assert getattr(_dummy(), "_guild_ids", None) is None


def test_scoped_registers_guilds_in_debug(monkeypatch):
    monkeypatch.setattr(cfg, "DEBUG_MODE", True)
    assert _dummy()._guild_ids == [int(g) for g in cfg.GUILD_IDS]
