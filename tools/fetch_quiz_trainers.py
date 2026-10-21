#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""トレーナークイズ用の手持ちを pkdb から resource/quiz_trainers.csv へ書き出す。

Botは PKDB_PASSWORD があれば pkdb を直接読むので、これが要るのは
pkdb へつながない手元（debug_cli.py など）でトレーナークイズを試すときだけ。
書き出したCSVは Git に入れない。

    python tools/fetch_quiz_trainers.py

pkdbへは apps-01 のコンテナの psql を pkdb_reader で使う（SSH鍵が要る）。
別のつなぎ方をするときは、psql のコマンドを QUIZ_TRAINER_PSQL に入れる。
"""
import os
from pathlib import Path
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot_module import trainer_quiz  # noqa: E402

DEFAULT_PSQL = ("ssh -i ~/.ssh/id_ed25519_pve debian@192.168.10.105 "
                "sudo docker exec -i pkdb-db-1 psql -U pkdb_reader -d sleepy_pkdb")


def main() -> int:
    command = shlex.split(os.environ.get("QUIZ_TRAINER_PSQL", DEFAULT_PSQL))
    command += ["-v", "ON_ERROR_STOP=1", "-q"]
    select = " ".join(trainer_quiz.TRAINER_SQL.split())
    done = subprocess.run(
        command,
        input=f"SET search_path = pokemondb; COPY ({select}) TO STDOUT WITH CSV HEADER",
        text=True, capture_output=True)
    if done.returncode:
        print(f"pkdbで失敗しました:\n{done.stderr.strip()}", file=sys.stderr)
        return 1
    path = Path(__file__).resolve().parents[1] / trainer_quiz.TRAINER_PATH
    path.write_text(done.stdout, encoding="utf-8")
    print(f"{path}: {len(done.stdout.splitlines()) - 1}件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
