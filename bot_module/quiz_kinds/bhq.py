# -*- coding: utf-8 -*-
# quiz_kinds/bhq.py
"""種族値クイズの穴埋め（bhq）: 穴のあいた種族値の穴に数字を入れて、いるポケモンの種族値にする。

- 本文は「H108 A130 B? C80 D? S102」の形。ポケモンの名前は出さない。出題のもとにした
  ポケモンはあるが、答えはそれに限らない（穴が多いと当てはまるポケモンは何匹もいる）。
- 穴は1枚ずつ（まとめてでもよい）答える。答えた値が、いま見えている欄（埋まった穴を含む）に
  合うポケモンのどれかの値なら正解で、本文のその穴を埋める（太字）。1枚ごとに正答・誤答を数える。
- まとめて答えたときは、穴の順に1枚ずつ判定する（先に埋めた値で当てはまるポケモンが絞られる）。
- 穴がみな埋まったら、当てはまるポケモンを答えとして開示する。
- 答え方は「b95」「ぼうぎょ95」、残りの穴が1つなら数字だけでもよい。
- 穴の数（1〜3）・穴の位置（既定は目立つ値＝一番高い値・すばやさ・ほかのポケモンが持っていない値を
  穴にしない。RANDOM_MODE ではどこでも）は
  /q の出題形式パネルで選ぶ。穴の位置はタイトルから、穴の数は本文から見分ける。
"""
import discord

from bot_module import func as ub
from bot_module import stat_holes
from bot_module.pokedex import get_pokedex

from .base import LOST_ANSWER, NO_POKEMON, Draft, PokemonKind, pokemon_id
from .bq import all_stats

RANDOM_MODE = "穴の位置ランダム"
DEFAULT_HOLES = 1
TITLE = "むしくい種族値クイズ"
RANDOM_TITLE = "（穴はどこでも）"  # 穴の位置がどこでもの問題（タイトルから見分ける）
REVEAL_LIMIT = 5  # 開示で種族値まで並べるポケモンの数
HINT_WORDS = ["ヒント", "合計", "ゴウケイ"]


def hole_names(holes) -> str:
    return "・".join(stat_holes.LABELS[index] for index in holes)


def graph_file(stats, holes=()):
    """種族値グラフ。穴の欄は板で隠す（ub.generate_graph の holes）。"""
    return discord.File(ub.generate_graph(list(stats), holes=holes), filename="image.png")


def candidates(shown) -> list:
    """見えている欄が一致するポケモン。"""
    return [p for p in get_pokedex().records if stat_holes.matches(p.stats, shown)]


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
        embed.title = TITLE + (RANDOM_TITLE if self.is_random(s) else "")
        embed.description = (
            "穴に数字を入れて、いるポケモンの種族値にしてね\n"
            f"答え方: `{self.example(holes)}`（1つずつでも、まとめてでもOK）")
        embed.set_thumbnail(url=self.image_link())  # 正解まで (?) マーク
        embed.set_image(url="attachment://image.png")
        content = stat_holes.show(qDatas.stats, holes)
        return Draft(content=content, file=graph_file(qDatas.stats, holes),
                     record=self.pokemon_record(qDatas, content),
                     extra={"holes": holes})

    @staticmethod
    def example(holes) -> str:
        # 数字は決まった値（本物に寄せると答えの見当がつく）
        return "".join(f"{stat_holes.LABELS[i].lower()}100" for i in holes)

    def conditions(self, s, draft):
        return {
            "絞り込み": s.state.bq_filter_dict,
            "出し方": "穴埋め",
            "穴の数": len(draft.extra["holes"]),
            "穴の位置": "どこでも" if self.is_random(s) else "目立つ値は見せる",
            "穴": hole_names(draft.extra["holes"]),
        }

    def restore(self, s):
        # 取得し直したEmbedの画像はCDNのURLになっている。添付への参照に戻す（bq と同じ）
        s.quizEmbed.set_image(url="attachment://image.png")
        title = s.quizEmbed.title or ""
        s.mode = RANDOM_MODE if RANDOM_TITLE in title else None
        content = s.qm.content or ""
        shown = stat_holes.parse_shown(content) or ()
        holes = sum(value is None for value in shown) + len(stat_holes.parse_filled(content))
        s.holes = holes or DEFAULT_HOLES

    def hint_words(self, s):
        return HINT_WORDS

    async def read_question(self, s):
        shown = stat_holes.parse_shown(s.qm.content)
        if shown is None or not candidates(shown):
            await s.rm.reply(LOST_ANSWER)
            return False
        s.examText = s.qm.content
        s.shownStats = shown
        s.filledSlots = stat_holes.parse_filled(s.qm.content)
        return True

    def answers(self, s):
        found = candidates(s.shownStats)
        return [p.name for p in found], found[0]

    def answer_id(self, s):
        return "|".join(pokemon_id(p) for p in candidates(s.shownStats))

    def remaining(self, s) -> list:
        return [i for i, value in enumerate(s.shownStats) if value is None]

    async def refresh(self, s) -> bool:
        """ほかの人が先に穴を埋めたかもしれないので、投稿を読み直す。終わっていれば False。"""
        try:
            latest = await s.qm.channel.fetch_message(s.qm.id)
        except (discord.HTTPException, AttributeError):
            return True
        footer = latest.embeds[0].footer.text if latest.embeds else ""
        if "(done)" in (footer or ""):
            return False
        if latest.content != s.qm.content and stat_holes.parse_shown(latest.content):
            s.qm = latest
            s.shownStats = stat_holes.parse_shown(latest.content)
            s.filledSlots = stat_holes.parse_filled(latest.content)
            s.examText = latest.content
            s.ansList, s.ansZero = self.answers(s)
        return True

    async def judge(self, s):
        if not await self.refresh(s):
            return True  # ほかの回答で先に開示された
        holes = self.remaining(s)
        values = stat_holes.parse_answer(s.rawText, holes)
        isMessage = isinstance(s.rm, discord.Message)
        if values is not None:
            values = {i: v for i, v in values.items() if i in holes}
        if not values:
            # 答えとして読めない・穴でない欄だけ（戦績に数えない）
            if isMessage:
                await s.rm.add_reaction("❓")
                await s.rm.reply(f"穴は {hole_names(holes)} だロ"
                                 f"（例: `{self.example(holes)}`）")
            await s.record(None, s.ansList[0])
            return True

        shown = list(s.shownStats)
        right, wrong = [], []
        for index in holes:  # 穴の順に1枚ずつ
            if index not in values:
                continue
            question = stat_holes.show(shown, ())
            trial = shown.copy()
            trial[index] = values[index]
            label = f"{stat_holes.LABELS[index]}{values[index]}"
            if candidates(trial):
                shown = trial
                right.append(index)
                await s.record("正答", label, question=question)
            else:
                wrong.append(index)
                await s.record("誤答", label, question=question)

        if isMessage:
            await s.rm.add_reaction("⭕" if right else "❌")
            if right and wrong:
                await s.rm.add_reaction("❌")
        if right and wrong and isMessage:
            await s.rm.reply(f"{hole_names(right)} は 合ってるロ。"
                             f"{hole_names(wrong)} は ちがうロ")
        if not right:
            return True

        s.shownStats = tuple(shown)
        s.filledSlots = s.filledSlots | set(right)
        content = stat_holes.show(shown, (), filled=s.filledSlots)
        s.examText = content
        found = candidates(shown)
        s.ansList, s.ansZero = [p.name for p in found], found[0]
        if None in shown:
            # 埋めた穴を見せる。グラフも、残った穴だけ隠したものに差し替える
            holes = [i for i, value in enumerate(shown) if value is None]
            await s.qm.edit(content=content, embed=s.quizEmbed,
                            attachments=[graph_file(shown, holes)])
            return True
        await s.qm.edit(content=content)
        await s.disclose(True, found[0].name)
        return True

    def giveup_answer(self, s):
        found = candidates(s.shownStats)
        names = "・".join(p.name for p in found[:5]) + ("など" if len(found) > 5 else "")
        return f"{names}（{stat_holes.full_text(found[0].stats)}）"

    async def hint_index(self, s):
        totals = sorted({sum(p.stats) for p in candidates(s.shownStats)})
        s.hintGiven = "合計"
        if len(totals) == 1:
            await s.rm.reply(f"合計は{totals[0]}だロ")
        else:
            shown = "・".join(map(str, totals[:5])) + ("など" if len(totals) > 5 else "")
            await s.rm.reply(f"合計は {shown} の どれかだロ")
        return None

    def reveal(self, s):
        found = candidates(s.shownStats)
        # 同じ種族値は1行にまとめ、種族値ごとに並べる（穴が残っていると何通りもある）
        rows = {}
        for pokemon in found:
            rows.setdefault(pokemon.stats, []).append(pokemon.name)
        lines = [f"{','.join(names)}　{stat_holes.full_text(stats)}"
                 for stats, names in list(rows.items())[:REVEAL_LIMIT]]
        if len(rows) > REVEAL_LIMIT:
            lines.append(f"ほか {len(rows) - REVEAL_LIMIT}通り")
        s.quizEmbed.description = "こたえ:\n" + "\n".join(lines)
        s.quizEmbed.set_thumbnail(url=self.image_link(found[0].name))

    def reveal_files(self, s):
        # 隠さないグラフにする（穴が残っていれば、当てはまるポケモンの1匹目）
        return [graph_file(candidates(s.shownStats)[0].stats)]

    def log_question(self, s, exAns):
        return s.examText, exAns

