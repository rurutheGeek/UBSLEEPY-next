# -*- coding: utf-8 -*-
# cogs/admin.py
"""管理者用の開発コマンド。"""
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands

import bot_module.config as cfg

from .daily import post_daily

GUILDS = [discord.Object(id=guild_id) for guild_id in cfg.GUILD_IDS]


class Admin(commands.Cog):
    """管理者権限が必要なコマンド。"""

    def __init__(self, bot):
        self.bot = bot

    @discord.app_commands.command(name="devtest", description="開発者用テストコマンド")
    @discord.app_commands.describe(channel="投稿するチャンネルID")
    @discord.app_commands.guilds(*GUILDS)
    @discord.app_commands.default_permissions(administrator=True)
    async def devtest(
        self, interaction: discord.Interaction, channel: discord.TextChannel = None
    ):
        # テストしたい処理をここに書く
        await interaction.response.send_message(
            f"テストコマンドが実行されました", ephemeral=True
        )

    @discord.app_commands.command(name="devlogin", description="ログイン投稿をテストします")
    @discord.app_commands.describe(channel="投稿するチャンネル")
    @discord.app_commands.guilds(*GUILDS)
    @discord.app_commands.default_permissions(administrator=True)
    async def devlogin(
        self, interaction: discord.Interaction, channel: discord.TextChannel = None
    ):
        if channel:
            channelid = channel.id
        else:
            channelid = cfg.DAIRY_CHANNEL_ID
        await post_daily(
            self.bot,
            datetime.now(ZoneInfo("Asia/Tokyo")).replace(hour=5, minute=0),
            channelid,
        )
        await interaction.response.send_message(
            f"ログインジョブを実行しました", ephemeral=True
        )

    @discord.app_commands.command(
        name="devimport", description="このサーバーにギルドコマンドをインポートします"
    )
    @discord.app_commands.default_permissions(administrator=True)
    async def devimport(self, interaction: discord.Interaction):
        if interaction.user.guild_permissions.administrator:
            if interaction.guild.id in cfg.GUILD_IDS:
                await interaction.response.send_message(
                    "このサーバーはすでに登録されています", ephemeral=True
                )
            else:
                cfg.GUILD_IDS.append(interaction.guild.id)
                with open("config.json", "r", encoding="utf-8") as file:
                    config_dict = json.load(file)

                config_dict["DEVELOP_ID_DICT"]["GUILD_IDS"] = cfg.GUILD_IDS
                with open("config.json", "w", encoding="utf-8") as file:
                    json.dump(config_dict, file, indent=4, ensure_ascii=False)
                    await self.bot.tree.sync(guild=discord.Object(id=interaction.guild.id))
                    await interaction.response.send_message(
                        "このサーバーにギルドコマンドを登録しました", ephemeral=True
                    )


async def setup(bot):
    await bot.add_cog(Admin(bot))