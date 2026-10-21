# -*- coding: utf-8 -*-
# trainer_quiz.py
"""トレーナークイズの問題（トレーナーの手持ち）。

手持ちのポケモンの名前とレベルを見て、トレーナーの名前を当てる。
手持ちは pkdb（sleepy_pkdb の app_quiz_trainer）から、はじめて使うときに一度だけ読む。
pkdb が使えないときは resource/quiz_trainers.csv（Git に入れない控え。
tools/fetch_quiz_trainers.py で書き出す）を使い、それも無ければ出題しない。

出すのは役割のあるトレーナー（ジムリーダー・四天王・ライバル・悪の組織など）だけで、
名前があるだけの一般トレーナーは出さない。手持ちとレベルがまったく同じ対戦は1問にまとめ、
そのどのトレーナーで答えても正解。作品は問題文に出さず、開示で出す。
出題中の答えはメモリに持たず、クイズの投稿の問題文（手持ちの並び）から引き直す。
"""
import csv
from dataclasses import dataclass
import os
from pathlib import Path
import random

from . import pokedex
from .logging_setup import logger
from .normalize import format_text

TRAINER_PATH = Path("resource/quiz_trainers.csv")
CSV_COLUMNS = ("title_id", "title_name", "trainer_key", "role", "class_ja", "name_ja",
               "slot", "ndex_number", "form_id", "level", "note")

TRAINER_SQL = """
SELECT t.title_id, s.title_name, t.trainer_key, t.role, t.class_ja, t.name_ja,
       t.slot, t.ndex_number, t.form_id, t.level, t.note
FROM app_quiz_trainer t
JOIN title_solo s ON s.title_id = t.title_id
WHERE t.named AND t.role IS NOT NULL AND t.name_ja IS NOT NULL
ORDER BY t.title_id, t.trainer_key, t.slot, t.id
"""

# 同じ手持ちの名前がこれより多い対戦は出さない（ゲームのデータに残る仮の手持ち。
# 第4世代のバトル施設のボスがみな「コラッタ Lv.5」など）。2人までは、同じ手持ちで
# 組んで戦う2人（ムサシとコジロウなど）として出す。
MAX_NAMES = 2

# ヒントで見せる役割の言い方（データの役割の名前のままでは分かりにくいもの）
ROLE_LABELS = {"そのほかのネームド": "物語に出る人物"}


@dataclass(frozen=True, slots=True)
class Battle:
    """1つの対戦。"""

    title_id: str
    title_name: str
    name: str  # トレーナーの名前（日本語）
    role: str
    trainer_class: str
    party: tuple[tuple[str, str, int], ...]  # (図鑑番号, フォーム, レベル) を手持ちの順に


@dataclass(frozen=True, slots=True)
class Party:
    """1問。手持ちとレベルが同じ対戦をまとめたもの。"""

    question: str  # クイズの投稿に出す手持ちの並び
    battles: tuple[Battle, ...]

    def names(self) -> list[str]:
        """正解の名前（出てくる順）。"""
        return list(dict.fromkeys(battle.name for battle in self.battles))

    def titles_label(self) -> str:
        """この手持ちで戦う作品（開示で全部並べる）。"""
        ordered = sorted({(b.title_id, b.title_name) for b in self.battles})
        return "・".join(name for _id, name in ordered)

    def roles_label(self) -> str:
        return "・".join(dict.fromkeys(
            ROLE_LABELS.get(battle.role, battle.role) for battle in self.battles))

    def hint_value(self, index):
        """ヒントの値（QuizSession が「ヒント」で読む）。"""
        if index == "役割":
            return self.roles_label()
        if index == "作品":
            return self.titles_label()
        return None


def pokemon_label(dex: pokedex.Pokedex, ndex_number: str, form_id: str) -> str | None:
    """手持ちに出す名前（フォームの名前つき）。図鑑に居なければ None。"""
    species = str(int(ndex_number))
    for record in dex.variants(species):
        if record.form_id == form_id:
            return record.name
    base = dex.base(species)
    return base.name if base is not None else None


def party_text(dex: pokedex.Pokedex, party) -> str | None:
    lines = []
    for ndex_number, form_id, level in party:
        label = pokemon_label(dex, ndex_number, form_id)
        if label is None:
            return None
        lines.append(f"{label} Lv.{level}")
    return "\n".join(lines)


def _split_alternatives(rows):
    """1つの対戦で同じ枠に何匹も並ぶとき（御三家で変わるライバルなど）は、別の手持ちに分ける。

    rows は (枠, 図鑑番号, フォーム, レベル) を枠の順に並べたもの。
    """
    slots: dict[int, list] = {}
    for slot, ndex_number, form_id, level in rows:
        slots.setdefault(slot, []).append((ndex_number, form_id, level))
    counts = {len(mons) for mons in slots.values()}
    width = max(counts)
    if counts - {1, width}:
        return []  # 並び方が分からない
    return [tuple(mons[i] if len(mons) > 1 else mons[0] for _slot, mons in sorted(slots.items()))
            for i in range(width)]


class TrainerCatalog:
    def __init__(self, rows, dex: pokedex.Pokedex):
        """rows は CSV_COLUMNS の並びのタプル。"""
        grouped: dict[tuple[str, str], dict] = {}
        for title_id, title_name, key, role, trainer_class, name, slot, ndex_number, \
                form_id, level, note in rows:
            if not name or not role or not ndex_number:
                continue
            battle = grouped.setdefault((str(title_id), str(key)), {
                "title_id": str(title_id), "title_name": str(title_name), "name": str(name),
                "role": str(role), "class": str(trainer_class or ""), "rows": [], "skip": False,
            })
            if level in (None, "") or "pool=yes" in str(note or ""):
                battle["skip"] = True  # レベルが決まっていない・バトル施設の候補の一覧
                continue
            battle["rows"].append((int(slot), str(ndex_number).zfill(4),
                                   str(form_id or "00").zfill(2), int(level)))

        by_question: dict[str, list[Battle]] = {}
        for info in grouped.values():
            if info["skip"] or not info["rows"]:
                continue
            for party in _split_alternatives(info["rows"]):
                text = party_text(dex, party)
                if text is None:
                    continue
                by_question.setdefault(text, []).append(Battle(
                    info["title_id"], info["title_name"], info["name"], info["role"],
                    info["class"], party))
        self.by_question: dict[str, Party] = {}
        for text, battles in by_question.items():
            party = Party(text, tuple(battles))
            if len(party.names()) <= MAX_NAMES:
                self.by_question[text] = party
        self.questions = list(self.by_question)
        self.names = {format_text(name) for party in self.by_question.values()
                      for name in party.names()}

    def __len__(self) -> int:
        return len(self.by_question)

    def random(self) -> Party | None:
        if not self.questions:
            return None
        return self.by_question[random.choice(self.questions)]

    def find(self, question: str) -> Party | None:
        """クイズの投稿の問題文から、もとの手持ちを引く。"""
        return self.by_question.get(str(question or "").strip())

    def is_trainer(self, text: str) -> bool:
        """出題するトレーナーの名前か（チャンネルにそのまま書かれた回答を拾うため）。"""
        return format_text(str(text or "").strip()) in self.names


def rows_from_csv(path: str | Path) -> list[tuple]:
    with open(path, encoding="utf-8-sig", newline="") as file:
        return [tuple(row.get(column) for column in CSV_COLUMNS)
                for row in csv.DictReader(file)]


def rows_from_pkdb() -> list[tuple]:
    import psycopg  # 遅延import（CSVだけで動かすときは不要）

    with psycopg.connect(
        host=os.environ.get("PKDB_HOST", pokedex.DEFAULT_PKDB_HOST),
        port=int(os.environ.get("PKDB_PORT", pokedex.DEFAULT_PKDB_PORT)),
        dbname=os.environ.get("PKDB_DB", pokedex.DEFAULT_PKDB_DB),
        user=os.environ.get("PKDB_USER", pokedex.DEFAULT_PKDB_USER),
        password=os.environ["PKDB_PASSWORD"],
        connect_timeout=10,
    ) as connection:
        return connection.execute(TRAINER_SQL).fetchall()


def load_catalog(csv_path: str | Path = TRAINER_PATH) -> TrainerCatalog:
    """pkdbがあればpkdbから、無ければCSVから読む。どちらも無ければ空。"""
    dex = pokedex.get_pokedex()
    if os.environ.get("PKDB_PASSWORD"):
        try:
            catalog = TrainerCatalog(rows_from_pkdb(), dex)
            logger.info(f"pkdbからトレーナーの手持ちを読み込みました: {len(catalog)}問")
            return catalog
        except Exception as error:
            logger.error(
                f"pkdbからトレーナーの手持ちを読み込めませんでした。CSVを使います\n{error}")
    if not Path(csv_path).exists():
        logger.warning(f"トレーナーの手持ちのCSVがありません: {csv_path}")
        return TrainerCatalog([], dex)
    catalog = TrainerCatalog(rows_from_csv(csv_path), dex)
    logger.info(f"CSVからトレーナーの手持ちを読み込みました: {len(catalog)}問")
    return catalog


_CATALOG: TrainerCatalog | None = None


def get_catalog() -> TrainerCatalog:
    """読み込み済みの手持ち。無ければその場で読む（空だったら次も読み直す）。"""
    global _CATALOG
    if _CATALOG is None:
        catalog = load_catalog()
        if not len(catalog):
            return catalog
        _CATALOG = catalog
    return _CATALOG


def loaded_catalog() -> TrainerCatalog | None:
    """読み込み済みなら手持ち。まだなら None（読みに行かない）。"""
    return _CATALOG


def set_catalog(catalog: TrainerCatalog | None) -> None:
    """テストや再読み込みのために差し替える。"""
    global _CATALOG
    _CATALOG = catalog
