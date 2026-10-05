# -*- coding: utf-8 -*-
# cogs/settings.py
"""投稿先チャンネル・ロールの設定（管理者用）。"""
import discord
from discord.ext import commands

import bot_module.config as cfg
from bot_module.command_scope import scoped
import bot_module.func as ub
import bot_module.guild_settings as guild_settings


CHANNEL_CHOICES = [
    ('クイズ（回答の受付）', 'QUIZ_CHANNEL_ID'),
    ('日替わり投稿', 'DAIRY_CHANNEL_ID'),
    ('ログ（警告以上）', 'LOG_CHANNEL_ID'),
]
LABELS = {key: label for label, key in CHANNEL_CHOICES}

ROLE_CHOICES = [
    ('おかねもちロール', 'MENYMONEY_ROLE_ID'),
]
ROLE_LABELS = {key: label for label, key in ROLE_CHOICES}


class Settings(commands.Cog):
    """投稿先チャンネルをDiscordから変えられるようにする。"""

    def __init__(self, bot):
        self.bot = bot

    @discord.app_commands.command(
        name="channel", description="機能ごとの投稿先チャンネルを設定します")
    @scoped
    @discord.app_commands.describe(
        setting="設定する機能", channel="投稿先チャンネル（省略すると現在の設定を表示）")
    @discord.app_commands.choices(
        setting=[
            discord.app_commands.Choice(name=label, value=key)
            for label, key in CHANNEL_CHOICES
        ]
    )
    @discord.app_commands.default_permissions(manage_guild=True)
    async def channel_command(
        self, interaction: discord.Interaction,
        setting: str = None, channel: discord.TextChannel = None
    ):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(
                "この操作は「サーバー管理」の権限が必要です", ephemeral=True)
            return
        if setting is None or channel is None:
            lines = []
            for label, key in CHANNEL_CHOICES:
                value = guild_settings.setting(interaction.guild.id, key)
                lines.append(f"**{label}**: <#{value}>" if value else f"**{label}**: 未設定")
            await interaction.response.send_message(
                "現在の投稿先:\n" + "\n".join(lines)
                + "\n\n変更するには `/channel setting:… channel:#…` を実行してください",
                ephemeral=True)
            return

        # ギルド設定としてDBへ保存する
        if guild_settings.set_setting(interaction.guild.id, setting, channel.id) == 'failed':
            await interaction.response.send_message(
                "設定を保存できませんでした。時間をおいて試してください",
                ephemeral=True)
            return
        ub.output_log(
            f"チャンネル設定を変更しました: {LABELS[setting]} -> #{channel.name}")
        await interaction.response.send_message(
            f"{LABELS[setting]}の投稿先を {channel.mention} に変更しました", ephemeral=True)

    @discord.app_commands.command(
        name="role", description="機能ごとのロールを設定します")
    @scoped
    @discord.app_commands.describe(
        setting="設定する機能", role="付与するロール（省略すると現在の設定を表示）")
    @discord.app_commands.choices(
        setting=[
            discord.app_commands.Choice(name=label, value=key)
            for label, key in ROLE_CHOICES
        ]
    )
    @discord.app_commands.default_permissions(manage_guild=True)
    async def role_command(
        self, interaction: discord.Interaction,
        setting: str = None, role: discord.Role = None
    ):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(
                "この操作は「サーバー管理」の権限が必要です", ephemeral=True)
            return
        if setting is None or role is None:
            lines = []
            for label, key in ROLE_CHOICES:
                value = guild_settings.setting(interaction.guild.id, key)
                lines.append(f"**{label}**: <@&{value}>" if value else f"**{label}**: 未設定")
            await interaction.response.send_message(
                "現在の設定:\n" + "\n".join(lines)
                + "\n\n変更するには `/role setting:… role:@…` を実行してください",
                ephemeral=True)
            return

        # ギルド設定としてDBへ保存する
        if guild_settings.set_setting(interaction.guild.id, setting, role.id) == 'failed':
            await interaction.response.send_message(
                "設定を保存できませんでした。時間をおいて試してください",
                ephemeral=True)
            return
        ub.output_log(
            f"ロール設定を変更しました: {ROLE_LABELS[setting]} -> @{role.name}")
        await interaction.response.send_message(
            f"{ROLE_LABELS[setting]}を {role.mention} に変更しました", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Settings(bot))