# -*- coding: utf-8 -*-
# quiz_kinds/bq.py
"""種族値クイズ（bq）: 種族値のグラフからポケモンを当てる。"""
import discord

from bot_module import func as ub
from bot_module.pokedex import get_pokedex

from .base import NO_POKEMON, Draft, NameAnswerKind, pokemon_id


class StatsQuiz(NameAnswerKind):

    async def build(self, s, embed, channel, voice_channel):
        qDatas = get_pokedex().random(s.state.bq_filter_dict)
        if qDatas is None:
            # 条件に合うポケモンがいない場合は、空のクイズを投稿せずに終わる
            await channel.send(NO_POKEMON)
            return None
        embed.title = "種族値クイズ"
        embed.description = "こたえ: ???"  # 正答後: こたえ: [ポケモン名](複数いる場合),[ポケモン名]
        file = discord.File(
            ub.generate_graph(list(qDatas.stats)), filename="image.png"
        )
        embed.set_image(url="attachment://image.png")  # 種族値クイズ図形の添付
        embed.set_thumbnail(url=self.image_link())  # 正解までDecamark(?)を表示
        content = ub.bss_to_text(qDatas)
        return Draft(content=content, file=file,
                     record=self.pokemon_record(qDatas, content.split(" ")[0]))

    def conditions(self, s, draft):
        return {"絞り込み": s.state.bq_filter_dict}

    def restore(self, s):
        # 取得し直したEmbedの画像はCDNのURLになっている。そのまま編集すると
        # グラフが埋め込みから外れて外に出るので、添付への参照に戻す
        s.quizEmbed.set_image(url="attachment://image.png")

    async def read_question(self, s):
        s.examText = s.qm.content.split(" ")[0]
        return True

    def answers(self, s):
        stats = tuple(map(int, s.examText.split("-")))
        aDatas = [p for p in get_pokedex().records if p.stats == stats]
        return [p.name for p in aDatas], aDatas[0]

    def answer_id(self, s):
        """同じ種族値のポケモンはみな正解。IDも全部並べる。"""
        return "|".join(
            pokemon_id(p) for p in get_pokedex().records
            if p.stats == s.ansZero.stats)

    def reveal(self, s):
        s.quizEmbed.description = f'こたえ: {",".join(s.ansList)}'
