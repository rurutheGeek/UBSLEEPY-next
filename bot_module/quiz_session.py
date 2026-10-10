# -*- coding: utf-8 -*-
# quiz_session.py
"""ポケモンクイズのセッション（出題・回答受付・判定・開示）。

cogs/quiz.py の Cog が作り、Discordへの送受信はこのクラスが行う。
実行時状態は QuizState にまとめ、Cogが持つものを渡す。
"""
import asyncio
import copy
import hashlib
from pathlib import Path
import random
import re
import secrets
import unicodedata

import discord
import jaconv

import bot_module.config as cfg
from bot_module import dex_text
from bot_module import func as ub
from bot_module import intro
from bot_module.pokedex import get_pokedex
import bot_module.save as save
from bot_module.save import SaveError

# 判定ログ（quiz_log）の judge に入れる、回答ではない操作
LOG_GIVEUP = "ギブアップ"
LOG_HINT = "ヒント"
# 判定ログに残す入力の原文の長さ（クイズへの返信なら何でも届くので、長文は切る）
LOG_RAW_LENGTH = 200


# 図鑑番号クイズ: 正解からこの数まで離れた番号（のポケモン）は「おしい」
NUMBER_NEAR = 3
NUMBER_RE = re.compile(r"^(?:no\.?|№)?\s*(\d{1,4})\s*番?$", re.IGNORECASE)


def parse_number(text) -> int | None:
    """「510」「No.510」「５１０番」のような回答を図鑑番号に。数字でなければ None。"""
    match = NUMBER_RE.match(unicodedata.normalize("NFKC", str(text or "")).strip())
    return int(match.group(1)) if match else None


def dex_answers(entries) -> dict:
    """図鑑説明クイズの正解。(種族, フォーム) -> (Pokemon, 開示で見せる名前)。

    説明文の載っているフォームが正解。基本の姿が入っている種族は、種族名で見せる。
    """
    pokedex = get_pokedex()
    answers = {}
    for entry in entries:
        base = pokedex.base(entry.species)
        records = [record for record in pokedex.variants(entry.species)
                   if record.form_id in entry.forms] or [base]
        for record in records:
            shown = base.name if "00" in entry.forms else record.name
            answers[(record.species, record.form_id)] = (record, shown)
    return answers


def pokemon_id(pokemon) -> str:
    """判定ログ用のポケモンのID（図鑑番号-フォーム）。"""
    return f"{pokemon.ndex_number}-{pokemon.form_id}"

# 鳴き声クイズの音源。tools/fetch_cries.py が置き、クイズはローカル参照だけする。
# latest=あたらしい鳴き声（全種）、legacy=BWまでの古い鳴き声（1〜649）。
CRY_DIRECTORY = Path("resource/cry")
CRY_KINDS = ("latest", "legacy")
# 開示で「どちらの鳴き声だったか」に使う呼び名
CRY_LABELS = {"latest": "今", "legacy": "昔"}
# 出題条件（既定は今の鳴き声。設定は /crydata で変更）
CRY_MODE_LABELS = {
    "latest": "今",
    "legacy": "昔",
    "mix": "両方",
}
# 添付ファイル名は cry-<nonce>-<ハッシュ>.ogg。
# nonceは出題ごとのランダム値（ファイル名に埋め込むので時刻にも状態にも依存しない）。
# ハッシュには答えの名前と鳴き声の種類を混ぜるので、種類はファイル名からは読めない。
# 同じポケモンでも毎回ファイル名が変わり、答えは投稿から逆算できる（状態を持たない）。
CRY_HASH_LENGTH = 12
CRY_NONCE_BYTES = 3
CRY_FILENAME_RE = re.compile(r"^cry-([0-9a-f]+)-([0-9a-f]+)\.ogg$")
# 鳴き声クイズ: 投稿につける「もう一度再生」ボタン
CRY_REPLAY_BUTTON_ID = "cryReplayButton"
CRY_REPLAY_LABEL = "もう一度再生"


def cry_hash(name: str, kind: str, nonce: str) -> str:
    """種類・nonce・答えの名前から、添付ファイル名に使う短いハッシュを作る。"""
    digest = hashlib.sha1(f"{kind}:{nonce}:{name}".encode("utf-8")).hexdigest()
    return digest[:CRY_HASH_LENGTH]


def cry_filename(name: str, kind: str, nonce: str) -> str:
    return f"cry-{nonce}-{cry_hash(name, kind, nonce)}.ogg"


def _audio_source(path):
    """ボイス再生用の音源。テストから差し替えられるよう関数にしてある。"""
    return discord.FFmpegPCMAudio(str(path))


def play_cry(voice_client, path) -> bool:
    """接続済みのボイスクライアントで鳴き声を流す。"""
    try:
        # 前の音が鳴っている間は play が失敗するので、止めてから流す
        if voice_client.is_playing():
            voice_client.stop()
        voice_client.play(_audio_source(path))
        return True
    except (discord.ClientException, discord.HTTPException, OSError) as error:
        ub.output_error(f"ボイスで鳴き声を流せませんでした: {error}")
        return False


def replay_button_view() -> discord.ui.View:
    """鳴き声クイズの投稿に付ける「もう一度再生」ボタン。"""
    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(
        label=CRY_REPLAY_LABEL,
        style=discord.ButtonStyle.secondary,
        custom_id=CRY_REPLAY_BUTTON_ID,
    ))
    return view


def cry_from_message(message) -> tuple | None:
    """投稿の添付ファイル名から (ポケモン名, 鳴き声の種類) を逆算する。

    名前と種類の組み合わせをハッシュして一致を探す。見つからなければNone
    （添付が消された・形式が違うとき）。
    """
    for attachment in getattr(message, "attachments", None) or []:
        match = CRY_FILENAME_RE.match(getattr(attachment, "filename", "") or "")
        if match is None:
            continue
        nonce, digest = match.group(1), match.group(2)
        for pokemon in get_pokedex().records:
            if pokemon.form_id != "00":
                continue
            for kind in CRY_KINDS:
                if cry_hash(pokemon.name, kind, nonce) == digest:
                    return pokemon.name, kind
    return None


class QuizState:
    """クイズの実行時状態（Botの再起動でリセットされる）。"""

    def __init__(self):
        self.bq_filter_dict = copy.deepcopy(cfg.DEFAULT_FILTER_DICT)  # 現在の出題条件
        self.bakusoku_mode = True  # 連続出題モード
        self.disclosing = set()  # 回答開示処理中のクイズ投稿（メッセージID）
        self.cry_mode = "latest"  # 鳴き声クイズの出題条件: latest / legacy / mix
        self.cry_filter_dict = {}  # 鳴き声クイズの絞り込み（地方・世代など。空は全部）
        self.intro_works = []  # イントロクイズの絞り込み: 作品（空は全部）
        self.intro_categories = []  # イントロクイズの絞り込み: 区分（空は全部）
        self.intro_secret = False  # イントロクイズ: シークレットの曲（初期バージョンなど）も出す


def cry_candidates(state) -> list:
    """出題条件（モードと絞り込み）に合う (ポケモン, 鳴き声の種類) の一覧。

    モード「昔」はBWまでの鳴き声しか無いので、ガラル・パルデアなど
    新しい地方を絞り込むと0件になる（件数表示と案内に使う）。
    """
    allowed = CRY_KINDS if state.cry_mode == "mix" else (state.cry_mode,)
    pokedex = get_pokedex()
    records = (pokedex.filter(state.cry_filter_dict)
               if state.cry_filter_dict else pokedex.records)
    # 1匹ずつ存在確認せず、フォルダの一覧を1回ずつ読む
    available = {kind: {path.stem for path in (CRY_DIRECTORY / kind).glob("*.ogg")}
                 for kind in allowed}
    candidates = []
    for pokemon in records:
        if pokemon.form_id != "00":
            continue
        kinds = [kind for kind in allowed
                 if str(pokemon.ndex_number) in available[kind]]
        if kinds:
            candidates.append((pokemon, kinds))
    return candidates


class QuizSession:
    def __init__(self, bot, quizName, state=None):
        self.bot = bot
        self.quizName = quizName
        self.state = state or QuizState()
        self.voice_channel = None  # 出題時に鳴き声を流すボイスチャンネル
        # 図鑑番号クイズの出し方: 番号からポケモンを当てる（既定はポケモンから番号）
        self.fromNumber = False

    @property
    def variant(self):
        """判定の分かれ目に使う種別。図鑑番号クイズ（noq）は出し方で2つに分ける。"""
        if self.quizName != "noq":
            return self.quizName
        return "ntopq" if self.fromNumber else "ptonq"

    async def post(self, sendChannel, voiceChannel=None):
        ub.output_log(f"{self.quizName}: クイズを出題します")
        self.voice_channel = voiceChannel

        quizContent = None
        quizFile = None
        quizEmbed = discord.Embed(title="", color=0x9013FE, description="")
        quizEmbed.set_footer(text=f"No.26 ポケモンクイズ - {self.quizName}")
        quizView = None
        voicePath = None  # ボイスチャンネルで流す音源（鳴き声・イントロ）
        qDatas = track = cryKind = None  # 出題のもと（出題ログに残す）
        # 必要な要素をクイズごとに編集

        if self.quizName == "bq":
            qDatas = get_pokedex().random(self.state.bq_filter_dict)
            if qDatas is not None:
                quizEmbed.title = "種族値クイズ"
                quizEmbed.description = "こたえ: ???"  # 正答後: こたえ: [ポケモン名](複数いる場合),[ポケモン名]
                quizFile = discord.File(
                    ub.generate_graph(list(qDatas.stats)), filename="image.png"
                )
                quizEmbed.set_image(
                    url="attachment://image.png"
                )  # 種族値クイズ図形の添付
                quizEmbed.set_thumbnail(
                    url=self.__imageLink()
                )  # 正解までDecamark(?)を表示
                quizContent = ub.bss_to_text(qDatas)

            else:
                # 条件に合うポケモンがいない場合は、空のクイズを投稿せずに終わる
                await sendChannel.send("現在の出題条件に合うポケモンがいません")
                return

        elif self.quizName == "acq":
            qDatas = get_pokedex().random({"進化段階": ["最終進化", "進化しない"]})
            if qDatas is None:
                await sendChannel.send("現在の出題条件に合うポケモンがいません")
                return
            quizEmbed.title = "ACクイズ"
            quizEmbed.description = (
                f"{qDatas.name} はこうげきととくこうどちらが高い?"
            )
            quizEmbed.set_thumbnail(url=self.__imageLink(qDatas.name))

            quizView = discord.ui.View()
            quizView.add_item(
                discord.ui.Button(
                    label="こうげき",
                    style=discord.ButtonStyle.primary,
                    custom_id="acq_こうげき",
                )
            )
            quizView.add_item(
                discord.ui.Button(
                    label="とくこう",
                    style=discord.ButtonStyle.primary,
                    custom_id="acq_とくこう",
                )
            )
            quizView.add_item(
                discord.ui.Button(
                    label="同値",
                    style=discord.ButtonStyle.secondary,
                    custom_id="acq_同値",
                )
            )

        elif self.quizName == "etojq":
            qDatas = self.__random_with({"進化段階": ["最終進化", "進化しない"]}, "eng")
            if qDatas is None:
                await sendChannel.send("現在の出題条件に合うポケモンがいません")
                return
            quizEmbed.title = "英和翻訳クイズ"
            quizEmbed.description = f"{qDatas.eng} -> [?]"

        elif self.quizName == "jtoeq":
            qDatas = self.__random_with({"進化段階": ["最終進化", "進化しない"]}, "eng")
            if qDatas is None:
                await sendChannel.send("現在の出題条件に合うポケモンがいません")
                return
            quizEmbed.title = "和英翻訳クイズ"
            quizEmbed.description = f"{qDatas.name} -> [?]"
            quizEmbed.set_thumbnail(url=self.__imageLink(qDatas.name))

        elif self.quizName == "ctojq":
            qDatas = self.__random_with({"進化段階": ["最終進化", "進化しない"]}, "cht")
            if qDatas is None:
                await sendChannel.send("現在の出題条件に合うポケモンがいません")
                return
            quizEmbed.title = "中日翻訳クイズ"
            quizEmbed.description = f"{qDatas.cht} -> [?]"

        elif self.quizName == "cryq":
            picked = self.__random_cry()
            if picked is None:
                mode_label = CRY_MODE_LABELS.get(
                    self.state.cry_mode, self.state.cry_mode)
                conditions = "、".join(
                    f"{key}: {'/'.join(values)}"
                    for key, values in self.state.cry_filter_dict.items())
                detail = f"モード: {mode_label}"
                if conditions:
                    detail += f"、{conditions}"
                hint = ("モード「昔」はBWまでの鳴き声です。"
                        if self.state.cry_mode == "legacy" else "")
                await sendChannel.send(
                    f"出題条件に合う鳴き声がありません（{detail}）\n"
                    f"{hint}`/crydata` で条件を確認、リセットで既定に戻せます")
                return
            qDatas, cryKind = picked
            quizEmbed.title = "鳴き声クイズ"
            if voiceChannel is not None:
                quizEmbed.description = (
                    "鳴き声をボイスチャンネルで流します。聞いてポケモン名を答えよう")
                quizView = replay_button_view()
            else:
                quizEmbed.description = "添付の鳴き声を聞いて ポケモン名を答えよう"
            quizEmbed.set_thumbnail(url=self.__imageLink())  # 正解までDecamark
            voicePath = CRY_DIRECTORY / cryKind / f"{qDatas.ndex_number}.ogg"
            cryNonce = secrets.token_hex(CRY_NONCE_BYTES)
            quizFile = discord.File(
                str(voicePath), filename=cry_filename(qDatas.name, cryKind, cryNonce))

        elif self.quizName == "dexq":
            catalog = await asyncio.to_thread(dex_text.get_catalog)
            entry = catalog.random()
            if entry is None:
                await sendChannel.send("図鑑説明を 読み込めて いないロ")
                return
            # 伏せ字にした文が同じになる種族は、みな正解。記録は判定と同じ先頭の正解で残す
            qDatas = next(iter(
                dex_answers(catalog.find(entry.question)).values()))[0]
            quizEmbed.title = "図鑑説明クイズ"
            # 答えは問題文から引き直すので、説明のほかは書かない
            quizEmbed.description = entry.question
            quizEmbed.set_thumbnail(url=self.__imageLink())  # 正解までDecamark

        elif self.quizName == "noq":
            candidates = [p for p in get_pokedex().records if p.form_id == "00"]
            if not candidates:
                await sendChannel.send("現在の出題条件に合うポケモンがいません")
                return
            qDatas = random.choice(candidates)
            quizEmbed.title = "図鑑番号クイズ"
            if self.variant == "ntopq":
                quizEmbed.description = f"No.{qDatas.species} -> [?]"
                quizEmbed.set_thumbnail(url=self.__imageLink())  # 正解までDecamark
            else:
                quizEmbed.description = f"{qDatas.name} -> [?]"
                quizEmbed.set_thumbnail(url=self.__imageLink(qDatas.name))

        elif self.quizName == "introq":
            track = intro.random_track(
                self.state.intro_works, self.state.intro_categories,
                self.state.intro_secret)
            if track is None:
                await sendChannel.send(
                    "出題条件に合う曲がありません"
                    "（`/introdata` で条件を確認、リセットで既定に戻せます）")
                return
            quizEmbed.title = "イントロクイズ"
            # 戦闘曲に限らない言い方にする（フィールド曲なども同じ文で出す）
            if voiceChannel is not None:
                quizEmbed.description = "イントロをボイスチャンネルで流します。"
                quizView = replay_button_view()
            else:
                quizEmbed.description = "添付のイントロを聞いて、"
            quizEmbed.description += (
                "何の曲か当てよう\n"
                "答え方: 作品の略称＋曲の中身（戦う相手・場所など）\n"
                "例: `BWシロナ` `DP野生` `SV四天王` `剣盾ジムリーダー`\n"
                "`ヒント` で作品が分かる　あきらめる: `ギブ`")
            voicePath = track.path
            quizFile = discord.File(
                str(voicePath),
                filename=intro.intro_filename(
                    track.id, secrets.token_hex(CRY_NONCE_BYTES)))

        else:
            ub.output_warning(f"不明なクイズ識別子(post): {self.quizName}")
            # ここでエラーを送信
            return

        self.qm = await sendChannel.send(
            content=quizContent, file=quizFile, embed=quizEmbed, view=quizView
        )

        await asyncio.to_thread(
            self.__log_post, qDatas, track, cryKind, quizContent, quizEmbed)

        if voicePath is not None and voiceChannel is not None:
            await self.__play_cry(voiceChannel, voicePath)

    def __conditions(self, cryKind) -> dict:
        """出題ログに残す、そのときの出題条件。"""
        conditions = {"連続出題": self.state.bakusoku_mode}
        if self.quizName == "bq":
            conditions["絞り込み"] = self.state.bq_filter_dict
        elif self.quizName == "cryq":
            conditions["モード"] = self.state.cry_mode
            conditions["絞り込み"] = self.state.cry_filter_dict
            conditions["鳴き声"] = cryKind
        elif self.quizName == "introq":
            conditions["作品"] = list(self.state.intro_works)
            conditions["区分"] = list(self.state.intro_categories)
            conditions["シークレット"] = self.state.intro_secret
        return conditions

    def __log_post(self, pokemon, track, cryKind, quizContent, quizEmbed):
        """出題を記録する。question は判定ログ（__log）と同じ書き方にそろえる。"""
        if track is not None:
            answer = track.title + (f"（{track.work}）" if track.work else "")
            question, answer_id = answer, track.id
        elif pokemon is not None:
            answer, answer_id = pokemon.name, pokemon_id(pokemon)
            if self.quizName == "bq":
                question = quizContent.split(" ")[0]
            elif self.variant in ("etojq", "jtoeq", "ctojq", "ntopq", "ptonq"):
                question = re.findall(r"^(.+)\s->", quizEmbed.description)[0]
            else:
                question = pokemon.name
        else:
            return
        guild_id = getattr(getattr(self.qm, "guild", None), "id", 0) or 0
        save.add_quiz_post(
            guild_id, self.quizName, getattr(self.qm, "id", None),
            question, answer, answer_id, self.__conditions(cryKind))

    async def __play_cry(self, voice_channel, path):
        """ボイスチャンネルで鳴き声を流す（全員が同時に聞ける）。

        権限が無い・接続できないときはログに残して添付だけにする。
        """
        try:
            voice_client = voice_channel.guild.voice_client
            if voice_client is None:
                voice_client = await voice_channel.connect(self_deaf=True)
            elif voice_client.channel != voice_channel:
                await voice_client.move_to(voice_channel)
        except (discord.Forbidden, discord.ClientException,
                discord.HTTPException, OSError) as error:
            ub.output_error(f"{self.quizName}: ボイスに接続できませんでした: {error}")
            return
        if play_cry(voice_client, path):
            ub.output_log(f"{self.quizName}: 鳴き声を再生します: {voice_channel.name}")

    async def try_response(self, response):

        # インスタンスがメッセージ/インタラクションかどうかで代入データを変える
        if isinstance(response, discord.Message):
            self.rm = response
            self.qm = response.reference.resolved
            self.ansText = ub.format_text(response.content)
            self.rawText = response.content
            self.opener = self.rm.author
        elif isinstance(response, discord.Interaction):
            self.rm = response
            self.qm = response.message
            self.ansText = self.rm.data["custom_id"].split("_")[1]
            self.rawText = self.ansText
            self.opener = self.rm.user
            # customIDが"acq_こうげき/とくこう/同値"のようなかたちを想定

        self.quizEmbed = self.qm.embeds[0]
        # 図鑑番号クイズの出し方は、問題文（No.510 -> / レパルダス ->）から見分ける
        self.fromNumber = bool(
            re.match(r"No\.\d+ ->", self.quizEmbed.description or ""))
        # この時点で出ているヒント（判定ログに残す。ヒントを足す前に控える）
        self.hintsShown = [field.name for field in self.quizEmbed.fields]
        self.hintGiven = None
        if self.quizName == "bq":
            # 取得し直したEmbedの画像はCDNのURLになっている。そのまま編集すると
            # グラフが埋め込みから外れて外に出るので、添付への参照に戻す
            self.quizEmbed.set_image(url="attachment://image.png")

        gives = ["ギブ", "ギブアップ", "降参", "敗北"]
        hints = []

        # クイズごとにヒント項目を作成する
        if self.variant in ["bq", "ctojq", "cryq", "dexq", "ntopq"]:
            hints = [
                "ヒント",
                "タイプ",
                "特性",
                "トクセイ",
                "地方",
                "チホウ",
                "分類",
                "ブンルイ",
                "作品",
                "サクヒン",
            ]
        elif self.quizName == "etojq":
            hints = [
                "ヒント",
                "タイプ",
                "特性",
                "トクセイ",
                "地方",
                "チホウ",
                "分類",
                "ブンルイ",
                "作品",
                "サクヒン",
                "語源",
                "ゴゲン",
            ]
        elif self.quizName == "jtoeq":
            hints = ["文字数", "モジスウ", "頭文字", "カシラモジ", "イニシャル"]
        elif self.variant == "ptonq":
            hints = ["ヒント", "地方", "チホウ", "作品", "サクヒン"]
        elif self.quizName == "introq":
            hints = ["ヒント", "作品", "サクヒン"]

        # ここでクイズの問題文を取得する
        if self.quizName == "bq":
            self.examText = self.qm.content.split(" ")[0]
        elif self.quizName == "acq":
            self.examText = self.quizEmbed.description.split(" ")[0]
        elif self.variant in ["etojq", "jtoeq", "ctojq", "ntopq", "ptonq"]:
            self.examText = re.findall(r"^(.+)\s->", self.quizEmbed.description)[0]
        elif self.quizName == "cryq":
            entry = cry_from_message(self.qm)
            if entry is None:
                await self.rm.reply(
                    "この問題の答えが分からなくなりました。もう一度 /q で出題してください")
                return
            self.examText = entry[0]
        elif self.quizName == "dexq":
            catalog = await asyncio.to_thread(dex_text.get_catalog)
            self.dexEntries = catalog.find(self.quizEmbed.description)
            if not self.dexEntries:
                await self.rm.reply(
                    "この問題の答えが分からなくなりました。もう一度 /q で出題してください")
                return
            self.dexCatalog = catalog
            self.dexAnswers = dex_answers(self.dexEntries)
            self.examText = next(iter(self.dexAnswers.values()))[1]
        elif self.quizName == "introq":
            self.track = intro.track_from_message(self.qm)
            if self.track is None:
                await self.rm.reply(
                    "この問題の答えが分からなくなりました。もう一度 /q で出題してください")
                return
            self.examText = self.track.title

        # ここでクイズの回答を取得する
        self.ansList, self.ansZero = self.__answers()

        if self.ansText in gives:
            await self.__giveup()
            await asyncio.to_thread(
                self.__log, LOG_GIVEUP, self.ansList[0], True)
        elif self.ansText in hints:
            await self.__hint()
            await asyncio.to_thread(
                self.__log, LOG_HINT, self.ansList[0], True, self.hintGiven)
        else:
            await self.__judge()

    async def __giveup(self):
        ub.output_log(f"{self.quizName}: ギブアップを実行")
        if isinstance(self.rm, discord.Message):
            await self.rm.add_reaction("😅")
            answer = self.ansList[0]
            if self.quizName == "introq" and self.ansZero.work:
                answer += f"（{self.ansZero.work}）"  # 曲名だけでは作品が分からない
            await self.rm.reply(f"答えは{answer}でした")
        await self.__disclose(False)

    async def __judge(self):
        ub.output_log(f"{self.quizName}: 正誤判定を実行")

        fixAns = self.ansText
        repPokeData = None
        nearReply = None  # 「おしい」の返事（戦績には数えない）
        notNumber = False
        if self.variant in ["bq", "etojq", "ctojq", "cryq", "dexq", "ntopq"]:
            if found := ub.fetch_pokemon(self.ansText):
                repPokeData = found[0]
                fixAns = repPokeData.name
                if self.quizName == "dexq":
                    fixAns, nearReply = self.__judge_dex(found)
                elif self.variant == "ntopq":
                    # 当てるのは種族。フォームの名前で答えても正解
                    gap = abs(int(repPokeData.species) - int(self.ansZero.species))
                    if gap == 0:
                        fixAns = self.ansList[0]
                    elif gap <= NUMBER_NEAR:
                        nearReply = "おしいロ！ 図鑑番号が 近い ポケモンだロ"
        elif self.variant == "ptonq":
            number = parse_number(self.rawText)
            if number is None:
                notNumber = True
            else:
                fixAns = str(number)
                if 0 < abs(number - int(self.ansList[0])) <= NUMBER_NEAR:
                    nearReply = "おしいロ！ 番号が 近いロ"
        elif self.quizName == "jtoeq":
            fixAns = jaconv.z2h(
                jaconv.kata2alphabet(fixAns), kana=False, ascii=False, digit=True
            ).lower()
            self.ansList[0] = self.ansList[0].lower()
        elif self.quizName == "introq":
            # 「略称＋戦う相手」か、1作品にしか無い言い方なら正解（対応リストで照合）
            introVerdict = intro.judge(self.track, self.ansText)
            if introVerdict == intro.CORRECT:
                fixAns = self.ansList[0]

        if fixAns in self.ansList:
            judge = "正答"
            isMessage = isinstance(self.rm, discord.Message)
            if isMessage:
                await self.rm.add_reaction("⭕")
            result = await self.__disclose(True, fixAns)
            if result == 1:
                # ほかの回答で先に開示された。戦績にもログにも数えない
                if isMessage:
                    await self.rm.remove_reaction("⭕", self.bot.user)
                return
        else:
            judge = "誤答"
            if isinstance(self.rm, discord.Message):
                reaction = "❌"
            if isinstance(
                self.rm, discord.Interaction
            ):  # ボタンで回答しているときはギブアップになる
                await self.__disclose(False)

        if (
            self.variant in ["bq", "etojq", "ctojq", "cryq", "dexq", "ntopq"]
            and repPokeData is None
        ):  # 例外処理
            judge = None
            if isinstance(self.rm, discord.Message):
                reaction = "❓"
                await self.rm.reply(f"{self.ansText} は図鑑に登録されていません")
        elif notNumber:
            judge = None
            if isinstance(self.rm, discord.Message):
                reaction = "❓"
                await self.rm.reply("図鑑番号を 数字で 答えてね（例: `510`）")
        elif judge == "誤答" and nearReply:
            judge = None  # 戦績には数えない
            if isinstance(self.rm, discord.Message):
                reaction = "❓"
                await self.rm.reply(nearReply)
        elif self.quizName == "introq" and introVerdict in (
                intro.AMBIGUOUS, intro.AMBIGUOUS_SONG, intro.PARTIAL, intro.UNKNOWN):
            judge = None  # 戦績には数えない
            if isinstance(self.rm, discord.Message):
                reaction = "❓"
                if introVerdict == intro.AMBIGUOUS:
                    await self.rm.reply(
                        "ほかの作品にも ある曲だロ。作品の略称もつけて答えてね"
                        "（`略称＋相手` のかたち。例: `BWシロナ`）")
                elif introVerdict == intro.PARTIAL:
                    await self.rm.reply(
                        "おしいロ！ もう少し くわしく答えてね")
                elif introVerdict == intro.AMBIGUOUS_SONG:
                    axes = intro.distinguishers(self.track, self.ansText)
                    if axes:
                        await self.rm.reply(
                            "その相手の曲は いくつかあるロ。"
                            f"{'も、'.join(axes)}も つけて答えてね")
                    else:
                        titles = "／".join(
                            f"`{title}`" for title in
                            intro.candidates(self.track, self.ansText))
                        await self.rm.reply(
                            f"その相手の曲は いくつかあるロ（{titles}）。"
                            "どれか分かるように答えてね（`決戦`・地方名などをつける）")
                else:
                    await self.rm.reply(f"{self.ansText} は曲リストにありません")
        elif (
            judge == "誤答"
            and self.quizName == "jtoeq"
            and len(
                (
                    pokes := [
                        p
                        for p in get_pokedex().records
                        if p.eng and p.eng.lower() == fixAns
                    ]
                )
            )
            > 0
        ):
            if isinstance(self.rm, discord.Message):
                await self.rm.reply(f"{fixAns} は {pokes[0].name} の英名です")

        if judge != "正答" and isinstance(self.rm, discord.Message):
            await self.rm.add_reaction(reaction)

        if judge is not None:
            try:
                # DBが遅くてもBot全体を止めないよう、別スレッドで書く
                await asyncio.to_thread(
                    ub.report,
                    self.opener.id, f"{self.quizName}{judge}", 1, self.opener.name
                )  # 回答記録のレポート
            except SaveError:
                ub.output_error("クイズ戦績の保存に失敗しました")
                if isinstance(self.rm, discord.Message):
                    await self.rm.reply("戦績の保存に失敗しました")

        await asyncio.to_thread(
            self.__log, judge, self.ansList[0], None,
            introVerdict if self.quizName == "introq"
            else ("おしい" if judge is None and nearReply else None),
            pokemon_id(repPokeData) if repPokeData is not None else None)

    def __judge_dex(self, found):
        """図鑑説明クイズの判定。(正解ならその名前・ちがえば答えた名前, おしいの返事)。

        種族名で答えたら基本の姿、フォームの名前ならそのフォームを答えたものとする。
        同じ種族の別のフォーム・進化の前後は「おしい」。
        """
        intended = [p for p in found if p.form_id == "00"] or found
        for pokemon in intended:
            if (pokemon.species, pokemon.form_id) in self.dexAnswers:
                return self.dexAnswers[(pokemon.species, pokemon.form_id)][1], None
        answered = {pokemon.species for pokemon in intended}
        species = {key[0] for key in self.dexAnswers}
        if answered & species:
            return intended[0].name, "おしいロ！ すがた（フォーム）が ちがうロ"
        if any(self.dexCatalog.related(one, other)
               for one in species for other in answered):
            return intended[0].name, "おしいロ！ 進化の前か後の ポケモンだロ"
        return intended[0].name, None

    async def __hint(self):
        ub.output_log(f"{self.quizName}: ヒント表示を実行")

        pokemon = self.ansZero
        hintIndex = None

        if self.variant in ["bq", "etojq", "ctojq", "cryq", "dexq", "ntopq"]:
            if (
                self.ansText == "ヒント"
            ):  # まだ出ていないヒントからランダムにヒントを出す
                hintIndexs = [
                    "タイプ1",
                    "タイプ2",
                    "特性1",
                    "特性2",
                    "隠れ特性",
                    "出身地",
                    "分類",
                    "初登場作品",
                ]  # ヒントになるインデックスの一覧
                alreadyHints = [
                    field.name for field in self.quizEmbed.fields
                ]  # 既出のヒントの一覧
                stillHints = [
                    x
                    for x in hintIndexs
                    if x not in alreadyHints
                    and pokemon.hint_value(x) is not None
                ]  # 未出のヒントの一覧（値が無いものは出さない）
                if stillHints:
                    hintIndex = random.choice(stillHints)
                else:
                    shownHints = [
                        x
                        for x in alreadyHints
                        if pokemon.hint_value(x) is not None
                    ]
                    if not shownHints:
                        await self.rm.reply("これ以上 出せるヒントが ないロ")
                        return
                    hintIndex = random.choice(shownHints)

            elif self.ansText in ["タイプ"]:
                if pokemon.type_1 and not any(
                    field.name == "タイプ1" for field in self.quizEmbed.fields
                ):
                    hintIndex = "タイプ1"
                elif pokemon.type_2 and not any(
                    field.name == "タイプ2" for field in self.quizEmbed.fields
                ):
                    hintIndex = "タイプ2"
                else:
                    await self.rm.reply(
                        f"タイプは{pokemon.type_1 or 'なし'}/{pokemon.type_2 or 'なし'}です"
                    )
                    return

            elif self.ansText in ["特性", "トクセイ"]:
                if pokemon.ability_1 and not any(
                    field.name == "特性1" for field in self.quizEmbed.fields
                ):
                    hintIndex = "特性1"
                elif pokemon.ability_2 and not any(
                    field.name == "特性2" for field in self.quizEmbed.fields
                ):
                    hintIndex = "特性2"
                elif pokemon.ability_h and not any(
                    field.name == "隠れ特性" for field in self.quizEmbed.fields
                ):
                    hintIndex = "隠れ特性"
                else:
                    await self.rm.reply(
                        f"とくせいは{pokemon.ability_1 or 'なし'}/{pokemon.ability_2 or 'なし'}/{pokemon.ability_h or 'なし'}です"
                    )
                    return

            elif self.ansText in ["地方", "チホウ"]:
                hintIndex = "出身地"
            elif self.ansText in ["分類", "ブンルイ"]:
                hintIndex = "分類"
            elif self.ansText in ["作品", "サクヒン"]:
                hintIndex = "初登場作品"
            elif self.ansText in ["語源", "ゴゲン"]:
                hintIndex = "英語名由来"

        elif self.quizName == "jtoeq":
            if self.ansText in ["文字数", "モジスウ"]:
                hintIndex = "文字数"
            elif self.ansText in ["頭文字", "カシラモジ", "イニシャル"]:
                hintIndex = "イニシャル"

        elif self.variant == "ptonq":
            # 番号の見当がつくもの（地方・初登場作品）だけ出す
            if self.ansText in ["作品", "サクヒン"]:
                hintIndex = "初登場作品"
            elif self.ansText in ["地方", "チホウ"] or not any(
                    field.name == "出身地" for field in self.quizEmbed.fields):
                hintIndex = "出身地"
            else:
                hintIndex = "初登場作品"

        elif self.quizName == "introq":
            hintIndex = "作品"  # ヒントは作品だけ

        else:
            ub.output_warning(f"不明なクイズ識別子(hint): {self.quizName}")
            return

        if hintIndex is None:
            return

        hintValue = pokemon.hint_value(hintIndex)
        if hintValue is None:
            await self.rm.reply(f"{hintIndex}は まだ 登録されて いないロ")
            return

        # 初出のヒントならEmbedにフィールドを追加
        if not any(field.name == hintIndex for field in self.quizEmbed.fields):
            self.quizEmbed.add_field(name=hintIndex, value=str(hintValue))
            try:
                # 添付（鳴き声・グラフ）は消さない。attachments を渡さないと保持される
                await self.qm.edit(embed=self.quizEmbed)
            except discord.errors.Forbidden:
                pass

        self.hintGiven = hintIndex
        await self.rm.reply(f"{hintIndex}は{hintValue}です")

    async def __disclose(self, tf, answered=None):
        if self.qm.id in self.state.disclosing:
            ub.output_log(f"{self.quizName}: 応答処理実行中につき処理を中断")
            return 1

        self.state.disclosing.add(self.qm.id)  # 回答開示処理を始める
        try:
            result = await self.__reveal(tf, answered)
        finally:
            # 途中で例外が出ても、開示中のまま残さない
            self.state.disclosing.discard(self.qm.id)
        if result == 0:
            await self.__continue()  # 連続出題を試みる
        return result

    async def __reveal(self, tf, answered):
        ub.output_log(f"{self.quizName}: 回答開示を実行")

        # 処理前に最新のメッセージ状態を取得して確認
        try:
            # メッセージを再取得して最新の状態を確認
            updated_message = await self.qm.channel.fetch_message(self.qm.id)
            ub.output_log(f"クイズのフッター:{updated_message.embeds[0].footer.text}")
            if updated_message.embeds and "(done)" in updated_message.embeds[0].footer.text:
                ub.output_log("クイズの処理中にクイズが終了しています")
                return 1  # 処理中断（失敗）を示す値
        except Exception as e:
            ub.output_log(f"メッセージ取得中にエラー: {e}")
            # エラーがあっても処理継続

        if tf:  # 正解者がいる場合
            clearTime = self.rm.created_at - self.qm.created_at  # 所要時間を求める
            days, seconds = divmod(clearTime.total_seconds(), 86400)  # 所要時間を分解
            hours, seconds = divmod(seconds, 3600)
            minutes, seconds = divmod(seconds, 60)
            clearTimes = f"{int(seconds)}秒"
            if days >= 1:
                clearTimes = (
                    f"{int(days)}日 {int(hours):02}:{int(minutes):02}:{int(seconds):02}"
                )
            elif hours >= 1:
                clearTimes = f"{int(hours):02}:{int(minutes):02}:{int(seconds):02}"
            elif minutes >= 1:
                clearTimes = f"{int(minutes):02}:{int(seconds):02}"
            authorText = f"{self.opener.name} さんが正解! [TIME {clearTimes}]"
            link = self.__imageLink(answered)

        else:  # 正解者が存在せず,ギブアップされた場合
            authorText = f"{self.opener.name} さんがギブアップ"
            link = self.__imageLink(
                self.ansList[0]
            )  # self.ansZero['おなまえ']でもいいかも

        if self.state.bakusoku_mode:
            # 次の問題が出る予告。別の投稿にすると遅くなるので、この行に付ける
            authorText += " ⏩連続出題ON"
        self.quizEmbed.set_author(name=authorText)  # 回答者の情報を表示

        if self.quizName == "bq":
            self.quizEmbed.description = f'こたえ: {",".join(self.ansList)}'
        elif self.quizName == "cryq":
            entry = cry_from_message(self.qm) or ('', '')
            label = CRY_LABELS.get(entry[1], '')
            self.quizEmbed.description = (
                f"こたえ: {self.ansList[0]}"
                + (f"（{label}のなきごえ）" if label else ''))
        elif self.quizName == "dexq":
            entry = self.dexEntries[0]
            self.quizEmbed.description = (
                f'{entry.text}\nこたえ: {",".join(self.ansList)}'
                f"\n作品: {entry.titles_label()}")
        elif self.quizName == "introq":
            self.quizEmbed.description = (
                f"こたえ: {self.ansList[0]}"
                + (f"（{self.ansZero.work}）" if self.ansZero.work else ''))
            appears = "、".join(work for work, _ in self.ansZero.appearances)
            if appears:  # 再録・流用で流れるほかの作品
                self.quizEmbed.description += f"\nほかに流れる作品: {appears}"
        elif self.quizName == "acq":
            self.quizEmbed.description = f"{ub.bss_to_text(self.ansZero)}\n"
            if self.ansList[0] == "同値":
                self.quizEmbed.description += (
                    f"{self.examText}はこうげきととくこうが同じ"
                )
            else:
                self.quizEmbed.description += (
                    f"{self.examText}は{self.ansList[0]}の方が高い"
                )

        elif self.variant in ["etojq", "jtoeq", "ctojq", "ntopq", "ptonq"]:
            self.quizEmbed.description = f"{self.examText} -> [{self.ansList[0]}]"
            if self.quizName == "etojq":
                if self.ansZero.etymology:
                    self.quizEmbed.description += f"\n{self.ansZero.etymology}"
            elif self.quizName == "ctojq":
                self.quizEmbed.description += (
                    f"\n拼音: {ub.pinyin_to_text(self.examText)}"
                )

        if not "Decamark" in link:
            self.quizEmbed.set_thumbnail(url=link)  # サムネイルを変更する

        self.quizEmbed.set_footer(text=self.quizEmbed.footer.text + "(done)")

        if isinstance(self.rm, discord.Message):
            try:
                # 添付は消さない（鳴き声をもう一度聞けるように）
                await self.qm.edit(embed=self.quizEmbed)
            except discord.errors.Forbidden:
                await self.qm.channel.send(embed=self.quizEmbed)

        elif isinstance(self.rm, discord.Interaction):
            fixView = discord.ui.View.from_message(self.qm)
            for child in fixView.children:
                child.disabled = True
            try:
                # 添付は消さない（attachments を渡さないと保持される）
                await self.rm.response.edit_message(
                    embed=self.quizEmbed, view=fixView
                )
            except discord.errors.Forbidden:
                pass

        return 0

    async def __continue(self):
        if self.state.bakusoku_mode:
            ub.output_log(f"{self.quizName}: 連続出題を実行")
            # 「生成チュウ」の表示は送信と削除で往復が増えるので出さない
            session = QuizSession(self.bot, self.quizName, self.state)
            session.fromNumber = self.fromNumber  # 同じ出し方で続ける
            await session.post(
                self.qm.channel, voiceChannel=self.voice_channel)

    def __answers(self):
        ub.output_log(f"{self.quizName}: 正答リスト生成を実行")
        answers = []
        aData = None
        pokedex = get_pokedex()

        if self.quizName == "bq":
            stats = tuple(map(int, self.examText.split("-")))
            aDatas = [p for p in pokedex.records if p.stats == stats]
            aData = aDatas[0]
            answers = [p.name for p in aDatas]

        elif self.quizName == "acq":
            aData = ub.fetch_pokemon(self.examText)[0]
            if aData.atk == aData.spa:
                answers.append("同値")
            elif aData.atk > aData.spa:
                answers.append("こうげき")
            else:
                answers.append("とくこう")

        elif self.quizName == "etojq":
            aData = [p for p in pokedex.records if p.eng == self.examText][0]
            answers.append(aData.name)

        elif self.quizName == "jtoeq":
            aData = ub.fetch_pokemon(self.examText)[0]
            answers.append(aData.eng)

        elif self.quizName == "ctojq":
            aData = [p for p in pokedex.records if p.cht == self.examText][0]
            answers.append(aData.name)

        elif self.quizName == "cryq":
            aData = ub.fetch_pokemon(self.examText)[0]
            answers.append(aData.name)

        elif self.quizName == "dexq":
            aData = next(iter(self.dexAnswers.values()))[0]
            answers = list(dict.fromkeys(
                shown for _record, shown in self.dexAnswers.values()))

        elif self.variant == "ntopq":
            aData = pokedex.base(self.examText.removeprefix("No."))
            answers.append(aData.name)

        elif self.variant == "ptonq":
            aData = ub.fetch_pokemon(self.examText)[0]
            answers.append(aData.species)

        elif self.quizName == "introq":
            aData = self.track
            answers.append(aData.title)

        else:
            ub.output_warning(f"不明なクイズ識別子(answers): {self.quizName}")
            return answers, aData

        return answers, aData  # 正答のリストと0番目の正答をタプルで返す

    def __random_with(self, filter_dict, field):
        """条件に合うポケモンから、指定の項目を持つ1匹をランダムに選ぶ。"""
        candidates = [
            p for p in get_pokedex().filter(filter_dict) if getattr(p, field)
        ]
        if not candidates:
            ub.output_error(f"{self.quizName}: 出題条件に合うポケモンがいません")
            return None
        return random.choice(candidates)

    def __random_cry(self):
        """鳴き声ファイルがある基本形態から (ポケモン, 種類) をランダムに選ぶ。

        出題条件（self.state.cry_mode）に合う種類だけを使う。
        mix のときは、あるものをランダムに選ぶ。
        """
        candidates = cry_candidates(self.state)
        if not candidates:
            ub.output_error(f"{self.quizName}: 鳴き声のあるポケモンがいません")
            return None
        pokemon, kinds = random.choice(candidates)
        return pokemon, random.choice(kinds)

    def __imageLink(self, searchWord=None):
        ub.output_log(f"{self.quizName}: 画像リンク生成を実行")
        link = f"{cfg.EX_SOURCE_LINK}Decamark.png"  # デフォルトは(?)マーク
        if searchWord is not None:
            if self.quizName in [
                    "bq", "acq", "etojq", "jtoeq", "ctojq", "cryq", "dexq",
                    "noq"]:
                displayImage = ub.fetch_pokemon(searchWord)
                if displayImage:  # 回答ポケモンが発見できた場合
                    link = f"{cfg.EX_SOURCE_LINK}art/{displayImage[0].image_number}.png"
            elif self.quizName != "introq":  # イントロクイズは画像を出さない
                ub.output_warning(f"不明なクイズ識別子(imageLink): {self.quizName}")
        return link

    def __answer_id(self) -> str:
        """正解のID。種族値クイズ・図鑑説明クイズは正解がいくつもあれば、全部並べる。"""
        if self.quizName == "introq":
            return self.ansZero.id
        if self.quizName == "bq":
            return "|".join(
                pokemon_id(p) for p in get_pokedex().records
                if p.stats == self.ansZero.stats)
        if self.quizName == "dexq":
            return "|".join(
                pokemon_id(record) for record, _shown in self.dexAnswers.values())
        return pokemon_id(self.ansZero)

    def __log(self, judge, exAns, recognized=None, detail=None, input_id=None):
        # 判定ログはDB（ubsleepy.quiz_log）へ。DBが無い手元はCSV（開発用）
        # 分析（間違いやすい問題・書き間違い・本人の苦手）に使う
        logPath = f"log/{self.quizName}log.csv"
        ub.output_log(f"{self.quizName}: log生成を実行\n {logPath}")
        guild_id = getattr(getattr(self.qm, "guild", None), "id", 0) or 0
        if recognized is None:
            recognized = judge is not None
        question = self.examText
        if self.quizName == "introq" and self.ansZero.work:
            # 同じ曲名がいくつもの作品にあるので、作品まで書いて区別する
            question = exAns = f"{self.examText}（{self.ansZero.work}）"
        save.add_quiz_log(
            guild_id, self.quizName, judge, question, self.ansText,
            recognized, csv_path=logPath, answer=exAns,
            quiz_message_id=getattr(self.qm, "id", None),
            user_id=getattr(self.opener, "id", None),
            answer_id=self.__answer_id(),
            input_raw=(self.rawText or "")[:LOG_RAW_LENGTH],
            input_id=input_id,
            hints="|".join(self.hintsShown),
            detail=detail)
