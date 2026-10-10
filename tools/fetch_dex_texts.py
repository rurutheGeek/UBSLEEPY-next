#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""図鑑説明クイズ用の説明文と進化のつながりを pkdb から resource/ へ書き出す。

resource/pokedex_text.csv（説明文）と resource/pokedex_evolution.csv（進化）。

Botは PKDB_PASSWORD があれば pkdb を直接読むので、これが要るのは
pkdb へつながない手元（debug_cli.py など）で図鑑説明クイズを試すときだけ。
書き出したCSVは Git に入れない。

    python tools/fetch_dex_texts.py

pkdbへは apps-01 のコンテナの psql を pkdb_reader で使う（SSH鍵が要る）。
別のつなぎ方をするときは、psql のコマンドを DEX_TEXT_PSQL に入れる。
"""
import os
from pathlib import Path
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot_module import dex_text  # noqa: E402

DEFAULT_PSQL = ("ssh -i ~/.ssh/id_ed25519_pve debian@192.168.10.105 "
                "sudo docker exec -i pkdb-db-1 psql -U pkdb_reader -d sleepy_pkdb")
COPIES = (
    (dex_text.DEX_TEXT_PATH,
     "SELECT t.ndex_number, t.form_id, s.title_name AS title, t.text "
     "FROM pokemon_pokedex_text t JOIN title_solo s ON s.title_id = t.title_id "
     "ORDER BY t.ndex_number, t.form_id, t.title_id"),
    (dex_text.EVOLUTION_PATH,
     "SELECT DISTINCT before_ndex_number, after_ndex_number "
     "FROM pokemon_evolution ORDER BY 1, 2"),
)


def main() -> int:
    command = shlex.split(os.environ.get("DEX_TEXT_PSQL", DEFAULT_PSQL))
    command += ["-v", "ON_ERROR_STOP=1", "-q"]
    for target, select in COPIES:
        done = subprocess.run(
            command, input=f"COPY ({select}) TO STDOUT WITH CSV HEADER",
            text=True, capture_output=True)
        if done.returncode:
            print(f"pkdbで失敗しました:\n{done.stderr.strip()}", file=sys.stderr)
            return 1
        path = Path(__file__).resolve().parents[1] / target
        path.write_text(done.stdout, encoding="utf-8")
        print(f"{path}: {len(done.stdout.splitlines()) - 1}件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
