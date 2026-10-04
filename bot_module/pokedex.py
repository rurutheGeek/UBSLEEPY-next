# -*- coding: utf-8 -*-
# pokedex.py
"""図鑑データのカタログ。

CSVをpandasのDataFrameのまま持ち回すのをやめ、1匹1レコードの
`Pokemon` に読み替えてメモリに置く。起動時にpkdb（PostgreSQL）から
一度だけ読み込み、コマンドごとのDBアクセスはしない。

PKDB_PASSWORD が無いときは resource/pokemon_database.csv を使う。
pkdbへの接続に失敗したときもCSVへ落として起動を守る。
"""
from __future__ import annotations

import os
import random
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .logging_setup import logger
from .normalize import format_text
from .settings import get_settings

# pkdb（apps-01）。読み取り専用ロールを使う。
DEFAULT_PKDB_HOST = "pkdb.apextox.dpdns.org"
DEFAULT_PKDB_PORT = 5432
DEFAULT_PKDB_DB = "sleepy_pkdb"
DEFAULT_PKDB_USER = "pkdb_reader"

# 図鑑1匹ぶんの値。最新の種族値・タイプ・特性に、名前と初登場の情報を付ける。
POKEDEX_SQL = """
SELECT q.ndex_number, q.form_id, q.name, q.form_name, q.official_name,
       q.name_alias, l.eng, l.cht,
       q.type_1, q.type_2,
       s.ability_1, s.ability_2, s.ability_h,
       s.basestats_h, s.basestats_a, s.basestats_b,
       s.basestats_c, s.basestats_d, s.basestats_s,
       t.title_name, t.generation, q.region, q.evolution_stage
FROM mv_quiz_status q
JOIN mv_latest_pokemon_status s
  ON s.ndex_number = q.ndex_number AND s.form_id = q.form_id
LEFT JOIN pokemon_name_lang l
  ON l.ndex_number = q.ndex_number AND l.form_id = q.form_id
LEFT JOIN (
    SELECT ndex_number, form_id, min(title_group_id) AS title_group_id
    FROM pokemon_status
    GROUP BY ndex_number, form_id
) f ON f.ndex_number = q.ndex_number AND f.form_id = q.form_id
LEFT JOIN title_group t ON t.title_group_id = f.title_group_id
ORDER BY q.ndex_number, q.form_id
"""

STAT_FIELDS = {
    "HP": "hp",
    "こうげき": "atk",
    "ぼうぎょ": "dfn",
    "とくこう": "spa",
    "とくぼう": "spd",
    "すばやさ": "spe",
}

FILTER_FIELDS = {
    "出身地": "region",
    "進化段階": "evolution_stage",
    "初登場世代": "generation",
}

EVOLUTION_STAGES = ("進化前", "中間進化", "最終進化", "進化しない")

# pkdbの進化段階は「無進化」。アプリの表示・フィルタはCSV時代の「進化しない」に合わせる。
EVOLUTION_STAGE_ALIASES = {"無進化": "進化しない"}

HINT_FIELDS = {
    "タイプ1": "type_1",
    "タイプ2": "type_2",
    "特性1": "ability_1",
    "特性2": "ability_2",
    "隠れ特性": "ability_h",
    "出身地": "region",
    "分類": "category",
    "初登場作品": "first_title",
    "英語名由来": "etymology",
}


def _empty_to_none(value):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return value


def _int_or_none(value):
    value = _empty_to_none(value)
    if value is None:
        return None
    return int(value)


def _aliases(value) -> tuple[str, ...]:
    value = _empty_to_none(value)
    if value is None:
        return ()
    return tuple(part.strip() for part in str(value).split(",") if part.strip())


@dataclass(frozen=True, slots=True)
class Pokemon:
    """図鑑の1匹。図鑑番号＋フォームで一意。"""

    ndex_number: str
    form_id: str
    species: str
    name: str
    species_name: str
    form_name: str | None
    aliases: tuple[str, ...]
    type_1: str | None
    type_2: str | None
    ability_1: str | None
    ability_2: str | None
    ability_h: str | None
    hp: int
    atk: int
    dfn: int
    spa: int
    spd: int
    spe: int
    region: str | None
    evolution_stage: str | None
    first_title: str | None
    generation: int | None
    eng: str | None
    cht: str | None
    display_number: str
    category: str | None = None
    etymology: str | None = None

    @property
    def stats(self) -> tuple[int, int, int, int, int, int]:
        return (self.hp, self.atk, self.dfn, self.spa, self.spd, self.spe)

    @property
    def total(self) -> int:
        return sum(self.stats)

    @property
    def types(self) -> tuple[str, ...]:
        return tuple(t for t in (self.type_1, self.type_2) if t)

    @property
    def abilities(self) -> tuple[str, ...]:
        return tuple(a for a in (self.ability_1, self.ability_2, self.ability_h) if a)

    @property
    def image_number(self) -> str:
        """外部画像（art/{number}.png）の番号。CSV時代のフォーム採番に合わせる。"""
        return self.display_number

    def stat(self, key: str) -> int | None:
        if key == "合計":
            return self.total
        attribute = STAT_FIELDS.get(key)
        return getattr(self, attribute) if attribute else None

    def hint_value(self, hint: str):
        """ヒント名に対応する値。未収載（分類・英語名由来など）はNone。"""
        if hint == "文字数":
            return len(self.eng) if self.eng else None
        if hint == "イニシャル":
            return self.eng[0:1] if self.eng else None
        attribute = HINT_FIELDS.get(hint)
        if attribute is None:
            return None
        value = getattr(self, attribute)
        if value is None or value == "":
            return None
        return value


def _display_name(name, form_name, official_name, form_id) -> str:
    """表示用の名前。

    DBの official_name は、同じ種族値のフォーム（ポワルンなど）では種族名だけに
    なる。図鑑のフォーム選択で見分けられるよう、基本の姿は種族名、それ以外は
    official_name、それも種族名と同じなら「種族名（フォーム名）」にする。
    """
    if form_id == "00":
        return name
    if official_name and official_name != name:
        return official_name
    if form_name:
        return f"{name}（{form_name}）"
    return name


def records_from_rows(rows) -> list[Pokemon]:
    """pkdbの行（タプル）をPokemonの並びへ。フォーム番号はform_id順の連番。"""
    records = []
    counts: dict[str, int] = defaultdict(int)
    for row in sorted(rows, key=lambda r: (str(r[0]), str(r[1]))):
        (
            ndex_number, form_id, name, form_name, official_name, name_alias,
            eng, cht, type_1, type_2, ability_1, ability_2, ability_h,
            hp, atk, dfn, spa, spd, spe, title_name, generation, region,
            evolution_stage,
        ) = row
        species = str(int(ndex_number))
        if form_id == "00":
            ordinal = 0
        else:
            counts[species] += 1
            ordinal = counts[species]
        display_number = species if ordinal == 0 else f"{species}.{ordinal}"
        stage = _empty_to_none(evolution_stage)
        stage = EVOLUTION_STAGE_ALIASES.get(stage, stage)
        records.append(
            Pokemon(
                ndex_number=str(ndex_number),
                form_id=str(form_id),
                species=species,
                name=_display_name(name, form_name, official_name, form_id),
                species_name=str(name),
                form_name=_empty_to_none(form_name),
                aliases=_aliases(name_alias),
                type_1=_empty_to_none(type_1),
                type_2=_empty_to_none(type_2),
                ability_1=_empty_to_none(ability_1),
                ability_2=_empty_to_none(ability_2),
                ability_h=_empty_to_none(ability_h),
                hp=int(hp),
                atk=int(atk),
                dfn=int(dfn),
                spa=int(spa),
                spd=int(spd),
                spe=int(spe),
                region=_empty_to_none(region),
                evolution_stage=stage,
                first_title=_empty_to_none(title_name),
                generation=_int_or_none(generation),
                eng=_empty_to_none(eng),
                cht=_empty_to_none(cht),
                display_number=display_number,
            )
        )
    return records


def _csv_number(value) -> tuple[str, int]:
    """CSVの「ぜんこくずかんナンバー」（25.0 / 3.1）を種族番号とフォーム連番へ。"""
    number = float(value)
    species = int(number)
    ordinal = int(round((number - species) * 10))
    return str(species), ordinal


def records_from_csv(path: str | Path) -> list[Pokemon]:
    """CSVからPokemonの並びを作る（pkdbが使えないときのフォールバック）。"""
    frame = pd.read_csv(path)
    records = []
    for row in frame.to_dict("records"):
        species, ordinal = _csv_number(row["ぜんこくずかんナンバー"])
        display_number = species if ordinal == 0 else f"{species}.{ordinal}"
        aliases = tuple(
            str(row[column])
            for column in ("インデックス1", "インデックス2", "インデックス3")
            if _empty_to_none(row[column]) is not None
        )
        records.append(
            Pokemon(
                ndex_number=f"{int(species):04d}",
                form_id="00" if ordinal == 0 else f"{ordinal:02d}",
                species=species,
                name=str(row["おなまえ"]),
                species_name=str(row["おなまえ"]),
                form_name=None,
                aliases=aliases,
                type_1=_empty_to_none(row["タイプ1"]),
                type_2=_empty_to_none(row["タイプ2"]),
                ability_1=_empty_to_none(row["特性1"]),
                ability_2=_empty_to_none(row["特性2"]),
                ability_h=_empty_to_none(row["隠れ特性"]),
                hp=int(row["HP"]),
                atk=int(row["こうげき"]),
                dfn=int(row["ぼうぎょ"]),
                spa=int(row["とくこう"]),
                spd=int(row["とくぼう"]),
                spe=int(row["すばやさ"]),
                region=_empty_to_none(row["出身地"]),
                evolution_stage=_empty_to_none(row["進化段階"]),
                first_title=_empty_to_none(row["初登場作品"]),
                generation=_int_or_none(row["初登場世代"]),
                eng=_empty_to_none(row["英語名"]),
                cht=_empty_to_none(row["中国語繁体"]),
                display_number=display_number,
                category=_empty_to_none(row["分類"]),
                etymology=_empty_to_none(row["英語名由来"]),
            )
        )
    return records


def records_from_pkdb() -> list[Pokemon]:
    """pkdbから全件読む。接続情報は環境変数から。"""
    import psycopg  # 遅延import（CSVだけで動かすときは不要）

    with psycopg.connect(
        host=os.environ.get("PKDB_HOST", DEFAULT_PKDB_HOST),
        port=int(os.environ.get("PKDB_PORT", DEFAULT_PKDB_PORT)),
        dbname=os.environ.get("PKDB_DB", DEFAULT_PKDB_DB),
        user=os.environ.get("PKDB_USER", DEFAULT_PKDB_USER),
        password=os.environ["PKDB_PASSWORD"],
        connect_timeout=10,
    ) as connection:
        rows = connection.execute(POKEDEX_SQL).fetchall()
    return records_from_rows(rows)


class Pokedex:
    """1,000件規模の図鑑カタログ。名前索引と種族ごとの索引を一度だけ作る。"""

    def __init__(self, records: list[Pokemon]):
        self.records = list(records)
        self.by_display_number: dict[str, Pokemon] = {}
        self.by_species: dict[str, list[Pokemon]] = {}
        self.name_index: dict[str, list[Pokemon]] = {}
        prefix_dict = get_settings().pokename_prefix_dict
        for record in self.records:
            self.by_display_number[record.display_number] = record
            self.by_species.setdefault(record.species, []).append(record)
            normalized_names = {
                self._normalize(text, prefix_dict)
                for text in (
                    record.name,
                    record.species_name,
                    record.form_name,
                    *record.aliases,
                )
                if text
            }
            for fixed in normalized_names:
                if fixed:
                    self.name_index.setdefault(fixed, []).append(record)

    @staticmethod
    def _normalize(text: str, prefix_dict: dict[str, str]) -> str:
        fixed = format_text(str(text))
        if (
            fixed
            and fixed[0] in prefix_dict
            and re.match(r"[ァ-ヺー]+", fixed[1:])
        ):
            fixed = prefix_dict[fixed[0]] + fixed[1:]
        return fixed

    def find(self, text: str) -> list[Pokemon]:
        """名前・別名から探す。同じ名前が複数ある場合はすべて返す。"""
        if not text:
            return []
        prefix_dict = get_settings().pokename_prefix_dict
        return list(self.name_index.get(self._normalize(text, prefix_dict), []))

    def variants(self, species: str) -> list[Pokemon]:
        return list(self.by_species.get(str(species), []))

    def base(self, species: str) -> Pokemon | None:
        variants = self.by_species.get(str(species))
        if not variants:
            return None
        for record in variants:
            if record.form_id == "00":
                return record
        return variants[0]

    def get(self, display_number: str) -> Pokemon | None:
        return self.by_display_number.get(str(display_number))

    def filter(self, filter_dict: dict) -> list[Pokemon]:
        """「タイプ」「特性」「出身地」などの条件で絞り込む。"""
        result = self.records
        for key, values in filter_dict.items():
            if not values:
                continue
            if key == "タイプ":
                result = [
                    p
                    for p in result
                    if p.type_1 in values or p.type_2 in values
                ]
            elif key == "特性":
                result = [
                    p
                    for p in result
                    if p.ability_1 in values
                    or p.ability_2 in values
                    or p.ability_h in values
                ]
            elif key in STAT_FIELDS or key == "合計":
                wanted = {int(value) for value in values}
                result = [p for p in result if p.stat(key) in wanted]
            elif key in FILTER_FIELDS:
                attribute = FILTER_FIELDS[key]
                if str(values[0]).isdecimal():
                    wanted = {int(value) for value in values}
                    result = [
                        p for p in result if getattr(p, attribute) in wanted
                    ]
                else:
                    result = [
                        p for p in result if getattr(p, attribute) in values
                    ]
            else:
                logger.warning(f"不明な絞り込み条件です: {key}")
        return result

    def random(self, filter_dict: dict) -> Pokemon | None:
        candidates = self.filter(filter_dict)
        if not candidates:
            return None
        return random.choice(candidates)

    def evolution_stages(self) -> set[str]:
        return {p.evolution_stage for p in self.records if p.evolution_stage}

    def regions(self) -> set[str]:
        return {p.region for p in self.records if p.region}

    def types(self) -> set[str]:
        return {t for p in self.records for t in p.types}

    def abilities(self) -> set[str]:
        return {a for p in self.records for a in p.abilities}


_POKEDEX: Pokedex | None = None


def load_pokedex(csv_path: str | Path | None = None) -> Pokedex:
    """pkdbがあればpkdbから、無ければCSVからカタログを作る。"""
    csv_path = csv_path or get_settings().paths.pokedex
    if os.environ.get("PKDB_PASSWORD"):
        try:
            records = records_from_pkdb()
            logger.info(f"pkdbから図鑑を読み込みました: {len(records)}匹")
            return Pokedex(records)
        except Exception as error:
            logger.error(
                f"pkdbから図鑑を読み込めませんでした。CSVを使います\n{error}"
            )
    records = records_from_csv(csv_path)
    logger.info(f"CSVから図鑑を読み込みました: {len(records)}匹")
    return Pokedex(records)


def get_pokedex() -> Pokedex:
    """読み込み済みのカタログ。無ければその場で読む。"""
    global _POKEDEX
    if _POKEDEX is None:
        _POKEDEX = load_pokedex()
    return _POKEDEX


def set_pokedex(pokedex: Pokedex | None) -> None:
    """テストや再読み込みのために差し替える。"""
    global _POKEDEX
    _POKEDEX = pokedex


def reload_pokedex() -> Pokedex:
    global _POKEDEX
    _POKEDEX = load_pokedex()
    return _POKEDEX
