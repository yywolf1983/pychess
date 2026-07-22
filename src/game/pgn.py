"""中国象棋 PGN 棋谱的解析与生成。

棋谱记谱采用标准中文记谱（如「炮二平五 马8进7」），与 Android 版 ChineseChess
的 NotationManager 保持一致；非标准起点（自定义摆棋 / 黑先）通过 FEN 头完整复现。

PGN 形如：
    [Event "..."]
    [Red "玩家"]
    [Black "电脑"]
    [Result "*"]
    [FEN "..."]        ; 仅当非标准起点时存在
    [Setup "1"]

    1. 炮二平五 马8进7 2. 车一平二 车9平8 ...
"""

import re
from datetime import datetime

from .notation import move_to_chinese, chinese_to_move
from .pos import Pos
from .move import Move
from .board import ChessInfo


# 与 Pikafish 引擎一致的 FEN 棋子映射（红方大写 / 黑方小写）
_FEN_TO_PIECE = {
    'k': 1, 'a': 2, 'b': 3, 'n': 4, 'r': 5, 'c': 6, 'p': 7,
    'K': 8, 'A': 9, 'B': 10, 'N': 11, 'R': 12, 'C': 13, 'P': 14,
}
_PIECE_TO_FEN = {v: k for k, v in _FEN_TO_PIECE.items()}


def standard_board():
    """返回标准开局二维棋盘（新实例，避免共享引用）。"""
    return [row[:] for row in ChessInfo().piece]


def is_standard_start(piece_2d):
    std = standard_board()
    for y in range(10):
        for x in range(9):
            if piece_2d[y][x] != std[y][x]:
                return False
    return True


def board_array_to_fen(piece_2d, is_red_go):
    """二维棋盘 -> FEN 串（红方大写，行优先，附带行棋方）。"""
    rows = []
    for y in range(9, -1, -1):
        empty = 0
        cells = []
        for x in range(9):
            p = piece_2d[y][x]
            if p == 0:
                empty += 1
            else:
                if empty:
                    cells.append(str(empty))
                    empty = 0
                cells.append(_PIECE_TO_FEN.get(p, ' '))
        if empty:
            cells.append(str(empty))
        rows.append(''.join(cells))
    turn = 'w' if is_red_go else 'b'
    return f"{'/'.join(rows)} {turn} - - 0 1"


def fen_to_board_array(fen):
    """FEN 串 -> (piece_2d, is_red_go)。解析失败返回 (None, True)。"""
    if not fen:
        return None, True
    parts = fen.strip().split()
    board_part = parts[0]
    turn = parts[1] if len(parts) > 1 else 'w'
    rows = board_part.split('/')
    if len(rows) != 10:
        return None, True
    piece_2d = [[0] * 9 for _ in range(10)]
    try:
        for i, row in enumerate(rows):
            y = 9 - i  # rows[0] 为黑方底线（y=9）
            x = 0
            for ch in row:
                if ch.isdigit():
                    x += int(ch)
                elif ch in _FEN_TO_PIECE:
                    piece_2d[y][x] = _FEN_TO_PIECE[ch]
                    x += 1
                else:
                    x += 1
    except Exception:
        return None, True
    return piece_2d, (turn == 'w')


def _strip_annotations(token):
    return token.rstrip('+#!?').strip()


def parse_pgn(text):
    """解析 PGN 文本 -> {'headers': dict, 'moves': [notation_str, ...]}。

    moves 为按先后手顺序排列的中文着法串（已去除注释、着法序号、变着符号）。
    """
    headers = {}
    header_re = re.compile(r'^\s*\[\s*([A-Za-z0-9_]+)\s+"([^"]*)"\s*\]\s*$')
    movetext_parts = []
    for line in text.splitlines():
        if header_re.match(line):
            m = header_re.match(line)
            headers[m.group(1)] = m.group(2)
            continue
        stripped = line.strip()
        if not stripped or stripped.startswith('%'):
            continue
        movetext_parts.append(line)
    movetext = '\n'.join(movetext_parts)

    # 去除花括号注释、分号注释、变着括号
    movetext = re.sub(r'\{[^}]*\}', ' ', movetext)
    movetext = re.sub(r';[^\n]*', ' ', movetext)
    movetext = re.sub(r'\([^)]*\)', ' ', movetext)

    moves = []
    for tok in movetext.split():
        if re.match(r'^\d+\.+$', tok):      # 着法序号：1. / 12... / 1...
            continue
        if tok in ('1-0', '0-1', '1/2-1/2', '*'):
            continue
        tok = _strip_annotations(tok)
        # 仅保留合法着法，过滤「感谢使用...」等尾部废文本。
        # 着法首字为棋子名（将/士/象/车/炮/卒/帅/仕/相/兵）或以「前/后」区分的同列棋子。
        if tok and (tok[0] in '将士象马车炮卒帅仕相兵前後'):
            moves.append(tok)
    return {'headers': headers, 'moves': moves}


def moves_to_pgn_text(move_strs, headers=None, start_is_red=True):
    """将中文着法串列表渲染为标准 PGN 文本。"""
    """将中文着法串列表渲染为与 Android 版 ChineseChess 一致的 PGN 文本：
    标签头（含 Game/Red/Black/Team/Result/ECCO/.../FEN）+ 开头块注释
    {#1,1#} + 红黑分行走法（红带序号，黑缩进，各带评估注释）。
    """
    headers = dict(headers or {})
    lines = []
    for key in ('Game', 'Event', 'Round', 'Date', 'Site',
                'RedTeam', 'Red', 'BlackTeam', 'Black',
                'Result', 'ECCO', 'Opening', 'Variation', 'Mode'):
        val = headers.get(key, '')
        lines.append(f'[{key} "{val}"]')
    if 'FEN' in headers:
        lines.append(f'[FEN "{headers["FEN"]}"]')
    lines.append('')
    lines.append('{#1,1#}')
    lines.append('')

    body = []
    n = 1
    i = 0
    while i < len(move_strs):
        red = move_strs[i]
        black = move_strs[i + 1] if i + 1 < len(move_strs) else None
        body.append(f'  {n}. {red} {{#0,0#}}')
        if black:
            body.append(f'      {black} {{#50,0#}}')
        i += 2
        n += 1
    body.append('  *')

    return '\n'.join(lines) + '\n' + '\n'.join(body)


def build_pgn(chess_info, move_history, start_board, start_is_red, extra_headers=None):
    """由当前对局信息生成完整 PGN 文本。

    start_board: 开局（或摆棋自定义）棋盘；start_is_red: 开局行棋方。
    """
    piece = [row[:] for row in start_board]
    is_red = start_is_red
    move_strs = []
    for mv in move_history:
        fx, fy, tx, ty = mv.from_pos.x, mv.from_pos.y, mv.to_pos.x, mv.to_pos.y
        pid = piece[fy][fx]
        move_strs.append(move_to_chinese(pid, fx, fy, tx, ty, piece))
        piece[ty][tx] = pid
        piece[fy][fx] = 0
        is_red = not is_red

    headers = {
        'Game': 'Chinese Chess',
        'Event': 'PyChess 对局',
        'Site': 'PyChess',
        'Date': datetime.now().strftime('%Y.%m.%d'),
        'Round': '-',
        'RedTeam': '',
        'Red': '红方',
        'BlackTeam': '',
        'Black': '黑方',
        'Result': '*',
        'ECCO': '',
        'Opening': '',
        'Variation': '',
    }
    if extra_headers:
        headers.update(extra_headers)

    # 非标准起点（自定义摆棋 / 黑先）写入 FEN，保证可完整复现
    if (not start_is_red) or (not is_standard_start(start_board)):
        headers['FEN'] = board_array_to_fen(start_board, start_is_red)

    return moves_to_pgn_text(move_strs, headers, start_is_red)
