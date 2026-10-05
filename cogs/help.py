# -*- coding: utf-8 -*-
# cogs/help.py
"""このBotのコマンドヘルプ。

`/help` で全コマンドの一覧、`/help コマンド名` で1つのコマンドの詳細を表示する。
"""
import discord
from discord.ext import commands

import bot_module.config as cfg
from bot_module.command_scope import scoped



class Help(commands.Cog):
    """コマンドの使い方を表示する。"""

    def __init__(self, bot):
        self.bot = bot

    def _commands(self):
        """登録済みコマンド（ギルド側を含む）を名前順で返す。"""
        found = {}
        for command in self.bot.tree.get_commands():
            found[command.name] = command
        for guild_id in cfg.GUILD_IDS:
            guild = discord.Object(id=guild_id)
            for command in self.bot.tree.get_commands(guild=guild):
                found[command.name] = command
        return [found[name] for name in sorted(found)]

    async def _autocomplete(self, interaction, current):
        return [
            discord.app_commands.Choice(name=command.name, value=command.name)
            for command in self._commands()
            if current.lower() in command.name.lower()
        ][:25]

    @staticmethod
    def _usage(command, prefix=''):
        parts = [f'/{prefix}{command.name}']
        for parameter in command.parameters:
            if parameter.required:
                parts.append(f'<{parameter.name}>')
            else:
                parts.append(f'[{parameter.name}]')
        return ' '.join(parts)

    @discord.app_commands.command(
        name='help', description='このBotのコマンド一覧と使い方')
    @discord.app_commands.describe(command='詳しく見たいコマンド（省略すると全部）')
    @discord.app_commands.autocomplete(command=_autocomplete)
    @scoped
    async def help(self, interaction: discord.Interaction, command: str = None):
        if command is None:
            embed = self._overview()
        else:
            found = next(
                (c for c in self._commands() if c.name == command), None)
            if found is None:
                await interaction.response.send_message(
                    f'`{command}` は見つかりませんでした（`/help` で一覧）',
                    ephemeral=True)
                return
            embed = self._detail(found)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    def _overview(self):
        lines = ['`/help コマンド名` で1つのコマンドの詳細を表示します。', '']
        for command in self._commands():
            lines.append(f'**/{command.name}** — {command.description}')
            for sub in getattr(command, 'commands', []):
                lines.append(f'　`/{command.name} {sub.name}` — {sub.description}')
        body = '\n'.join(lines)
        if len(body) > 4000:
            body = body[:3999] + '…'
        name = getattr(self.bot.user, 'display_name', None) or 'UBSLEEPY'
        return discord.Embed(
            title=f'{name} ヘルプ', description=body, color=0x2EAFFF)

    def _detail(self, command):
        embed = discord.Embed(
            title=f'/{command.name}',
            description=command.description,
            color=0x2EAFFF)
        subs = getattr(command, 'commands', None)
        if subs:
            for sub in subs:
                embed.add_field(
                    name=self._usage(sub, prefix=f'{command.name} '),
                    value=sub.description or '（説明なし）',
                    inline=False)
            return embed
        for parameter in command.parameters:
            required = '（必須）' if parameter.required else '（任意）'
            embed.add_field(
                name=parameter.name,
                value=f'{parameter.description or "（説明なし）"} {required}',
                inline=False)
        return embed


async def setup(bot):
    await bot.add_cog(Help(bot))
