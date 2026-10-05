#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""鳴き声クイズ用の鳴き声をPokeAPIから取得して resource/cry/ へ置く。

    python tools/fetch_cries.py            # 未取得ぶんだけ
    python tools/fetch_cries.py --force    # 取得済みも取り直す
    python tools/fetch_cries.py --limit 5  # 動作確認

基本形態（form_id=00）の全国図鑑番号から、あたらしい鳴き声
（cries/pokemon/latest/{番号}.ogg）と、BWまでの古い鳴き声
（cries/pokemon/legacy/{番号}.ogg）をそれぞれ
resource/cry/latest/ と resource/cry/legacy/ へ置く。
legacy は 1〜649 ぶんだけなので、無いものは missing として飛ばす。
クイズはここをローカル参照する（外部へは取りに行かない）。
"""
import argparse
from pathlib import Path
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bot_module.config  # noqa: F401  設定を読み込むため
from bot_module.pokedex import get_pokedex

BASE_URL = "https://raw.githubusercontent.com/PokeAPI/cries/main/cries/pokemon"
KINDS = ("latest", "legacy")
OUTPUT_DIR = Path("resource/cry")


def fetch(url: str, path: Path) -> None:
    """1件ダウンロードする。途中で落ちても壊れたファイルを残さない。"""
    temporary = path.with_suffix(path.suffix + ".part")
    with urllib.request.urlopen(url, timeout=30) as response:
        temporary.write_bytes(response.read())
    temporary.replace(path)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="取得済みも取り直す")
    parser.add_argument("--limit", type=int, default=0, help="種類ごとに取得する最大件数（0は全部）")
    parser.add_argument("--sleep", type=float, default=0.05, help="1件ごとの待ち（秒）")
    args = parser.parse_args(argv)

    numbers = sorted({p.ndex_number for p in get_pokedex().records if p.form_id == "00"})
    fetched = skipped = missing = failed = 0
    for kind in KINDS:
        directory = OUTPUT_DIR / kind
        directory.mkdir(parents=True, exist_ok=True)
        count = 0
        for number in numbers:
            path = directory / f"{number}.ogg"
            if path.exists() and not args.force:
                skipped += 1
                continue
            if args.limit and count >= args.limit:
                break
            try:
                fetch(f"{BASE_URL}/{kind}/{int(number)}.ogg", path)
                fetched += 1
                count += 1
            except urllib.error.HTTPError as error:
                if error.code == 404:
                    missing += 1  # legacy が無い世代
                else:
                    failed += 1
                    print(f"failed: {kind}/{number} ({error})", file=sys.stderr)
            except (urllib.error.URLError, OSError) as error:
                failed += 1
                print(f"failed: {kind}/{number} ({error})", file=sys.stderr)
            if args.sleep:
                time.sleep(args.sleep)
    print(f"fetched {fetched} / skipped {skipped} / missing {missing} / failed {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
