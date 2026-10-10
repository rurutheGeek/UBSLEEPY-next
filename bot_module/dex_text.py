# -*- coding: utf-8 -*-
# dex_text.py
"""図鑑説明クイズの問題（図鑑の説明文）。

説明文は pkdb（sleepy_pkdb の pokemon_pokedex_text）から、はじめて使うときに
一度だけ読む。pkdb が使えないときは resource/pokedex_text.csv（Git に入れない
控え。tools/fetch_dex_texts.py で書き出す）を使い、それも無ければ出題しない。

当てるのはポケモン名。フォーム（メガシンカ・リージョンフォームなど）の説明は、
そのフォームの名前で答える。同じ種族の別のフォームや、進化の前後を答えたら
「おしい」と返す（進化のつながりは pkdb の pokemon_evolution。控えは
resource/pokedex_evolution.csv）。
説明文に出てくるポケモンの名前は、答えに限らずみな伏せ字にする（進化前の名前
でも答えが分かるため）。出題中の答えはメモリに持たず、クイズの投稿の問題文から
引き直す（伏せ字にした文が同じになる種族は、みな正解）。
"""
import csv
from dataclasses import dataclass
import os
from pathlib import Path
import random
import re

from . import pokedex
from .logging_setup import logger

DEX_TEXT_PATH = Path("resource/pokedex_text.csv")
CSV_COLUMNS = ("ndex_number", "form_id", "title", "text")
EVOLUTION_PATH = Path("resource/pokedex_evolution.csv")
EVOLUTION_COLUMNS = ("before_ndex_number", "after_ndex_number")

DEX_TEXT_SQL = """
SELECT t.ndex_number, t.form_id, s.title_name, t.text
FROM pokemon_pokedex_text t
JOIN title_solo s ON s.title_id = t.title_id
ORDER BY t.ndex_number, t.form_id, t.title_id
"""

EVOLUTION_SQL = """
SELECT DISTINCT before_ndex_number, after_ndex_number FROM pokemon_evolution
ORDER BY 1, 2
"""

# 伏せ字。長さで答えが絞れないよう、名前の長さによらず4つ。
# Discord が太字の記号として読まないよう、エスケープして出す。
MASK = "\\*" * 4


@dataclass(frozen=True, slots=True)
class DexText:
    """説明文1つ。同じ種族の同じ文は、作品とフォームをまとめて1つにする。"""

    species: str  # 図鑑番号（先頭の0なし。Pokemon.species と同じ）
    text: str
    titles: tuple[str, ...]
    question: str  # 答えの名前を伏せた文（クイズの投稿に出す）
    # この文が載っているフォーム。図鑑に居ないフォーム（模様ちがいなど）は基本の姿 "00"
    forms: tuple[str, ...] = ("00",)

    def titles_label(self) -> str:
        """この文が載っている作品（開示で全部並べる）。"""
        return "・".join(self.titles)


def name_pattern(names) -> re.Pattern | None:
    """ポケモンの名前のどれかに当たる正規表現。名前が無ければ None。

    名前のフォームのかっこ書き（CSVの図鑑では種族名に付いている）は外す。
    長い名前から当てる（レアコイルを「レア****」にしない）。
    ニドラン♀・♂は性別ごと伏せる。
    """
    cores = {re.sub(r"[(（].*$", "", str(name)).rstrip("♀♂").strip()
             for name in names}
    cores.discard("")
    if not cores:
        return None
    ordered = sorted(cores, key=lambda core: (-len(core), core))
    return re.compile("(?:" + "|".join(map(re.escape, ordered)) + ")[♀♂]?")


def mask_names(text: str, pattern: re.Pattern | None) -> str:
    """説明文に出てくるポケモンの名前を伏せる。"""
    if pattern is None:
        return text
    return pattern.sub(lambda _: MASK, text)


class DexTextCatalog:
    def __init__(self, rows, dex: pokedex.Pokedex, evolutions=()):
        """rows は (図鑑番号, フォーム, 作品名, 説明文) の並び。図鑑に居ない種族は捨てる。

        evolutions は (進化前の図鑑番号, 進化後の図鑑番号) の並び。
        """
        titles: dict[tuple[str, str], list[str]] = {}
        forms: dict[tuple[str, str], list[str]] = {}
        for ndex_number, form_id, title, text in rows:
            text = str(text or "").strip()
            if not text:
                continue
            species = str(int(ndex_number))
            found = titles.setdefault((species, text), [])
            if title and title not in found:
                found.append(title)
            known = {record.form_id for record in dex.variants(species)}
            form = str(form_id) if str(form_id) in known else "00"
            if form not in forms.setdefault((species, text), []):
                forms[(species, text)].append(form)

        # 進化でつながる種族をひとまとまりにする（種族 -> 同じまとまりの種族）
        self.families: dict[str, set[str]] = {}
        for before, after in evolutions:
            before, after = str(int(before)), str(int(after))
            family = (self.families.get(before, {before})
                      | self.families.get(after, {after}))
            for member in family:
                self.families[member] = family

        pattern = name_pattern(
            record.species_name for record in dex.records)
        self.by_species: dict[str, list[DexText]] = {}
        self.by_question: dict[str, list[DexText]] = {}
        for (species, text), names in titles.items():
            base = dex.base(species)
            if base is None:
                continue
            entry = DexText(species, text, tuple(names),
                            mask_names(text, pattern),
                            tuple(sorted(forms[(species, text)])))
            self.by_species.setdefault(species, []).append(entry)
            self.by_question.setdefault(entry.question, []).append(entry)

    def __len__(self) -> int:
        return sum(len(entries) for entries in self.by_species.values())

    def random(self) -> DexText | None:
        """種族を選んでから文を選ぶ（説明文の多い古いポケモンに偏らせない）。"""
        if not self.by_species:
            return None
        return random.choice(self.by_species[random.choice(list(self.by_species))])

    def find(self, question: str) -> list[DexText]:
        """クイズの投稿の問題文から、もとの説明文を引く。種族ごとに1つ。"""
        entries, seen = [], set()
        for entry in self.by_question.get(str(question or "").strip(), []):
            if entry.species not in seen:
                seen.add(entry.species)
                entries.append(entry)
        return entries


    def related(self, species: str, other: str) -> bool:
        """進化の前後（同じ進化のまとまり）か。"""
        return str(other) in self.families.get(str(species), ())


def rows_from_csv(path: str | Path, columns=CSV_COLUMNS) -> list[tuple]:
    with open(path, encoding="utf-8-sig", newline="") as file:
        return [tuple(row[column] for column in columns)
                for row in csv.DictReader(file)]


def rows_from_pkdb() -> tuple[list[tuple], list[tuple]]:
    """(説明文の行, 進化の行)。"""
    import psycopg  # 遅延import（CSVだけで動かすときは不要）

    with psycopg.connect(
        host=os.environ.get("PKDB_HOST", pokedex.DEFAULT_PKDB_HOST),
        port=int(os.environ.get("PKDB_PORT", pokedex.DEFAULT_PKDB_PORT)),
        dbname=os.environ.get("PKDB_DB", pokedex.DEFAULT_PKDB_DB),
        user=os.environ.get("PKDB_USER", pokedex.DEFAULT_PKDB_USER),
        password=os.environ["PKDB_PASSWORD"],
        connect_timeout=10,
    ) as connection:
        return (connection.execute(DEX_TEXT_SQL).fetchall(),
                connection.execute(EVOLUTION_SQL).fetchall())


def load_catalog(csv_path: str | Path = DEX_TEXT_PATH,
                 evolution_path: str | Path = EVOLUTION_PATH) -> DexTextCatalog:
    """pkdbがあればpkdbから、無ければCSVから読む。どちらも無ければ空。"""
    dex = pokedex.get_pokedex()
    if os.environ.get("PKDB_PASSWORD"):
        try:
            rows, evolutions = rows_from_pkdb()
            catalog = DexTextCatalog(rows, dex, evolutions)
            logger.info(f"pkdbから図鑑説明を読み込みました: {len(catalog)}件")
            return catalog
        except Exception as error:
            logger.error(
                f"pkdbから図鑑説明を読み込めませんでした。CSVを使います\n{error}")
    if not Path(csv_path).exists():
        logger.warning(f"図鑑説明のCSVがありません: {csv_path}")
        return DexTextCatalog([], dex)
    evolutions = (rows_from_csv(evolution_path, EVOLUTION_COLUMNS)
                  if Path(evolution_path).exists() else [])
    catalog = DexTextCatalog(rows_from_csv(csv_path), dex, evolutions)
    logger.info(f"CSVから図鑑説明を読み込みました: {len(catalog)}件")
    return catalog


_CATALOG: DexTextCatalog | None = None


def get_catalog() -> DexTextCatalog:
    """読み込み済みの説明文。無ければその場で読む（空だったら次も読み直す）。"""
    global _CATALOG
    if _CATALOG is None:
        catalog = load_catalog()
        if not len(catalog):
            return catalog
        _CATALOG = catalog
    return _CATALOG


def set_catalog(catalog: DexTextCatalog | None) -> None:
    """テストや再読み込みのために差し替える。"""
    global _CATALOG
    _CATALOG = catalog
