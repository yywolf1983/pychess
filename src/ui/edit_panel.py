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


class EditPanelMixin:
    def _handle_edit_click(self, x: int, y: int):
        """编辑态下点击棋盘：放置 / 拾起移动 / 双击删除。"""
        pos = self.chess_view.get_board_coordinates(x, y - self.board_offset_y)
        if pos.x < 0:
            return
        now = pygame.time.get_ticks()
        cell = (pos.x, pos.y)
        cur = self.chess_info.piece[pos.y][pos.x]

        # 双击删除：上一次同格快速点击且当时是“拾起”，则丢弃拾起的棋子（即删除）
        if (self._edit_last_click and self._edit_last_click[0] == cell
                and now - self._edit_last_click[1] < 300 and self._edit_last_click[2] == 'pickup'):
            pid = self.edit_piece
            self.edit_piece = None
            self._edit_pickup_cell = None
            self._edit_last_click = None
            # 记录删除操作，便于悔棋还原
            self.edit_history.append({'type': 'delete', 'pos': cell, 'pid': pid})
            self._after_edit()
            return

        if self.edit_piece is not None:
            # 放置选中的棋子（上限校验，避免多出棋子）
            if self._piece_count(self.edit_piece) >= self._piece_max_count(self.edit_piece):
                return
            pid = self.edit_piece
            # 区分“从棋盘拾起后移动”与“从调色板放置”：记录不同撤销项
            if self._edit_pickup_cell is not None and self._edit_pickup_cell != cell:
                self.edit_history.append({'type': 'move', 'from': self._edit_pickup_cell,
                                          'to': cell, 'pid': pid})
            elif self._edit_pickup_cell is None:
                self.edit_history.append({'type': 'place', 'pos': cell, 'pid': pid})
            # 同格放回（_edit_pickup_cell == cell）属无操作移动，不记录撤销
            self.chess_info.piece[pos.y][pos.x] = pid
            self._edit_pickup_cell = None
            self._edit_last_click = (cell, now, 'place')
            self._after_edit()
            self.edit_piece = None  # 放置后取消选中（只选择一次，避免持续选中）
            return

        # 未选中棋子：点击已有棋子则拾起（移动）；记录原格子
        if cur != 0:
            self.edit_piece = cur
            self._edit_pickup_cell = cell
            self.chess_info.piece[pos.y][pos.x] = 0
            self._edit_last_click = (cell, now, 'pickup')
            self._after_edit()
            return
        # 空格且无选中：忽略
        self._edit_last_click = (cell, now, 'empty')


    def _palette_item_at(self, x: int, y: int):
        """返回摆棋面板中 (x, y) 处的条目：('piece', pid) / ('clear', None) / None。
        已达上限的棋子返回 None（置灰禁用，不可拖拽/选中）。"""
        if self.edit_vp is None:
            return None
        if x >= self.edit_vp.right - 10:
            return None
        # 屏幕坐标 -> 内容坐标（绘制时 content - scroll，故回加 scroll）
        cy = y + self.edit_scroll
        for key, rect in self.edit_ui.items():
            if rect.collidepoint(x, cy):
                if key == 'clear':
                    return ('clear', None)
                if key == 'copy_fen':
                    return ('copy_fen', None)
                if key.startswith('piece_'):
                    pid = int(key.split('_')[1])
                    if self._piece_count(pid) >= self._piece_max_count(pid):
                        return None
                    return ('piece', pid)
                return None
        return None


    def _handle_edit_panel_click(self, x: int, y: int):
        # 已改为在 handle_click 中通过拖拽/选中处理，保留可空实现
        return


    def toggle_edit(self):
        self.editing = not self.editing
        self.edit_piece = None
        self._edit_pickup_cell = None
        self.edit_history = []  # 进入 / 退出摆棋都清空撤销栈
        self.edit_scroll = 0
        self._edit_dragging = False
        self.edit_drag_pid = None
        self.edit_drag_pos = None
        self.edit_drag_start = None
        self.edit_drag_moved = False
        self._edit_last_click = None
        self.chess_info.select = Pos(-1, -1)
        self.chess_info.ret = []
        self._clear_hint()
        if self.editing:
            # 进入摆棋：关闭 AI，切换为双人模式防止引擎介入
            self.is_ai_thinking = False
            self.game_mode = 'pvp'
            self.chess_info.status = 0
            self.chess_info.is_machine = False
        else:
            # 退出摆棋：重置后提示选择先手方
            self.chess_info.status = 0
            self._after_edit()
            self._reset_snapshots()
            self._show_modal('edit_first_move', '摆棋完成', '请选择由哪一方开始行棋：',
                             [{'id': 'red', 'label': '红方先走',
                               'base': (214, 56, 56), 'hover': (188, 40, 40)},
                              {'id': 'black', 'label': '黑方先走',
                               'base': (60, 72, 92), 'hover': (84, 98, 120)}])


    def _after_edit(self):
        """编辑后重置对局状态计数，避免自定义局面误判和棋/将军。"""
        self.chess_info.status = 0
        self.chess_info.select = Pos(-1, -1)
        self.chess_info.ret = []
        self._clear_hint()
        self.chess_info.is_checked = False
        self.chess_info.is_machine = False
        obj = getattr(self.chess_info, 'position_history', None)
        if hasattr(obj, 'clear'):
            obj.clear()
        for attr in ('total_moves', 'peace_round', 'consecutive_check_red',
                     'consecutive_check_black', 'consecutive_attack_red',
                     'consecutive_attack_black', 'draw_offer_pending',
                     'draw_hint', 'draw_offer_suppressed'):
            if hasattr(self.chess_info, attr):
                try:
                    setattr(self.chess_info, attr, 0)
                except Exception:
                    pass
        self.eval_history = []
        self.eval_by_step = []
        self.eval_score = None
        self.eval_gen += 1
        self.eval_step_gen += 1


    def _piece_img(self, pid, size):
        """取指定棋子的缩放图片（参照 Android SetupModeView 用真实棋子图绘制）。"""
        key = (pid, size)
        if key in self._edit_img_cache:
            return self._edit_img_cache[key]
        imgs = self.chess_view.images
        if pid <= 7:
            idx = pid - 1
            src = imgs['black'][idx] if idx < len(imgs['black']) else None
        else:
            idx = pid - 8
            src = imgs['red'][idx] if idx < len(imgs['red']) else None
        img = None
        if src is not None:
            img = pygame.transform.scale(src, (size, size)).convert_alpha()
        self._edit_img_cache[key] = img
        return img


    @staticmethod
    def _piece_max_count(pid):
        # 与 Android SetupModeView.getMaxPieceCount 完全一致：
        # 将/帅 1，士/仕、象/相、马、车、炮 各 2，卒/兵 5
        if pid in (1, 8):
            return 1
        if pid in (2, 3, 4, 5, 6, 9, 10, 11, 12, 13):
            return 2
        if pid in (7, 14):
            return 5
        return 0


    def _piece_count(self, pid):
        cnt = 0
        for r in range(10):
            for c in range(9):
                if self.chess_info.piece[r][c] == pid:
                    cnt += 1
        return cnt


    def _draw_edit_panel(self, sb_x):
        """参照 Android 摆棋界面：使用真实棋子图片，分多行展示（每行 3 枚）。
        面板整体在侧栏视口内可滚动，滚动条集成在侧栏右侧（参照 Android 可滚动面板）。
        已达上限的棋子置灰禁用，未达上限的棋子置亮可选。"""
        inner_x = sb_x + 20
        inner_w = self.sidebar_width - 40

        # 滚动视口：标题/“完成编辑”按钮之下，到全宽底部面板之前
        vp_top = self.edit_button.bottom + 8
        vp_bottom = self.board_offset_y + self.board_height - 10
        vp = pygame.Rect(sb_x, vp_top, self.sidebar_width, vp_bottom - vp_top)
        self.edit_vp = vp

        # 内容坐标（不随滚动变化）；绘制时整体下移 -scroll，命中时回加 scroll
        self._draw_section(inner_x, vp_top + 4, '摆棋：选择棋子')

        black_palette = [(1, '将'), (2, '士'), (3, '象'), (4, '马'), (5, '车'), (6, '炮'), (7, '卒')]
        red_palette = [(8, '帅'), (9, '仕'), (10, '相'), (11, '马'), (12, '车'), (13, '炮'), (14, '兵')]
        cols = 3
        gap = 8
        cw = (inner_w - (cols - 1) * gap) // cols  # 每格宽（约 64）
        ch = 60
        img_size = cw - 16

        self.edit_ui = {}

        def draw_color_rows(palette, label, y0):
            self._draw_text_left(label, inner_x, y0, 'small', (170, 188, 210))
            yy = y0 + 8
            for i, (pid, name) in enumerate(palette):
                r, c = divmod(i, cols)
                x = inner_x + c * (cw + gap)
                y = yy + r * (ch + gap)
                rect = pygame.Rect(x, y, cw, ch)  # 内容坐标
                self.edit_ui['piece_%d' % pid] = rect
                cnt = self._piece_count(pid)
                maxed = cnt >= self._piece_max_count(pid)
                active = self.edit_piece == pid
                draw_y = y - self.edit_scroll
                # 视口裁剪：完全在视口外的格子跳过绘制
                if draw_y + ch < vp_top or draw_y > vp_bottom:
                    continue
                surf_rect = pygame.Rect(rect.x, draw_y, cw, ch)
                if active:
                    # 选中态：金边 + 半透明黄底（参照 Android 选中态）
                    surf = pygame.Surface((cw, ch), pygame.SRCALPHA)
                    surf.fill((255, 252, 200, 150))
                    self.screen.blit(surf, (surf_rect.x, surf_rect.y))
                    pygame.draw.rect(self.screen, (255, 215, 0), surf_rect, border_radius=8, width=2)
                elif maxed:
                    # 置灰：已达上限，禁用
                    pygame.draw.rect(self.screen, (48, 56, 68), surf_rect, border_radius=8)
                else:
                    # 置亮：可选棋子用较亮背景
                    pygame.draw.rect(self.screen, (78, 108, 150), surf_rect, border_radius=8)
                img = self._piece_img(pid, img_size)
                if img:
                    ix = surf_rect.centerx - img.get_width() // 2
                    iy = surf_rect.centery - img.get_height() // 2
                    self.screen.blit(img, (ix, iy))
                if maxed:
                    # 已达上限：置灰蒙版（不显示文字，仅置灰即可）
                    ov = pygame.Surface((cw, ch), pygame.SRCALPHA)
                    ov.fill((34, 40, 50, 180))
                    self.screen.blit(ov, (surf_rect.x, surf_rect.y))
            rows = (len(palette) + cols - 1) // cols
            return yy + rows * (ch + gap)

        y = draw_color_rows(black_palette, '黑方', vp_top + 32)
        y = draw_color_rows(red_palette, '红方', y + 6)

        # 清空棋盘（无橡皮擦按钮：删除棋子改用“双击棋盘棋子”）
        base_y = y + 6
        clear_rect = pygame.Rect(inner_x, base_y, inner_w, ch)
        self.edit_ui['clear'] = clear_rect
        draw_y = clear_rect.y - self.edit_scroll
        if not (draw_y + ch < vp_top or draw_y > vp_bottom):
            surf_rect = pygame.Rect(clear_rect.x, draw_y, clear_rect.width, clear_rect.height)
            self._draw_button(surf_rect, '清空棋盘', 'small',
                              base=(120, 70, 70), hover=(150, 86, 86), text_color=(245, 240, 240))

        hint_y = clear_rect.bottom + 16
        self.edit_ui['hint'] = pygame.Rect(inner_x, hint_y, inner_w, 20)
        if hint_y - self.edit_scroll <= vp_bottom and hint_y - self.edit_scroll >= vp_top - 20:
            self._draw_text_left('点击/拖拽棋子到棋盘放置；双击棋盘棋子删除',
                                 inner_x, hint_y - self.edit_scroll, 'small', (170, 188, 210))

        # FEN 区域：根据当前摆棋局面重建并显示（可一键复制）
        fen_y = hint_y + 26
        self.edit_ui['fen_label'] = pygame.Rect(inner_x, fen_y, inner_w, 18)
        self._draw_text_left('当前局面 FEN', inner_x, fen_y - self.edit_scroll, 'small', (170, 188, 210))

        fen_box_y = fen_y + 22
        fen_box_h = 56
        self.edit_ui['fen'] = pygame.Rect(inner_x, fen_box_y, inner_w, fen_box_h)
        draw_fen_y = fen_box_y - self.edit_scroll
        if not (draw_fen_y + fen_box_h < vp_top or draw_fen_y > vp_bottom):
            box_rect = pygame.Rect(inner_x, draw_fen_y, inner_w, fen_box_h)
            pygame.draw.rect(self.screen, (24, 32, 44), box_rect, border_radius=8)
            pygame.draw.rect(self.screen, (70, 90, 120), box_rect, width=1, border_radius=8)
            fen_str = self.ai._board_to_fen(self.chess_info)
            self._draw_wrapped_text(fen_str, inner_x + 8, draw_fen_y + 8,
                                    inner_w - 16, 15, (180, 210, 235), 'small')

        copy_y = fen_box_y + fen_box_h + 8
        copy_rect = pygame.Rect(inner_x, copy_y, inner_w, 34)
        self.edit_ui['copy_fen'] = copy_rect
        draw_copy_y = copy_y - self.edit_scroll
        if not (draw_copy_y + 34 < vp_top or draw_copy_y > vp_bottom):
            self._draw_button(pygame.Rect(inner_x, draw_copy_y, inner_w, 34), '复制 FEN',
                              'small', base=(60, 110, 150), hover=(78, 132, 172),
                              text_color=(255, 255, 255))

        # 内容总高度（用于滚动条），并钳制滚动偏移
        content_bottom = copy_y + 34
        self.edit_content_bottom = content_bottom
        max_scroll = max(0, content_bottom - vp_bottom)
        if self.edit_scroll > max_scroll:
            self.edit_scroll = max_scroll
        if self.edit_scroll < 0:
            self.edit_scroll = 0
        self._draw_edit_scrollbar(vp, content_bottom, max_scroll)


    def _edit_scrollbar_rect(self, vp, max_scroll):
        """返回滚动条滑块矩形（max_scroll<=0 时返回 None）。"""
        if max_scroll <= 0:
            return None
        content_h = self.edit_content_bottom - vp.y
        thumb_h = max(28, int(vp.height * vp.height / content_h))
        if thumb_h >= vp.height:
            return None
        track_h = vp.height
        ty = vp.y + int(self.edit_scroll / max_scroll * (track_h - thumb_h))
        return pygame.Rect(vp.right - 7, ty, 4, thumb_h)


    def _draw_edit_scrollbar(self, vp, content_bottom, max_scroll):
        # 轨道（始终绘制，整合在侧栏右侧）
        track = pygame.Rect(vp.right - 6, vp.y, 3, vp.height)
        pygame.draw.rect(self.screen, (120, 140, 165, 90), track, border_radius=2)
        thumb = self._edit_scrollbar_rect(vp, max_scroll)
        if thumb:
            pygame.draw.rect(self.screen, (190, 205, 222), thumb, border_radius=2)


    def _draw_edit_drag_ghost(self):
        """拖拽棋子时，在鼠标位置绘制半透明“幽灵”棋子，便于从摆棋区拖到棋盘。"""
        if self.edit_drag_pid is None or self.edit_drag_pos is None:
            return
        if not self.edit_drag_moved:
            return  # 仅点击（未拖动）时不绘制幽灵
        img = self._piece_img(self.edit_drag_pid, 48)
        if img is None:
            return
        x, y = self.edit_drag_pos
        ghost = img.copy()
        ghost.set_alpha(200)
        self.screen.blit(ghost, (x - ghost.get_width() // 2, y - ghost.get_height() // 2))

