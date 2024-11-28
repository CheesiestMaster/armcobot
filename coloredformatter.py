from ansicolor import AnsiColor
import logging

COLORS = {
    logging.DEBUG: AnsiColor.CYN_CLR,
    logging.INFO: AnsiColor.GRN_CLR,
    logging.WARNING: AnsiColor.YLW_CLR,
    logging.ERROR: AnsiColor.RED_CLR,
    logging.CRITICAL: AnsiColor.BLK_RED,
}

class ColoredFormatter(logging.Formatter):
    def __init__(self, *args, **kwargs):
        self.COLORS = COLORS.copy()
        super().__init__(*args, **kwargs)

    def format(self, record):
        color = self.COLORS.get(record.levelno, AnsiColor.WHT_CLR)
        
        record.msg = f"{color.value}{record.msg}{AnsiColor.RESET.value}"
        return super().format(record)

    def set_color(self, level, color):
        # check if level is an int and in the keys of COLORS
        if not isinstance(level, int) or level not in self.COLORS:
            raise ValueError(f"Invalid log level: {level}")
        if not isinstance(color, AnsiColor):
            raise ValueError(f"Invalid color: {color}")
        self.COLORS[level] = color
