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
from bot_module import intro
from bot_module.pokedex import get_pokedex
from bot_module.quiz_session import (
    CRY_DIRECTORY, CRY_MODE_LABELS, CRY_REPLAY_BUTTON_ID, QuizSession, QuizState,
    cry_candidates, cry_from_message, play_cry)
from bot_module.save import SaveError


def voice_channel_for(channel):
    """ボイスチャンネル付属のテキストチャットなら、そのボイスチャンネルを返す。"""
    if isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
        return channel
    return None

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

def update_intro_filter(state, words: list) -> list:
    """イントロクイズの出題条件（作品・区分）の言葉を state に適用する。

    「リセット」で全部、「作品」「区分」だけを書くとその条件を消す。
    区分の言葉（戦闘・フィールド・その他）は区分に、それ以外は作品名として探す
    （部分一致）。1回の入力に書いたぶんで置き換える。見つからなかった言葉を返す。
    """
    categories, work_names, unknown = [], [], []
    for word in words:
        if word == "リセット":
            state.intro_works = []
            state.intro_categories = []
        elif word == "作品":
            state.intro_works = []
        elif word == "区分":
            state.intro_categories = []
        elif word in intro.CATEGORY_ALIASES or word.lower() in intro.CATEGORY_ALIASES:
            category = intro.CATEGORY_ALIASES.get(
                word, intro.CATEGORY_ALIASES.get(word.lower()))
            if category not in categories:
                categories.append(category)
        elif matched := intro.match_works(word):
            work_names += [name for name in matched if name not in work_names]
        else:
            unknown.append(word)
    if categories:
        state.intro_categories = categories
    if work_names:
        state.intro_works = work_names
    return unknown


def intro_filter_embed(state) -> discord.Embed:
    """イントロクイズの出題条件と、選べる作品の一覧。"""
    count = len(intro.filter_tracks(state.intro_works, state.intro_categories))
    lines = [
        f"該当曲数: {count}曲",
        f"作品: {'、'.join(state.intro_works) or 'なし（全部）'}",
        f"区分: {'、'.join(state.intro_categories) or 'なし（全部）'}",
        "使い方: `/introdata 戦闘|フィールド|その他`、`/introdata 作品名`"
        "（作品名は略称や一部でも可。リセットで既定）",
        "回答: `略称＋戦う相手`（例: `BWシロナ`）。相手が1作品だけなら略称なしでも可",
    ]
    names = intro.works()
    if names:
        listing = "\n".join(
            f"{name}（{len(intro.filter_tracks([name]))}曲）"
            + (f" 略称: {'／'.join(intro.work_abbreviations(name))}"
               if intro.work_abbreviations(name) else "")
            for name in names)
        if len(listing) > 1000:
            listing = listing[:1000].rsplit("\n", 1)[0] + "\n…"
    else:
        listing = "曲がまだ用意されていません（tools/build_intro_clips.py）"
    embed = discord.Embed(
        title="イントロクイズの出題条件", color=0x9013FE,
        description="\n".join(lines))
    embed.add_field(name="選べる作品", value=listing, inline=False)
    return embed


class Quiz(commands.Cog):
    """クイズの出題・戦績・連続出題モード。"""

    def __init__(self, bot):
        self.bot = bot
        self.state = QuizState()
        self._replay_counts = {}  # 鳴き声の再生ボタン: メッセージID -> 回数

    @commands.Cog.listener()
    async def on_ready(self):
        # 起動時と再接続時に図鑑カタログを用意する（pkdbが無ければCSV）
        get_pokedex()

    @discord.app_commands.command(
        name="q", description="クイズを出題します（鳴き声クイズはボイスでも再生）")
    @scoped
    @discord.app_commands.describe(
        quizname="クイズの種別 未記入で種族値クイズが指定されます",
        work="イントロクイズ: 出題する作品（一部でも可。以後の出題にも残ります）",
        category="イントロクイズ: 戦闘曲かフィールド曲か（以後の出題にも残ります）",
    )
    @discord.app_commands.choices(
        quizname=[
            discord.app_commands.Choice(name=val, value=val)
            for val in list(cfg.QUIZNAME_DICT.keys())
        ],
        category=[
            discord.app_commands.Choice(name=val, value=val)
            for val in intro.CATEGORIES
        ],
    )
    async def q(self, interaction: discord.Interaction, quizname: str = "種族値クイズ",
                work: str = None, category: str = None):
        if cfg.QUIZNAME_DICT[quizname] == "introq" and (work or category):
            unknown = update_intro_filter(
                self.state, [word for word in (work, category) if word])
            if unknown:
                await interaction.response.send_message(
                    f"作品が見つかりません: {'、'.join(unknown)}",
                    embed=intro_filter_embed(self.state), ephemeral=True)
                return
        seiseiEmbed = discord.Embed(
            title="**妖精さん おしごとチュウ**",
            color=0xFFFFFF,  # デフォルトカラー
            description=f"{quizname}を生成しています",
        )
        await interaction.response.send_message(embed=seiseiEmbed, delete_after=1)
        # ボイスチャンネル付属のテキストチャットで出したときは、そこで鳴き声を流す
        await QuizSession(self.bot, cfg.QUIZNAME_DICT[quizname], self.state).post(
            interaction.channel, voiceChannel=voice_channel_for(interaction.channel))

    @q.autocomplete("work")
    async def _work_autocomplete(self, interaction: discord.Interaction, current: str):
        key = intro.normalize_title(current)
        return [
            discord.app_commands.Choice(name=name[:100], value=name[:100])
            for name in intro.works()
            if key in intro.normalize_title(name)
        ][:25]

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        """ボットが入っているボイスチャンネルが空になったら退出する。"""
        voice_client = member.guild.voice_client
        if voice_client is None or voice_client.channel is None:
            return
        if any(not other.bot for other in voice_client.channel.members):
            return
        name = voice_client.channel.name
        await voice_client.disconnect()
        ub.output_log(f"ボイスチャンネルから退出しました: {name}")

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
            count = len(cry_candidates(self.state))
            lines = [
                f"現在: **{CRY_MODE_LABELS[self.state.cry_mode]}**",
                f"該当: {count}匹（鳴き声のあるもの）",
                "使い方: `/crydata 今|昔|両方`、"
                "`/crydata 地方 カントー`、`/crydata 世代 1`"
                "（リセットで既定）",
            ]
            if filters:
                for key, values in filters.items():
                    lines.append(f"{key}: {'、'.join(values)}")
            else:
                lines.append("絞り込み: なし（全部）")
            if count == 0:
                lines.append(
                    "※この組み合わせに鳴き声がありません"
                    "（モード「昔」はBWまで。`今` か `両方` にすると増えます）")
            cryEmbed = discord.Embed(
                title="鳴き声クイズの出題条件",
                color=0x9013FE,
                description="\n".join(lines),
            )
            await message.channel.send(response, embed=cryEmbed)

        # イントロクイズの出題条件（作品・戦闘/フィールド）
        elif message.content.startswith("/introdata"):
            words = message.content.split()[1:]
            response = "現在のイントロクイズの出題条件は以下の通りです"
            if words:
                unknown = update_intro_filter(self.state, words)
                response = "イントロクイズの出題条件が変更されました"
                if unknown:
                    response = f"作品が見つかりません: {'、'.join(unknown)}"
                ub.output_log("イントロの出題条件が更新されました")
            await message.channel.send(
                response, embed=intro_filter_embed(self.state))

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
                    session = QuizSession(self.bot, embedFooterText.split()[3], self.state)
                    # 回答後も同じVCで鳴き声を流せるように、回答元のVCを引き継ぐ
                    session.voice_channel = voice_channel_for(message.channel)
                    await session.try_response(message)

                else:
                    ub.output_log("botへのリプライは無視されました")

        #チャンネルのidがギルドのクイズチャンネルの場合（名前当てクイズへの回答）
        elif (message.guild is not None
              and message.channel.id == guild_settings.setting(
                  message.guild.id, 'QUIZ_CHANNEL_ID')):
            await self._answer_in_channel(message, ("bq", "cryq", "introq"))

        # ボイスチャンネル付属のテキストチャット（鳴き声クイズへの回答）
        elif (message.guild is not None
              and voice_channel_for(message.channel) is not None):
            await self._answer_in_channel(message, ("cryq", "introq", "bq"))

    async def _answer_in_channel(self, message, quiz_names):
        """チャンネルに書かれたポケモン名・曲名を、最新の未回答クイズへの回答にする。

        図鑑にも曲リストにも無い言葉（雑談など）は無視する（fetch_pokemon は
        見つからないと空のリストを返すので、真偽で判定する）。
        イントロクイズへは曲名だけ、ほかのクイズへはポケモン名だけを回答にする。
        """
        is_pokemon = bool(ub.fetch_pokemon(message.content))
        is_track = "introq" in quiz_names and bool(intro.find_tracks(message.content))
        quiz_names = [
            name for name in quiz_names
            if (is_track if name == "introq" else is_pokemon)]
        if not quiz_names:
            return
        async for quizMessage in message.channel.history(limit=10):
            if not quizMessage.embeds:
                continue
            footer = quizMessage.embeds[0].footer.text or ""
            if "(done)" in footer:
                continue
            for name in quiz_names:
                if f"No.26 ポケモンクイズ - {name}" not in footer:
                    continue
                # メッセージをリプライに偽装する
                message.reference = discord.MessageReference(
                    message_id=quizMessage.id,
                    channel_id=quizMessage.channel.id,
                    guild_id=quizMessage.guild.id,
                )
                message.reference.resolved = quizMessage
                session = QuizSession(self.bot, name, self.state)
                # 回答後も同じVCで鳴き声を流せるように、回答元のVCを引き継ぐ
                session.voice_channel = voice_channel_for(message.channel)
                await session.try_response(message)
                return
        if is_pokemon:
            ub.output_warning("ポケモン名が投稿されましたがクイズ投稿が見つかりませんでした")

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        """鳴き声・イントロクイズの「もう一度再生」ボタンを処理する。"""
        data = interaction.data or {}
        if data.get("component_type") != 2:
            return
        if data.get("custom_id") != CRY_REPLAY_BUTTON_ID:
            return
        entry = cry_from_message(interaction.message)
        track = None if entry else intro.track_from_message(interaction.message)
        voice_client = getattr(interaction.guild, "voice_client", None)
        if ((entry is None and track is None)
                or voice_client is None or voice_client.channel is None):
            await interaction.response.send_message(
                "ボイスチャンネルにいないときは、添付の音声を聞いてください",
                ephemeral=True)
            return
        if track is not None:
            path = track.path
        else:
            name, kind = entry
            found = ub.fetch_pokemon(name)
            if not found:
                return
            path = CRY_DIRECTORY / kind / f"{found[0].ndex_number}.ogg"
        if play_cry(voice_client, path):
            # 連打しても同じ文が積み上がらないよう、回数を1行で出す
            message_id = getattr(interaction.message, "id", 0)
            count = self._replay_counts.get(message_id, 0) + 1
            self._replay_counts[message_id] = count
            for old in list(self._replay_counts)[:-50]:
                self._replay_counts.pop(old, None)
            await interaction.response.send_message(
                f"再生{count}回目", ephemeral=True)
        else:
            await interaction.response.send_message(
                "再生できませんでした", ephemeral=True)



async def setup(bot):
    await bot.add_cog(Quiz(bot))