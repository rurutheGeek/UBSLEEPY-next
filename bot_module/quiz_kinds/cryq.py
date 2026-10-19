# -*- coding: utf-8 -*-
# quiz_kinds/cryq.py
"""鳴き声クイズ（cryq）: 添付（またはボイスチャンネル）の鳴き声からポケモンを当てる。"""
import hashlib
from pathlib import Path
import random
import re
import secrets

import discord

from bot_module import func as ub
from bot_module.pokedex import get_pokedex

from .base import LOST_ANSWER, Draft, NameAnswerKind

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
# 鳴き声・イントロクイズ: 投稿につける「もう一度再生」ボタン
CRY_REPLAY_BUTTON_ID = "cryReplayButton"
CRY_REPLAY_LABEL = "もう一度再生"


def cry_hash(name: str, kind: str, nonce: str) -> str:
    """種類・nonce・答えの名前から、添付ファイル名に使う短いハッシュを作る。"""
    digest = hashlib.sha1(f"{kind}:{nonce}:{name}".encode("utf-8")).hexdigest()
    return digest[:CRY_HASH_LENGTH]


def cry_filename(name: str, kind: str, nonce: str) -> str:
    return f"cry-{nonce}-{cry_hash(name, kind, nonce)}.ogg"


def replay_button_view() -> discord.ui.View:
    """鳴き声・イントロクイズの投稿に付ける「もう一度再生」ボタン。"""
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


class CryQuiz(NameAnswerKind):

    async def build(self, s, embed, channel, voice_channel):
        picked = self.random_cry(s.state)
        if picked is None:
            mode_label = CRY_MODE_LABELS.get(s.state.cry_mode, s.state.cry_mode)
            conditions = "、".join(
                f"{key}: {'/'.join(values)}"
                for key, values in s.state.cry_filter_dict.items())
            detail = f"モード: {mode_label}"
            if conditions:
                detail += f"、{conditions}"
            hint = ("モード「昔」はBWまでの鳴き声です。"
                    if s.state.cry_mode == "legacy" else "")
            await channel.send(
                f"出題条件に合う鳴き声がありません（{detail}）\n"
                f"{hint}`/crydata` で条件を確認、リセットで既定に戻せます")
            return None
        qDatas, cryKind = picked
        embed.title = "鳴き声クイズ"
        view = None
        if voice_channel is not None:
            embed.description = (
                "鳴き声をボイスチャンネルで流します。聞いてポケモン名を答えよう")
            view = replay_button_view()
        else:
            embed.description = "添付の鳴き声を聞いて ポケモン名を答えよう"
        embed.set_thumbnail(url=self.image_link())  # 正解までDecamark
        voicePath = CRY_DIRECTORY / cryKind / f"{qDatas.ndex_number}.ogg"
        cryNonce = secrets.token_hex(CRY_NONCE_BYTES)
        file = discord.File(
            str(voicePath), filename=cry_filename(qDatas.name, cryKind, cryNonce))
        return Draft(file=file, view=view, voice_path=voicePath,
                     record=self.pokemon_record(qDatas), extra={"鳴き声": cryKind})

    def random_cry(self, state):
        """鳴き声ファイルがある基本形態から (ポケモン, 種類) をランダムに選ぶ。

        出題条件（state.cry_mode）に合う種類だけを使う。
        mix のときは、あるものをランダムに選ぶ。
        """
        candidates = cry_candidates(state)
        if not candidates:
            ub.output_error(f"{self.name}: 鳴き声のあるポケモンがいません")
            return None
        pokemon, kinds = random.choice(candidates)
        return pokemon, random.choice(kinds)

    def conditions(self, s, draft):
        return {
            "モード": s.state.cry_mode,
            "絞り込み": s.state.cry_filter_dict,
            "鳴き声": draft.extra.get("鳴き声"),
        }

    async def read_question(self, s):
        entry = cry_from_message(s.qm)
        if entry is None:
            await s.rm.reply(LOST_ANSWER)
            return False
        s.examText = entry[0]
        return True

    def answers(self, s):
        aData = ub.fetch_pokemon(s.examText)[0]
        return [aData.name], aData

    def reveal(self, s):
        entry = cry_from_message(s.qm) or ('', '')
        label = CRY_LABELS.get(entry[1], '')
        s.quizEmbed.description = (
            f"こたえ: {s.ansList[0]}"
            + (f"（{label}のなきごえ）" if label else ''))
