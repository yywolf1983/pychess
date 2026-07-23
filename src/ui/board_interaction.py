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


class BoardInteractionMixin:
    def handle_board_click(self, pos: Pos):
        if self.browse_index is not None:
            # 局面浏览中点击棋盘：以当前浏览局面为起点「分叉」进入实时对局，
            # 后续走法覆盖原谱剩余着法，棋谱列表与评分曲线同步刷新。
            self._enter_live_from_browse()
        if self.chess_info.get_game_status() != 'playing':
            return
        
        if self.is_ai_thinking:
            return
        
        if self.game_mode == 'mvm':
            return
        
        if self.game_mode == 'pvm_red' and not self.chess_info.is_red_go:
            # 轮到 AI（电脑）行棋：触发 AI 落子（浏览分叉后也能立即接管）
            self.check_ai_turn()
            return
        
        if self.game_mode == 'pvm_black' and self.chess_info.is_red_go:
            self.check_ai_turn()
            return
        

        # 支招（教练）状态下、且尚未选中棋子时点击棋盘：撤支教招的棋盘高亮
        # （起点圆圈 / 箭头），保留底部候选列表以便重新选择；随后按正常选子流程，
        # 让玩家可手动落子。否则会出现“点了棋子高亮仍不消失”的问题。
        if getattr(self, 'ai_lines', None) and self.chess_info.select.x < 0:
            self.chess_info.select = Pos(-1, -1)
            self.chess_info.ret = []
            self._clear_hint(keep_lines=True)

        # 点击已选中的同一颗棋子 -> 取消选中，并结束支招
        if self.chess_info.select.x == pos.x and self.chess_info.select.y == pos.y:
            self.chess_info.select = Pos(-1, -1)
            self.chess_info.ret = []
            self._clear_hint()
            return
        
        if self.chess_info.select.x >= 0:
            from_pos = Pos(self.chess_info.select.x, self.chess_info.select.y)
            if self.chess_info.move_piece(pos.x, pos.y):
                # 落子后：若与支招推荐线一致则续显提示线条，否则结束提示
                self._record_snapshot()
                if not self._update_hint_after_move(from_pos, pos):
                    self._clear_hint()
                else:
                    # 已开始跟线：收起着法选择框（曲线重新露出），跟线箭头仍保留
                    self.ai_lines = []
                self.hint_window = None
                self.check_ai_turn()
                # 放在 check_ai_turn 之后：AI 思考期间 request_eval 内部守卫会跳过，
                # 待 AI 落子(handle_ai_move)后再评估，避免行棋与评估两个引擎同时冷
                # 启动、抢占 CPU 导致落子卡顿；pvp 模式仍会正常触发评估。
                self.request_eval()
                status = self.chess_info.get_game_status()
                if status != 'playing':
                    # 终局结果改在对局状态卡片的终局横幅中展示，不再弹出浮窗提示
                    res_text = self._result_info()[0] if self._result_info() else ''
                    _ = res_text
            else:
                # 改选其它棋子 -> 结束支招提示
                self._clear_hint()
                self.chess_info.select_piece(pos.x, pos.y)
        else:
            self.chess_info.select_piece(pos.x, pos.y)


    def _enter_live_from_browse(self, undo=False):
        """从局面浏览切换到实时对局：以当前浏览局面为新起点，截断谱的后续着法。

        用于「读谱时随时行棋」——在浏览某一步时点击棋盘即在当前局面分叉，原谱
        剩余着法被新走法覆盖；棋谱列表、评分曲线随截断后的快照同步刷新。
        undo=True 表示由「悔棋」触发，从当前步往回退若干步后在该局面分叉。
        """
        k = self.browse_index
        # board_snapshots[0] 为起始局面，browse_index=k 表示已走 k 步，
        # 故截断历史/快照到当前步，并把棋盘恢复为当前浏览局面。
        self.chess_info.move_history = self.chess_info.move_history[:k]
        self.board_snapshots = self.board_snapshots[:k + 1]
        self.chess_info.piece = [row[:] for row in self.board_snapshots[k]]

        # 当前应行棋方：起点红先，每走一步轮转一次。
        start_red = getattr(self, '_pgn_start_red', True)
        self.chess_info.is_red_go = start_red if (k % 2 == 0) else (not start_red)

        # 退出浏览，并清掉与实时快照不再对齐的分步评分，回退到 eval_history 曲线。
        self.browse_index = None
        self.eval_by_step = []
        self.eval_step_gen += 1
        self.eval_gen += 1
        self.eval_score = None

        # 当前局面按实时对局重新判定（清除原谱终局/和棋残留状态），
        # 并重新计算将军状态，使提示/横幅与真实局面一致。
        self.chess_info.status = 0
        self.chess_info.winner = None
        self.chess_info.draw_reason = ''
        self.chess_info.select = Pos(-1, -1)
        self.chess_info.ret = []
        self._clear_hint()
        self.chess_info.is_checked = is_king_danger(
            self.chess_info.piece, self.chess_info.is_red_go)

        # 失效棋谱列表缓存（着法数已变化），下次绘制重建。
        self._move_strs_len = -1
        self.show_toast('已悔棋到该局面' if undo else '已从该局面开始行棋')


    def _clear_hint(self, keep_lines=False):
        """清空支招提示（线条 / 标签 / 选中项 / 多步窗口）。

        keep_lines=True 时保留 ai_lines（候选着法列表），用于进入模拟行棋后
        退出仍能回到着法选择界面。
        """
        self.chess_info.suggest_moves = []
        self.chess_info.suggest_move_labels = []
        self.chess_info.suggest_replies = []
        self.chess_info.suggest = None
        self.chess_info.suggest_track = False
        self._track_pv = None
        self._track_idx = 0
        self.hint_selected = -1
        self.hint_ui = []
        self.hint_window = None
        self.hint_browse_index = -1
        if not keep_lines:
            self.ai_lines = []


    def _same_move(self, mv, from_pos, to_pos):
        """比较棋步的起止点是否一致。"""
        return (mv.from_pos.x == from_pos.x and mv.from_pos.y == from_pos.y
                and mv.to_pos.x == to_pos.x and mv.to_pos.y == to_pos.y)


    def _update_hint_after_move(self, from_pos, to_pos):
        """玩家落子后调用：判断是否与支招推荐线一致。

        返回 True 表示仍在跟线（已续显剩余提示线条，无需清除）；
        返回 False 表示已偏离推荐线（调用方应清除提示）。
        """
        lines = getattr(self, 'ai_lines', None)
        if not lines and not getattr(self.chess_info, 'suggest_track', False):
            return False
        # 落子后目标格上的棋子，用于判定本方颜色
        piece = self.chess_info.piece[to_pos.y][to_pos.x]
        if piece == 0:
            return False
        made_is_red = piece >= 8

        # 已在跟线中：校验本步是否与推荐线下一手（同色）一致
        if getattr(self.chess_info, 'suggest_track', False) and self._track_pv is not None:
            k = self._find_pv_match(self._track_pv, self._track_idx,
                                    from_pos, to_pos, made_is_red)
            if k is not None:
                self._track_idx = k + 1
                self._refresh_track_moves()
                return True
            # 偏离推荐线 -> 结束提示
            self._end_hint_track()
            return False

        # 尚未跟线：若本步与某一路候选首着一致，则锁定该路并进入跟线
        for i, ln in enumerate(lines):
            pv = ln.get('pv_moves') or []
            if not pv:
                continue
            if self._same_move(pv[0], from_pos, to_pos):
                self._track_pv = pv
                self._track_my_is_red = ln.get('my_is_red', True)
                self._track_idx = 1
                self.chess_info.suggest_sel_index = i
                self.hint_selected = i
                self._refresh_track_moves()
                return True
        return False


    def _find_pv_match(self, pv, start, from_pos, to_pos, made_is_red):
        """在 pv[start:] 中查找与玩家本步（同色且起止一致）对应的索引。"""
        for k in range(start, len(pv)):
            is_red = self._track_my_is_red if (k % 2 == 0) else (not self._track_my_is_red)
            if is_red != made_is_red:
                continue
            if self._same_move(pv[k], from_pos, to_pos):
                return k
        return None


    def _refresh_track_moves(self):
        """根据当前跟踪进度刷新棋盘上的提示线条（剩余推荐着法）。"""
        pv = self._track_pv
        if not pv or self._track_idx >= len(pv):
            # 推荐线已走完（或为空）-> 清除提示
            self._end_hint_track()
            return
        # 跟线提示只展示接下来两步（玩家一步 + 对方一步），超出不再绘制
        self.chess_info.suggest_moves = list(pv[self._track_idx:self._track_idx + 2])
        self.chess_info.suggest_move_labels = [''] * len(self.chess_info.suggest_moves)
        self.chess_info.suggest_track = True


    def _advance_hint_after_move(self, from_pos, to_pos):
        """对手（AI）行棋时推进跟线：若 AI 走的是推荐应招则前进；
        若与推荐应招不一致，则取消提示线。"""
        if not getattr(self.chess_info, 'suggest_track', False) or self._track_pv is None:
            return
        if self._track_idx >= len(self._track_pv):
            self._clear_hint()
            return
        # 仅校验当前期望的那一步（对手应招）是否与推荐一致
        exp = self._track_pv[self._track_idx]
        if not self._same_move(exp, from_pos, to_pos):
            # AI 行棋与提示的步子不一样 -> 取消提示线
            self._clear_hint()
            return
        self._track_idx += 1
        self._refresh_track_moves()


    def _end_hint_track(self):
        """结束跟线：清除提示线条与跟踪状态。"""
        self.chess_info.suggest_track = False
        self._track_pv = None
        self._track_idx = 0
        self.chess_info.suggest_moves = []
        self.chess_info.suggest_move_labels = []
        self.chess_info.suggest_replies = []
        self.chess_info.suggest = None
        self.chess_info.suggest_sel_index = 0


    def _select_hint(self, index):
        """在支招区域点击某候选着法：选中其起点棋子，并让棋盘提示该行的前两步
        （先手实线 + 后手虚线）。"""
        if index < 0 or index >= len(self.chess_info.suggest_moves):
            return
        mv = self.chess_info.suggest_moves[index]
        self.hint_selected = index
        # 与棋盘箭头绘制（_draw_suggestions 使用的 suggest_sel_index）保持同步，
        # 否则选中其它行时棋盘仍提示第 0 行的前两步
        self.chess_info.suggest_sel_index = index
        self.chess_info.select_piece(mv.from_pos.x, mv.from_pos.y)


    def _handle_candidate_click(self, x, y):
        """底部候选着法面板：单击某路候选选中其起点棋子（棋盘联动高亮）；
        双击则进入「支招演示」：按该候选的完整推荐线（PV）逐步模拟行棋。"""
        if not getattr(self, 'ai_lines', None):
            return
        for entry in self.candidate_ui:
            if entry['rect'].collidepoint(x, y):
                idx = entry['index']
                now = pygame.time.get_ticks()
                last = getattr(self, '_candidate_last_click', None)
                if last is not None and last[0] == idx and now - last[1] < 400:
                    # 双击同一行：进入整路线模拟演示（不影响真实对局）
                    self._candidate_last_click = None
                    line = self.ai_lines[idx]
                    if line.get('pv_moves'):
                        self.start_simulation(line)
                    return
                self._candidate_last_click = (idx, now)
                self._select_hint(idx)
                return

