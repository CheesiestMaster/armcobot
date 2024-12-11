from ansicolor import AnsiColor
from utils import RollingCounter
import logging

COLORS = {
    logging.DEBUG: AnsiColor.CYN_CLR,
    logging.INFO: AnsiColor.GRN_CLR,
    logging.WARNING: AnsiColor.YLW_CLR,
    logging.ERROR: AnsiColor.RED_CLR,
    logging.CRITICAL: AnsiColor.BLK_RED,
}

stats = {
    "today_DEBUG": RollingCounter(24*60*60),
    "today_INFO": RollingCounter(24*60*60),
    "today_WARNING": RollingCounter(24*60*60),
    "today_ERROR": RollingCounter(24*60*60),
    "today_CRITICAL": RollingCounter(24*60*60),
    "today_total": RollingCounter(24*60*60),
    "total_DEBUG": 0,
    "total_INFO": 0,
    "total_WARNING": 0,
    "total_ERROR": 0,
    "total_CRITICAL": 0,
    "total_total": 0,
}

class ColoredFormatter(logging.Formatter):
    def __init__(self, *args, **kwargs):
        self.COLORS = COLORS.copy()
        super().__init__(*args, **kwargs)

    def format(self, record):
        color = self.COLORS.get(record.levelno, AnsiColor.WHT_CLR)
        stats[f"today_{record.levelname}"].set()
        stats["today_total"].set()
        stats[f"total_{record.levelname}"] += 1
        stats["total_total"] += 1
        record.msg = f"{color.value}{record.msg}{AnsiColor.RESET.value}"
        return super().format(record)

    def set_color(self, level, color):
        # check if level is an int and in the keys of COLORS
        if not isinstance(level, int) or level not in self.COLORS:
            raise ValueError(f"Invalid log level: {level}")
        if not isinstance(color, AnsiColor):
            raise ValueError(f"Invalid color: {color}")
        self.COLORS[level] = color
