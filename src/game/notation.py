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


def _source_label(piece_2d, pid: int, fx: int, fy: int, is_red: bool) -> str:
    """源子纵线记谱：同列有同名同方棋子时用「前/后/中」或数字前缀区分。

    - 兵/卒（pid 7/14）：2 个用「前/后」，3 个及以上用「前/二/三…」（数字前缀）。
    - 其它棋子：2 个用「前/后」，3 个用「前/中/后」，更多沿用「前/中/后」。
    排序规则：红方 y 较大为「前」（更靠近对方），黑方 y 较小为「前」。
    """
    same = [y for y in range(10) if piece_2d[y][fx] == pid]
    if len(same) <= 1:
        return file_name(fx, is_red)
    ordered = sorted(same, reverse=is_red)  # 红方大 y 在前（靠近对方），黑方小 y 在前
    idx = ordered.index(fy)
    n = len(ordered)
    if pid in (7, 14):  # 兵/卒：前 + 中文数字序号
        if idx == 0:
            return '前'
        return '二三四五六七八九'[idx - 1]
    if n == 2:
        return '前' if idx == 0 else '后'
    if idx == 0:
        return '前'
    if idx == n // 2:
        return '中'
    return '后'


def move_to_chinese(pid: int, fx: int, fy: int, tx: int, ty: int,
                    board=None) -> str:
    """将一步着法转为标准中文记谱，如「炮二平五」「马八进七」。

    board 为可选当前棋盘二维数组：提供时若同列存在同名同方棋子，源子改用
    「前/后/中」或数字前缀区分，与标准记谱及反向解析保持一致。
    黑方走法使用全角数字（与 Android 版 ChineseChess 保存格式一致）。
    """
    if pid <= 0:
        return ""
    name = piece_name(pid)
    is_red = pid >= 8
    # 仅当同列存在其它同名同方棋子时才用「前/后/中/数字」前缀（置于名前），
    # 否则用普通纵线名（置于名后）。注意：单列棋子纵线名（红方中文数字）
    # 不可误判为前缀。
    if board is not None and any(board[y][fx] == pid for y in range(10) if y != fy):
        src = _source_label(board, pid, fx, fy, is_red)
        body = src + name
    else:
        body = name + file_name(fx, is_red)
    result = (body + move_type(fy, ty, is_red) +
              target_position(fx, fy, tx, ty, pid, is_red))
    # 黑方走法使用全角数字
    if not is_red:
        result = result.translate(str.maketrans('0123456789', '０１２３４５６７８９'))
    return result


# 反向解析：首字 -> 棋子 id。马/车/炮 红黑同字，需借行棋方消歧。
_RED_NAMES = {'帅': 8, '仕': 9, '相': 10, '马': 11, '车': 12, '炮': 13, '兵': 14}
_BLACK_NAMES = {'将': 1, '士': 2, '象': 3, '马': 4, '车': 5, '炮': 6, '卒': 7}


def _normalize_notation(notation: str) -> str:
    """将全角数字（０-９）转为半角（0-9），兼容不同来源棋谱的记谱差异。"""
    return notation.translate(str.maketrans('０１２３４５６７８９', '0123456789'))


_CN_NUM = '一二三四五六七八九'
def _file_char_to_num(ch: str):
    """将纵线字符解析为 1-9 的列序号；支持中文数字与半/全角阿拉伯数字。

    返回 None 表示无法识别为纵线。
    """
    if ch in _CN_NUM:
        return _CN_NUM.index(ch) + 1
    n = _normalize_notation(ch)
    if n in '123456789':
        return int(n)
    return None


def _canon_notation(notation: str) -> str:
    """将记谱规约为「数字规范形」：全角->半角、中文数字->阿拉伯数字，

    仅保留棋子名/前中后/进平退 与列序号数字，使红黑、不同数字写法的记谱可比较。
    棋子名与 前/后/中 不含数字，替换安全。
    """
    s = _normalize_notation(notation)
    return s.translate(str.maketrans(_CN_NUM, '123456789'))


def chinese_to_move(piece_2d, is_red_turn: bool, notation: str):
    """将中文着法记谱（如「炮二平五」）解析为 (fx, fy, tx, ty)。

    piece_2d: 走子「前」的棋盘二维数组；is_red_turn: 该步是否为红方走子。
    无法解析（记谱非法/无匹配走法）时返回 None。

    支持两种源子表示：
      - 纵线名（如「炮二平五」「卒５平６」）
      - 「前/后 + 棋子名」（同列有同名同方棋子时区分，如「前卒平五」）
    """
    if not notation or len(notation) < 4:
        return None
    # 兼容全角数字记谱（如「卒５平６」），统一转为半角再解析
    notation = _normalize_notation(notation)

    from .rule import possible_moves

    def _match_at(fx, fy, pid):
        for m in possible_moves(piece_2d, fx, fy, pid):
            # move_to_chinese 对红黑、前后/中/数字前缀、全角/半角数字的记谱风格不一，
            # 因此统一转为「数字规范形」再比较：红黑与各种数字写法均能匹配。
            gen = move_to_chinese(pid, fx, fy, m.x, m.y, piece_2d)
            if _canon_notation(gen) == _canon_notation(notation):
                return (fx, fy, m.x, m.y)
        return None

    # 前/后/中 或数字前缀记谱：notation[0] 为前缀，notation[1] 为棋子名
    if (notation[0] in ('前', '后', '中')
            or notation[0] in '一二三四五六七八九'):
        pch = notation[1]
        pid = _RED_NAMES.get(pch) if is_red_turn else _BLACK_NAMES.get(pch)
        if pid is None:
            return None
        for y in range(10):
            for x in range(9):
                if piece_2d[y][x] == pid:
                    res = _match_at(x, y, pid)
                    if res is not None:
                        return res
        return None

    ch = notation[0]
    # 依据行棋方确定棋子 id（马/车/炮 红黑同字，靠 is_red_turn 消歧）
    pid = _RED_NAMES.get(ch) if is_red_turn else _BLACK_NAMES.get(ch)
    if pid is None:
        return None
    # 源纵线 -> fx。纵线字符可能用中文数字（红方惯例）或半/全角阿拉伯数字
    # （黑方惯例），这里统一识别，兼容不同来源、不同生成版本的棋谱。
    fch = notation[1]
    num = _file_char_to_num(fch)
    if num is None:
        return None
    fx = 8 - (num - 1) if is_red_turn else (num - 1)
    # 定位该子在棋盘上的纵坐标 fy（同一方同类型棋子不会同列）
    fy = None
    for y in range(10):
        if piece_2d[y][fx] == pid:
            fy = y
            break
    if fy is None:
        return None
    return _match_at(fx, fy, pid)
