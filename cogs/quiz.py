# -*- coding: utf-8 -*-
# cogs/quiz.py
"""ポケモンクイズ（/q /quizrate /bmode）と回答の受付。

セッション（出題・判定・開示）は bot_module.quiz_session にある。
"""
import copy

import discord
from discord.ext import commands

import bot_module.config as cfg
from bot_module.command_scope import scoped
import bot_module.func as ub
import bot_module.guild_settings as guild_settings
from bot_module.pokedex import get_pokedex
from bot_module.quiz_session import CRY_MODE_LABELS, QuizSession, QuizState
from bot_module.save import SaveError

# /crydata の入力ゆれ -> 鳴き声クイズの出題条件（モード）
# キーは「今／昔／両方」。他の言い方も受け付ける。
CRY_MODE_ALIASES = {
    "今": "latest", "いま": "latest", "now": "latest",
    "デフォルト": "latest", "でふぉると": "latest", "default": "latest",
    "あたらしい": "latest", "新しい": "latest", "新": "latest", "latest": "latest",
    "昔": "legacy", "むかし": "legacy", "old": "legacy",
    "BW以前": "legacy", "BWいぜん": "legacy", "BW": "legacy", "bw": "legacy",
    "古い": "legacy", "legacy": "legacy",
    "両方": "mix", "りょうほう": "mix", "ミックス": "mix", "みっくす": "mix",
    "mix": "mix",
}
# 出題条件の言葉（/bqdata・/crydata で共有）。この言葉だけを書くとその条件を消す。
FILTER_REMOVE_WORDS = (
    "タイプ", "特性", "出身地", "初登場世代", "進化段階",
    "HP", "こうげき", "ぼうぎょ", "とくこう", "とくぼう", "すばやさ", "合計",
)
STAT_WORDS = ("HP", "こうげき", "ぼうぎょ", "とくこう", "とくぼう", "すばやさ", "合計")


def update_filter(filters: dict, words: list, reset: dict) -> dict:
    """出題条件の言葉を filters に適用する（/bqdata・/crydata で共有）。

    「リセット」で reset の内容へ、「種族値」で種族値の条件を消す。
    条件名だけを書くとその条件を消し、値は make_filter_dict で足す。
    """
    if "リセット" in words:
        filters.clear()
        filters.update(copy.deepcopy(reset))
        words.remove("リセット")
    if "種族値" in words:
        for key in STAT_WORDS:
            filters.pop(key, None)
        words.remove("種族値")
    for word in words:
        if word in FILTER_REMOVE_WORDS:
            filters.pop(word, None)
    words = [word for word in words if word not in FILTER_REMOVE_WORDS]
    filters.update(ub.make_filter_dict(words))
    return filters



class Quiz(commands.Cog):
    """クイズの出題・戦績・連続出題モード。"""

    def __init__(self, bot):
        self.bot = bot
        self.state = QuizState()

    @commands.Cog.listener()
    async def on_ready(self):
        # 起動時と再接続時に図鑑カタログを用意する（pkdbが無ければCSV）
        get_pokedex()

    @discord.app_commands.command(name="q", description="現在の出題設定に基づいてクイズを出題します")
    @scoped
    @discord.app_commands.describe(
        quizname="クイズの種別 未記入で種族値クイズが指定されます"
    )
    @discord.app_commands.choices(
        quizname=[
            discord.app_commands.Choice(name=val, value=val)
            for val in list(cfg.QUIZNAME_DICT.keys())
        ]
    )
    async def q(self, interaction: discord.Interaction, quizname: str = "種族値クイズ"):
        seiseiEmbed = discord.Embed(
            title="**妖精さん おしごとチュウ**",
            color=0xFFFFFF,  # デフォルトカラー
            description=f"{quizname}を生成しています",
        )
        await interaction.response.send_message(embed=seiseiEmbed, delete_after=1)
        await QuizSession(self.bot, cfg.QUIZNAME_DICT[quizname], self.state).post(
            interaction.channel)

    @discord.app_commands.command(name="quizrate", description="クイズの戦績を表示します")
    @scoped
    @discord.app_commands.describe(
        user="表示したいメンバー名",
        quizname="クイズの種別 未記入で種族値クイズが指定されます",
    )
    @discord.app_commands.choices(
        quizname=[
            discord.app_commands.Choice(name=val, value=val)
            for val in list(cfg.QUIZNAME_DICT.keys())
        ]
    )
    async def quizrate(
        self,
        interaction: discord.Interaction,
        user: discord.Member = None,
        quizname: str = "種族値クイズ",
    ):
        if user is not None:
            showId = user.id
            showName = user.name
        else:
            showId = interaction.user.id
            showName = interaction.user.name

        ub.output_log("戦績表示を実行します")
        try:
            w = ub.report(
                showId, f"{cfg.QUIZNAME_DICT[quizname]}正答", 0, showName)
            l = ub.report(
                showId, f"{cfg.QUIZNAME_DICT[quizname]}誤答", 0, showName)
        except SaveError:
            await ub.save_error(interaction)
            return
        await interaction.response.send_message(
            f"""{showName}さんの{quizname}戦績
正答: {w}回 誤答: {l}回
正答率: {int(w/(w+l)*100) if not w+l==0 else 0}%"""
        )

    @discord.app_commands.command(name="bmode", description="クイズの連続出題モードを切り替えます")
    @scoped
    @discord.app_commands.describe(mode="連続出題モードのオンオフ 未記入でトグル切り替え")
    @discord.app_commands.choices(
        mode=[
            discord.app_commands.Choice(name="ON", value="ON"),
            discord.app_commands.Choice(name="OFF", value="OFF"),
        ]
    )
    async def bmode(self, interaction: discord.Interaction, mode: str = None):
        if mode == "ON":
            self.state.bakusoku_mode = True
        elif mode == "OFF":
            self.state.bakusoku_mode = False
        else:
            self.state.bakusoku_mode = not self.state.bakusoku_mode
        ub.output_log("爆速モードが" + str(self.state.bakusoku_mode) + "になりました")
        await interaction.response.send_message(
            f"連続出題が{'ON' if self.state.bakusoku_mode else 'OFF'}になりました"
        )

    # メッセージの送受信を観測したときの処理
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:  # メッセージ送信者がBotだった場合は無視する
            return

        if message.content.startswith("/bqdata"):
            bqFilterWords = message.content.split()[1:]

            if bqFilterWords:
                # 既定の条件（config.json）へ戻す。既定値そのものを書き換えないよう複製する
                update_filter(self.state.bq_filter_dict, bqFilterWords,
                              cfg.DEFAULT_FILTER_DICT)
                response = "種族値クイズの出題条件が変更されました"
                ub.output_log("出題条件が更新されました")

            else:
                response = "現在の種族値クイズの出題条件は以下の通りです"

            filters = self.state.bq_filter_dict

            bqFilteredEmbed = discord.Embed(
                title="種族値クイズの出題条件",
                color=0x9013FE,
                description=f"該当ポケモン数: {len(get_pokedex().filter(filters))}匹",
            )

            for i, key in enumerate(filters.keys()):
                values = "\n".join(filters[key])
                bqFilteredEmbed.add_field(name=key, value=values, inline=False)

            ub.output_log("出題条件を表示します")
            await message.channel.send(response, embed=bqFilteredEmbed)

        # 鳴き声クイズの出題条件（あたらしい / BWまで / ミックス）
        elif message.content.startswith("/crydata"):
            words = message.content.split()[1:]
            response = "現在の鳴き声クイズの出題条件は以下の通りです"

            if "リセット" in words:
                # モードも絞り込みも既定に戻す
                self.state.cry_mode = "latest"
                self.state.cry_filter_dict.clear()
                words.remove("リセット")
                response = "鳴き声クイズの出題条件を既定に戻しました"

            mode = None
            rest = []
            for word in words:
                if word in CRY_MODE_ALIASES:
                    mode = CRY_MODE_ALIASES[word]
                else:
                    rest.append(word)
            if mode is not None:
                self.state.cry_mode = mode
                response = "鳴き声クイズの出題条件が変更されました"
                ub.output_log(f"鳴き声の出題条件が{self.state.cry_mode}になりました")
            if rest:
                update_filter(self.state.cry_filter_dict, rest, {})
                response = "鳴き声クイズの出題条件が変更されました"
                ub.output_log("鳴き声の出題条件が更新されました")

            filters = self.state.cry_filter_dict
            lines = [
                f"現在: **{CRY_MODE_LABELS[self.state.cry_mode]}**",
                "使い方: `/crydata 今|昔|両方`、"
                "`/crydata 地方 カントー`、`/crydata 世代 1`"
                "（リセットで既定）",
            ]
            if filters:
                for key, values in filters.items():
                    lines.append(f"{key}: {'、'.join(values)}")
            else:
                lines.append("絞り込み: なし（全部）")
            cryEmbed = discord.Embed(
                title="鳴き声クイズの出題条件",
                color=0x9013FE,
                description="\n".join(lines),
            )
            await message.channel.send(response, embed=cryEmbed)

        # bot自身へのリプライ(reference)に反応
        elif message.reference is not None:
            # リプライ先メッセージのキャッシュを取得
            message.reference.resolved = await message.channel.fetch_message(
                message.reference.message_id
            )

            # bot自身へのリプライに反応
            if message.reference.resolved.author == self.bot.user:
                embeds = message.reference.resolved.embeds
                embedFooterText = embeds[0].footer.text if embeds else None
                # リプライ先にembedが含まれるかつ未回答のクイズの投稿か
                if (
                    embedFooterText
                    and "No.26 ポケモンクイズ" in embedFooterText
                    and not "(done)" in embedFooterText
                ):
                    await QuizSession(self.bot, embedFooterText.split()[3], self.state).try_response(message)

                else:
                    ub.output_log("botへのリプライは無視されました")

        #チャンネルのidがギルドのクイズチャンネルの場合
        elif (message.guild is not None
              and message.channel.id == guild_settings.setting(
                  message.guild.id, 'QUIZ_CHANNEL_ID')):
            #メッセージの内容がポケモン名であるか判定
            if ub.fetch_pokemon(message.content) is not None:
                #一番新しいクイズの投稿を探し,未回答の場合は
                foundQuiz = False
                async for quizMessage in message.channel.history(limit=10):
                    if quizMessage.embeds:
                        embedFooterText = quizMessage.embeds[0].footer.text or ""
                        if (
                            "No.26 ポケモンクイズ - bq" in embedFooterText
                            and not "(done)" in embedFooterText
                        ):
                            #メッセージをリプライに偽装する quizクラスの内容を修正すべき
                            message.reference = discord.MessageReference(
                                message_id=quizMessage.id,
                                channel_id=quizMessage.channel.id,
                                guild_id=quizMessage.guild.id,
                                #resolved=message
                            )
                            message.reference.resolved = quizMessage
                            await QuizSession(self.bot, embedFooterText.split()[3], self.state).try_response(message)
                            foundQuiz = True
                            break
                if not foundQuiz:
                    ub.output_warning("ポケモン名が投稿されましたがクイズ投稿が見つかりませんでした")



async def setup(bot):
    await bot.add_cog(Quiz(bot))