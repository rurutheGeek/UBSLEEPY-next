# -*- coding: utf-8 -*-
# logging_setup.py
"""標準 logging の設定と、Discord へ警告以上を送るためのハンドラ。"""
import logging
from collections import deque
from datetime import datetime
from zoneinfo import ZoneInfo

LOGGER_NAME = "ubsleepy"
logger = logging.getLogger(LOGGER_NAME)

_CONSOLE_MARK = "_ubsleepy_console_handler"


def _jst_converter(secs):
    return datetime.fromtimestamp(secs, ZoneInfo("Asia/Tokyo")).timetuple()


def setup_logging(level=logging.INFO):
    """コンソール出力を用意する。二重に呼んでもハンドラは増やさない。"""
    logger.setLevel(logging.DEBUG)

    for handler in logger.handlers:
        if getattr(handler, _CONSOLE_MARK, False):
            return

    console = logging.StreamHandler()
    console.setFormatter(
        logging.Formatter("[%(asctime)s|%(levelname)s] %(message)s", datefmt="%H:%M:%S")
    )
    console.formatter.converter = _jst_converter
    console.setLevel(level)
    setattr(console, _CONSOLE_MARK, True)
    logger.addHandler(console)


class DiscordLogHandler(logging.Handler):
    """警告以上を貯めておき、Cog が Discord へ流す。"""

    def __init__(self, level=logging.WARNING, maxlen=1000):
        super().__init__(level)
        self.records = deque(maxlen=maxlen)
        self.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))

    def emit(self, record):
        if record.levelno < self.level:
            return
        try:
            self.records.append(self.format(record))
        except Exception:
            self.handleError(record)

    def drain(self):
        lines = list(self.records)
        self.records.clear()
        return lines

    def requeue(self, lines):
        """送れなかった行を元の順で戻す。"""
        for line in reversed(lines):
            self.records.appendleft(line)