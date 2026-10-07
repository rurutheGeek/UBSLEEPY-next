#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""イントロクイズ用に、アルバムの各曲の冒頭を切り出して resource/intro/ へ置く。

    python tools/build_intro_clips.py /path/to/アルバム [...]         # 未作成ぶんだけ
    python tools/build_intro_clips.py /path/to/music --match ポケ     # フォルダ名で選ぶ
    python tools/build_intro_clips.py /path/to/アルバム --force       # 作り直す
    python tools/build_intro_clips.py /path/to/アルバム --limit 5     # 動作確認
    python tools/build_intro_clips.py /path/to/アルバム --dry-run     # 分類だけ見る

    python tools/build_intro_clips.py /path/to/別のアルバム --append  # 作品を足す

フォルダ（Nextcloudの music など。複数可）を下まで探し、曲ごとに冒頭10秒を
Opus（.ogg）へ圧縮して resource/intro/clips/<id>.ogg に置く。タグは落とす
（添付したファイルから曲名が読めないように）。曲リストは
resource/intro/manifest.csv（id,title,work,category,aliases）。
music の下には他のアルバムもあるので、--match でアルバムのフォルダ名を選ぶ
（途中のフォルダ名のどれかに合えばよい。`.` で始まるフォルダは見ない）。
短いジングル（--min-seconds 未満。既定15秒）は入れない。

- 作品（work）はアルバムタグ（無ければ親フォルダ名）から、機種名や
  「スーパーミュージックコレクション」などを落としたもの。
- 区分（category）は曲名・コメントから 戦闘／フィールド／その他 を推定する。
  推定は目安なので、manifest.csv を手で直してよい。既にある行の
  title・work・category・aliases は作り直しても保つ（--reclassify で推定し直す）。
- aliases は別名（`|` 区切り）。回答で受け付ける表記を足せる。

ffmpeg と ffprobe が要る。クイズはここで作ったものをローカル参照するだけ。
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot_module import intro  # noqa: E402

AUDIO_SUFFIXES = (".mp3", ".flac", ".m4a", ".ogg", ".opus", ".wav", ".aac", ".wma")
# 戦闘曲。「バトル」だけでは戦闘にしない（バトルタワー・バトルポイントなど、
# 戦闘施設のロビーやジングルを弾くため）。
BATTLE_PATTERN = re.compile(
    r"戦闘|戦い|たたかい|せんとう|決戦|レイドバトル|ラストバトル|last\s*battle|"
    r"battle\s*!|(?<![a-z])vs(?![a-z])",
    re.IGNORECASE)
# 「〜に勝利！」「勝利(VSトレーナー)」「戦いの予兆」などは戦闘曲ではない
VICTORY_PATTERN = re.compile(
    r"勝利|しょうり|victory|予兆|プログラム起動|結果発表|もらった|手に入れた|"
    r"ゲット|うけつけ", re.IGNORECASE)
# 曲名は戦闘曲のようでも、戦闘中には流れない曲（ポケモンリーグの建物の曲）
FIELD_TITLES = re.compile(r"決戦[！!]\s*ポケモンリーグ")
BATTLE_HEAD = re.compile(r"^\s*(戦闘|戦い|せんとう)\s*[！!：:（(]")
FIELD_PATTERN = re.compile(
    r"道路|どうろ|ロード|への道|小道|タウン|シティ|の町|の街|の村|むら|ビレッジ|"
    r"洞窟|どうくつ|ほら穴|森|もり|山|やま|ざん|トンネル|ゲート|たんこう|炭鉱|"
    r"海|湖|みずうみ|島|水道|すいどう|砂漠|さばく|平原|草原|雪原|湿原|しつげん|"
    r"なみのり|そらをとぶ|じてんしゃ|サイクリング|フィールド|エリア|"
    r"route|road|town|city|village|field",
    re.IGNORECASE)
TRACK_NUMBER = re.compile(r"^\s*(\d+[-_. ]+)+")
# アルバム名から落とす、機種名と「スーパーミュージックコレクション」など
WORK_PREFIX = re.compile(
    r"^(ニンテンドー\s*3?DS|Nintendo\s*Switch|GBA)\s*", re.IGNORECASE)
WORK_SUFFIX = re.compile(
    r"\s*(スーパー\s*ミュージック.*|ミュージック・スーパーコンプリート.*|"
    r"オリジナル\s*サウンドトラック.*)$")


def tidy_work(album: str) -> str:
    """アルバム名を作品名らしく短くする（空になるなら元のまま）。"""
    name = WORK_SUFFIX.sub("", WORK_PREFIX.sub("", album.strip())).strip()
    return name or album.strip()


WORK_OVERRIDES_PATH = Path("resource/intro_track_works.csv")


EXCLUDE = "-"  # 付け替えの作品名がこれなら出題しない


def work_overrides(path: Path = WORK_OVERRIDES_PATH) -> list:
    """曲の付け替え・除外・改名（アルバム名の一部, 曲名か空, Discか空, 作品名, 曲名）。"""
    rules = []
    for row in intro._rows(path):
        row = [*row, "", "", "", ""][:5]
        if row[0] and (row[3] or row[4]):
            rules.append((intro.normalize_title(row[0]), intro.normalize_title(row[1]),
                          row[2], row[3], row[4]))
    return rules


def disc_of(tags: dict) -> str:
    """タグのDisc番号（「2/4」は2）。無ければ空。"""
    return str(tags.get("disc") or "").split("/")[0].strip()


def apply_overrides(album: str, title: str, disc: str, work: str, overrides) -> tuple:
    """付け替えを当てた (作品名, 曲名)。出題しない曲は作品名が EXCLUDE。"""
    album_key, title_key = intro.normalize_title(album), intro.normalize_title(title)
    for album_part, wanted_title, wanted_disc, new_work, new_title in overrides:
        if (album_part in album_key and wanted_title in ("", title_key)
                and wanted_disc in ("", disc)):
            return new_work or work, new_title or title
    return work, title


def classify(title: str, comment: str = "") -> str:
    """曲名とコメントから区分を推定する（戦闘を先に見る）。"""
    text = f"{title} {comment}"
    if FIELD_TITLES.search(title):
        return intro.CATEGORY_FIELD
    if VICTORY_PATTERN.search(title) and not BATTLE_HEAD.match(title):
        return intro.CATEGORY_OTHER
    if BATTLE_PATTERN.search(text):
        return intro.CATEGORY_BATTLE
    if FIELD_PATTERN.search(text):
        return intro.CATEGORY_FIELD
    return intro.CATEGORY_OTHER


def track_id(path: Path) -> str:
    """上2つのフォルダ名とファイル名から決まるid（作り直しても変わらない）。

    アルバムの下に Disc 1 などがあっても、アルバムどうしでぶつからない。
    """
    key = f"{path.parent.parent.name}/{path.parent.name}/{path.name}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def read_tags(path: Path) -> dict:
    """ffprobe でタグと長さ（duration）を読む（キーは小文字）。読めなければ空。"""
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "format=duration:format_tags:stream_tags", "-of", "json", str(path)],
        capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return {}
    try:
        data = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        return {}
    tags = {}
    for stream in data.get("streams", []):  # ogg/opus はストリーム側にタグがある
        tags.update({k.lower(): v for k, v in (stream.get("tags") or {}).items()})
    tags.update({
        k.lower(): v for k, v in ((data.get("format") or {}).get("tags") or {}).items()})
    tags["duration"] = (data.get("format") or {}).get("duration") or ""
    return tags


def duration_of(tags: dict) -> float | None:
    try:
        return float(tags.get("duration") or "")
    except ValueError:
        return None


def describe(path: Path, tags: dict, overrides=()) -> dict:
    """1曲ぶんの曲リストの行を作る。"""
    title = (tags.get("title") or "").strip() or TRACK_NUMBER.sub("", path.stem).strip()
    album = (tags.get("album") or "").strip() or path.parent.name
    category = classify(title, tags.get("comment") or "")
    work, title = apply_overrides(
        album, title, disc_of(tags), tidy_work(album), overrides)
    return {
        "id": track_id(path),
        "title": title,
        "work": work,
        "category": category,
        "aliases": "",
    }


def cut(source: Path, target: Path, seconds: float, bitrate: str) -> None:
    """冒頭を切り出して圧縮する。途中で落ちても壊れたファイルを残さない。"""
    temporary = target.with_suffix(".part.ogg")
    fade = max(seconds - 0.5, 0)
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(source), "-t", str(seconds),
         "-vn", "-map_metadata", "-1", "-map_chapters", "-1",
         "-af", f"afade=t=out:st={fade}:d=0.5",
         "-ac", "2", "-c:a", "libopus", "-b:a", bitrate, str(temporary)],
        check=True, capture_output=True)
    temporary.replace(target)


def read_manifest(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8-sig", newline="") as file:
        return {row["id"]: row for row in csv.DictReader(file) if row.get("id")}


def write_manifest(path: Path, rows: list) -> None:
    temporary = path.with_suffix(".csv.part")
    with open(temporary, "w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=intro.MANIFEST_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("source", type=Path, nargs="+",
                        help="アルバムのフォルダ（下まで探す。複数可）")
    parser.add_argument("--match", default="",
                        help="アルバムのフォルダ名がこの正規表現に合う曲だけ使う")
    parser.add_argument("--category", action="append", choices=intro.CATEGORIES,
                        help="この区分の曲だけ使う（複数可。未指定は全部）")
    parser.add_argument("--min-seconds", type=float, default=15,
                        help="これより短い曲（ジングル）は入れない（0で全部）")
    parser.add_argument("--output", type=Path, default=intro.INTRO_DIRECTORY,
                        help="出力先（既定: resource/intro）")
    parser.add_argument("--seconds", type=float, default=10, help="切り出す長さ（秒）")
    parser.add_argument("--bitrate", default="64k", help="Opusのビットレート")
    parser.add_argument("--force", action="store_true", help="作成済みの音源も作り直す")
    parser.add_argument("--reclassify", action="store_true",
                        help="既にある行の曲名・作品・区分も読み直す（別名は保つ）")
    parser.add_argument("--append", action="store_true",
                        help="今回のフォルダに無い曲も曲リストに残す（作品を足すとき）")
    parser.add_argument("--limit", type=int, default=0, help="新しく切り出す最大件数（0は全部）")
    parser.add_argument("--dry-run", action="store_true", help="切り出さず、分類だけ表示する")
    args = parser.parse_args(argv)

    for root in args.source:
        if not root.is_dir():
            print(f"フォルダがありません: {root}", file=sys.stderr)
            return 1
    album_pattern = re.compile(args.match) if args.match else None
    sources = sorted({
        path for root in args.source for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in AUDIO_SUFFIXES
        and not any(part.startswith(".") for part in path.relative_to(root).parts)
        and (album_pattern is None or any(
            album_pattern.search(part) for part in path.relative_to(root).parts[:-1]))})
    clips = args.output / intro.CLIP_DIRECTORY_NAME
    manifest_path = args.output / intro.MANIFEST_NAME
    existing = read_manifest(manifest_path)
    if not args.dry_run:
        clips.mkdir(parents=True, exist_ok=True)

    overrides = work_overrides()
    rows = []
    cut_count = skipped = failed = short = excluded = 0
    for path in sources:
        tags = read_tags(path)
        length = duration_of(tags)
        if args.min_seconds and length is not None and length < args.min_seconds:
            short += 1
            continue
        row = describe(path, tags, overrides)
        if row["work"] == EXCLUDE:
            excluded += 1
            continue
        old = existing.get(row["id"])
        if old is not None:
            if args.reclassify:
                row["aliases"] = old.get("aliases") or ""
            else:
                row = {field: old.get(field) or "" for field in intro.MANIFEST_FIELDS}
        if args.category and row["category"] not in args.category:
            continue
        if args.dry_run:
            print(f"{row['category']}\t{row['work']}\t{row['title']}")
            rows.append(row)
            continue
        target = clips / f"{row['id']}.ogg"
        if target.exists() and not args.force:
            skipped += 1
        elif args.limit and cut_count >= args.limit:
            continue  # 音源の無い曲は曲リストに入れない
        else:
            try:
                cut(path, target, args.seconds, args.bitrate)
                cut_count += 1
            except (subprocess.CalledProcessError, OSError) as error:
                failed += 1
                detail = getattr(error, "stderr", b"") or b""
                print(f"failed: {path} ({detail.decode(errors='replace').strip() or error})",
                      file=sys.stderr)
                continue
        rows.append(row)

    if args.append:
        seen = {row["id"] for row in rows}
        rows = [{field: old.get(field) or "" for field in intro.MANIFEST_FIELDS}
                for track, old in existing.items() if track not in seen] + rows
    counts = {category: 0 for category in intro.CATEGORIES}
    for row in rows:
        counts[row["category"] if row["category"] in counts else intro.CATEGORY_OTHER] += 1
    summary = " / ".join(f"{category} {count}" for category, count in counts.items())
    if args.dry_run:
        print(f"{len(rows)}曲（{summary}） / short {short}")
        return 0
    write_manifest(manifest_path, rows)
    print(f"cut {cut_count} / skipped {skipped} / short {short} / "
          f"excluded {excluded} / failed {failed}")
    print(f"{len(rows)}曲（{summary}） -> {manifest_path}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
