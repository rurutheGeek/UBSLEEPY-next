# -*- coding: utf-8 -*-
# cogs/quiz.py
"""ポケモンクイズ（/q /quizrecord /bmode）と回答の受付。

セッション（出題・判定・開示）は bot_module.quiz_session にある。
"""
import asyncio
import copy
import os

import discord
from discord.ext import commands, tasks

import bot_module.config as cfg
from bot_module.logging_setup import logger
from bot_module.command_scope import scoped
import bot_module.func as ub
import bot_module.guild_settings as guild_settings
from bot_module import dex_text
from bot_module import intro
from bot_module.pokedex import get_pokedex
from bot_module.quiz_session import (
    CRY_DIRECTORY, CRY_MODE_LABELS, CRY_REPLAY_BUTTON_ID, QuizSession, QuizState,
    cry_candidates, cry_from_message, parse_number, play_cry)
from bot_module import save
from bot_module.save import SaveError

# /q の mode: 図鑑番号クイズの出し方（True は番号からポケモンを当てる）
NUMBER_MODES = {"ポケモン→番号": False, "番号→ポケモン": True}

# /quizrecord で並べる苦手な問題の数（記録が少なければ、あるだけ）
WEAK_LIMIT = 10


def record_embed(user_name, quizname, correct, wrong, weak) -> discord.Embed:
    """/quizrecord の表示。戦績（セーブデータ）と、苦手な問題（判定ログ）。

    weak は save.weak_questions の返り値。None（集計できない）なら戦績だけ出す。
    ギブアップは回数を分けて見せず、苦手な問題の「誤答」に含めて数える。
    """
    total = correct + wrong
    lines = [
        f"正答: {correct}回 誤答: {wrong}回",
        f"正答率: {int(correct / total * 100) if total else 0}%",
    ]
    embed = discord.Embed(title=f"{user_name}さんの{quizname}戦績", color=0x9013FE)
    if weak is not None:
        lines.append("")
        lines.append("**苦手な問題**")
        if not weak:
            lines.append("まだ 間違えた問題の記録が ないロ")
        for number, (question, answer, ok, ng, gave, usual) in enumerate(weak, 1):
            name = answer or question
            if answer and answer != question:
                name = f"{answer}（{question}）"
            line = f"{number}. **{name}** — 誤答{ng + gave}・正答{ok}"
            if usual:
                line += f"　よく書いた答え: {usual}"
            lines.append(line)
        embed.set_footer(text="苦手な問題は 2026年10月の更新より あとの記録から")
    embed.description = "\n".join(lines)[:4000]
    return embed


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

# /introdata でシークレットの曲（未使用曲・古いバージョン）を出題に入れる・外す言葉
SECRET_WORDS = {
    "シークレット": True, "しーくれっと": True, "シークレットあり": True, "secret": True,
    "シークレットなし": False, "しーくれっとなし": False, "通常": False,
}


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
            state.intro_secret = False
        elif word in SECRET_WORDS:
            state.intro_secret = SECRET_WORDS[word]
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
    count = len(intro.filter_tracks(
        state.intro_works, state.intro_categories, state.intro_secret))
    hidden = len(intro.filter_tracks(
        state.intro_works, state.intro_categories, True)) - count
    lines = [
        f"該当曲数: {count}曲",
        f"作品: {'、'.join(state.intro_works) or 'なし（全部）'}",
        f"区分: {'、'.join(state.intro_categories) or 'なし（全部）'}",
        "シークレット: " + (
            "あり（未使用曲・古いバージョンも出す）" if state.intro_secret
            else f"なし（`/introdata シークレット` で {hidden}曲 追加）"),
        "使い方: `/introdata 戦闘|フィールド|その他`、`/introdata 作品名`"
        "（作品名は略称や一部でも可。リセットで既定）",
        "回答: `略称＋戦う相手`（例: `BWシロナ`）。相手が1作品だけなら略称なしでも可",
    ]
    names = intro.works()
    if names:
        listing = "\n".join(
            f"{name}（{len(intro.filter_tracks([name], secret=state.intro_secret))}曲）"
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

    async def cog_load(self):
        self.refresh_intro_lists.start()

    async def cog_unload(self):
        self.refresh_intro_lists.cancel()

    @tasks.loop(seconds=60)
    async def refresh_intro_lists(self):
        """イントロクイズの対応リストをpkdbから読み直す（直しを配備なしで反映する）。"""
        if not os.environ.get("PKDB_PASSWORD"):
            return
        try:
            lists = await asyncio.to_thread(intro.fetch_database_lists)
        except Exception as error:
            logger.error(f"pkdbからイントロクイズの対応リストを読めませんでした\n{error}")
            return
        if intro.use_database_lists(lists):
            logger.info("イントロクイズの対応リストを読み直しました")

    @commands.Cog.listener()
    async def on_ready(self):
        # 起動時と再接続時に図鑑カタログを用意する（pkdbが無ければCSV）
        get_pokedex()
        # 図鑑説明クイズの説明文も先に読んでおく（最初の出題を待たせない）
        await asyncio.to_thread(dex_text.get_catalog)

    @discord.app_commands.command(
        name="q", description="現在の出題設定に基づいてクイズを出題します")
    @scoped
    @discord.app_commands.describe(
        quizname="クイズの種別 未記入で種族値クイズが指定されます",
        mode="図鑑番号クイズの出し方 未記入でポケモンから番号を当てます",
    )
    @discord.app_commands.choices(
        quizname=[
            discord.app_commands.Choice(name=val, value=val)
            for val in list(cfg.QUIZNAME_DICT.keys())
        ],
        mode=[
            discord.app_commands.Choice(name=val, value=val)
            for val in NUMBER_MODES
        ],
    )
    async def q(self, interaction: discord.Interaction,
                quizname: str = "種族値クイズ", mode: str = None):
        seiseiEmbed = discord.Embed(
            title="**妖精さん おしごとチュウ**",
            color=0xFFFFFF,  # デフォルトカラー
            description=f"{quizname}を生成しています",
        )
        await interaction.response.send_message(embed=seiseiEmbed, delete_after=1)
        # ボイスチャンネル付属のテキストチャットで出したときは、そこで鳴き声を流す
        session = QuizSession(self.bot, cfg.QUIZNAME_DICT[quizname], self.state)
        session.fromNumber = NUMBER_MODES.get(mode, False)
        await session.post(
            interaction.channel, voiceChannel=voice_channel_for(interaction.channel))

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

    @discord.app_commands.command(
        name="quizrecord", description="クイズの戦績と苦手な問題を表示します")
    @scoped
    @discord.app_commands.describe(
        user="表示したいメンバー名 未記入で自分",
        quizname="クイズの種別 未記入で種族値クイズが指定されます",
    )
    @discord.app_commands.choices(
        quizname=[
            discord.app_commands.Choice(name=val, value=val)
            for val in list(cfg.QUIZNAME_DICT.keys())
        ]
    )
    async def quizrecord(
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
        quiz = cfg.QUIZNAME_DICT[quizname]

        ub.output_log("戦績表示を実行します")
        try:
            w = ub.report(showId, f"{quiz}正答", 0, showName)
            l = ub.report(showId, f"{quiz}誤答", 0, showName)
        except SaveError:
            await ub.save_error(interaction)
            return
        # 苦手は判定ログから。読めないとき・DBが無いときは戦績だけ出す
        try:
            weak = await asyncio.to_thread(
                save.weak_questions, showId, quiz, WEAK_LIMIT)
        except SaveError:
            weak = None
        await interaction.response.send_message(
            embed=record_embed(showName, quizname, w, l, weak))

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
            # 返信先はDiscordが付けてくる。無いときだけ取りに行く
            if not isinstance(message.reference.resolved, discord.Message):
                if message.reference.message_id is None:
                    return
                try:
                    message.reference.resolved = await message.channel.fetch_message(
                        message.reference.message_id
                    )
                except discord.HTTPException:
                    return  # 返信先が消えている・読めない

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
            await self._answer_in_channel(message, ("bq", "cryq", "introq", "dexq", "noq"))

        # ボイスチャンネル付属のテキストチャット（鳴き声クイズへの回答）
        elif (message.guild is not None
              and voice_channel_for(message.channel) is not None):
            await self._answer_in_channel(message, ("cryq", "introq", "bq", "dexq", "noq"))

    async def _answer_in_channel(self, message, quiz_names):
        """チャンネルに書かれたポケモン名・曲名を、最新の未回答クイズへの回答にする。

        図鑑にも曲リストにも無い言葉（雑談など）は無視する（fetch_pokemon は
        見つからないと空のリストを返すので、真偽で判定する）。
        イントロクイズへは曲名だけ、図鑑番号を当てるクイズへは数字だけ、
        ほかのクイズへはポケモン名だけを回答にする。
        """
        is_pokemon = bool(ub.fetch_pokemon(message.content))
        is_track = "introq" in quiz_names and bool(intro.find_tracks(message.content))
        is_number = parse_number(message.content) is not None
        quiz_names = [
            name for name in quiz_names
            if (is_track if name == "introq"
                else (is_number or is_pokemon) if name == "noq" else is_pokemon)]
        if not quiz_names:
            return
        async for quizMessage in message.channel.history(limit=10):
            # ほかのBot（テスト用など）が出したクイズには反応しない
            if quizMessage.author != self.bot.user:
                continue
            if not quizMessage.embeds:
                continue
            footer = quizMessage.embeds[0].footer.text or ""
            if "(done)" in footer:
                continue
            for name in quiz_names:
                if f"No.26 ポケモンクイズ - {name}" not in footer:
                    continue
                if name == "noq":
                    # 番号から出した問題は名前、ポケモンから出した問題は数字だけ拾う
                    from_number = (
                        quizMessage.embeds[0].description or "").startswith("No.")
                    if not (is_pokemon if from_number else is_number):
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

    async def _answer_acq(self, interaction: discord.Interaction):
        """物理特殊クイズのボタンを回答にする。"""
        embeds = getattr(interaction.message, "embeds", None)
        footer = (embeds[0].footer.text or "") if embeds else ""
        if "No.26 ポケモンクイズ - acq" in footer and "(done)" not in footer:
            await QuizSession(self.bot, "acq", self.state).try_response(interaction)
        if not interaction.response.is_done():
            # 回答済み・ほかの人が先に開示したとき。「操作に失敗」にしない
            await interaction.response.defer()

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        """クイズのボタン（物理特殊クイズの回答、「もう一度再生」）を処理する。"""
        data = interaction.data or {}
        if data.get("component_type") != 2:
            return
        if (data.get("custom_id") or "").startswith("acq_"):
            await self._answer_acq(interaction)
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