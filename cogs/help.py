# -*- coding: utf-8 -*-
# cogs/help.py
"""このBotのコマンドヘルプ。

`/help` で全コマンドの一覧、`/help コマンド名` で1つのコマンドの詳細を表示する。
"""
import discord
from discord.ext import commands

import bot_module.config as cfg
from bot_module.command_scope import scoped

# スラッシュコマンドではない、チャンネルへそのまま送るコマンド。
# （名前, 使い方, 説明）
TEXT_COMMANDS = (
    ('bqdata', '/bqdata [条件...]',
     '種族値クイズの出題条件の表示・変更（例: `/bqdata リセット`、`/bqdata タイプ みず`）'),
    ('crydata', '/crydata [デフォルト|BW以前|両方]',
     '鳴き声クイズの出題条件の表示・変更（既定はデフォルト。例: `/crydata BW以前`）'),
)


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
        names = [command.name for command in self._commands()]
        names += [name for name, _usage, _description in TEXT_COMMANDS
                  if name not in names]
        return [
            discord.app_commands.Choice(name=name, value=name)
            for name in sorted(names)
            if current.lower() in name.lower()
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
            text = next((t for t in TEXT_COMMANDS if t[0] == command), None)
            if found is None and text is None:
                await interaction.response.send_message(
                    f'`{command}` は見つかりませんでした（`/help` で一覧）',
                    ephemeral=True)
                return
            embed = self._detail(found) if found is not None else self._text_detail(text)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    def _overview(self):
        lines = [
            '`/help コマンド名` で1つのコマンドの詳細を表示します。',
            'お問い合わせ: https://github.com/rurutheGeek/UBSLEEPY-next/issues',
            '',
        ]
        for command in self._commands():
            lines.append(f'**/{command.name}** — {command.description}')
            for sub in getattr(command, 'commands', []):
                lines.append(f'　`/{command.name} {sub.name}` — {sub.description}')
        lines.append('')
        lines.append('**テキストコマンド**（チャンネルにそのまま送信）')
        for name, usage, description in TEXT_COMMANDS:
            lines.append(f'`{usage}` — {description}')
        body = '\n'.join(lines)
        if len(body) > 4000:
            body = body[:3999] + '…'
        name = getattr(self.bot.user, 'display_name', None) or 'UBSLEEPY'
        return discord.Embed(
            title=f'{name} ヘルプ', description=body, color=0x2EAFFF)

    @staticmethod
    def _text_detail(text):
        name, usage, description = text
        embed = discord.Embed(
            title=usage, description=description, color=0x2EAFFF)
        embed.set_footer(text='チャンネルにそのまま送信してください')
        return embed

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
