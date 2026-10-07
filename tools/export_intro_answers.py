#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""イントロクイズの回答対応リストを、確認用のCSVに書き出す。

    python tools/export_intro_answers.py [出力先.csv]

曲（別バージョンはまとめる）ごとに、どの答えが正解になるかを並べる。
- 略称なしで正解: その言い方だけで曲が1つに決まる答え
- 略称つきで正解: 作品の略称を頭につければ正解になる答え
- 曲が決まらない: 同じ作品に同じ相手の曲がいくつかあり、正解にならない答え
直したいときは resource/intro_aliases.csv（別名）・intro_works.csv（略称）・
intro_words.csv（言い換え）を編集する。
"""
import csv
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot_module import intro  # noqa: E402

FIELDS = ("略称", "作品", "曲名", "曲数", "略称なしで正解", "略称つきで正解",
          "曲が決まらない", "ほかに流れる作品", "別名（リスト）", "修正メモ")


def candidates(track) -> list:
    """確認用に見せる答えの言い方（曲名から取り出した相手と別名）。"""
    names = [*intro.answer_cores(track.title), *track.listed_aliases, *track.aliases]
    return list(dict.fromkeys([*names, track.title]))


def rows() -> list:
    groups = {}
    for track in intro.load_tracks():
        groups.setdefault((track.work, track.song), []).append(track)
    result = []
    for (work, _song), tracks in groups.items():
        track = min(tracks, key=lambda t: len(t.title))
        abbreviations = intro.work_abbreviations(work)
        short = abbreviations[0] if abbreviations else work
        plain, qualified, unclear = [], [], []
        for name in candidates(track):
            verdict = intro.judge(track, name)
            if verdict == intro.CORRECT:
                plain.append(name)
            elif intro.judge(track, short + name) == intro.CORRECT:
                qualified.append(short + name)
            else:
                unclear.append(name)
        result.append({
            "略称": "／".join(abbreviations), "作品": work, "曲名": track.title,
            "曲数": len(tracks), "略称なしで正解": " | ".join(plain),
            "略称つきで正解": " | ".join(qualified),
            "曲が決まらない": " | ".join(unclear),
            "ほかに流れる作品": " | ".join(
                work + (f"（{'・'.join(names)}）" if names else "")
                for work, names in track.appearances),
            "別名（リスト）": " | ".join(track.listed_aliases), "修正メモ": "",
        })
    return sorted(result, key=lambda row: (row["作品"], row["曲名"]))


def markdown(data: list) -> str:
    """ブラウザで読みやすい、作品ごとの表（Nextcloudでそのまま見られる）。"""
    lines = [
        "# イントロクイズ 回答対応リスト（確認用）", "",
        f"{len(data)}曲（別バージョンは「×曲数」でまとめて表示）。", "",
        "- **略称なしで正解**: その答えだけで曲が1つに決まるもの",
        "- **略称つきで正解**: 作品の略称を頭（か末尾）につければ正解になるもの",
        "- **曲が決まらない**: 同じ作品に同じ相手の曲が複数あるなどで、正解にならないもの",
        "- ひらがな・カタカナ・全角半角・記号のちがいは無視。相手に「戦」「VS」をつけても可",
        "- 曲名そのままの答え（略称つきも可）は表から省略",
        "- **ほかに流れる作品**: 再録・流用で流れる作品。その略称でも答えられ、絞り込みにも入る",
    ]

    def cell(row, key):
        answers = [a for a in row[key].split(" | ")
                   if a and not a.endswith(row["曲名"])]
        return "、".join(answers).replace("|", "／")

    work = None
    for row in data:
        if row["作品"] != work:
            work = row["作品"]
            lines += ["", f"## {work}（略称: {row['略称']}）", "",
                      "| 曲名 | 略称なしで正解 | 略称つきで正解 | 曲が決まらない "
                      "| ほかに流れる作品 |",
                      "|---|---|---|---|---|"]
        count = f" ×{row['曲数']}" if row["曲数"] != 1 else ""
        lines.append(
            f"| {row['曲名'].replace('|', '／')}{count} | {cell(row, '略称なしで正解')} "
            f"| {cell(row, '略称つきで正解')} | {cell(row, '曲が決まらない')} "
            f"| {row['ほかに流れる作品'].replace(' | ', '、')} |")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    path = Path(argv[0]) if argv else Path("temp/intro_answers.csv")
    path.parent.mkdir(parents=True, exist_ok=True)
    data = rows()
    with open(path, "w", encoding="utf-8-sig", newline="") as file:  # Excelで開ける
        writer = csv.DictWriter(file, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(data)
    path.with_suffix(".md").write_text(markdown(data), encoding="utf-8")
    print(f"{len(data)}曲 -> {path}（.md も）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
