# -*- coding: utf-8 -*-
# cogs/logs.py
"""警告以上のログをDiscordのログチャンネルへ流す。"""
from discord.ext import commands, tasks

import bot_module.config as cfg
import bot_module.guild_settings as guild_settings
from bot_module.logging_setup import DiscordLogHandler, logger


class LogRelay(commands.Cog):
    """標準loggingに寄せたログのうち、警告以上をDiscordへ送る。"""

    def __init__(self, bot):
        self.bot = bot
        self.handler = DiscordLogHandler()
        logger.addHandler(self.handler)

    async def cog_load(self):
        self.relay.start()

    def cog_unload(self):
        self.relay.cancel()
        logger.removeHandler(self.handler)

    @tasks.loop(seconds=30)
    async def relay(self):
        lines = self.handler.drain()
        if not lines:
            return
        try:
            channel = self.bot.get_channel(
                guild_settings.setting(cfg.ACTIVE_GUILD_ID, 'LOG_CHANNEL_ID'))
            if channel is None:
                # チャンネルがまだ見えないときは次回に回す
                self.handler.requeue(lines)
                return

            text = "\n".join(lines)
            # 文字数制限のため2000文字ずつ送る
            for i in range(0, len(text), 2000):
                await channel.send(text[i : i + 2000])
        except Exception as e:
            # 送れなかった行は失わず、一度の失敗で tasks.loop ごと止まらないようにする
            self.handler.requeue(lines)
            logger.error(f"ログの中継に失敗しました\n{e}")


async def setup(bot):
    await bot.add_cog(LogRelay(bot))