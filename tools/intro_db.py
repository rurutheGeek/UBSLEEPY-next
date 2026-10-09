#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""イントロクイズの別名・登場作品・シークレットを pkdb で直す。

Botは pkdb（sleepy_pkdb の app_intro_* 表）を1分ごとに読み直すので、
ここで直せば配備なしで本番・テストの両方に反映される。

    python tools/intro_db.py list ゼロラボ               # 曲を探して、いまの登録を見る
    python tools/intro_db.py alias add SV ゼロラボ オーリム フトゥー
    python tools/intro_db.py alias remove SV ゼロラボ オーリム
    python tools/intro_db.py alias add Pt フロンティアブレーン ネジキ --in HGSS
                                                         # HGSSで流れるときだけの呼び名
    python tools/intro_db.py appear add DP ディアルガ・パルキア ORAS   # ORASでも流れる
    python tools/intro_db.py appear remove DP ディアルガ・パルキア ORAS
    python tools/intro_db.py secret add BDSP "野生ポケモン（別バージョン）" 理由
    python tools/intro_db.py secret remove BDSP "野生ポケモン（別バージョン）"
    python tools/intro_db.py judge SV ゼロラボ sv博士    # その曲が出題されたときの判定
    python tools/intro_db.py push                        # リポジトリのCSVでpkdbを置き換える
    python tools/intro_db.py pull                        # pkdbの内容をCSVへ書き出す

作品は略称でも作品名でもよい。曲名は一部でよい（その作品で1曲に決まること）。
直したあとは judge で確かめる。コードの変更・PR・配備は要らない。
ときどき pull してCSVをコミットしておく（pkdbが使えないときの控えになる）。

pkdbへは apps-01 のコンテナの psql を pkdb_editor で使う（SSH鍵が要る）。
別のつなぎ方をするときは、psql のコマンドを INTRO_DB_PSQL に入れる。
"""
import argparse
import os
from pathlib import Path
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot_module import intro  # noqa: E402

DEFAULT_PSQL = ("ssh -i ~/.ssh/id_ed25519_pve debian@192.168.10.105 "
                "sudo docker exec -i pkdb-db-1 psql -U pkdb_editor -d sleepy_pkdb")
TABLES = ("app_intro_alias", "app_intro_appearance", "app_intro_secret")
CSV_HEADERS = {
    "aliases": ["イントロクイズ: 作品（略称）,曲名,別名（| 区切り）",
                "pkdb（app_intro_alias）が正。tools/intro_db.py pull で書き出した控え。"],
    "appearances": [
        "イントロクイズ: 原曲の作品（略称）,曲名,流れる作品（略称）,そこでの呼び名（| 区切り）",
        "pkdb（app_intro_appearance・app_intro_alias）が正。tools/intro_db.py pull で書き出した控え。"],
    "secret": ["イントロクイズ: シークレットの曲（ふだんは出題しない。/introdata シークレット で出す）",
               "作品（略称）,曲名,理由",
               "未使用曲や古いバージョンなど、ふつうに遊んでいて聞く機会がほぼ無い曲だけを書く。",
               "pkdb（app_intro_secret）が正。tools/intro_db.py pull で書き出した控え。"],
}


class Problem(Exception):
    """使い方・入力の誤り（メッセージを出して終わる）。"""


def psql(sql: str) -> list:
    """SQLを流し、結果の行（タブ区切りを分けたもの）を返す。"""
    command = shlex.split(os.environ.get("INTRO_DB_PSQL", DEFAULT_PSQL))
    command += ["-v", "ON_ERROR_STOP=1", "-q", "-At", "-F", "'\t'"
                if "ssh" in command[0] else "\t"]
    done = subprocess.run(command, input=sql, text=True, capture_output=True)
    if done.returncode:
        raise Problem(f"pkdbで失敗しました:\n{done.stderr.strip()}")
    return [line.split("\t") for line in done.stdout.splitlines() if line]


def literal(text: str) -> str:
    if any(char in text for char in "\t\n\r\\"):
        raise Problem(f"タブ・改行・\\ は使えません: {text!r}")
    return "'" + text.replace("'", "''") + "'"


def values(*cells) -> str:
    return "(" + ", ".join(literal(cell) for cell in cells) + ")"


def load() -> None:
    """pkdbの今の内容を、判定に使う対応リストとして読み込む。"""
    tables = [psql(sql + ";") for sql in intro.DATABASE_LISTS_SQL]
    tables[2] = [(row + [""])[:3] for row in tables[2]]
    intro.use_database_lists(intro.rows_from_database(*tables))


def work_name(text: str) -> str:
    """作品を、表に入れる略称（先頭の略称）にする。"""
    names = intro.work_names(text)
    if names == (text,) and not intro.work_abbreviations(text):
        raise Problem(f"作品が分かりません: {text}（略称は resource/intro_works.csv）")
    return names[0]


def find_song(work: str, title: str) -> tuple:
    """(作品の略称, 表に入れる曲名, その曲の音源たち)。曲リストに無ければ止める。"""
    abbreviation = work_name(work)
    key = intro.work_key(abbreviation)
    songs = {}
    for track in intro.load_tracks():
        if intro.work_key(track.work) == key:
            songs.setdefault(track.song, []).append(track)
    if not songs:
        raise Problem("曲リスト（resource/intro/manifest.csv）にその作品の曲がありません")
    wanted = intro.canon(title)
    exact = [tracks for tracks in songs.values()
             if any(wanted in (intro.canon(t.title), t.song,
                               *map(intro.canon, intro.answer_cores(t.title)))
                    for t in tracks)]
    found = exact or [tracks for tracks in songs.values()
                      if any(wanted in intro.canon(t.title) for t in tracks)]
    if len(found) != 1:
        names = "\n".join(f"  {min(t.title for t in tracks)}"
                          for tracks in (found or songs.values()))
        raise Problem(f"曲が1つに決まりません: {work} {title}\n{names}")
    return abbreviation, min((t.title for t in found[0]), key=len), found[0]


def show(tracks) -> None:
    """その曲の登録と、自動で通る答えを出す。"""
    track = min(tracks, key=lambda t: len(t.title))
    print(f"{track.abbreviations[0]} / {track.title}"
          + (f"（音源 {len(tracks)}）" if len(tracks) > 1 else "")
          + ("　※シークレット" if any(t.secret for t in tracks) else ""))
    print("  自動で通る答え:", "／".join(intro.answer_cores(track.title)))
    print("  別名:", "／".join(dict.fromkeys(a for t in tracks for a in t.listed_aliases)) or "-")
    for appears, names in dict(a for t in tracks for a in t.appearances).items():
        print(f"  {appears} でも流れる:", "／".join(names) or "（呼び名なし）")


def command_list(args) -> None:
    load()
    wanted = intro.canon(args.word or "")
    songs = {}
    for track in intro.load_tracks():
        words = (track.title, track.work, *track.abbreviations, *track.listed_aliases)
        if not wanted or any(wanted in intro.canon(word) for word in words):
            songs.setdefault((track.work, track.song), []).append(track)
    for tracks in songs.values():
        show(tracks)
    print(f"{len(songs)}曲")


def command_alias(args) -> None:
    load()
    work, title, _tracks = find_song(args.work, args.title)
    in_work = work_name(args.in_work) if args.in_work else work
    if args.action == "add":
        sql = "".join(
            "INSERT INTO pokemondb.app_intro_alias (work, title, in_work, alias) VALUES "
            f"{values(work, title, in_work, alias)} ON CONFLICT DO NOTHING;\n"
            for alias in args.aliases)
        if in_work != work:
            sql += ("INSERT INTO pokemondb.app_intro_appearance (work, title, appears_in) "
                    f"VALUES {values(work, title, in_work)} ON CONFLICT DO NOTHING;\n")
    else:
        sql = "".join(
            "DELETE FROM pokemondb.app_intro_alias WHERE (work, title, in_work, alias) = "
            f"{values(work, title, in_work, alias)};\n" for alias in args.aliases)
    psql(f"BEGIN;\n{sql}COMMIT;")
    report(args.work, args.title, [in_work + alias for alias in args.aliases])


def command_appear(args) -> None:
    load()
    work, title, _tracks = find_song(args.work, args.title)
    appears = work_name(args.appears_in)
    if args.action == "add":
        sql = ("INSERT INTO pokemondb.app_intro_appearance (work, title, appears_in) "
               f"VALUES {values(work, title, appears)} ON CONFLICT DO NOTHING;")
    else:
        sql = ("BEGIN;\nDELETE FROM pokemondb.app_intro_alias WHERE (work, title, in_work) = "
               f"{values(work, title, appears)};\n"
               "DELETE FROM pokemondb.app_intro_appearance WHERE (work, title, appears_in) = "
               f"{values(work, title, appears)};\nCOMMIT;")
    psql(sql)
    report(args.work, args.title, [])


def command_secret(args) -> None:
    load()
    work, _title, tracks = find_song(args.work, args.title)
    # シークレットは音源ごと（Ver. 1.0 だけを隠す、など）。曲名は音源の名前そのまま
    wanted = intro.canon(args.title)
    exact = [t for t in tracks if intro.canon(t.title) == wanted]
    if not exact:  # 「戦闘！」を省いた書き方でも、音源が1つに決まればよい
        partial = [t for t in tracks if wanted in intro.canon(t.title)]
        exact = partial if len(partial) == 1 else []
    if len(exact or tracks) != 1 and not exact:
        names = "\n".join(f"  {t.title}" for t in tracks)
        raise Problem(f"音源が1つに決まりません。曲名を全部書いてください:\n{names}")
    title = (exact or tracks)[0].title
    if args.action == "add":
        sql = ("INSERT INTO pokemondb.app_intro_secret (work, title, reason) VALUES "
               f"{values(work, title, args.reason or '')} ON CONFLICT (work, title) "
               "DO UPDATE SET reason = EXCLUDED.reason, updated_at = now();")
    else:
        sql = ("DELETE FROM pokemondb.app_intro_secret WHERE (work, title) = "
               f"{values(work, title)};")
    psql(sql)
    report(args.work, args.title, [])


def report(work: str, title: str, answers: list) -> None:
    """直したあとの登録と、足した答えの判定を出す。"""
    load()
    _work, _title, tracks = find_song(work, title)
    show(tracks)
    for answer in answers:
        print(f"  判定 {answer}: {intro.judge(tracks[0], answer)}")
    print("Botには1分以内に反映されます。")


def command_judge(args) -> None:
    load()
    _work, _title, tracks = find_song(args.work, args.title)
    show(tracks)
    for answer in args.answers:
        print(f"  判定 {answer}: {intro.judge(tracks[0], answer)}")


def command_push(_args) -> None:
    """リポジトリのCSVで pkdb の3表を置き換える。"""
    intro.use_database_lists(None)
    aliases, appearances = [], []
    for row in intro._rows(intro.ALIASES_PATH):
        if len(row) >= 3 and row[0]:
            aliases += [(row[0], row[1], row[0], alias) for alias in intro._split(row[2])]
    for row in intro._rows(intro.APPEARANCES_PATH):
        if len(row) >= 3 and row[2]:
            appearances.append((row[0], row[1], row[2]))
            aliases += [(row[0], row[1], row[2], alias)
                        for alias in intro._split((row + [""])[3])]
    secrets = [(row + [""])[:3] for row in intro._rows(intro.SECRET_PATH) if len(row) >= 2]
    sql = "BEGIN;\n" + "".join(f"DELETE FROM pokemondb.{table};\n" for table in TABLES)
    for table, columns, rows in (
            ("app_intro_alias", "work, title, in_work, alias", aliases),
            ("app_intro_appearance", "work, title, appears_in", appearances),
            ("app_intro_secret", "work, title, reason", secrets)):
        for row in dict.fromkeys(map(tuple, rows)):
            sql += f"INSERT INTO pokemondb.{table} ({columns}) VALUES {values(*row)};\n"
    psql(sql + "COMMIT;")
    print(f"pkdbを置き換えました: 別名 {len(aliases)} / 登場作品 {len(appearances)} "
          f"/ シークレット {len(secrets)}")


def command_pull(_args) -> None:
    """pkdbの内容を、リポジトリのCSV（控え）へ書き出す。"""
    load()
    import csv
    for name, path in (("aliases", intro.ALIASES_PATH),
                       ("appearances", intro.APPEARANCES_PATH),
                       ("secret", intro.SECRET_PATH)):
        rows = intro._database_lists[name]
        with open(path, "w", encoding="utf-8", newline="") as file:
            file.write("".join(f"# {line}\n" for line in CSV_HEADERS[name]))
            csv.writer(file, lineterminator="\n").writerows(rows)
        print(f"{path}: {len(rows)}行")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list", help="曲を探して、いまの登録を見る")
    listing.add_argument("word", nargs="?")
    listing.set_defaults(run=command_list)
    alias = commands.add_parser("alias", help="別名を足す・消す")
    alias.add_argument("action", choices=("add", "remove"))
    alias.add_argument("work")
    alias.add_argument("title")
    alias.add_argument("aliases", nargs="+")
    alias.add_argument("--in", dest="in_work", help="その作品で流れるときだけの呼び名にする")
    alias.set_defaults(run=command_alias)
    appear = commands.add_parser("appear", help="ほかに流れる作品を足す・消す")
    appear.add_argument("action", choices=("add", "remove"))
    appear.add_argument("work")
    appear.add_argument("title")
    appear.add_argument("appears_in")
    appear.set_defaults(run=command_appear)
    secret = commands.add_parser("secret", help="シークレットにする・戻す")
    secret.add_argument("action", choices=("add", "remove"))
    secret.add_argument("work")
    secret.add_argument("title")
    secret.add_argument("reason", nargs="?")
    secret.set_defaults(run=command_secret)
    judge = commands.add_parser("judge", help="その曲が出題されたときの判定を見る")
    judge.add_argument("work")
    judge.add_argument("title")
    judge.add_argument("answers", nargs="+")
    judge.set_defaults(run=command_judge)
    commands.add_parser("push", help="CSVでpkdbを置き換える").set_defaults(run=command_push)
    commands.add_parser("pull", help="pkdbをCSVへ書き出す").set_defaults(run=command_pull)
    args = parser.parse_args(argv)
    try:
        args.run(args)
    except Problem as problem:
        print(problem, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
