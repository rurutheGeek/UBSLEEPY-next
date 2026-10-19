# -*- coding: utf-8 -*-
# quiz_kinds/bq.py
"""種族値クイズ（bq）: 種族値からポケモンを当てる。出し方が2つある。

- 既定: 種族値のグラフと「108-130-95-80-85-102 合計600」を出す。
- 1匹に決まる欄だけ（MIN_MODE）: 1匹（同じ種族値）に決まる、いちばん少ない欄だけを
  「H108 A? B? C? D? S102」の形で出す。どの組み合わせを見せるかは毎回ランダム。
  見せた欄が一致するポケモンはみな正解。出し方は本文に ? があるかで見分ける。
"""
import random

import discord

from bot_module import func as ub
from bot_module import stat_holes
from bot_module.pokedex import get_pokedex

from .base import NO_POKEMON, Draft, NameAnswerKind, pokemon_id

MIN_MODE = "1匹に決まる欄だけ"


def all_stats() -> set:
    """図鑑にある種族値（重なりは1つ）。"""
    return {p.stats for p in get_pokedex().records}


def stats_key(stats) -> str:
    """判定ログ・出題ログの question（既定の出し方と同じ書き方にそろえる）。"""
    return "-".join(map(str, stats))


class StatsQuiz(NameAnswerKind):

    def is_min(self, s) -> bool:
        return getattr(s, "mode", None) == MIN_MODE

    async def build(self, s, embed, channel, voice_channel):
        qDatas = get_pokedex().random(s.state.bq_filter_dict)
        if qDatas is None:
            # 条件に合うポケモンがいない場合は、空のクイズを投稿せずに終わる
            await channel.send(NO_POKEMON)
            return None
        embed.description = "こたえ: ???"  # 正答後: こたえ: [ポケモン名](複数いる場合),[ポケモン名]
        embed.set_thumbnail(url=self.image_link())  # 正解までDecamark(?)を表示
        if self.is_min(s):
            # グラフは出さない（伏せた欄の大きさが形で分かってしまう）
            shown = random.choice(stat_holes.minimal_views(qDatas.stats, all_stats()))
            holes = tuple(index for index in range(6) if index not in shown)
            embed.title = f"種族値クイズ（{MIN_MODE}）"
            content = stat_holes.show(qDatas.stats, holes)
            return Draft(content=content,
                         record=self.pokemon_record(qDatas, stats_key(qDatas.stats)),
                         extra={"見せた欄": content})
        embed.title = "種族値クイズ"
        file = discord.File(
            ub.generate_graph(list(qDatas.stats)), filename="image.png"
        )
        embed.set_image(url="attachment://image.png")  # 種族値クイズ図形の添付
        content = ub.bss_to_text(qDatas)
        return Draft(content=content, file=file,
                     record=self.pokemon_record(qDatas, content.split(" ")[0]))

    def conditions(self, s, draft):
        conditions = {"絞り込み": s.state.bq_filter_dict}
        if self.is_min(s):
            conditions["出し方"] = MIN_MODE
            conditions.update(draft.extra)
        return conditions

    def restore(self, s):
        # 出し方は本文（? があれば一部だけ見せた問題）から見分ける
        if stat_holes.HOLE in (s.qm.content or ""):
            s.mode = MIN_MODE
            return
        # 取得し直したEmbedの画像はCDNのURLになっている。そのまま編集すると
        # グラフが埋め込みから外れて外に出るので、添付への参照に戻す
        s.quizEmbed.set_image(url="attachment://image.png")

    async def read_question(self, s):
        if self.is_min(s):
            s.examText = s.qm.content
            return True
        s.examText = s.qm.content.split(" ")[0]
        return True

    def matching(self, s) -> list:
        if self.is_min(s):
            shown = stat_holes.parse_shown(s.examText)
            return [p for p in get_pokedex().records
                    if stat_holes.matches(p.stats, shown)]
        stats = tuple(map(int, s.examText.split("-")))
        return [p for p in get_pokedex().records if p.stats == stats]

    def answers(self, s):
        aDatas = self.matching(s)
        return [p.name for p in aDatas], aDatas[0]

    def answer_id(self, s):
        """同じ種族値（見せた欄が同じ）のポケモンはみな正解。IDも全部並べる。"""
        if self.is_min(s):
            return "|".join(pokemon_id(p) for p in self.matching(s))
        return "|".join(
            pokemon_id(p) for p in get_pokedex().records
            if p.stats == s.ansZero.stats)

    def reveal(self, s):
        s.quizEmbed.description = f'こたえ: {",".join(s.ansList)}'
        if self.is_min(s):
            s.quizEmbed.description += f"\n{stat_holes.full_text(s.ansZero.stats)}"

    def log_question(self, s, exAns):
        if self.is_min(s):
            # 見せた欄は毎回変わるので、ポケモンごとに集計できるよう種族値で残す
            return stats_key(s.ansZero.stats), exAns
        return s.examText, exAns
