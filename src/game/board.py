from typing import List
from .pos import Pos
from .move import Move
from .rule import (
    BLACK_KING, BLACK_ADVISOR, BLACK_ELEPHANT, BLACK_KNIGHT, BLACK_ROOK, BLACK_CANNON, BLACK_PAWN,
    RED_KING, RED_ADVISOR, RED_ELEPHANT, RED_KNIGHT, RED_ROOK, RED_CANNON, RED_PAWN,
    possible_moves, is_king_danger, is_checkmate, is_stalemate, is_red
)


import json
import os

class Setting:
    def __init__(self):
        self.is_music_play = True
        self.is_effect_play = True
        self.m_level = 3
        self.depth = 10
        self.skill_level = 20
        self.multi_pv = 1
        self.contempt = 20
        self.force_variation = True
        self.thinking_time = 3
    
    def save(self):
        config_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'config')
        os.makedirs(config_dir, exist_ok=True)
        config_path = os.path.join(config_dir, 'settings.json')
        
        data = {
            'is_music_play': self.is_music_play,
            'is_effect_play': self.is_effect_play,
            'm_level': self.m_level,
            'depth': self.depth,
            'skill_level': self.skill_level,
            'multi_pv': self.multi_pv,
            'contempt': self.contempt,
            'force_variation': self.force_variation,
            'thinking_time': self.thinking_time
        }
        
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
    
    def load(self):
        config_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'config')
        config_path = os.path.join(config_dir, 'settings.json')
        
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                self.is_music_play = data.get('is_music_play', True)
                self.is_effect_play = data.get('is_effect_play', True)
                self.m_level = data.get('m_level', 3)
                self.depth = data.get('depth', 10)
                self.skill_level = data.get('skill_level', 20)
                self.multi_pv = data.get('multi_pv', 1)
                self.contempt = data.get('contempt', 20)
                self.force_variation = data.get('force_variation', True)
                self.thinking_time = data.get('thinking_time', 3)
            except Exception:
                pass


class ChessInfo:
    def __init__(self):
        self.piece = self._create_initial_board()
        self.is_red_go = True
        self.select = Pos(-1, -1)
        self.pre_pos = Pos(-1, -1)
        self.cur_pos = Pos(-1, -1)
        self.ret: List[Pos] = []
        self.status = 0
        self.is_machine = False
        self.setting = Setting()
        self.is_checked = False
        self.suggest_moves: List[Move] = []
        self.suggest_move_labels: List[str] = []
        self.suggest = None
        self.suggest_replies = []
        self.force_variation = False
        self.variation_randomness = 3
        self.move_history: List[Move] = []

        # 和棋相关状态
        self.peace_round = 0               # 未吃子回合计数（每完整回合 +1）
        self.position_history = {}         # 局面哈希 -> 出现次数（三次重复判定）
        self.total_moves = 0
        self.consecutive_check_red = 0     # 红方连续将军计数
        self.consecutive_check_black = 0   # 黑方连续将军计数
        self.consecutive_attack_red = 0    # 红方连续攻击（长捉）计数
        self.consecutive_attack_black = 0  # 黑方连续攻击（长捉）计数
        self.last_attacked_pos = None      # 上次被攻击棋子的位置
        self.last_attacked_type = 0        # 上次被攻击棋子的类型
        self.last_move_was_check = False
        self.draw_reason = ''              # 和棋原因
        self.draw_offer = None             # 谁发起的和棋请求 ('red'/'black')
        self.draw_offer_pending = None     # 规则触发的和棋提示文案（询问是否和棋）
        self.draw_hint = ''                # 强制变着提示（重复局面/长将/长捉）
        self.draw_offer_suppressed = False # 玩家拒绝规则和棋后，抑制重复弹窗
        self.attack_num_r = 0              # 红方攻击性棋子数
        self.attack_num_b = 0              # 黑方攻击性棋子数
        self.winner = None                 # 认输时的胜方 ('red'/'black')

        # 基准局面：本局开始时的棋盘（标准开局或摆棋自定义局面）。
        # 悔棋时据此精确重放历史，避免摆棋删除的棋子被标准开局重新填回。
        self.base_piece = [row[:] for row in self.piece]
        self.base_red_go = self.is_red_go
        # 支招「跟线」模式：玩家按推荐线行棋时持续提示剩余着法
        self.suggest_track = False
        # 记录开局局面，使三照重复判定从首局面开始计数（否则漏计开局态）
        self._record_position()

    def _create_initial_board(self) -> List[List[int]]:
        board = [[0] * 9 for _ in range(10)]
        
        board[0][0] = RED_ROOK
        board[0][1] = RED_KNIGHT
        board[0][2] = RED_ELEPHANT
        board[0][3] = RED_ADVISOR
        board[0][4] = RED_KING
        board[0][5] = RED_ADVISOR
        board[0][6] = RED_ELEPHANT
        board[0][7] = RED_KNIGHT
        board[0][8] = RED_ROOK
        board[2][1] = RED_CANNON
        board[2][7] = RED_CANNON
        board[3][0] = RED_PAWN
        board[3][2] = RED_PAWN
        board[3][4] = RED_PAWN
        board[3][6] = RED_PAWN
        board[3][8] = RED_PAWN
        
        board[9][0] = BLACK_ROOK
        board[9][1] = BLACK_KNIGHT
        board[9][2] = BLACK_ELEPHANT
        board[9][3] = BLACK_ADVISOR
        board[9][4] = BLACK_KING
        board[9][5] = BLACK_ADVISOR
        board[9][6] = BLACK_ELEPHANT
        board[9][7] = BLACK_KNIGHT
        board[9][8] = BLACK_ROOK
        board[7][1] = BLACK_CANNON
        board[7][7] = BLACK_CANNON
        board[6][0] = BLACK_PAWN
        board[6][2] = BLACK_PAWN
        board[6][4] = BLACK_PAWN
        board[6][6] = BLACK_PAWN
        board[6][8] = BLACK_PAWN
        
        # 注意：红/黑炮应在兵线之后一格（红 y=2、黑 y=7 已是炮位），
        # 兵线分别为红 y=3、黑 y=6，二者不可重叠。
        return board

    def reset(self):
        self.piece = self._create_initial_board()
        self.is_red_go = True
        self.select = Pos(-1, -1)
        self.pre_pos = Pos(-1, -1)
        self.cur_pos = Pos(-1, -1)
        self.ret = []
        self.status = 0
        self.is_machine = False
        self.is_checked = False
        self.suggest_moves = []
        self.suggest_move_labels = []
        self.suggest = None
        self.suggest_replies = []
        self.force_variation = False
        self.suggest_track = False
        self.move_history = []
        self.peace_round = 0
        self.position_history = {}
        self.total_moves = 0
        self.consecutive_check_red = 0
        self.consecutive_check_black = 0
        self.consecutive_attack_red = 0
        self.consecutive_attack_black = 0
        self.last_attacked_pos = None
        self.last_attacked_type = 0
        self.last_move_was_check = False
        self.draw_reason = ''
        self.draw_offer = None
        self.draw_offer_pending = None
        self.draw_hint = ''
        self.draw_offer_suppressed = False
        self.attack_num_r = 0
        self.attack_num_b = 0
        self.winner = None
        # 新局：基准局面回到标准开局
        self.base_piece = [row[:] for row in self.piece]
        self.base_red_go = self.is_red_go
        self.suggest_track = False
        # 记录开局局面，使三照重复判定从首局面开始计数（否则漏计开局态）
        self._record_position()

    def restore_base(self):
        """将棋盘恢复到本局基准局面（标准开局或摆棋自定义局面），
        并复位交互/和棋状态，但保留 move_history 供上层重新写入。
        用于悔棋重放，避免摆棋删除的棋子被标准开局重新填回。"""
        self.piece = [row[:] for row in self.base_piece]
        self.is_red_go = self.base_red_go
        self.select = Pos(-1, -1)
        self.pre_pos = Pos(-1, -1)
        self.cur_pos = Pos(-1, -1)
        self.ret = []
        self.status = 0
        self.is_machine = False
        self.is_checked = False
        self.suggest_moves = []
        self.suggest_move_labels = []
        self.suggest = None
        self.suggest_replies = []
        self.force_variation = False
        self.suggest_track = False
        self.peace_round = 0
        self.position_history = {}
        self.total_moves = 0
        self.consecutive_check_red = 0
        self.consecutive_check_black = 0
        self.consecutive_attack_red = 0
        self.consecutive_attack_black = 0
        self.last_attacked_pos = None
        self.last_attacked_type = 0
        self.last_move_was_check = False
        self.draw_reason = ''
        self.draw_offer = None
        self.draw_offer_pending = None
        self.draw_hint = ''
        self.draw_offer_suppressed = False
        self.attack_num_r = 0
        self.attack_num_b = 0
        self.winner = None
        # 记录被重置到的基准局面，使三照重复判定从该局面开始计数
        self._record_position()

    def get_piece_at(self, x: int, y: int) -> int:
        if 0 <= x < 9 and 0 <= y < 10:
            return self.piece[y][x]
        return 0

    def select_piece(self, x: int, y: int) -> bool:
        piece_id = self.get_piece_at(x, y)
        if piece_id == 0:
            return False
        
        is_red_piece = piece_id >= 8
        if is_red_piece != self.is_red_go:
            return False
        
        self.select = Pos(x, y)
        self.ret = possible_moves(self.piece, x, y, piece_id)
        return True

    def move_piece(self, x: int, y: int) -> bool:
        if self.select.x == -1:
            return False
        
        from_x, from_y = self.select.x, self.select.y
        piece_id = self.piece[from_y][from_x]
        
        for pos in self.ret:
            if pos.x == x and pos.y == y:
                temp_piece = [row[:] for row in self.piece]
                temp_piece[y][x] = piece_id
                temp_piece[from_y][from_x] = 0
                
                is_red_side = piece_id >= 8
                if is_king_danger(temp_piece, is_red_side):
                    return False
                
                mover_is_red = self.is_red_go
                captured = self.piece[y][x]

                self.pre_pos = Pos(from_x, from_y)
                self.cur_pos = Pos(x, y)
                self.piece[y][x] = piece_id
                self.piece[from_y][from_x] = 0
                self.move_history.append(Move(Pos(from_x, from_y), Pos(x, y)))

                self.is_red_go = not self.is_red_go
                self.select = Pos(-1, -1)
                self.ret = []

                self.is_checked = is_king_danger(self.piece, self.is_red_go)

                # 更新和棋相关计数（长将/长捉/未吃子回合/局面重复）
                self._update_move_info(mover_is_red, captured, from_x, from_y, x, y, piece_id)

                # 终局：胜方为刚完成走子的一方（is_red_go 当前指向「被将死/被困毙」方）
                if is_checkmate(self.piece, self.is_red_go):
                    self.status = 2
                    self.winner = 'red' if not self.is_red_go else 'black'
                elif is_stalemate(self.piece, self.is_red_go):
                    self.status = 3
                    self.winner = 'red' if not self.is_red_go else 'black'
                else:
                    self._check_draw_conditions()

                return True
        
        return False

    # ============ 和棋相关逻辑（参考 Android ChessInfo） ============

    def _is_attacking_piece(self, t: int) -> bool:
        return t in (BLACK_ROOK, BLACK_KNIGHT, BLACK_CANNON, BLACK_PAWN,
                     RED_ROOK, RED_KNIGHT, RED_CANNON, RED_PAWN)

    def _generate_position_hash(self) -> str:
        rows = [','.join(str(c) for c in row) for row in self.piece]
        rows.append('1' if self.is_red_go else '0')
        return ';'.join(rows)

    def _record_position(self):
        h = self._generate_position_hash()
        self.position_history[h] = self.position_history.get(h, 0) + 1

    def _reset_consecutive_attack(self):
        self.consecutive_attack_red = 0
        self.consecutive_attack_black = 0
        self.last_attacked_pos = None
        self.last_attacked_type = 0

    def _update_move_info(self, mover_is_red: bool, captured: int,
                          from_x: int, from_y: int, to_x: int, to_y: int, piece_id: int):
        self.total_moves += 1

        # 未吃子回合：仅当黑方走完一个完整回合且未吃子时 +1
        if captured != 0:
            self.peace_round = 0
        elif not mover_is_red:
            self.peace_round += 1

        # 长将计数
        if self.is_checked:
            if mover_is_red:
                self.consecutive_check_red += 1
                self.consecutive_check_black = 0
            else:
                self.consecutive_check_black += 1
                self.consecutive_check_red = 0
        else:
            if mover_is_red:
                self.consecutive_check_red = 0
            else:
                self.consecutive_check_black = 0
        self.last_move_was_check = self.is_checked

        # 长捉计数（仅攻击性棋子参与）
        if self._is_attacking_piece(piece_id):
            self._update_consecutive_attack(from_x, from_y, to_x, to_y, piece_id, captured, mover_is_red)
        else:
            self._reset_consecutive_attack()

        self._record_position()

    def _update_consecutive_attack(self, from_x, from_y, to_x, to_y, piece_id, captured, mover_is_red):
        attacks = possible_moves(self.piece, to_x, to_y, piece_id)
        is_attack_move = False
        if captured != 0:
            is_attack_move = True
        else:
            for ap in attacks:
                tp = self.piece[ap.y][ap.x]
                if tp != 0 and (is_red(piece_id) != is_red(tp)):
                    is_attack_move = True
                    break

        if not is_attack_move:
            self._reset_consecutive_attack()
            return

        if self.last_attacked_pos is not None and self.last_attacked_type != 0:
            if captured != 0 and captured == self.last_attacked_type:
                self._reset_consecutive_attack()
                return

            # 是否仍在攻击同一位置的同一棋子
            attacking_same = False
            for ap in attacks:
                if (ap.x == self.last_attacked_pos.x and ap.y == self.last_attacked_pos.y
                        and self.piece[ap.y][ap.x] == self.last_attacked_type):
                    attacking_same = True
                    break

            if attacking_same:
                if mover_is_red:
                    self.consecutive_attack_red += 1
                    self.consecutive_attack_black = 0
                else:
                    self.consecutive_attack_black += 1
                    self.consecutive_attack_red = 0
                return

            # 是否攻击同一类型的棋子（目标可能被移动）
            attacking_same_type = False
            for ap in attacks:
                tp = self.piece[ap.y][ap.x]
                if tp != 0 and tp == self.last_attacked_type:
                    attacking_same_type = True
                    self.last_attacked_pos = ap
                    break

            if attacking_same_type:
                if mover_is_red:
                    self.consecutive_attack_red += 1
                    self.consecutive_attack_black = 0
                else:
                    self.consecutive_attack_black += 1
                    self.consecutive_attack_red = 0
                return

            # 攻击了不同棋子，重置并记录新的被攻击棋子
            self._reset_consecutive_attack()
            for ap in attacks:
                tp = self.piece[ap.y][ap.x]
                if tp != 0 and is_red(piece_id) != is_red(tp):
                    self.last_attacked_pos = ap
                    self.last_attacked_type = tp
                    break
        else:
            # 首次攻击，记录被攻击棋子并计数
            for ap in attacks:
                tp = self.piece[ap.y][ap.x]
                if tp != 0 and is_red(piece_id) != is_red(tp):
                    self.last_attacked_pos = ap
                    self.last_attacked_type = tp
                    if mover_is_red:
                        self.consecutive_attack_red = 1
                        self.consecutive_attack_black = 0
                    else:
                        self.consecutive_attack_black = 1
                        self.consecutive_attack_red = 0
                    break

    def _count_attacking_pieces(self):
        red = black = 0
        for row in self.piece:
            for c in row:
                if c in (RED_ROOK, RED_KNIGHT, RED_CANNON, RED_PAWN):
                    red += 1
                elif c in (BLACK_ROOK, BLACK_KNIGHT, BLACK_CANNON, BLACK_PAWN):
                    black += 1
        self.attack_num_r = red
        self.attack_num_b = black
        return red, black

    def is_threefold_repetition(self) -> bool:
        return self.position_history.get(self._generate_position_hash(), 0) >= 3

    def is_both_sides_perpetual_check(self) -> bool:
        # 双方各连续将军 >=3 次（参照 Android isBothSidesPerpetualCheck）
        return self.consecutive_check_red >= 3 and self.consecutive_check_black >= 3

    def is_both_sides_perpetual_attack(self) -> bool:
        # 双方各连续攻击 >=3 次（参照 Android isBothSidesPerpetualAttack）
        return self.consecutive_attack_red >= 3 and self.consecutive_attack_black >= 3

    def is_one_side_perpetual_check(self) -> bool:
        # 单方连续将军 >=4 次且对方无连续将军（参照 Android isOneSidePerpetualCheck）
        return (self.consecutive_check_red >= 4 and self.consecutive_check_black == 0) or \
               (self.consecutive_check_black >= 4 and self.consecutive_check_red == 0)

    def is_one_side_perpetual_attack(self) -> bool:
        # 单方连续攻击 >=4 次且对方无连续攻击（参照 Android isOneSidePerpetualAttack）
        return (self.consecutive_attack_red >= 4 and self.consecutive_attack_black == 0) or \
               (self.consecutive_attack_black >= 4 and self.consecutive_attack_red == 0)

    def is_one_forbidden_one_allowed(self) -> bool:
        """一方有禁止着法（长将或长捉 >=4），另一方没有（长将/长捉均 <4）。
        参照 Android isOneForbiddenOneAllowed：覆盖「一方长将+另一方也将军但不足4次」的边界。"""
        red_forbidden = (self.consecutive_check_red >= 4 or self.consecutive_attack_red >= 4)
        black_forbidden = (self.consecutive_check_black >= 4 or self.consecutive_attack_black >= 4)
        return (red_forbidden and not black_forbidden) or (black_forbidden and not red_forbidden)

    def get_forbidden_side(self) -> str:
        red_forbidden = (self.consecutive_check_red >= 4 or self.consecutive_attack_red >= 4)
        black_forbidden = (self.consecutive_check_black >= 4 or self.consecutive_attack_black >= 4)
        if red_forbidden and not black_forbidden:
            return '红方'
        if black_forbidden and not red_forbidden:
            return '黑方'
        return ''

    def _check_draw_conditions(self):
        """走子后检测和棋条件：参照 Android checkDrawConditions / handleForceVariation。

        检测顺序与 Android 一致：
          1. 双方长将 / 双方长捉 -> 双方不变作和，弹窗询问是否和棋
          2. 三次重复 / 单方长将 / 单方长捉 -> 强制变着（must vary）
          3. 双方 30 回合内无吃子 / 双方均无攻击性棋子 -> 弹窗询问和棋
        和棋均需在弹窗中确认，不直接判和（与 Android 一致）。
        """
        if self.status != 0:
            return

        red_attack, black_attack = self._count_attacking_pieces()

        # 汇总当前是否存在和棋触发条件，便于“拒绝后抑制重复弹窗”
        both_check = self.is_both_sides_perpetual_check()
        both_attack = self.is_both_sides_perpetual_attack()
        one_check = self.is_one_side_perpetual_check()
        one_attack = self.is_one_side_perpetual_attack()
        one_forbidden = self.is_one_forbidden_one_allowed()
        threefold = self.is_threefold_repetition()
        no_attack = (red_attack == 0 and black_attack == 0)
        peace = self.peace_round >= 30

        has_draw_condition = (both_check or both_attack or one_check
                              or one_attack or one_forbidden or threefold
                              or no_attack or peace)

        # 条件消失后解除抑制，使下次真正变化时能再次提示
        if not has_draw_condition:
            self.draw_offer_suppressed = False
            return
        if self.draw_offer_suppressed:
            return

        # 1) 双方长将 / 双方长捉 -> 询问和棋
        if both_check:
            self.draw_offer_pending = '双方长将，双方不变作和，是否和棋？'
            return
        if both_attack:
            self.draw_offer_pending = '双方长捉，双方不变作和，是否和棋？'
            return

        # 2) 三次重复 / 单方长将 / 单方长捉 / 一禁一许 -> 强制变着
        if threefold:
            self.draw_hint = '检测到重复局面，请变着！'
            return
        if one_check:
            side = '红方' if self.consecutive_check_red >= 4 else '黑方'
            self.draw_hint = f'{side}长将，必须变着！'
            return
        if one_attack:
            side = '红方' if self.consecutive_attack_red >= 4 else '黑方'
            self.draw_hint = f'{side}长捉，必须变着！'
            return
        if one_forbidden:
            side = self.get_forbidden_side()
            verb = '长将' if (self.consecutive_check_red >= 4 or self.consecutive_check_black >= 4) else '长捉'
            self.draw_hint = f'{side}{verb}，必须变着！'
            return

        # 3) 双方 30 回合内无吃子 / 双方均无攻击性棋子 -> 询问和棋
        if peace:
            self.draw_offer_pending = '双方 30 回合内未吃子，是否和棋？'
            return
        if no_attack:
            self.draw_offer_pending = '双方都无攻击性棋子，是否和棋？'
            return

    def accept_draw(self):
        """双方同意和棋或电脑接受和棋。"""
        self.status = 4
        self.draw_reason = '双方同意和棋'
        self.winner = None
        self.draw_offer = None

    def decline_draw(self):
        self.draw_offer = None

    def is_valid_move(self, from_x: int, from_y: int, to_x: int, to_y: int) -> bool:
        piece_id = self.get_piece_at(from_x, from_y)
        if piece_id == 0:
            return False
        
        is_red_piece = piece_id >= 8
        if is_red_piece != self.is_red_go:
            return False
        
        moves = possible_moves(self.piece, from_x, from_y, piece_id)
        for pos in moves:
            if pos.x == to_x and pos.y == to_y:
                temp_piece = [row[:] for row in self.piece]
                temp_piece[to_y][to_x] = piece_id
                temp_piece[from_y][from_x] = 0
                return not is_king_danger(temp_piece, is_red_piece)
        
        return False

    def get_game_status(self) -> str:
        if self.status == 0:
            return "playing"
        elif self.status == 2:
            return "checkmate"
        elif self.status == 3:
            return "stalemate"
        elif self.status == 4:
            return "draw"
        return "unknown"

    def clone(self):
        info = ChessInfo()
        info.piece = [row[:] for row in self.piece]
        info.is_red_go = self.is_red_go
        info.select = self.select.clone()
        info.pre_pos = self.pre_pos.clone()
        info.cur_pos = self.cur_pos.clone()
        info.ret = [p.clone() for p in self.ret]
        info.status = self.status
        info.is_machine = self.is_machine
        info.setting = self.setting
        info.is_checked = self.is_checked
        info.suggest_moves = [m for m in self.suggest_moves]
        info.suggest_move_labels = [l for l in self.suggest_move_labels]
        info.suggest_replies = [r for r in self.suggest_replies]
        info.force_variation = self.force_variation
        info.variation_randomness = self.variation_randomness
        info.move_history = [m for m in self.move_history]
        info.attack_num_r = self.attack_num_r
        info.attack_num_b = self.attack_num_b
        info.draw_hint = self.draw_hint
        info.draw_offer_suppressed = self.draw_offer_suppressed
        return info

    def deep_clone(self):
        """完整深拷贝：复制全部对局状态（含和棋计数、历史、胜负等）。

        用于「模拟行棋」：进入模拟前保存当前局面的完整副本，退出模拟时还原，
        从而不污染真实对局。
        """
        info = ChessInfo()
        info.piece = [row[:] for row in self.piece]
        info.is_red_go = self.is_red_go
        info.select = self.select.clone()
        info.pre_pos = self.pre_pos.clone()
        info.cur_pos = self.cur_pos.clone()
        info.ret = [p.clone() for p in self.ret]
        info.status = self.status
        info.is_machine = self.is_machine
        info.is_checked = self.is_checked
        info.setting = self.setting
        info.suggest = self.suggest
        info.suggest_moves = [m for m in self.suggest_moves]
        info.suggest_move_labels = [l for l in self.suggest_move_labels]
        info.suggest_replies = [r for r in self.suggest_replies]
        info.force_variation = self.force_variation
        info.variation_randomness = self.variation_randomness
        info.move_history = [Move(Pos(m.from_pos.x, m.from_pos.y),
                                  Pos(m.to_pos.x, m.to_pos.y)) for m in self.move_history]
        info.winner = self.winner
        info.peace_round = self.peace_round
        info.position_history = dict(self.position_history)
        info.total_moves = self.total_moves
        info.consecutive_check_red = self.consecutive_check_red
        info.consecutive_check_black = self.consecutive_check_black
        info.consecutive_attack_red = self.consecutive_attack_red
        info.consecutive_attack_black = self.consecutive_attack_black
        info.last_attacked_pos = self.last_attacked_pos
        info.last_attacked_type = self.last_attacked_type
        info.last_move_was_check = self.last_move_was_check
        info.draw_reason = self.draw_reason
        info.draw_offer = self.draw_offer
        info.draw_offer_pending = self.draw_offer_pending
        info.draw_hint = self.draw_hint
        info.draw_offer_suppressed = self.draw_offer_suppressed
        info.attack_num_r = self.attack_num_r
        info.attack_num_b = self.attack_num_b
        return info
