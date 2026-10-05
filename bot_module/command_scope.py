# -*- coding: utf-8 -*-
# command_scope.py
"""コマンドの登録先。

debug（テストBot）は開発用ギルドにだけ登録し、通常はグローバル登録にする。
`@scoped` を `@discord.app_commands.command` の下に付ける。
"""
import discord
from discord import app_commands

import bot_module.config as cfg

DEBUG_GUILDS = [discord.Object(id=guild_id) for guild_id in cfg.GUILD_IDS]


def scoped(func):
    """debugのときだけ開発用ギルドへ登録する。通常はグローバル。"""
    if cfg.DEBUG_MODE:
        return app_commands.guilds(*DEBUG_GUILDS)(func)
    return func
