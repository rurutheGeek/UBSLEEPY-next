# -*- coding: utf-8 -*-
# quiz_kinds/bvq.py
"""種族値クイズの種族値あて（bvq）: ポケモンを見て、ある欄の種族値を数字で答える。出し方が2つある。

- TOP_MODE: いちばん高い欄（同じ値が並ぶときはそのどれか）。例「ガブリアス の こうげき は？」→ 130
- SPEED_MODE: すばやさ。

問題文は「**ガブリアス** の **こうげき** の種族値は？」の形で、ポケモンと欄はここから引き直す。
出し方はタイトルから見分ける。チャンネルにそのまま書いた数字も回答として拾う。
"""
import random
import re
import unicodedata

from bot_module import stat_holes
from bot_module.pokedex import get_pokedex

from .base import LOST_ANSWER, NO_POKEMON, Draft, Judgement, PokemonKind

TOP_MODE = "一番高い欄をあてる"
SPEED_MODE = "すばやさをあてる"
TITLES = {TOP_MODE: "高いとこクイズ", SPEED_MODE: "すばやさクイズ"}
QUESTION_RE = re.compile(r"\*\*(.+?)\*\* の \*\*(.+?)\*\* の種族値は")
# 「130」「A130」「こうげき130」「130です」くらいまで読む
NUMBER_RE = re.compile(r"^\D{0,6}?(\d{1,3})\D{0,4}$")
HINT_WORDS = ["ヒント", "合計", "ゴウケイ"]


def parse_value(text) -> int | None:
    match = NUMBER_RE.match(unicodedata.normalize("NFKC", str(text or "")).strip())
    return int(match.group(1)) if match else None


class StatValueQuiz(PokemonKind):

    def mode(self, s) -> str:
        return SPEED_MODE if getattr(s, "mode", None) == SPEED_MODE else TOP_MODE

    async def build(self, s, embed, channel, voice_channel):
        qDatas = get_pokedex().random(s.state.bq_filter_dict)
        if qDatas is None:
            await channel.send(NO_POKEMON)
            return None
        stats = qDatas.stats
        if self.mode(s) == SPEED_MODE:
            slot = stat_holes.SPEED
        else:
            slot = random.choice([i for i, v in enumerate(stats) if v == max(stats)])
        embed.title = TITLES[self.mode(s)]
        embed.description = (
            f"**{qDatas.name}** の **{stat_holes.NAMES[slot]}** の種族値は？\n"
            "数字で答えてね")
        embed.set_thumbnail(url=self.image_link(qDatas.name))
        return Draft(record=self.pokemon_record(
            qDatas, f"{qDatas.name} {stat_holes.NAMES[slot]}"))

    def conditions(self, s, draft):
        return {"絞り込み": s.state.bq_filter_dict, "出し方": self.mode(s)}

    def restore(self, s):
        title = s.quizEmbed.title or ""
        s.mode = SPEED_MODE if TITLES[SPEED_MODE] in title else TOP_MODE

    def hint_words(self, s):
        return HINT_WORDS

    async def read_question(self, s):
        match = QUESTION_RE.search(s.quizEmbed.description or "")
        pokemon = match and next(
            (p for p in get_pokedex().records if p.name == match.group(1)), None)
        if pokemon is None or match.group(2) not in stat_holes.NAMES:
            await s.rm.reply(LOST_ANSWER)
            return False
        s.examText = f"{match.group(1)} {match.group(2)}"
        s.valueSlot = stat_holes.NAMES.index(match.group(2))
        s.valuePokemon = pokemon
        return True

    def answers(self, s):
        return [str(s.valuePokemon.stats[s.valueSlot])], s.valuePokemon

    def interpret(self, s):
        value = parse_value(s.rawText)
        if value is None:
            return Judgement(answer=s.ansText,
                             unrecognized="種族値を 数字で 答えてね（例: `100`）")
        return Judgement(answer=str(value), pokemon=s.ansZero)

    def giveup_answer(self, s):
        return s.ansList[0]

    async def hint_index(self, s):
        if any(field.name == "合計" for field in s.quizEmbed.fields):
            await s.rm.reply(f"合計は{s.ansZero.total}だロ。これ以上 出せるヒントが ないロ")
            return None
        return "合計"

    def reveal(self, s):
        name = stat_holes.NAMES[s.valueSlot]
        s.quizEmbed.description = (
            f"**{s.ansZero.name}** の **{name}** は **{s.ansList[0]}**\n"
            f"{stat_holes.full_text(s.ansZero.stats)}")
