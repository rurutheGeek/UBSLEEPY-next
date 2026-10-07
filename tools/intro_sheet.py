#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""イントロクイズの別名・登場作品を、1つの編集用の表（Markdown）で出し入れする。

    python tools/intro_sheet.py export [表.md] [前の表.md]  # 書き出す（前の表のメモを引き継ぐ）
    python tools/intro_sheet.py import [表.md]   # 表の内容を対応リストへ取り込む

表は作品ごとの見出しの下に、曲ごとに1行（別バージョンはまとめる）。
直すのは「別名」と「ほかに流れる作品」の2列だけ。

- 別名: その作品でその曲を指す呼び方（個人名・肩書きなど）。`／` か `、` で区切る。
- ほかに流れる作品: 再録・流用で流れる作品の略称。`、` で区切る。その作品でだけ
  通る呼び名は `HGSS（ネジキ／ダリア）` のようにかっこで書く。
- メモ: 自由に書く（取り込みでは読まない）。

取り込むと resource/intro_aliases.csv と resource/intro_appearances.csv を
表の内容で作り直す（この2つは表から作るもので、手では直さない）。
"""
import csv
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot_module import intro  # noqa: E402

DEFAULT_PATH = Path("temp/intro_sheet.md")
HEADER = "| 曲名 | 自動で通る答え（編集不要） | 別名 | ほかに流れる作品 | メモ |"
COLUMNS = ("曲名", "別名", "ほかに流れる作品", "メモ")
NAME_SEPARATOR = "／"
WORK_SEPARATOR = "、"
HEADING = re.compile(r"^## .*（略称: ([^／）]+)")
APPEARANCE = re.compile(r"^([^（(]+?)\s*(?:[（(](.*)[)）])?$")

GUIDE = """# イントロクイズ 編集用リスト

直すのは **別名** と **ほかに流れる作品** の2列だけです（曲名は変えないでください）。

- **自動で通る答え**: 曲名から自動で取り出した言い方で、書かなくても正解になります
  （「の」や「のポケモン」「ポケモン」を省いた形、「〜戦」「VS〜」も通ります）。
  この列は見るだけで、直しても反映されません。

- **別名**: その作品でその曲を指す呼び方（個人名・肩書きなど）。`／` か `、` で区切ります。
  例: `シロナ／チャンピオン`
- **ほかに流れる作品**: 再録・流用で流れる作品の略称。`、` で区切ります。
  その作品でだけ通る呼び名は、かっこの中に `／` 区切りで書きます。
  例: `HGSS（ネジキ／ダリア）、USUM`
- **メモ**: 気づいたことを自由に（曲を外したい、曲名がおかしい、など）。

答え方のルール:
- `作品の略称＋相手`（例: `BWシロナ`）。相手が1作品にしか居なければ略称なしでも正解。
- 相手は曲名から自動で取り出します（「戦闘！チャンピオン」→ チャンピオン）。
  表に書くのは、曲名に出てこない呼び方だけで足ります。
- 別名は、書いた作品の略称とだけ組み合わせます（`ORASミクリ` のような、
  その作品に居ない人の答えは通りません）。
"""


def cell(text: str) -> str:
    return (text or "").replace("|", "｜").replace("\n", " ").strip()


def groups() -> dict:
    """(作品, 曲) ごとの曲（別バージョンをまとめる）。"""
    result = {}
    for track in intro.load_tracks():
        result.setdefault((track.work, track.song), []).append(track)
    return result


def export(path: Path, memo_from: Path | None = None) -> int:
    """表を書き出す。memo_from の表があれば、そのメモを引き継ぐ。"""
    memos = {}
    if memo_from is not None and memo_from.exists():
        for abbreviation, title, _names, _works, memo in parse(memo_from):
            memos[(intro.canon(abbreviation),
                   intro.IntroTrack("", title, "", "").song)] = memo
    lines = [GUIDE]
    work = None
    for (name, _song), tracks in sorted(
            groups().items(), key=lambda item: (item[0][0], min(t.title for t in item[1]))):
        track = min(tracks, key=lambda t: len(t.title))
        if name != work:
            work = name
            abbreviations = "／".join(intro.work_abbreviations(name)) or name
            lines += ["", f"## {name}（略称: {abbreviations}）", "", HEADER,
                      "|---|---|---|---|---|"]
        aliases = list(dict.fromkeys(
            alias for t in tracks for alias in (*t.listed_aliases, *t.aliases)))
        appearances = {}
        for t in tracks:
            for appears, names in t.appearances:
                appearances.setdefault(appears, [])
                appearances[appears] += [n for n in names if n not in appearances[appears]]
        shown = WORK_SEPARATOR.join(
            appears + (f"（{NAME_SEPARATOR.join(names)}）" if names else "")
            for appears, names in appearances.items())
        count = f" ×{len(tracks)}" if len(tracks) > 1 else ""
        automatic = [core for core in intro.answer_cores(track.title)
                     if intro.canon(core) != intro.canon(track.title)]
        memo = memos.get((intro.canon(abbreviations.split("／")[0]), track.song), "")
        lines.append(f"| {cell(track.title)}{count} | {cell(NAME_SEPARATOR.join(automatic))} "
                     f"| {cell(NAME_SEPARATOR.join(aliases))} | {cell(shown)} | {cell(memo)} |")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{len(groups())}曲 -> {path}")
    return 0


def clean(text: str) -> str:
    """エディタが足す飾り（`コード`・*強調*）を落とす。"""
    return re.sub(r"[`*]", "", text or "").strip()


def split_names(text: str) -> list:
    return [name.strip() for name in re.split(r"[／|｜、,，]", clean(text)) if name.strip()]


def split_works(text: str) -> list:
    """「HGSS（ネジキ／ダリア）、USUM」を (作品, 呼び名のリスト) に分ける。"""
    parts, depth, current = [], 0, ""
    for char in clean(text):
        if char in "（(":
            depth += 1
        elif char in "）)":
            depth = max(depth - 1, 0)
        if char in "、," and depth == 0:
            parts.append(current)
            current = ""
        else:
            current += char
    parts.append(current)
    result = []
    for part in parts:
        match = APPEARANCE.match(part.strip())
        if match and match.group(1).strip():
            result.append((match.group(1).strip(), split_names(match.group(2))))
    return result


def parse(path: Path) -> list:
    """表を (作品の略称, 曲名, 別名のリスト, 登場作品のリスト, メモ) の並びにする。"""
    rows, abbreviation, index = [], None, None
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        heading = HEADING.match(line.strip())
        if heading:
            abbreviation = heading.group(1).strip()
            continue
        if not line.strip().startswith("|") or abbreviation is None:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if clean(cells[0]) == "曲名":  # 見出し行から列の位置を読む（列が増えても読める）
            index = {clean(name).split("（")[0]: i for i, name in enumerate(cells)}
            continue
        if index is None or not cells[0] or set(cells[0]) <= set("-: "):
            continue
        cells += [""] * len(index)
        title, names, works, memo = (
            cells[index[column]] if column in index else "" for column in COLUMNS)
        title = re.sub(r"\s*×\d+$", "", clean(title))
        rows.append((abbreviation, title, split_names(names), split_works(works),
                     memo.strip()))
    return rows


def write_rules(path: Path, header: list, rows: list) -> None:
    temporary = path.with_suffix(".csv.part")
    with open(temporary, "w", encoding="utf-8", newline="") as file:
        file.write("".join(f"# {line}\n" for line in header))
        csv.writer(file, lineterminator="\n").writerows(rows)
    temporary.replace(path)


def import_(path: Path) -> int:
    rows = parse(path)
    if not rows:
        print(f"表が読めませんでした: {path}", file=sys.stderr)
        return 1
    known = {(intro.canon((intro.work_abbreviations(track.work) or (track.work,))[0]),
              track.song) for track in intro.load_tracks()}
    unknown_works = set()
    aliases, appearances = [], []
    for abbreviation, title, names, works, _memo in rows:
        if (intro.canon(abbreviation), intro.canon(title)) not in known:
            probe = intro.IntroTrack("", title, "", "")
            if (intro.canon(abbreviation), probe.song) not in known:
                print(f"曲リストに無い行（曲名が変わっていませんか）: {abbreviation} {title}",
                      file=sys.stderr)
        if names:
            aliases.append([abbreviation, title, "|".join(names)])
        for work, work_names in works:
            if intro.work_names(work) == (work,):
                unknown_works.add(work)
            appearances.append([abbreviation, title, work, "|".join(work_names)])
    for work in sorted(unknown_works):
        print(f"略称の分からない作品: {work}（intro_works.csv に足してください）",
              file=sys.stderr)
    write_rules(intro.ALIASES_PATH, [
        "イントロクイズ: 作品（略称）,曲名,別名（| 区切り）",
        "tools/intro_sheet.py が編集用の表から作る。手では直さない。"], aliases)
    write_rules(intro.APPEARANCES_PATH, [
        "イントロクイズ: 原曲の作品（略称）,曲名,流れる作品（略称）,そこでの呼び名（| 区切り）",
        "tools/intro_sheet.py が編集用の表から作る。手では直さない。"], appearances)
    intro.reset_answer_lists()
    print(f"{len(rows)}曲: 別名 {len(aliases)}行 / 登場作品 {len(appearances)}行 を取り込みました")
    return 0


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] not in ("export", "import"):
        print(__doc__)
        return 1
    path = Path(argv[1]) if len(argv) > 1 else DEFAULT_PATH
    if argv[0] == "import":
        return import_(path)
    return export(path, Path(argv[2]) if len(argv) > 2 else None)


if __name__ == "__main__":
    sys.exit(main())
