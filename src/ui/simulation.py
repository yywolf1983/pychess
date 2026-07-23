import os
import json
import pygame
import threading
import time
import queue
from datetime import datetime
from typing import Optional
from ..game.board import ChessInfo, Setting
from ..game.pos import Pos
from ..game.move import Move
from ..game.rule import is_king_danger
from ..ai.pikafish import PikafishAI
from .chess_view import ChessView


class SimulationMixin:
    def _copy_chess_state(self, dst, src):
        """将 src 的全部对局状态拷贝进 dst（保持 dst 对象引用不变，避免棋盘视图失效）。"""
        dst.piece = [row[:] for row in src.piece]
        dst.is_red_go = src.is_red_go
        dst.select = src.select.clone()
        dst.pre_pos = src.pre_pos.clone()
        dst.cur_pos = src.cur_pos.clone()
        dst.ret = [p.clone() for p in src.ret]
        dst.status = src.status
        dst.is_machine = src.is_machine
        dst.is_checked = src.is_checked
        dst.suggest = src.suggest
        dst.suggest_moves = list(src.suggest_moves)
        dst.suggest_move_labels = list(src.suggest_move_labels)
        dst.suggest_replies = list(src.suggest_replies)
        dst.suggest_track = False
        dst.force_variation = src.force_variation
        dst.variation_randomness = src.variation_randomness
        dst.move_history = [Move(Pos(m.from_pos.x, m.from_pos.y),
                                 Pos(m.to_pos.x, m.to_pos.y)) for m in src.move_history]
        dst.winner = src.winner
        dst.peace_round = src.peace_round
        dst.position_history = dict(src.position_history)
        dst.total_moves = src.total_moves
        dst.consecutive_check_red = src.consecutive_check_red
        dst.consecutive_check_black = src.consecutive_check_black
        dst.consecutive_attack_red = src.consecutive_attack_red
        dst.consecutive_attack_black = src.consecutive_attack_black
        dst.last_attacked_pos = src.last_attacked_pos
        dst.last_attacked_type = src.last_attacked_type
        dst.last_move_was_check = src.last_move_was_check
        dst.draw_reason = src.draw_reason
        dst.draw_offer = src.draw_offer
        dst.draw_offer_pending = src.draw_offer_pending
        dst.draw_hint = src.draw_hint
        dst.draw_offer_suppressed = src.draw_offer_suppressed
        dst.attack_num_r = src.attack_num_r
        dst.attack_num_b = src.attack_num_b


    def start_simulation(self, line):
        """进入模拟行棋：保存当前局面副本，逐步演示某路候选的完整推荐线。

        直接修改 self.chess_info 演示，退出时还原；模拟期间不触发 AI、不污染真实对局。
        """
        pv_moves = line.get('pv_moves') or []
        if not pv_moves:
            return
        self.sim_restore = self.chess_info.deep_clone()
        self.sim_pv = list(pv_moves)
        self.sim_pv_cn = list(line.get('pv_cn') or [])
        self.sim_index = 0
        self.simulating = True
        self.sim_scroll = 0
        # 仅隐藏棋盘上的箭线条，保留 ai_lines 以便退出模拟后回到着法选择
        self._clear_hint(keep_lines=True)
        self.chess_info.select = Pos(-1, -1)
        self.chess_info.ret = []
        # 清除进入模拟前的真实着法提示线（上一步轨迹），避免其残留在棋盘上
        self.chess_info.pre_pos = Pos(-1, -1)
        self.chess_info.cur_pos = Pos(-1, -1)


    def _sim_apply_move(self, mv):
        ci = self.chess_info
        pid = ci.piece[mv.from_pos.y][mv.from_pos.x]
        ci.piece[mv.to_pos.y][mv.to_pos.x] = pid
        ci.piece[mv.from_pos.y][mv.from_pos.x] = 0
        ci.move_history.append(Move(Pos(mv.from_pos.x, mv.from_pos.y),
                                    Pos(mv.to_pos.x, mv.to_pos.y)))
        ci.is_red_go = not ci.is_red_go
        ci.is_checked = is_king_danger(ci.piece, ci.is_red_go)
        ci.select = Pos(-1, -1)
        ci.ret = []


    def _rebuild_sim(self):
        """从保存副本重建当前局面，并应用前 sim_index 步。"""
        self._copy_chess_state(self.chess_info, self.sim_restore)
        # 模拟期间一律不显示着法轨迹线与支招箭头线
        # （sim_restore 克隆于进入模拟前，可能仍携带真实着法的轨迹与支招推荐线）
        self.chess_info.pre_pos = Pos(-1, -1)
        self.chess_info.cur_pos = Pos(-1, -1)
        self.chess_info.suggest_moves = []
        self.chess_info.suggest_move_labels = []
        self.chess_info.suggest_replies = []
        self.chess_info.suggest = None
        self.chess_info.suggest_track = False
        for k in range(self.sim_index):
            self._sim_apply_move(self.sim_pv[k])


    def sim_step_forward(self):
        if self.simulating and self.sim_index < len(self.sim_pv):
            self.sim_index += 1
            self._rebuild_sim()
            self.request_eval(force=True)


    def sim_step_back(self):
        if self.simulating and self.sim_index > 0:
            self.sim_index -= 1
            self._rebuild_sim()
            self.request_eval(force=True)


    def end_simulation(self):
        if self.sim_restore is not None:
            self._copy_chess_state(self.chess_info, self.sim_restore)
        self.simulating = False
        self.sim_pv = []
        self.sim_pv_cn = []
        self.sim_index = 0
        self.sim_restore = None
        self.sim_ui = {}
        self.sim_scroll = 0
        # 退出模拟后重新评估真实局面（仅刷新显示，不写入曲线）
        self.eval_skip_append = True
        self.request_eval(force=True)
        # 恢复后让 AI 在轮到它时继续（如适用）
        if self.chess_info.get_game_status() == 'playing':
            self.check_ai_turn()


    def _draw_sim_button(self, rect, label, disabled, danger=False):
        if disabled:
            fill = (70, 80, 96, 200)
            tcol = (150, 160, 175)
        elif danger:
            fill = (150, 60, 60, 235)
            tcol = (235, 240, 245)
        else:
            fill = (52, 110, 80, 235)
            tcol = (235, 245, 238)
        s = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
        pygame.draw.rect(s, fill, s.get_rect(), border_radius=7)
        self.screen.blit(s, (rect.x, rect.y))
        self._draw_text(label, rect.centerx, rect.centery, 'small', tcol)


    def _draw_simulation_panel(self):
        """模拟行棋面板：标题 + 步骤指示 + 完整推荐线（高亮当前步，可滚动）+ 控制按钮。"""
        h = self.eval_bottom_h
        w = self.window_width
        y0 = self.board_offset_y + self.board_height
        self.candidate_ui = []
        self.sim_ui = {}
        bg = pygame.Surface((w, h), pygame.SRCALPHA)
        bg.fill((18, 24, 34, 245))
        self.screen.blit(bg, (0, y0))
        pygame.draw.line(self.screen, (90, 130, 170), (0, y0), (w, y0), 1)

        total = len(self.sim_pv)
        self._draw_text_right(f'步骤 {self.sim_index}/{total}', w - 14, y0 + 16,
                              'small', (180, 200, 220))

        pv_cn = self.sim_pv_cn
        list_top = y0 + 34
        list_bottom = y0 + h - 44
        row_h = 24
        view_h = list_bottom - list_top
        max_scroll = max(0, len(pv_cn) * row_h - view_h)
        self.sim_scroll = max(0, min(max_scroll, self.sim_scroll))
        # 自动滚动使当前步可见
        cur_top = self.sim_index * row_h
        if cur_top < self.sim_scroll:
            self.sim_scroll = cur_top
        elif cur_top + row_h > self.sim_scroll + view_h:
            self.sim_scroll = cur_top + row_h - view_h

        first = max(0, int(self.sim_scroll // row_h))
        last = min(len(pv_cn), int((self.sim_scroll + view_h) // row_h) + 1)
        for i in range(first, last):
            yy = list_top + i * row_h - self.sim_scroll
            side = '（红）' if (i % 2 == 0) else '（黑）'
            txt = f'{i+1:02d}. {pv_cn[i]}{side}'
            if i == self.sim_index:
                hl = pygame.Surface((w - 16, row_h - 2), pygame.SRCALPHA)
                pygame.draw.rect(hl, (60, 110, 160, 220), hl.get_rect(), border_radius=5)
                self.screen.blit(hl, (8, yy))
                self._draw_text_left(txt, 16, yy + row_h // 2, 'small', (255, 255, 255))
            else:
                col = (255, 156, 146) if (i % 2 == 0) else (150, 214, 255)
                self._draw_text_left(txt, 16, yy + row_h // 2, 'small', col)

        # 底部控制按钮
        by = y0 + h - 36
        btn_h = 26
        bw = (w - 16 - 16) // 3
        back = pygame.Rect(8, by, bw, btn_h)
        fwd = pygame.Rect(8 + bw + 8, by, bw, btn_h)
        ex = pygame.Rect(8 + (bw + 8) * 2, by, bw, btn_h)
        self._draw_sim_button(back, '◀ 上一步', self.sim_index <= 0)
        self._draw_sim_button(fwd, '▶ 下一步', self.sim_index >= total)
        self._draw_sim_button(ex, '✕ 退出', False, danger=True)
        self.sim_ui = {'back': back, 'forward': fwd, 'exit': ex}


    def _handle_sim_click(self, x, y):
        ui = self.sim_ui
        if not ui:
            return
        if ui.get('back') and ui['back'].collidepoint(x, y):
            self.sim_step_back()
        elif ui.get('forward') and ui['forward'].collidepoint(x, y):
            self.sim_step_forward()
        elif ui.get('exit') and ui['exit'].collidepoint(x, y):
            self.end_simulation()

