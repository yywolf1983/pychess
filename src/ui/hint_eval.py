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


class HintEvalMixin:
    def handle_action(self, action: str):
        if action == 'restart':
            self._show_modal('confirm_restart', '新建棋局',
                             '确定要开始新棋局吗？当前对局进度将丢失。',
                             [{'id': 'no', 'label': '取消'},
                              {'id': 'yes', 'label': '确定'}])
        elif action == 'undo':
            if self.editing:
                self.undo_edit()
            else:
                self.undo_move()
        elif action == 'prev':
            if self.editing:
                self.show_toast('摆棋中不可浏览历史')
            else:
                self.prev_step()
        elif action == 'next':
            if self.editing:
                self.show_toast('摆棋中不可浏览历史')
            else:
                self.next_step()
        elif action == 'hint':
            if self.editing:
                return  # 摆棋中无需支招
            self.show_hint()
        elif action == 'save':
            self.save_game()
        elif action == 'load':
            self.load_game()
        elif action == 'settings':
            self.show_settings = True
        elif action == 'flip':
            # 翻转棋盘视角（红/黑上下对调）；棋子与文字保持正向
            self.chess_view.toggle_flip()


    def show_hint(self):
        """向引擎请求当前行棋方的最佳着法，并在棋盘上以箭头提示。"""
        if self.chess_info.get_game_status() != 'playing':
            return
        if self.is_ai_thinking or self.hint_loading:
            return
        # 仅当轮到人类时给出提示
        if self.game_mode == 'mvm':
            return
        if self.game_mode == 'pvm_red' and not self.chess_info.is_red_go:
            return
        if self.game_mode == 'pvm_black' and self.chess_info.is_red_go:
            return

        if not self.ai.is_initialized():
            self.ai.initialize()

        self.hint_loading = True
        self._clear_hint()
        t = threading.Thread(target=self._compute_hint)
        t.daemon = True
        t.start()


    def _compute_hint(self):
        try:
            settings = Setting()
            # 支招需要更长的变化线以在一行内展示更多步：加深搜索并放宽思考时间
            settings.depth = max(20, self.settings.depth)
            settings.skill_level = self.settings.skill_level
            settings.thinking_time = min(2.5, max(1.5, self.settings.thinking_time))
            # 支招展示最多 5 路候选着法
            if self.ai.engine_supports_multi_pv:
                multi_pv = 5
            else:
                multi_pv = 1
            settings.multi_pv = multi_pv
            settings.contempt = self.settings.contempt
            settings.force_variation = False
            results = self.ai.get_top_moves(self.chess_info, settings, top_n=multi_pv)
            self.hint_queue.put(results)
        except Exception as e:
            print('支招失败:', e)
            self.hint_queue.put(None)


    def _consume_hint_result(self):
        """消费支招队列结果，生成多路候选着法提示与多步支招窗口。"""
        try:
            hint_result = self.hint_queue.get_nowait()
        except queue.Empty:
            return
        # 模拟行棋期间忽略支招结果（避免污染棋盘上的推荐线条），退出后会重新评估
        if self.simulating:
            return

        self.hint_loading = False
        if hint_result is not None and len(hint_result) > 0:
            from ..game.notation import move_to_chinese
            moves = []
            replies = []
            labels = []
            ai_lines = []
            scores_num = []  # 浮层选择框用的数值评分（红方视角）
            for i, r in enumerate(hint_result):
                if r.move is None or not r.move.is_valid():
                    continue
                mv = r.move
                moves.append(mv)
                rep = r.reply_move
                replies.append(rep if (rep is not None and rep.is_valid()) else None)
                # 完整 PV：基于当前棋盘顺序应用每一步，生成中文记谱与 Move 序列
                sim = self.chess_info.clone()
                pv_cn = []
                pv_moves = []
                pv_uci = list(r.pv_uci) if r.pv_uci else []
                if pv_uci:
                    for u in pv_uci:
                        m2 = self.ai._uci_to_move(u)
                        if not m2.is_valid():
                            break
                        pid = sim.piece[m2.from_pos.y][m2.from_pos.x]
                        if pid == 0:
                            break
                        cn = move_to_chinese(pid, m2.from_pos.x, m2.from_pos.y,
                                             m2.to_pos.x, m2.to_pos.y)
                        pv_cn.append(cn)
                        pv_moves.append(m2)
                        sim.piece[m2.to_pos.y][m2.to_pos.x] = pid
                        sim.piece[m2.from_pos.y][m2.from_pos.x] = 0
                        sim.is_red_go = not sim.is_red_go
                else:
                    # 兜底：引擎未给出完整 PV 时，仅用「我方 + 对方应招」的 Move 对象
                    for mm in [mv] + ([rep] if (rep is not None and rep.is_valid()) else []):
                        pid = sim.piece[mm.from_pos.y][mm.from_pos.x]
                        cn = move_to_chinese(pid, mm.from_pos.x, mm.from_pos.y,
                                             mm.to_pos.x, mm.to_pos.y)
                        pv_cn.append(cn)
                        pv_moves.append(mm)
                        sim.piece[mm.to_pos.y][mm.to_pos.x] = pid
                        sim.piece[mm.from_pos.y][mm.from_pos.x] = 0
                        sim.is_red_go = not sim.is_red_go
                # 兼容旧字段：首步为我方着法，次步为对方应招
                my_cn = pv_cn[0] if pv_cn else ''
                opp_cn = pv_cn[1] if len(pv_cn) > 1 else ''
                pid_my = self.chess_info.piece[mv.from_pos.y][mv.from_pos.x]
                # 分数统一换算成红方视角，便于阅读
                red_persp = r.score if self.chess_info.is_red_go else -r.score
                scores_num.append(red_persp)
                score_text = self._format_score(red_persp)[0]
                labels.append(
                    f'推荐{i+1} ({mv.from_pos.x},{mv.from_pos.y})→'
                    f'({mv.to_pos.x},{mv.to_pos.y}) {score_text}'
                )
                ai_lines.append({'score': score_text, 'my': my_cn, 'opp': opp_cn,
                                'my_is_red': pid_my >= 8, 'pv_cn': pv_cn,
                                'pv_moves': pv_moves})
            # 过滤：PV 不足 5 步的候选不展示（四个列表并行过滤，保持索引一致）
            keep = [i for i, ln in enumerate(ai_lines) if len(ln.get('pv_cn') or []) >= 5]
            if not keep:
                keep = list(range(len(ai_lines)))  # 兜底：避免全部被过滤导致空白
            moves = [moves[i] for i in keep]
            replies = [replies[i] for i in keep]
            labels = [labels[i] for i in keep]
            ai_lines = [ai_lines[i] for i in keep]
            self.chess_info.suggest_moves = moves
            self.chess_info.suggest_replies = replies
            self.chess_info.suggest_move_labels = labels
            self.ai_lines = ai_lines
            # 新支招默认不进入跟线模式（仅高亮选中那一路的第一步）
            self.chess_info.suggest_track = False
            self._track_pv = None
            self._track_idx = 0
            if moves:
                m0 = moves[0]
                self.chess_info.suggest = (
                    m0.from_pos.x, m0.from_pos.y, m0.to_pos.x, m0.to_pos.y)
            # 着法选择恢复为底部候选列表（见 _draw_eval_bottom），不再使用浮动支招浮窗
            self.hint_window = None
        else:
            self.chess_info.suggest_moves = []
            self.chess_info.suggest_replies = []
            self.chess_info.suggest_move_labels = []
            self.chess_info.suggest = None
            self.chess_info.suggest_track = False
            self._track_pv = None
            self._track_idx = 0
            self.hint_window = None
            self.ai_lines = []

        # 侧栏可点击条目（原有交互保留）
        self.hint_ui = []
        for i, m in enumerate(self.chess_info.suggest_moves):
            self.hint_ui.append({'from': (m.from_pos.x, m.from_pos.y),
                                 'to': (m.to_pos.x, m.to_pos.y),
                                 'label': self.chess_info.suggest_move_labels[i]})
        self.hint_selected = -1


    def query_ai_rule_draw(self):
        """规则触发和棋提示（人机模式）：后台询问电脑是否接受和棋。

        电脑不占优（评分 <= 阈值）则接受，否则拒绝。
        """
        if not self.ai.is_initialized():
            self.ai.initialize()
        self.draw_loading = True
        t = threading.Thread(target=self._compute_rule_draw)
        t.daemon = True
        t.start()


    def _compute_rule_draw(self):
        try:
            settings = Setting()
            settings.depth = self.settings.depth
            settings.skill_level = self.settings.skill_level
            settings.thinking_time = min(1.0, self.settings.thinking_time)
            settings.multi_pv = 1
            settings.contempt = self.settings.contempt
            settings.force_variation = False
            result = self.ai.get_best_move_with_score(self.chess_info, settings)
            # score 为正表示行棋方（电脑）占优
            accept = result is not None and result.score <= 30
            self.draw_response_queue.put(accept)
        except Exception as e:
            print('和棋判定失败:', e)
            self.draw_response_queue.put(False)


    def request_eval(self, force=False):
        """后台评估当前局面评分（红方视角），并更新评分曲线。"""
        if not force and (self.eval_loading or self.is_ai_thinking):
            return
        if not self.ai.is_initialized():
            self.ai.initialize()
        self.eval_gen += 1
        self.eval_loading = True
        t = threading.Thread(target=self._compute_eval)
        t.daemon = True
        t.start()


    def _compute_eval(self):
        gen = self.eval_gen
        try:
            settings = Setting()
            settings.depth = self.settings.depth
            settings.skill_level = self.settings.skill_level
            settings.thinking_time = min(0.5, self.settings.thinking_time)
            settings.multi_pv = 1
            settings.contempt = self.settings.contempt
            settings.force_variation = False
            result = self.ai.get_best_move_with_score(self.chess_info, settings)
            if gen != self.eval_gen:
                return
            if result is not None:
                # 引擎分数以“行棋方”视角；转换为红方视角
                raw = result.score
                red_persp = raw if self.chess_info.is_red_go else -raw
                self.eval_score = red_persp
                self.eval_history.append(red_persp)
                self.eval_depth = self.ai.current_depth
        except Exception as e:
            print('评估失败:', e)
        finally:
            self.eval_loading = False

    # ------------------------------------------------------------------
    # 加载棋谱后的分步评分（与 board_snapshots 对齐）
    # ------------------------------------------------------------------
    def request_eval_batch(self):
        """加载棋谱后调用：后台为整局每一步局面计算评分，写入 eval_by_step。

        曲线绘制时只显示到当前浏览步，因此「下一步」曲线增加、「上一步」减少。
        """
        if not self.board_snapshots:
            return
        self.eval_by_step = [None] * len(self.board_snapshots)
        self.eval_step_gen += 1
        gen = self.eval_step_gen
        threading.Thread(target=self._compute_eval_batch, args=(gen,),
                         daemon=True).start()

    def _compute_eval_batch(self, gen):
        """后台线程：逐快照评估并填充 eval_by_step；代际变化即中止。"""
        snapshots = self.board_snapshots
        n = len(snapshots)
        if n == 0:
            return
        # 轻量评估参数：整局步数多，控制深度与时长以保证曲线较快生成
        s = Setting()
        s.depth = max(6, min(self.settings.depth, 12))
        s.thinking_time = min(0.4, max(0.2, self.settings.thinking_time * 0.15))
        s.best_move_number = 1
        s.enable_thinking = False
        try:
            # 起点行棋方：快照 i=0 对应初始局面，行棋方随步数奇偶交替
            start_red = (self.chess_info.is_red_go
                         if (n - 1) % 2 == 0
                         else (not self.chess_info.is_red_go))
            for i in range(n):
                if gen != self.eval_step_gen:
                    return
                ci = self.chess_info.clone()
                ci.piece = [row[:] for row in snapshots[i]]
                ci.is_red_go = start_red if i % 2 == 0 else (not start_red)
                res = self.ai.get_best_move_with_score(ci, s)
                red_persp = res.score if ci.is_red_go else -res.score
                red_persp = max(-2000, min(2000, red_persp))
                self.eval_by_step[i] = red_persp
                # 若当前正在浏览这一步（或已回到终局），同步底部评分显示
                if self.browse_index is not None:
                    if self.browse_index == i:
                        self.eval_score = red_persp
                elif i == n - 1:
                    self.eval_score = red_persp
        except Exception as e:
            print('批量评分失败:', e)

    def _eval_curve_data(self):
        """返回当前应绘制的评分曲线数据（红方视角，单位 centipawn）。

        加载/浏览时返回「与 board_snapshots 对齐的分步评分」截止到当前浏览步，
        使「上一步」减少、「下一步」增加曲线；实时对局回退到 eval_history。
        """
        aligned = bool(self.eval_by_step) and len(self.eval_by_step) == len(self.board_snapshots)
        full = self.eval_by_step if aligned else self.eval_history
        if not full:
            return []
        if self.browse_index is not None:
            return full[:self.browse_index + 1]
        return full

    def _sync_eval_to_browse(self):
        """上一步/下一步切换浏览局面时，同步底部「当前局面评分」显示。"""
        if not (self.eval_by_step and len(self.eval_by_step) == len(self.board_snapshots)):
            return
        idx = self.browse_index if self.browse_index is not None else len(self.eval_by_step) - 1
        if 0 <= idx < len(self.eval_by_step) and self.eval_by_step[idx] is not None:
            self.eval_score = self.eval_by_step[idx]


    @staticmethod
    def _format_score(score):
        """参照 Android：+红优 / -黑优，mate(>=10000) 显示将杀。"""
        if score is None:
            return '评估中…', (120, 132, 150)
        if abs(score) >= 10000:
            mate = score > 0
            return ('红方 将杀' if mate else '黑方 将杀'), ((214, 56, 56) if mate else (45, 45, 48))
        if score > 0:
            return f'红方 +{score}', (214, 56, 56)
        if score < 0:
            return f'黑方 +{-score}', (45, 45, 48)
        return '均势', (120, 132, 150)


    def _draw_eval_curve(self, x, y, w, h):
        """整局评分曲线（参照 Android ScoreCurveView 美化版）。"""
        card = pygame.Rect(x, y, w, h)
        self._draw_rounded_card(card, (26, 30, 42), (12, 15, 22), (46, 56, 72))

        pad = 16
        plot = pygame.Rect(x + pad, y + pad, w - 2 * pad, h - 2 * pad)
        hist = self._eval_curve_data()
        cy = plot.y + plot.height // 2

        # 过滤尚未计算的分步评分（加载棋谱时后台逐步填充，可能含 None）
        pts_data = [(i, v) for i, v in enumerate(hist) if v is not None]
        if not pts_data:
            self._draw_text('暂无评分数据', plot.centerx, cy, 'small', (150, 162, 180))
            return

        n = len(hist)
        # 自适应缩放（参照 Android ADAPTIVE_MAX=100 / SC_MAX=400）
        max_abs = 1
        for _, v in pts_data:
            max_abs = max(max_abs, abs(v))
        scale = float(max(100, min(400, max_abs)))

        def to_y(v):
            ratio = max(-1.0, min(1.0, v / scale))
            return plot.y + plot.height / 2 - ratio * (plot.height / 2 - 2)

        # 网格线
        for frac in (1.0, 0.5, -0.5, -1.0):
            gy = cy - frac * (plot.height / 2)
            pygame.draw.line(self.screen, (40, 48, 64), (plot.x, gy), (plot.x + plot.width, gy), 1)
        # 中线虚线（仅作参考基准，不标注文字，避免误导）
        self._draw_dashed_line(plot.x, cy, plot.x + plot.width, cy, (130, 150, 180), 2, 8, 6)

        def to_x(i):
            return plot.x + (plot.width * i / (n - 1)) if n > 1 else plot.centerx

        # 按原始步序定位（保证曲线随浏览向右增长，未算出的步先留空）
        pts = [(to_x(i), to_y(v)) for i, v in pts_data]
        last_i, last_v = pts_data[-1]
        line_col = (236, 92, 92) if last_v >= 0 else (82, 150, 236)

        if len(pts) >= 2:
            # 渐变填充
            smooth = self._catmull_rom(pts, 14)
            fill_surf = pygame.Surface((plot.width, plot.height), pygame.SRCALPHA)
            poly = [(p[0] - plot.x, p[1] - plot.y) for p in
                    ([(plot.x, cy)] + smooth + [(plot.x + plot.width, cy)])]
            pygame.draw.polygon(fill_surf, (*line_col, 50), poly)
            self.screen.blit(fill_surf, (plot.x, plot.y))
            # 每步竖线（颜色按优势）
            for i, v in pts_data:
                c = (220, 70, 70) if v >= 0 else (70, 130, 220)
                px, py = to_x(i), to_y(v)
                pygame.draw.line(self.screen, c, (px, cy), (px, py), 2 if i == last_i else 1)
            # 平滑曲线
            pygame.draw.lines(self.screen, line_col, False, smooth, 2)
        else:
            pygame.draw.line(self.screen, line_col, (pts[0][0], cy), pts[0], 2)

        # 末点发光 + 白心
        last = pts[-1]
        glow = pygame.Surface((20, 20), pygame.SRCALPHA)
        pygame.draw.circle(glow, (*line_col, 90), (10, 10), 10)
        self.screen.blit(glow, (last[0] - 10, last[1] - 10))
        pygame.draw.circle(self.screen, line_col, last, 4)
        pygame.draw.circle(self.screen, (255, 255, 255), last, 2)


    def _current_depth(self):
        """当前展示的搜索深度：AI 思考时取实时深度，否则取最近一次评估深度。"""
        if self.is_ai_thinking:
            return self.ai.current_depth
        return self.eval_depth


    def _draw_eval_bottom(self):
        """界面底部：AI 候选着法列表（占原评分曲线位置）。

        列出引擎给出的全部候选着法（当前方一步 + 对方应招），
        含序号徽标、评分药丸与着法文本，点击可切换选中（棋盘联动高亮）。
        着法较多时列表可滚动（滚轮 / 右侧滚动条拖拽）。
        """
        # 模拟行棋时，底部改为模拟控制面板
        if self.simulating:
            self._draw_simulation_panel()
            return
        h = self.eval_bottom_h
        w = self.window_width
        y0 = self.board_offset_y + self.board_height
        self.candidate_ui = []
        self.candidate_scrollbar_track = None
        self.candidate_scrollbar_thumb = None
        self.candidate_max_scroll = 0

        bg = pygame.Surface((w, h), pygame.SRCALPHA)
        bg.fill((18, 24, 34, 240))
        self.screen.blit(bg, (0, y0))
        pygame.draw.line(self.screen, (40, 52, 70), (0, y0), (w, y0), 1)

        lines = getattr(self, 'ai_lines', None)
        if lines:
            self._draw_text(f'AI 候选着法（{len(lines)}）', w // 2, y0 + 16, 'small', (170, 195, 225))
        else:
            # 未请求支招时展示评分曲线
            self._draw_text('评分曲线', w // 2, y0 + 16, 'small', (170, 195, 225))
            self._draw_eval_curve(8, y0 + 30, w - 16, h - 38)
            self.candidate_scroll = 0
            return

        top = y0 + 30
        bottom = y0 + h - 4
        row_h = 34
        content_h = len(lines) * row_h
        view_h = bottom - top
        max_scroll = max(0, content_h - view_h)
        if self.candidate_scroll > max_scroll:
            self.candidate_scroll = max_scroll
        if self.candidate_scroll < 0:
            self.candidate_scroll = 0
        self.candidate_max_scroll = max_scroll

        scroll_w = 10 if max_scroll > 0 else 0
        list_x = 2
        list_w = w - 4 - scroll_w

        first = max(0, int(self.candidate_scroll // row_h))
        last = min(len(lines), int((self.candidate_scroll + view_h) // row_h) + 1)
        mx, my = self.mouse_pos
        for i in range(first, last):
            ln = lines[i]
            yy = top + i * row_h - self.candidate_scroll
            rect = pygame.Rect(list_x, yy, list_w, row_h - 4)
            selected = (self.hint_selected >= 0 and i == self.hint_selected % len(lines))
            hover = rect.collidepoint(mx, my)
            sim_rect = self._draw_candidate_row(rect, i, ln, selected, hover)
            self.candidate_ui.append({'index': i, 'rect': rect, 'sim_rect': sim_rect})

        if max_scroll > 0:
            self._draw_candidate_scrollbar(top, bottom, max_scroll)


    def _draw_colored_pv(self, pv_cn, x, y, h, max_w, my_is_red, more=False):
        """单行逐着法红/黑分色绘制 PV，首项暖橙强调；超出宽度或仍有后续时以「…」表示。"""
        gap = 1
        cyy = y + h // 2
        xx = x
        for idx, mv in enumerate(pv_cn):
            is_red = my_is_red if idx % 2 == 0 else (not my_is_red)
            col = (255, 150, 140) if is_red else (140, 205, 255)
            if idx == 0:
                col = (255, 196, 120)  # 首步（推荐着法）暖橙高亮
            surf = self._text_surface(mv, 'xsmall', col)
            w = surf.get_width() if surf else len(mv) * 10
            # 放得下才绘制；放不下则以 … 收尾（充分利用整行宽度）
            if xx + w > max_w:
                self._draw_text_left('…', xx, cyy, 'xsmall', (150, 160, 180))
                return
            self._draw_text_left(mv, xx, cyy, 'xsmall', col)
            xx += w + gap
        if more and xx + 8 <= max_w:
            # 已显示 5 步且仍有后续，补省略号表示延续
            self._draw_text_left('…', xx, cyy, 'xsmall', (150, 160, 180))


    def _draw_candidate_row(self, rect, i, ln, selected, hover):
        """绘制单条候选着法卡片。返回右侧「▶ 模拟」按钮的命中矩形。

        视觉：最佳着法(第1路)金色强调；选中/悬停态左侧高亮条 + 卡片描边。
        每条候选固定展示前 5 步走法（红黑分色，首项强调），不足 5 步者已在来源处过滤。
        """
        best = (i == 0)
        is_red = ln.get('my_is_red', True)

        # 背景与描边（最佳仅用普通底，前面加星标记即可）
        if selected:
            fill, border, accent = (52, 104, 162, 235), (120, 190, 255, 220), (120, 190, 255)
        elif hover:
            fill, border, accent = (40, 50, 68, 225), (90, 110, 140, 180), None
        else:
            fill, border, accent = (30, 38, 52, 205), (52, 62, 82, 160), None

        bg = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
        pygame.draw.rect(bg, fill, bg.get_rect(), border_radius=8)
        pygame.draw.rect(bg, border, bg.get_rect(), width=1, border_radius=8)
        self.screen.blit(bg, (rect.x, rect.y))

        # 左侧高亮条（最佳/选中）
        if accent:
            bar = pygame.Surface((3, rect.height - 14), pygame.SRCALPHA)
            bar.fill(accent)
            self.screen.blit(bar, (rect.x + 4, rect.y + 7))

        cx = rect.x + 4
        cyy = rect.y + rect.height // 2

        # 序号圆形徽标（最佳用金色）
        badge_r = 6
        if best:
            bc, tc = (240, 200, 120), (40, 30, 10)
        elif selected:
            bc, tc = (200, 228, 255), (20, 40, 70)
        else:
            bc, tc = (108, 142, 196), (255, 255, 255)
        pygame.draw.circle(self.screen, bc, (cx + badge_r, cyy), badge_r)
        self._draw_text(str(i + 1), cx + badge_r, cyy, 'xsmall', tc)

        # 评分药丸（紧凑，给着法序列让出更多横向空间）
        st = ln['score']
        if st.startswith('+'):
            scolor, sfill = (140, 226, 140), (38, 70, 42)
        elif st.startswith('-'):
            scolor, sfill = (244, 146, 146), (74, 40, 40)
        else:
            scolor, sfill = (240, 208, 134), (78, 66, 38)
        score_surf = self._text_surface(st, 'xsmall', scolor)
        chip_x = cx + badge_r * 2 + 1
        if score_surf:
            sw = score_surf.get_width() + 10
            chip = pygame.Rect(chip_x, cyy - 9, sw, 18)
            cps = pygame.Surface((chip.width, chip.height), pygame.SRCALPHA)
            pygame.draw.rect(cps, sfill, cps.get_rect(), border_radius=9)
            self.screen.blit(cps, (chip.x, chip.y))
            self.screen.blit(score_surf, (chip.x + 5, cyy - score_surf.get_height() // 2))
            chip_x = chip.right

        # 着法序列（红/黑分色，首项强调）：在可用宽度内尽量多显示，放不下时以 … 表示还有后续
        full_pv = ln.get('pv_cn') or ([ln['my']] + ([ln['opp']] if ln['opp'] else []))
        txt_x = chip_x + 2
        if best:
            # 最优着法前面加星（原位置），左侧已压缩以腾出空间保证首行也能显示更多步
            self._draw_text_left('★', txt_x, rect.y + rect.height // 2, 'xsmall', (240, 200, 120))
            txt_x += 11
        # 传入绝对右边界（rect.right-1），与函数内绝对坐标 xx 同基准比较，
        # 避免把绝对坐标与“相对可用宽度”误比导致提前截断、省略号远离边框
        right_edge = max(txt_x + 1, rect.right - 1)
        self._draw_colored_pv(full_pv, txt_x, rect.y, rect.height, right_edge, is_red, False)

        return None


    def _draw_candidate_scrollbar(self, top, bottom, max_scroll):
        """绘制候选列表右侧滚动条（轨道 + 滑块）。"""
        track = pygame.Rect(self.window_width - 9, top, 6, bottom - top)
        ts = pygame.Surface((track.width, track.height), pygame.SRCALPHA)
        pygame.draw.rect(ts, (120, 140, 165, 90), ts.get_rect(), border_radius=3)
        self.screen.blit(ts, (track.x, track.y))
        view_h = track.height
        content_h = view_h + max_scroll
        thumb_h = max(30, int(view_h * view_h / content_h))
        thumb_h = min(thumb_h, view_h)
        ty = track.y + int(self.candidate_scroll / max_scroll * (track.height - thumb_h))
        thumb = pygame.Rect(track.x, ty, track.width, thumb_h)
        pygame.draw.rect(self.screen, (200, 215, 232), thumb, border_radius=3)
        self.candidate_scrollbar_track = track
        self.candidate_scrollbar_thumb = thumb


    def _candidate_scrollbar_down(self, x, y):
        """命中候选滚动条区域则开始拖拽，返回是否命中。"""
        if not getattr(self, 'ai_lines', None) or self.candidate_max_scroll <= 0:
            return False
        if self.candidate_scrollbar_track is None:
            return False
        y0 = self.board_offset_y + self.board_height
        if not (y0 <= y <= y0 + self.eval_bottom_h and x >= self.window_width - 13):
            return False
        self.candidate_dragging = True
        self._candidate_scroll_to_y(y)
        return True


    def _candidate_scroll_to_y(self, y):
        track = self.candidate_scrollbar_track
        if track is None:
            return
        thumb_h = self.candidate_scrollbar_thumb.height if self.candidate_scrollbar_thumb else 30
        ty = max(track.y, min(track.y + track.height - thumb_h, y - thumb_h // 2))
        denom = max(1, track.height - thumb_h)
        ratio = (ty - track.y) / denom
        self.candidate_scroll = int(ratio * self.candidate_max_scroll)

