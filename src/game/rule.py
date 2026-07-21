from typing import List, Optional
from .pos import Pos

AREA = [
    [3, 3, 3, 4, 4, 4, 3, 3, 3],
    [3, 3, 3, 4, 4, 4, 3, 3, 3],
    [3, 3, 3, 4, 4, 4, 3, 3, 3],
    [3, 3, 3, 3, 3, 3, 3, 3, 3],
    [3, 3, 3, 3, 3, 3, 3, 3, 3],
    [1, 1, 1, 1, 1, 1, 1, 1, 1],
    [1, 1, 1, 1, 1, 1, 1, 1, 1],
    [1, 1, 1, 2, 2, 2, 1, 1, 1],
    [1, 1, 1, 2, 2, 2, 1, 1, 1],
    [1, 1, 1, 2, 2, 2, 1, 1, 1]
]

BLACK_KING = 1
BLACK_ADVISOR = 2
BLACK_ELEPHANT = 3
BLACK_KNIGHT = 4
BLACK_ROOK = 5
BLACK_CANNON = 6
BLACK_PAWN = 7

RED_KING = 8
RED_ADVISOR = 9
RED_ELEPHANT = 10
RED_KNIGHT = 11
RED_ROOK = 12
RED_CANNON = 13
RED_PAWN = 14


def in_area(x: int, y: int) -> int:
    if x < 0 or x > 8 or y < 0 or y > 9:
        return 0
    return AREA[y][x]


def is_same_side(from_id: int, to_id: int) -> bool:
    if to_id == 0:
        return False
    return (from_id <= 7 and to_id <= 7) or (from_id >= 8 and to_id >= 8)


def is_red(piece_id: int) -> bool:
    return piece_id >= 8 and piece_id <= 14


def is_black(piece_id: int) -> bool:
    return piece_id >= 1 and piece_id <= 7


def possible_moves(piece: List[List[int]], from_x: int, from_y: int, piece_id: int) -> List[Pos]:
    ret = []

    if piece is None or len(piece) != 10 or from_x < 0 or from_x >= 9 or from_y < 0 or from_y >= 10:
        return ret

    directions = [[0, 1], [0, -1], [1, 0], [-1, 0]]

    if piece_id == BLACK_KING or piece_id == RED_KING:
        area_val = 2 if piece_id == BLACK_KING else 4
        for dir in directions:
            to_x = from_x + dir[0]
            to_y = from_y + dir[1]
            if in_area(to_x, to_y) == area_val and not is_same_side(piece_id, piece[to_y][to_x]):
                ret.append(Pos(to_x, to_y))
        eat_pos = fly_king(1 if piece_id == BLACK_KING else 2, from_x, from_y, piece)
        if not eat_pos == Pos(-1, -1):
            ret.append(eat_pos)

    elif piece_id == BLACK_ADVISOR or piece_id == RED_ADVISOR:
        area_val = 2 if piece_id == BLACK_ADVISOR else 4
        advisor_moves = [[1, 1], [1, -1], [-1, 1], [-1, -1]]
        for move in advisor_moves:
            to_x = from_x + move[0]
            to_y = from_y + move[1]
            if in_area(to_x, to_y) == area_val and not is_same_side(piece_id, piece[to_y][to_x]):
                ret.append(Pos(to_x, to_y))

    elif piece_id == BLACK_ELEPHANT or piece_id == RED_ELEPHANT:
        min_area = 1 if piece_id == BLACK_ELEPHANT else 3
        max_area = 2 if piece_id == BLACK_ELEPHANT else 4
        elephant_moves = [[2, 2], [2, -2], [-2, 2], [-2, -2]]
        elephant_legs = [[1, 1], [1, -1], [-1, 1], [-1, -1]]
        for i in range(len(elephant_moves)):
            move = elephant_moves[i]
            leg = elephant_legs[i]
            to_x = from_x + move[0]
            to_y = from_y + move[1]
            leg_x = from_x + leg[0]
            leg_y = from_y + leg[1]
            if (min_area <= in_area(to_x, to_y) <= max_area and
                    not is_same_side(piece_id, piece[to_y][to_x]) and
                    piece[leg_y][leg_x] == 0):
                ret.append(Pos(to_x, to_y))

    elif piece_id == BLACK_KNIGHT or piece_id == RED_KNIGHT:
        knight_moves = [[1, 2], [1, -2], [-1, 2], [-1, -2], [2, 1], [2, -1], [-2, 1], [-2, -1]]
        knight_legs = [[0, 1], [0, -1], [0, 1], [0, -1], [1, 0], [1, 0], [-1, 0], [-1, 0]]
        for i in range(len(knight_moves)):
            move = knight_moves[i]
            leg = knight_legs[i]
            to_x = from_x + move[0]
            to_y = from_y + move[1]
            leg_x = from_x + leg[0]
            leg_y = from_y + leg[1]
            if (0 <= to_x < 9 and 0 <= to_y < 10 and
                    0 <= leg_x < 9 and 0 <= leg_y < 10 and
                    piece[leg_y][leg_x] == 0 and
                    not is_same_side(piece_id, piece[to_y][to_x])):
                ret.append(Pos(to_x, to_y))

    elif piece_id == BLACK_ROOK or piece_id == RED_ROOK:
        for dir in directions:
            x, y = from_x + dir[0], from_y + dir[1]
            while 0 <= x < 9 and 0 <= y < 10:
                if piece[y][x] == 0:
                    ret.append(Pos(x, y))
                else:
                    if not is_same_side(piece_id, piece[y][x]):
                        ret.append(Pos(x, y))
                    break
                x += dir[0]
                y += dir[1]

    elif piece_id == BLACK_CANNON or piece_id == RED_CANNON:
        for dir in directions:
            x, y = from_x + dir[0], from_y + dir[1]
            obstacle_count = 0
            while 0 <= x < 9 and 0 <= y < 10:
                if piece[y][x] == 0:
                    if obstacle_count == 0:
                        ret.append(Pos(x, y))
                else:
                    obstacle_count += 1
                    if obstacle_count == 1:
                        next_x, next_y = x + dir[0], y + dir[1]
                        while 0 <= next_x < 9 and 0 <= next_y < 10:
                            if piece[next_y][next_x] != 0:
                                if not is_same_side(piece_id, piece[next_y][next_x]):
                                    ret.append(Pos(next_x, next_y))
                                break
                            next_x += dir[0]
                            next_y += dir[1]
                x += dir[0]
                y += dir[1]

    elif piece_id == BLACK_PAWN:
        if from_y >= 5:
            to_y = from_y - 1
            if to_y >= 0 and not is_same_side(piece_id, piece[to_y][from_x]):
                ret.append(Pos(from_x, to_y))
        else:
            pawn_moves = [[0, -1], [1, 0], [-1, 0]]
            for move in pawn_moves:
                to_x = from_x + move[0]
                to_y = from_y + move[1]
                if 0 <= to_x < 9 and 0 <= to_y < 10 and not is_same_side(piece_id, piece[to_y][to_x]):
                    ret.append(Pos(to_x, to_y))

    elif piece_id == RED_PAWN:
        if from_y >= 5:
            pawn_moves = [[0, 1], [1, 0], [-1, 0]]
            for move in pawn_moves:
                to_x = from_x + move[0]
                to_y = from_y + move[1]
                if 0 <= to_x < 9 and 0 <= to_y < 10 and not is_same_side(piece_id, piece[to_y][to_x]):
                    ret.append(Pos(to_x, to_y))
        else:
            to_y = from_y + 1
            if to_y < 10 and not is_same_side(piece_id, piece[to_y][from_x]):
                ret.append(Pos(from_x, to_y))

    return ret


def fly_king(id: int, from_x: int, from_y: int, piece: List[List[int]]) -> Pos:
    if piece is None or len(piece) != 10:
        return Pos(-1, -1)
    for i in range(10):
        if piece[i] is None or len(piece[i]) != 9:
            return Pos(-1, -1)

    if from_x < 0 or from_x >= 9 or from_y < 0 or from_y >= 10:
        return Pos(-1, -1)

    if id == 1:
        if from_y < 7 or from_x < 3 or from_x > 5:
            return Pos(-1, -1)
        for i in range(from_y - 1, -1, -1):
            if piece[i][from_x] > 0:
                if piece[i][from_x] == RED_KING:
                    return Pos(from_x, i)
                break
    else:
        if from_y > 2 or from_x < 3 or from_x > 5:
            return Pos(-1, -1)
        for i in range(from_y + 1, 10):
            if piece[i][from_x] > 0:
                if piece[i][from_x] == BLACK_KING:
                    return Pos(from_x, i)
                break

    return Pos(-1, -1)


def is_king_danger(piece: List[List[int]], is_red_king: bool) -> bool:
    if piece is None or len(piece) != 10:
        return False
    for i in range(10):
        if piece[i] is None or len(piece[i]) != 9:
            return False

    king_x, king_y = -1, -1
    target_king = RED_KING if is_red_king else BLACK_KING

    for y in range(10):
        for x in range(9):
            if piece[y][x] == target_king:
                king_x, king_y = x, y
                break
        if king_x != -1:
            break

    if king_x == -1:
        return True

    attack_directions = [[-1, 0], [1, 0], [0, -1], [0, 1]]
    knight_moves = [[1, 2], [1, -2], [-1, 2], [-1, -2], [2, 1], [2, -1], [-2, 1], [-2, -1]]

    for dir in attack_directions:
        x, y = king_x + dir[0], king_y + dir[1]
        obstacle_count = 0
        while 0 <= x < 9 and 0 <= y < 10:
            piece_id = piece[y][x]
            if piece_id != 0:
                is_enemy = piece_id <= 7 if is_red_king else piece_id >= 8
                if is_enemy:
                    if piece_id == BLACK_ROOK or piece_id == RED_ROOK:
                        if obstacle_count == 0:
                            return True
                    elif piece_id == BLACK_CANNON or piece_id == RED_CANNON:
                        if obstacle_count == 1:
                            return True
                    else:
                        break
                    obstacle_count += 1
                else:
                    obstacle_count += 1
            x += dir[0]
            y += dir[1]

    for y in range(10):
        for x in range(9):
            piece_id = piece[y][x]
            is_enemy_cannon = piece_id == BLACK_CANNON if is_red_king else piece_id == RED_CANNON
            if is_enemy_cannon:
                if x == king_x or y == king_y:
                    obstacle_count = 0
                    if x == king_x:
                        start = min(y, king_y) + 1
                        end = max(y, king_y)
                        for i in range(start, end):
                            if piece[i][x] != 0:
                                obstacle_count += 1
                    else:
                        start = min(x, king_x) + 1
                        end = max(x, king_x)
                        for i in range(start, end):
                            if piece[y][i] != 0:
                                obstacle_count += 1
                    if obstacle_count == 1:
                        return True

    for y in range(10):
        for x in range(9):
            piece_id = piece[y][x]
            is_enemy = piece_id == BLACK_KNIGHT if is_red_king else piece_id == RED_KNIGHT
            if is_enemy:
                dx, dy = king_x - x, king_y - y
                if (abs(dx) == 2 and abs(dy) == 1) or (abs(dx) == 1 and abs(dy) == 2):
                    # 别腿马：腿在“走 2 格”方向的内侧相邻格（另一方向偏移恒为 0）
                    if abs(dx) == 2:
                        leg_x, leg_y = x + (1 if dx > 0 else -1), y
                    else:
                        leg_x, leg_y = x, y + (1 if dy > 0 else -1)
                    if 0 <= leg_x < 9 and 0 <= leg_y < 10 and piece[leg_y][leg_x] == 0:
                        return True

    pawn_moves = [[0, 1], [1, 0], [-1, 0]] if is_red_king else [[0, -1], [1, 0], [-1, 0]]
    enemy_pawn = BLACK_PAWN if is_red_king else RED_PAWN

    for move in pawn_moves:
        x, y = king_x + move[0], king_y + move[1]
        if 0 <= x < 9 and 0 <= y < 10:
            if piece[y][x] == enemy_pawn:
                return True

    enemy_king = BLACK_KING if is_red_king else RED_KING
    enemy_king_x, enemy_king_y = -1, -1

    for y in range(10):
        for x in range(9):
            if piece[y][x] == enemy_king:
                enemy_king_x, enemy_king_y = x, y
                break
        if enemy_king_x != -1:
            break

    if enemy_king_x != -1 and enemy_king_x == king_x:
        path_clear = True
        start_y = min(king_y, enemy_king_y) + 1
        end_y = max(king_y, enemy_king_y)
        for y in range(start_y, end_y):
            if piece[y][king_x] != 0:
                path_clear = False
                break
        if path_clear:
            return True

    advisor_moves = [[1, 1], [1, -1], [-1, 1], [-1, -1]]
    enemy_advisor = BLACK_ADVISOR if is_red_king else RED_ADVISOR

    for move in advisor_moves:
        x, y = king_x + move[0], king_y + move[1]
        in_palace = (3 <= x <= 5 and 0 <= y <= 2) if is_red_king else (3 <= x <= 5 and 7 <= y <= 9)
        if in_palace and piece[y][x] == enemy_advisor:
            return True

    return False


def can_defend_check(piece: List[List[int]], from_x: int, from_y: int, piece_id: int) -> bool:
    is_red_side = is_red(piece_id)
    moves = possible_moves(piece, from_x, from_y, piece_id)

    for move in moves:
        temp_piece = [row[:] for row in piece]
        captured = piece[move.y][move.x]
        is_capture_king = captured == BLACK_KING or captured == RED_KING

        temp_piece[move.y][move.x] = piece_id
        temp_piece[from_y][from_x] = 0

        if is_capture_king:
            return True

        if not is_king_danger(temp_piece, is_red_side):
            return True

    return False


def is_checkmate(piece: List[List[int]], is_red_turn: bool) -> bool:
    if not is_king_danger(piece, is_red_turn):
        return False

    for y in range(10):
        for x in range(9):
            piece_id = piece[y][x]
            if piece_id == 0:
                continue
            piece_is_red = is_red(piece_id)
            if piece_is_red != is_red_turn:
                continue
            if can_defend_check(piece, x, y, piece_id):
                return False

    return True


def is_stalemate(piece: List[List[int]], is_red_turn: bool) -> bool:
    if is_king_danger(piece, is_red_turn):
        return False

    for y in range(10):
        for x in range(9):
            piece_id = piece[y][x]
            if piece_id == 0:
                continue
            piece_is_red = is_red(piece_id)
            if piece_is_red != is_red_turn:
                continue

            moves = possible_moves(piece, x, y, piece_id)
            for move in moves:
                temp_piece = [row[:] for row in piece]
                temp_piece[move.y][move.x] = piece_id
                temp_piece[y][x] = 0

                if not is_king_danger(temp_piece, is_red_turn):
                    return False

    return True


def is_king_face_to_face(piece: List[List[int]]) -> bool:
    if piece is None:
        return False

    red_king_x, red_king_y = -1, -1
    black_king_x, black_king_y = -1, -1

    for y in range(10):
        for x in range(9):
            if piece[y][x] == RED_KING:
                red_king_x, red_king_y = x, y
            elif piece[y][x] == BLACK_KING:
                black_king_x, black_king_y = x, y

    if red_king_x == -1 or black_king_x == -1:
        return False

    if red_king_x != black_king_x:
        return False

    start = min(red_king_y, black_king_y) + 1
    end = max(red_king_y, black_king_y)
    for y in range(start, end):
        if piece[y][red_king_x] != 0:
            return False

    return True
