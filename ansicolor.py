from enum import Enum
from itertools import product

# we will be using the enum meta programming to create the enum

foreground = { # dict of color names to ansi sequences
    "CLR": "",
    "BLK": "\033[30m",
    "RED": "\033[31m",
    "GRN": "\033[32m",
    "YLW": "\033[33m",
    "BLU": "\033[34m",
    "MGT": "\033[35m",
    "CYN": "\033[36m",
    "WHT": "\033[37m",

}

background = {
    "CLR": "",
    "BLK": "\033[40m",
    "RED": "\033[41m",
    "GRN": "\033[42m",
    "YLW": "\033[43m",
    "BLU": "\033[44m",
    "MGT": "\033[45m",
    "CYN": "\033[46m",
    "WHT": "\033[47m",
}

codes = {}
# use product to create the full set where f!=b in the format of f_b
for f, b in product(foreground, background):
    if f != b:
        codes[f"{f}_{b}"] = foreground[f] + background[b]

codes["RESET"] = "\033[0m"

AnsiColor = Enum("AnsiColor", codes)