# -*- coding: utf-8 -*-
# intro.py
"""イントロクイズの曲リスト（作品・区分つき）。

音源は tools/build_intro_clips.py が曲の冒頭を切り出して resource/intro/ へ置く。
クイズはここをローカル参照だけする（Nextcloudへは取りに行かない）。
曲リストは resource/intro/manifest.csv（id,title,work,category,aliases）。
区分や別名は手で直してよい（作り直しても既存の行は保たれる）。

回答は曲名そのままでなくてよい。「作品の略称＋戦う相手」（例: BWシロナ）で答える。
相手が1作品にしか居なければ略称は要らない。そのための対応リスト（Gitで管理）:
- resource/intro_works.csv   作品名（一部）,略称（`|` 区切り）
- resource/intro_words.csv   言葉,言い換え（漢字のよみなど。回答と曲名の両方に当てる）
- resource/intro_aliases.csv 作品（略称。空は全作品）,相手,別名（`|` 区切り）
- resource/intro_secret.csv  作品（略称）,曲名,理由（ふだんは出題しない曲）
- resource/intro_appearances.csv 原曲の作品,相手,登場する作品,そこでの呼び名
  （再録・流用。音源は原曲だけだが、登場する作品の略称でも答えられ、絞り込みにも入る）

別名・登場作品・シークレットの3つは、pkdb（sleepy_pkdb の app_intro_* 表）に
あればそちらを使う。Botは定期的に読み直すので、表を直せば配備なしで反映される
（直し方は tools/intro_db.py）。pkdbが使えないときはCSVを使う。
"""
import csv
import os
from dataclasses import dataclass
from functools import cached_property, lru_cache
import hashlib
from pathlib import Path
import random
import re

from bot_module.logging_setup import logger
from bot_module.normalize import format_text

INTRO_DIRECTORY = Path("resource/intro")
WORKS_PATH = Path("resource/intro_works.csv")
WORDS_PATH = Path("resource/intro_words.csv")
ALIASES_PATH = Path("resource/intro_aliases.csv")
APPEARANCES_PATH = Path("resource/intro_appearances.csv")
SECRET_PATH = Path("resource/intro_secret.csv")
MANIFEST_NAME = "manifest.csv"
CLIP_DIRECTORY_NAME = "clips"
MANIFEST_FIELDS = ("id", "title", "work", "category", "aliases")

# 区分（出題の絞り込みに使う）
CATEGORY_BATTLE = "戦闘"
CATEGORY_FIELD = "フィールド"
CATEGORY_OTHER = "その他"
CATEGORIES = (CATEGORY_BATTLE, CATEGORY_FIELD, CATEGORY_OTHER)
# /introdata・/q の入力ゆれ -> 区分
CATEGORY_ALIASES = {
    "戦闘": CATEGORY_BATTLE, "せんとう": CATEGORY_BATTLE, "戦闘曲": CATEGORY_BATTLE,
    "バトル": CATEGORY_BATTLE, "ばとる": CATEGORY_BATTLE, "battle": CATEGORY_BATTLE,
    "フィールド": CATEGORY_FIELD, "ふぃーるど": CATEGORY_FIELD,
    "フィールド曲": CATEGORY_FIELD, "field": CATEGORY_FIELD,
    "その他": CATEGORY_OTHER, "そのた": CATEGORY_OTHER, "other": CATEGORY_OTHER,
}

# 添付ファイル名は intro-<nonce>-<ハッシュ>.ogg（鳴き声クイズと同じ考え方）。
# ハッシュに曲のidを混ぜるので、ファイル名からは曲が読めず、投稿から逆算できる。
INTRO_HASH_LENGTH = 12
INTRO_FILENAME_RE = re.compile(r"^intro-([0-9a-f]+)-([0-9a-f]+)\.ogg$")

# 曲名の照合で無視する記号・空白
_IGNORED = re.compile(r"[\s　!！?？・･:：~〜～\-‐－―ー_,，、.。'’\"”“()（）\[\]「」『』<>＜＞/／&＆+＋]")


def normalize_title(text: str) -> str:
    """曲名・作品名の表記ゆれ（かな・全半角・記号・空白）をならす。"""
    return _IGNORED.sub("", format_text(text or ""))


def _rows(path: Path) -> list:
    """対応リストのCSVを読む（#で始まる行と空行は飛ばす。無ければ空）。"""
    try:
        with open(path, encoding="utf-8-sig", newline="") as file:
            return [
                [cell.strip() for cell in row] for row in csv.reader(file)
                if row and row[0].strip() and not row[0].lstrip().startswith("#")]
    except OSError:
        return []


# pkdb から読んだ対応リスト（CSVと同じ行の形。名前 -> 行の並び）。None ならCSVを使う。
_database_lists = None

DATABASE_LISTS_SQL = (
    "SELECT work, title, in_work, alias FROM pokemondb.app_intro_alias"
    " ORDER BY work, title, in_work, alias",
    "SELECT work, title, appears_in FROM pokemondb.app_intro_appearance"
    " ORDER BY work, title, appears_in",
    "SELECT work, title, coalesce(reason, '') FROM pokemondb.app_intro_secret"
    " ORDER BY work, title",
)


def rows_from_database(aliases, appearances, secrets) -> dict:
    """pkdbの行を、CSVと同じ行の形にまとめる。

    app_intro_alias は1行に別名1つ。in_work が原曲の作品と同じなら別名、
    違えば「その作品で流れるときの呼び名」（登場作品の行に付く）。
    """
    own, reused = {}, {}
    for work, title, appears_in in appearances:
        reused.setdefault((work, title, appears_in), [])
    for work, title, in_work, alias in aliases:
        if canon(in_work) == canon(work):
            own.setdefault((work, title), []).append(alias)
        else:
            reused.setdefault((work, title, in_work), []).append(alias)
    return {
        "aliases": [[*key, "|".join(names)] for key, names in own.items()],
        "appearances": [[*key, "|".join(names)] for key, names in reused.items()],
        "secret": [list(row) for row in secrets],
    }


def fetch_database_lists():
    """pkdbから対応リストを読む。1行も無ければ None（CSVを使う）。"""
    import psycopg  # 遅延import（CSVだけで動かすときは不要）

    from bot_module import pokedex

    with psycopg.connect(
        host=os.environ.get("PKDB_HOST", pokedex.DEFAULT_PKDB_HOST),
        port=int(os.environ.get("PKDB_PORT", pokedex.DEFAULT_PKDB_PORT)),
        dbname=os.environ.get("PKDB_DB", pokedex.DEFAULT_PKDB_DB),
        user=os.environ.get("PKDB_USER", pokedex.DEFAULT_PKDB_USER),
        password=os.environ["PKDB_PASSWORD"],
        connect_timeout=10,
    ) as connection:
        tables = [connection.execute(sql).fetchall() for sql in DATABASE_LISTS_SQL]
    return rows_from_database(*tables) if any(tables) else None


def use_database_lists(lists) -> bool:
    """対応リストを差し替える（None でCSVへ戻す）。変わったら True。"""
    global _database_lists
    if lists == _database_lists:
        return False
    _database_lists = lists
    reset_answer_lists()
    return True


def refresh_from_database() -> bool:
    """pkdbの対応リストを読み直す。変わったら True。

    PKDB_PASSWORD が無ければ何もしない。読めなかったときは今のリストのまま続ける。
    """
    if not os.environ.get("PKDB_PASSWORD"):
        return False
    try:
        lists = fetch_database_lists()
    except Exception as error:
        logger.error(f"pkdbからイントロクイズの対応リストを読めませんでした\n{error}")
        return False
    return use_database_lists(lists)


def _list_rows(name: str, path: Path) -> list:
    """対応リストの行。pkdbから読めていればそれ、無ければCSV。"""
    if _database_lists is not None:
        return _database_lists[name]
    return _rows(path)


def _split(cell: str) -> list:
    return [part.strip() for part in (cell or "").split("|") if part.strip()]


@lru_cache(maxsize=None)
def _words() -> tuple:
    """言い換え（ならした言葉 -> ならした言い換え）。長い言葉から当てる。"""
    pairs = {}
    for row in _rows(WORDS_PATH):
        if len(row) >= 2 and normalize_title(row[0]) and normalize_title(row[1]):
            pairs[normalize_title(row[0])] = normalize_title(row[1])
    return tuple(sorted(pairs.items(), key=lambda pair: -len(pair[0])))


def canon(text: str) -> str:
    """照合用の形。表記ゆれをならし、言い換え（よみ）をそろえる。"""
    key = normalize_title(text)
    for word, alias in _words():
        key = key.replace(word, alias)
    return key


@lru_cache(maxsize=None)
def _work_rules() -> tuple:
    """(ならした作品名の一部, 略称のタプル) の並び。"""
    return tuple(
        (normalize_title(row[0]), tuple(_split(row[1])))
        for row in _rows(WORKS_PATH) if len(row) >= 2 and normalize_title(row[0]))


@lru_cache(maxsize=None)
def work_abbreviations(work: str) -> tuple:
    """作品の略称（対応リストに無ければ空）。"""
    name = normalize_title(work)
    found = []
    for part, abbreviations in _work_rules():
        if part in name:
            found += [a for a in abbreviations if a not in found]
    return tuple(found)


@lru_cache(maxsize=None)
def _alias_rules() -> tuple:
    """(作品の略称の照合形か空, 相手の照合形, 別名のタプル) の並び。"""
    return tuple(
        (canon(row[0]), canon(row[1]), tuple(_split(row[2])))
        for row in _list_rows("aliases", ALIASES_PATH) if len(row) >= 3 and canon(row[1]))


@lru_cache(maxsize=None)
def _appearance_rules() -> tuple:
    """(原曲の作品の略称, 相手, 登場する作品, 呼び名のタプル) の並び。"""
    return tuple(
        (canon(row[0]), canon(row[1]), row[2], tuple(_split((row + [""])[3])))
        for row in _list_rows("appearances", APPEARANCES_PATH)
        if len(row) >= 3 and canon(row[1]) and row[2])


@lru_cache(maxsize=None)
def _secret_rules() -> tuple:
    """シークレットの曲の (作品の略称, 曲名) の並び（どちらも照合形）。"""
    return tuple(
        (canon(row[0]), canon(row[1]))
        for row in _list_rows("secret", SECRET_PATH) if len(row) >= 2 and canon(row[1]))


@lru_cache(maxsize=None)
def work_key(work: str) -> str:
    """作品を見分けるキー。作品名でも略称でも同じ作品なら同じ値になる。"""
    name = normalize_title(work)
    for part, abbreviations in _work_rules():
        if part in name or name in map(normalize_title, abbreviations):
            return part
    return name


@lru_cache(maxsize=None)
def work_names(work: str) -> tuple:
    """作品を指す言い方（略称と、渡された名前）。作品名でも略称でも引ける。"""
    key = work_key(work)
    for part, abbreviations in _work_rules():
        if part == key:
            return (*abbreviations, work)
    return (work,)


def reset_answer_lists() -> None:
    """対応リストを読み直す（ファイルを差し替えたとき・テスト用）。"""
    for cached in (_words, _work_rules, work_abbreviations, _alias_rules,
                   _appearance_rules, _secret_rules, work_key, work_names):
        cached.cache_clear()
    _cache["key"] = None


_PAREN = re.compile(r"[（(]([^（()）]*)[)）]")
_VS = re.compile(r"[（(]\s*VS\.?\s*([^)）]+)[)）]", re.IGNORECASE)
_REMARK = re.compile(r"\s*-[^-]+-\s*$")
_SECOND = re.compile(r"\s*[〜～~].*$")
_HEAD = re.compile(r"^(?:(?:戦闘|決戦|戦い)\s*[！!：:]|battle!)\s*(.+)$", re.IGNORECASE)
# 同じ曲の別バージョンを表すかっこ書き（地方名などは別の曲として残す）
_NOT_A_PLACE = re.compile(r"^\d+$|ver|バージョン|original|交代", re.IGNORECASE)
# 言わなくてもその曲を指すかっこ書き（昼夜のある曲は、書かなければ昼＝朝の曲）
_DEFAULT_PLACES = ("昼",)
_GENERIC_HEADS = ("戦い", "戦闘", "勝利", "")
# 最終戦の曲（「決戦！N」「戦闘！チャンピオンネモ」「戦闘！本気のマスタード」）
_FINAL_HEAD = re.compile(r"^\s*決戦\s*[！!：:]")
_FINAL_PREFIX = re.compile(r"^(?:チャンピオン|本気の)(.{2,})$")


def answer_places(title: str) -> list:
    """曲名のかっこ書きのうち、別の曲として区別するもの（地方名など）。"""
    text = _REMARK.sub("", title)
    text = _SECOND.sub("", text) or text
    return [p.strip() for p in _PAREN.findall(_VS.sub("", text))
            if p.strip() and not _NOT_A_PLACE.search(p)]


def answer_cores(title: str) -> list:
    """曲名から「戦う相手」として答えられる言い方を取り出す。

    「戦闘！チャンピオン（Ver. 1.0）」→ チャンピオン、
    「戦い(VS野生ポケモン)」→ 野生ポケモン・野生、
    「戦闘！ゼクロム・レシラム」→ ゼクロム・レシラム・ゼクロム・レシラム（それぞれ）。
    型に合わない曲名は、かっこ書きを除いた曲名そのもの。
    """
    cores = []
    versus = _VS.search(title)
    text = _REMARK.sub("", title)
    text = _SECOND.sub("", text) or text
    places = [p.strip() for p in _PAREN.findall(_VS.sub("", text))
              if p.strip() and not _NOT_A_PLACE.search(p)]
    base = _PAREN.sub("", text).strip()
    if versus:
        opponent = versus.group(1).strip()
        head = _PAREN.sub("", title[:versus.start()]).strip()
        if head not in _GENERIC_HEADS:
            cores.append(head)  # 「ラストバトル(VSライバル)」のラストバトル
    else:
        match = _HEAD.match(base)
        opponent = match.group(1).strip() if match else base
    cores.insert(0, opponent)
    parts = [part.strip() for part in re.split(r"[・･／/]", opponent)]
    if len(parts) > 1:
        cores += [part for part in parts if len(part) >= 2]
    for core in list(cores):
        if core.endswith("ポケモン") and len(core) > 4:
            cores.append(core[:-4].rstrip("の"))  # 野生ポケモン -> 野生
    for core in list(cores):
        if "の" in core.strip("の"):
            cores.append(core.replace("の", ""))  # フラダリラボのオヤブン -> フラダリラボオヤブン
    base_cores = list(cores)
    for place in places:  # （カントー）など
        for core in list(cores):
            if not any(other in core for other in places):
                cores += [place + core, place + "の" + core, core + place]
    if len(places) > 1:  # （ジョウト）（GBプレイヤー）は両方言えば強い答えになる
        for core in base_cores:
            for first, second in (places[:2], places[1::-1]):
                joined = first + second
                cores += [joined + core, joined + "の" + core, core + joined,
                          first + core + second]
    cores += [core.replace("昼", "朝") for core in cores if "昼" in core]
    return list(dict.fromkeys(core for core in cores if core))


@dataclass(frozen=True)
class IntroTrack:
    id: str
    title: str
    work: str
    category: str
    aliases: tuple = ()

    @property
    def path(self) -> Path:
        return INTRO_DIRECTORY / CLIP_DIRECTORY_NAME / f"{self.id}.ogg"

    def _keys(self, names) -> dict:
        """回答の照合形 -> 強さ。names は別名（強さ3）。

        強さ2はこの曲を指す言い方（曲名・戦う相手）。強さ1は（カントー）などを
        省いた言い方で、省かない曲がほかにあればそちらを指す（「野生ポケモン」は
        地方なしの曲）。強さ3は別名。人が決めた答えなので、同じ作品のほかの曲と
        重なっても正解にする（LAアルセウスでアルセウス2〜4も正解）。

        最終戦の曲は「決戦」まで言う。相手の名前だけ（N・ネモ・マスタード）は
        ふだんの戦闘曲を指すので強さ1にする。ふだんの戦闘曲が無い相手
        （決戦！ダイゴ）は、名前だけでも決まる。「戦闘！チャンピオンネモ」は
        決戦ネモ でも正解。ただし「決戦！スグリ」が別にあるなら 決戦スグリ は
        そちらを指し、「戦闘！チャンピオンスグリ」は チャンピオンスグリ と答える
        （決戦＋相手も強さ1にして、曲名どおりの曲を優先する）。
        """
        places = answer_places(self.title)
        final = bool(_FINAL_HEAD.match(self.title))
        strong, loose = set(), set()
        named = {canon(name) for name in names}
        for name in names:  # 「野生ポケモン(ガラル)」は ガラル野生 でも通す（地方は省かせない）
            named |= {canon(core) for core in answer_cores(name)
                      if any(place in core for place in answer_places(name))}
        for core in answer_cores(self.title):
            shown = core.replace("朝", "昼")
            placed = all(place in shown or place in _DEFAULT_PLACES for place in places)
            (strong if placed and not final else loose).add(canon(core))
            prefixed = _FINAL_PREFIX.match(core)
            if prefixed:  # チャンピオンネモ -> ネモ・決戦ネモ（どちらも弱）
                loose.add(canon(prefixed.group(1)))
                loose.add(canon("決戦" + prefixed.group(1)))
        keys = {}
        for strength, cores in ((1, loose), (2, strong), (3, named)):
            for core in cores - {""}:
                for key in (core, core + canon("戦"), "VS" + core):
                    keys[key] = strength
        bare = canon(_PAREN.sub("", self.title))
        keys[bare] = max(keys.get(bare, 0), 1 if places else 2)
        keys[canon(self.title)] = keys[self.song] = 2
        keys.pop("", None)
        return keys

    @cached_property
    def plain(self) -> dict:
        """作品の略称なしで受け付ける回答（照合形 -> 強さ）。

        曲名、戦う相手（＋「戦」「VS」）、別名（原曲の作品のものも、
        ほかに流れる作品でのものも）。
        """
        names = [*self.listed_aliases, *self.aliases]
        for _appears, aliases in self.appearances:
            names += aliases
        return self._keys(names)

    @cached_property
    def secret(self) -> bool:
        """ふだんは出題しない曲か（未使用曲・古いバージョン。intro_secret.csv に書いたもの）。"""
        abbreviations = {canon(a) for a in self.abbreviations}
        return any(
            title == canon(self.title) and work in abbreviations
            for work, title in _secret_rules())

    @cached_property
    def _rule_keys(self) -> tuple:
        """対応リストの行と照らす (相手・曲名の照合形, 作品の略称の照合形)。"""
        cores = {canon(core) for core in answer_cores(self.title)}
        cores |= {canon(self.title), self.song}
        return cores, {canon(a) for a in self.abbreviations}

    @cached_property
    def appearances(self) -> tuple:
        """この曲が流れるほかの作品（再録・流用）。(作品, 呼び名のタプル) の並び。"""
        cores, abbreviations = self._rule_keys
        return tuple(
            (appears, aliases)
            for work, core, appears, aliases in _appearance_rules()
            if core in cores and work in abbreviations)

    @cached_property
    def work_keys(self) -> frozenset:
        """作品での絞り込みに使うキー（原曲の作品と、登場する作品）。"""
        return frozenset(
            map(work_key, (self.work, *(appears for appears, _ in self.appearances))))

    @cached_property
    def listed_aliases(self) -> tuple:
        """対応リスト（intro_aliases.csv）でこの曲に当たる別名（原曲の作品でのもの）。"""
        cores, abbreviations = self._rule_keys
        found = []
        for work, core, aliases in _alias_rules():
            if core in cores and (not work or work in abbreviations):
                found += [alias for alias in aliases if alias not in found]
        return tuple(found)

    @cached_property
    def song(self) -> str:
        """同じ曲かどうかを決める形。別バージョン（Ver. 1.0・昼/夜・(2)）は同じ曲、
        「戦闘！N」と「決戦！N」、（カントー）と（ジョウト）は別の曲。"""
        text = _REMARK.sub("", self.title)
        text = _SECOND.sub("", text) or text
        text = _PAREN.sub(
            lambda m: "" if _NOT_A_PLACE.search(m.group(1).strip() or "0") else m.group(0),
            text)
        return canon(text)

    @cached_property
    def abbreviations(self) -> tuple:
        """作品の略称と作品名（回答の頭か末尾につける）。"""
        return (*work_abbreviations(self.work), self.work)

    @cached_property
    def qualified(self) -> dict:
        """「略称＋相手」「相手＋略称」の回答（照合形 -> 強さ）。

        別名は、その別名が付いた作品の略称とだけ組み合わせる
        （ネジキはPtとHGSS、ミクリはエメラルドとBW2、のように作品ごとに決まる）。
        曲名・戦う相手は、曲が流れるどの作品の略称とでも組み合わせられる。
        """
        keys = dict(self.native)
        for appears, aliases in self.appearances:
            for key, strength in self._combined(work_names(appears),
                                                self._keys(aliases)).items():
                keys[key] = max(strength, keys.get(key, 0))
        return keys

    @cached_property
    def native(self) -> dict:
        """qualified のうち、原曲の作品の略称と組み合わせたもの。"""
        return self._combined(
            self.abbreviations, self._keys([*self.listed_aliases, *self.aliases]))

    @staticmethod
    def _combined(names, plain: dict) -> dict:
        keys = {}
        for abbreviation in {canon(a) for a in names} - {""}:
            for key, strength in plain.items():
                for combined in (abbreviation + key, key + abbreviation,
                                 abbreviation + "ノ" + key):
                    keys[combined] = max(strength, keys.get(combined, 0))
        return keys

    def hint_value(self, index: str):
        """ヒントの値（無ければNone）。"""
        if index == "作品":
            return self.work or None
        return None


# ヒントは作品だけ（頭文字・文字数・区分は役に立たなかったのでやめた）
INTRO_HINTS = ("作品",)

_cache = {"key": None, "tracks": []}


def load_tracks() -> list:
    """曲リストを読む。音源のある曲だけ返す（ファイルが変われば読み直す）。"""
    manifest = INTRO_DIRECTORY / MANIFEST_NAME
    try:
        key = (str(manifest), manifest.stat().st_mtime_ns)
    except OSError:
        return []
    if _cache["key"] != key:
        tracks = []
        with open(manifest, encoding="utf-8-sig", newline="") as file:
            for row in csv.DictReader(file):
                track_id = (row.get("id") or "").strip()
                title = (row.get("title") or "").strip()
                if not track_id or not title:
                    continue
                category = (row.get("category") or "").strip()
                tracks.append(IntroTrack(
                    id=track_id,
                    title=title,
                    work=(row.get("work") or "").strip(),
                    category=category if category in CATEGORIES else CATEGORY_OTHER,
                    aliases=tuple(
                        alias.strip()
                        for alias in (row.get("aliases") or "").split("|")
                        if alias.strip()),
                ))
        _cache["key"] = key
        _cache["tracks"] = tracks
    return [track for track in _cache["tracks"] if track.path.exists()]


def works() -> list:
    """曲リストにある作品名（リストの並び順）。"""
    return list(dict.fromkeys(track.work for track in load_tracks() if track.work))


def match_works(word: str) -> list:
    """入力に合う作品名を返す。略称か完全一致が無ければ部分一致。"""
    key = normalize_title(word)
    if not key:
        return []
    names = works()
    exact = [name for name in names
             if normalize_title(name) == key
             or key in map(normalize_title, work_abbreviations(name))]
    return exact or [name for name in names if key in normalize_title(name)]


def filter_tracks(work_names=(), categories=(), secret=False) -> list:
    """作品・区分で絞り込む（空は絞り込まない）。

    シークレットの曲（未使用曲・古いバージョン）は、secret=True のときだけ入れる。
    """
    wanted = set(map(work_key, work_names))
    return [
        track for track in load_tracks()
        if (not wanted or wanted & track.work_keys)
        and (not categories or track.category in categories)
        and (secret or not track.secret)
    ]


def random_track(work_names=(), categories=(), secret=False):
    candidates = filter_tracks(work_names, categories, secret)
    return random.choice(candidates) if candidates else None


def find_tracks(text: str) -> list:
    """回答として読める曲（略称つき・略称なしのどちらでも）。作品をまたいで全部返す。"""
    key = canon(text)
    if not key:
        return []
    return [track for track in load_tracks()
            if key in track.plain or key in track.qualified]


# 回答の判定
CORRECT = "correct"
AMBIGUOUS = "ambiguous"  # 相手は合っているが、どの作品か決まらない
AMBIGUOUS_SONG = "ambiguous_song"  # 作品は決まるが、同じ相手の曲がいくつかある
PARTIAL = "partial"  # 答えの一部だけ合っている（トレーナー → 学園のトレーナー）
WRONG = "wrong"
UNKNOWN = "unknown"  # 曲リストのどれにも当たらない


PARTIAL_LENGTH = 3  # これより短い言葉は「一部が合っている」と見なさない


def is_partial(track, key: str) -> bool:
    """答えが、この曲の答えの一部になっているか（略称は外して比べる）。

    「トレーナー」は「学園のトレーナー」の一部、「オリジン」は
    「オリジンフォルムディアルガ・パルキア」の一部。おしいので聞き返す。
    """
    rests = {key}
    for abbreviation in {canon(a) for a in track.abbreviations} - {""}:
        if key.startswith(abbreviation):
            rests.add(key[len(abbreviation):].lstrip("ノ"))
        if key.endswith(abbreviation):
            rests.add(key[:-len(abbreviation)])
    return any(
        len(rest) >= PARTIAL_LENGTH and rest in answer
        for rest in rests for answer in track.plain)


def judge(track, text: str) -> str:
    """回答を判定する。

    その言い方で曲が1つに決まるときだけ正解にする（別バージョンは同じ曲）。
    略称なしで複数の作品に当たるなら AMBIGUOUS、作品は決まっても
    「戦闘！N」と「決戦！N」のように曲がいくつかあるなら AMBIGUOUS_SONG。
    """
    key = canon(text)
    if not key:
        return UNKNOWN
    tracks = load_tracks()
    if key in track.qualified:
        field = "qualified"
        pool = [other for other in tracks if key in other.qualified]
    elif key in track.plain:
        field = "plain"
        pool = [other for other in tracks if key in other.plain]
    elif is_partial(track, key):
        return PARTIAL
    elif any(key in other.plain or key in other.qualified for other in tracks):
        return WRONG
    else:
        return UNKNOWN
    pool = [other for other in pool if other.id != track.id] + [track]
    # 略称つきなら作品は決まっている（再録で流れる作品の略称でもよい）
    if field == "plain" and len({other.work for other in pool}) > 1:
        return AMBIGUOUS
    mine = getattr(track, field)[key]
    if mine == 3:
        return CORRECT  # 別名は、同じ作品のほかの曲と重なってもよい
    # 曲名から取り出した言い方どうしで比べる（別名で当たった曲は数えない）
    rivals = [other for other in pool
              if (other.work, other.song) != (track.work, track.song)
              and getattr(other, field)[key] < 3]
    if field == "qualified" and key in track.native:
        # その作品の曲なら、再録でその作品にも流れるだけの曲とは迷わない
        rivals = [other for other in rivals if key in other.native]
    rivals = [getattr(other, field)[key] for other in rivals]
    if any(strength >= mine for strength in rivals):
        return AMBIGUOUS_SONG
    return CORRECT


_REGIONS = ("カントー", "ジョウト", "ホウエン", "シンオウ", "イッシュ", "カロス",
            "アローラ", "ガラル", "パルデア", "ヒスイ")


def distinguishers(track, text: str) -> list:
    """聞き返すときに、答えへ足してほしいもの（決戦・地方・時間帯）。

    候補の曲名どうしで違うところだけを返す。これで区別できなければ空。
    """
    titles = candidates(track, text)
    if len(titles) < 2:
        return []
    axes = []
    if len({bool(_FINAL_HEAD.match(title)) for title in titles}) > 1:
        axes.append("決戦")
    places = [set(answer_places(title)) for title in titles]
    if len({frozenset(p & {"昼", "夜"}) for p in places}) > 1:
        axes.append("時間帯")
    if len({frozenset(p & set(_REGIONS)) for p in places}) > 1:
        axes.insert(1 if axes[:1] == ["決戦"] else 0, "地方")
    return axes


def candidates(track, text: str) -> list:
    """その答えで当たる曲の曲名（同じ作品のぶん。聞き返すときに見せる）。"""
    key = canon(text)
    field = "qualified" if key in track.qualified else "plain"
    songs = {}
    for other in load_tracks():
        if other.work == track.work and key in getattr(other, field):
            title = songs.get(other.song)
            if title is None or len(other.title) < len(title):
                songs[other.song] = other.title
    return list(songs.values())


def intro_hash(track_id: str, nonce: str) -> str:
    digest = hashlib.sha1(f"intro:{nonce}:{track_id}".encode("utf-8")).hexdigest()
    return digest[:INTRO_HASH_LENGTH]


def intro_filename(track_id: str, nonce: str) -> str:
    return f"intro-{nonce}-{intro_hash(track_id, nonce)}.ogg"


def track_from_message(message):
    """投稿の添付ファイル名から曲を逆算する。見つからなければNone。"""
    for attachment in getattr(message, "attachments", None) or []:
        match = INTRO_FILENAME_RE.match(getattr(attachment, "filename", "") or "")
        if match is None:
            continue
        nonce, digest = match.group(1), match.group(2)
        for track in load_tracks():
            if intro_hash(track.id, nonce) == digest:
                return track
    return None
