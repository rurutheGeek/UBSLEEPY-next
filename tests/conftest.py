# -*- coding: utf-8 -*-
# tests/conftest.py
# 図鑑CSVやconfig.jsonを読み込むモジュールがあるため、
# どのディレクトリからpytestを実行してもリポジトリ直下で動くようにする。
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

os.chdir(ROOT)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))