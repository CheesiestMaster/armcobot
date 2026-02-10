from enum import Enum


class AnsiColor(Enum):
    """
    ANSI escape codes for terminal colors. Used by ColoredFormatter for
    log output. Includes foreground, background, and combined codes.
    """

    # Foreground only colors (with CLR background)
    CLR_CLR = ""
    BLK_CLR = "\033[30m"
    RED_CLR = "\033[31m"
    GRN_CLR = "\033[32m"
    YLW_CLR = "\033[33m"
    BLU_CLR = "\033[34m"
    MGT_CLR = "\033[35m"
    CYN_CLR = "\033[36m"
    WHT_CLR = "\033[37m"

    # Background only colors (with CLR foreground)
    CLR_BLK = "\033[40m"
    CLR_RED = "\033[41m"
    CLR_GRN = "\033[42m"
    CLR_YLW = "\033[43m"
    CLR_BLU = "\033[44m"
    CLR_MGT = "\033[45m"
    CLR_CYN = "\033[46m"
    CLR_WHT = "\033[47m"

    # Foreground + Background combinations (excluding same color)
    BLK_RED = "\033[30m\033[41m"
    BLK_GRN = "\033[30m\033[42m"
    BLK_YLW = "\033[30m\033[43m"
    BLK_BLU = "\033[30m\033[44m"
    BLK_MGT = "\033[30m\033[45m"
    BLK_CYN = "\033[30m\033[46m"
    BLK_WHT = "\033[30m\033[47m"

    RED_BLK = "\033[31m\033[40m"
    RED_GRN = "\033[31m\033[42m"
    RED_YLW = "\033[31m\033[43m"
    RED_BLU = "\033[31m\033[44m"
    RED_MGT = "\033[31m\033[45m"
    RED_CYN = "\033[31m\033[46m"
    RED_WHT = "\033[31m\033[47m"

    GRN_BLK = "\033[32m\033[40m"
    GRN_RED = "\033[32m\033[41m"
    GRN_YLW = "\033[32m\033[43m"
    GRN_BLU = "\033[32m\033[44m"
    GRN_MGT = "\033[32m\033[45m"
    GRN_CYN = "\033[32m\033[46m"
    GRN_WHT = "\033[32m\033[47m"

    YLW_BLK = "\033[33m\033[40m"
    YLW_RED = "\033[33m\033[41m"
    YLW_GRN = "\033[33m\033[42m"
    YLW_BLU = "\033[33m\033[44m"
    YLW_MGT = "\033[33m\033[45m"
    YLW_CYN = "\033[33m\033[46m"
    YLW_WHT = "\033[33m\033[47m"

    BLU_BLK = "\033[34m\033[40m"
    BLU_RED = "\033[34m\033[41m"
    BLU_GRN = "\033[34m\033[42m"
    BLU_YLW = "\033[34m\033[43m"
    BLU_MGT = "\033[34m\033[45m"
    BLU_CYN = "\033[34m\033[46m"
    BLU_WHT = "\033[34m\033[47m"

    MGT_BLK = "\033[35m\033[40m"
    MGT_RED = "\033[35m\033[41m"
    MGT_GRN = "\033[35m\033[42m"
    MGT_YLW = "\033[35m\033[43m"
    MGT_BLU = "\033[35m\033[44m"
    MGT_CYN = "\033[35m\033[46m"
    MGT_WHT = "\033[35m\033[47m"

    CYN_BLK = "\033[36m\033[40m"
    CYN_RED = "\033[36m\033[41m"
    CYN_GRN = "\033[36m\033[42m"
    CYN_YLW = "\033[36m\033[43m"
    CYN_BLU = "\033[36m\033[44m"
    CYN_MGT = "\033[36m\033[45m"
    CYN_WHT = "\033[36m\033[47m"

    WHT_BLK = "\033[37m\033[40m"
    WHT_RED = "\033[37m\033[41m"
    WHT_GRN = "\033[37m\033[42m"
    WHT_YLW = "\033[37m\033[43m"
    WHT_BLU = "\033[37m\033[44m"
    WHT_MGT = "\033[37m\033[45m"
    WHT_CYN = "\033[37m\033[46m"

    # Reset code
    RESET = "\033[0m"