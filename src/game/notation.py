"""中国象棋标准中文记谱（移植自 Android convertMoveToChineseNotation）。

坐标约定与 ChessInfo 一致：x 为列 0-8，y 为行 0-9；
y=0 为红方底线（下方），y=9 为黑方底线（上方）。
棋子编号：黑 1-7（将/士/象/马/车/炮/卒），红 8-14（帅/仕/相/马/车/炮/兵）。
"""

RED_FILES = ["一", "二", "三", "四", "五", "六", "七", "八", "九"]
BLACK_FILES = ["1", "2", "3", "4", "5", "6", "7", "8", "9"]

PIECE_NAMES = {
    1: "将", 2: "士", 3: "象", 4: "马", 5: "车", 6: "炮", 7: "卒",
    8: "帅", 9: "仕", 10: "相", 11: "马", 12: "车", 13: "炮", 14: "兵",
}

RED_STEPS = ["", "一", "二", "三", "四", "五", "六", "七", "八", "九"]
BLACK_STEPS = ["", "1", "2", "3", "4", "5", "6", "7", "8", "9"]


def piece_name(pid: int) -> str:
    return PIECE_NAMES.get(pid, "")


def file_name(x: int, is_red: bool) -> str:
    """纵线名称：红方从右到左（右=一），黑方从左到右（左=1）。"""
    if is_red:
        return RED_FILES[8 - x]
    return BLACK_FILES[x]


def move_type(fy: int, ty: int, is_red: bool) -> str:
    dy = ty - fy
    if is_red:
        if dy > 0:
            return "进"
        if dy < 0:
            return "退"
        return "平"
    else:
        if dy < 0:
            return "进"
        if dy > 0:
            return "退"
        return "平"


def target_position(fx: int, fy: int, tx: int, ty: int,
                    pid: int, is_red: bool) -> str:
    """目标表示：直线棋子（将/车/炮/兵）同纵线进退用步数，否则用目标纵线。"""
    straight = pid in (1, 5, 6, 7, 8, 12, 13, 14)
    if straight and fx == tx:
        steps = abs(ty - fy)
        return RED_STEPS[steps] if is_red else BLACK_STEPS[steps]
    return file_name(tx, is_red)


def move_to_chinese(pid: int, fx: int, fy: int, tx: int, ty: int) -> str:
    """将一步着法转为标准中文记谱，如「炮二平五」「马八进七」。"""
    if pid <= 0:
        return ""
    name = piece_name(pid)
    is_red = pid >= 8
    return (name + file_name(fx, is_red) +
            move_type(fy, ty, is_red) +
            target_position(fx, fy, tx, ty, pid, is_red))
