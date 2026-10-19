# -*- coding: utf-8 -*-
# quiz_kinds/bhq.py
"""種族値穴埋めクイズ（bhq）: ポケモンの名前と、穴のあいた種族値から、穴の数字を当てる。

本文は「H108 A130 B? C80 D? S102」の形。答えは「b95d85」「ぼうぎょ95 とくぼう85」、
または数字だけを穴の順に。穴の数（1〜3）は /q の holes で選ぶ。
穴の位置は既定では手がかりの欄（いちばん高い欄・いちばんめずらしい値の欄・すばやさ）を
避け、RANDOM_MODE ではどこでもよい。どちらもタイトルと本文から見分ける。
"""
import re

from bot_module import stat_holes
from bot_module.pokedex import get_pokedex

from .base import LOST_ANSWER, NO_POKEMON, Draft, Judgement, PokemonKind
from .bq import all_stats

RANDOM_MODE = "穴の位置ランダム"
DEFAULT_HOLES = 1
TITLE = "種族値穴埋めクイズ"
NAME_RE = re.compile(r"\*\*(.+?)\*\*")
HINT_WORDS = ["ヒント", "合計", "ゴウケイ"]


def hole_names(holes) -> str:
    return "・".join(stat_holes.LABELS[index] for index in holes)


class StatHoleQuiz(PokemonKind):

    def is_random(self, s) -> bool:
        return getattr(s, "mode", None) == RANDOM_MODE

    async def build(self, s, embed, channel, voice_channel):
        qDatas = get_pokedex().random(s.state.bq_filter_dict)
        if qDatas is None:
            await channel.send(NO_POKEMON)
            return None
        count = getattr(s, "holes", None) or DEFAULT_HOLES
        holes = stat_holes.choose_holes(
            qDatas.stats, count, all_stats(), keep=not self.is_random(s))
        embed.title = TITLE + (f"（{RANDOM_MODE}）" if self.is_random(s) else "")
        embed.description = (
            f"**{qDatas.name}** の 種族値の 穴をうめてね\n"
            f"答え方: `{self.example(qDatas.stats, holes)}`（穴の順に数字だけでもOK）")
        embed.set_thumbnail(url=self.image_link(qDatas.name))
        return Draft(content=stat_holes.show(qDatas.stats, holes),
                     record=self.pokemon_record(qDatas),
                     extra={"holes": holes})

    @staticmethod
    def example(stats, holes) -> str:
        # 数字は決まった値（本物に寄せると答えの見当がつく）
        return "".join(f"{stat_holes.LABELS[i].lower()}100" for i in holes)

    def conditions(self, s, draft):
        return {
            "絞り込み": s.state.bq_filter_dict,
            "穴の数": len(draft.extra["holes"]),
            "穴の位置": RANDOM_MODE if self.is_random(s) else "手がかりの欄を残す",
            "穴": hole_names(draft.extra["holes"]),
        }

    def restore(self, s):
        title = s.quizEmbed.title or ""
        s.mode = RANDOM_MODE if RANDOM_MODE in title else None
        shown = stat_holes.parse_shown(s.qm.content) or ()
        s.holes = sum(value is None for value in shown) or DEFAULT_HOLES

    def hint_words(self, s):
        return HINT_WORDS

    async def read_question(self, s):
        name = NAME_RE.search(s.quizEmbed.description or "")
        shown = stat_holes.parse_shown(s.qm.content)
        pokemon = name and next(
            (p for p in get_pokedex().records if p.name == name.group(1)), None)
        if pokemon is None or shown is None:
            await s.rm.reply(LOST_ANSWER)
            return False
        s.examText = name.group(1)
        s.holeSlots = tuple(i for i, value in enumerate(shown) if value is None)
        s.statsPokemon = pokemon
        return True

    def answers(self, s):
        pokemon = s.statsPokemon
        return [self.answer_text(pokemon.stats, s.holeSlots)], pokemon

    @staticmethod
    def answer_text(stats, holes) -> str:
        return "".join(f"{stat_holes.LABELS[i]}{stats[i]}" for i in holes)

    def interpret(self, s):
        holes = s.holeSlots
        values = stat_holes.parse_answer(s.rawText, holes)
        if values is None:
            return Judgement(
                answer=s.ansText,
                unrecognized=(f"`{self.example(s.ansZero.stats, holes)}` のように "
                              "欄と数字で 答えてね"))
        missing = [i for i in holes if i not in values]
        if len(missing) == len(holes):
            return Judgement(
                answer=s.ansText,
                unrecognized=(f"穴は {hole_names(holes)} だロ"
                              f"（例: `{self.example(s.ansZero.stats, holes)}`）"))
        if missing:
            return Judgement(
                answer=s.ansText,
                unrecognized=f"穴は {hole_names(holes)} の{len(holes)}つだロ。"
                             f"{hole_names(missing)} も まとめて答えてね")
        stats = s.ansZero.stats
        right = [i for i in holes if values[i] == stats[i]]
        answer = "".join(f"{stat_holes.LABELS[i]}{values[i]}" for i in holes)
        detail = None
        if 0 < len(right) < len(holes):
            detail = f"{hole_names(right)}が正解"
        return Judgement(answer=answer, pokemon=s.ansZero, detail=detail)

    async def after_wrong(self, s, judgement):
        if judgement.detail:
            await s.rm.reply(f"{judgement.detail.removesuffix('が正解')} は 合ってるロ")

    def giveup_answer(self, s):
        return stat_holes.full_text(s.ansZero.stats)

    async def hint_index(self, s):
        if any(field.name == "合計" for field in s.quizEmbed.fields):
            await s.rm.reply(f"合計は{sum(s.ansZero.stats)}だロ。これ以上 出せるヒントが ないロ")
            return None
        return "合計"

    def reveal(self, s):
        stats = s.ansZero.stats
        cells = [
            f"**{label}{value}**" if index in s.holeSlots else f"{label}{value}"
            for index, (label, value) in enumerate(zip(stat_holes.LABELS, stats))]
        s.quizEmbed.description = f"**{s.ansZero.name}**\nこたえ: {' '.join(cells)}"

    def log_question(self, s, exAns):
        return s.examText, exAns
