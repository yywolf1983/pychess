import os
import json
import math
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


class SidebarMixin:
    def draw_menu_bar(self):
        """顶部菜单栏：新局 / 读谱 / 存谱 / 设置 + 对战模式。"""
        bar = pygame.Rect(0, 0, self.window_width, self.menu_h)
        self._gradient_rect(bar, (40, 54, 74), (26, 36, 52))
        pygame.draw.line(self.screen, (64, 82, 108),
                         (0, self.menu_h - 1), (self.window_width, self.menu_h - 1), 1)
        for btn in self.menu_buttons:
            key = btn['key']
            if btn['kind'] == 'mode':
                label = self.mode_label(full=False)
                active = self.mode_menu_open
                base, hover = (54, 72, 98), (216, 168, 80)
                icon = self.mode_icon_kind()
                icon_color = self.mode_color()
                badge = None
            else:
                label = btn['label']
                active = False
                base, hover = (54, 72, 98), (100, 150, 255)
                icon = btn.get('icon')
                icon_color = None
                badge = None
            self._draw_button(btn['rect'], label, 'small',
                              base=base, hover=hover, active=active,
                              text_color=(235, 240, 248), icon=icon,
                              icon_color=icon_color, badge=badge,
                              disabled=self._controls_disabled)
        # 分组分隔线：在「模式」按钮之前
        mode_btn = next(b for b in self.menu_buttons if b['key'] == 'mode')
        pygame.draw.line(self.screen, (64, 82, 108),
                         (mode_btn['rect'].x - 16, 18), (mode_btn['rect'].x - 16, self.menu_h - 18), 1)
        # 品牌（窗口最右侧）
        bx = self.window_width - 170 - 16
        by = self.menu_h // 2
        self._draw_text_left('中国象棋', bx + 4, by, 'large', (245, 212, 132))


    def _draw_mode_menu(self):
        """点击头部「模式」按钮后弹出的选择列表（覆盖在侧栏上方）。"""
        if not self.mode_menu_open:
            self.mode_menu_rects = []
            return
        # 以头部「模式」按钮为锚点，向下展开
        anchor = next(b['rect'] for b in self.menu_buttons if b['key'] == 'mode')
        # 直接用 MODE_META 统一标签 / 图标 / 主题色
        items = [(m, self.MODE_META[m][0], self.MODE_META[m][2]) for m in
                 ('pvp', 'pvm_red', 'pvm_black', 'mvm')]
        row_h = 46
        pad = 6
        w = 240
        x = min(anchor.x, self.window_width - w - 8)
        y = anchor.y + anchor.h + 4
        panel = pygame.Rect(x, y, w, len(items) * row_h + pad * 2)
        # 记录面板区域，供「模式菜单展开时屏蔽下方按钮悬停高亮」使用
        self.mode_menu_panel_rect = panel
        # 半透明遮罩（捕获外部点击关闭），仅覆盖侧栏右侧区域
        self._gradient_rect(panel, (40, 54, 74), (28, 38, 54))
        pygame.draw.rect(self.screen, (120, 150, 190), panel, 1, border_radius=8)
        self.mode_menu_rects = []
        for i, (mode, label, color) in enumerate(items):
            ry = y + pad + i * row_h
            r = pygame.Rect(x + pad, ry, w - 2 * pad, row_h - 6)
            sel = mode == self.game_mode
            hovered = r.collidepoint(self.mouse_pos)
            if sel:
                bg = (72, 108, 152)        # 选中项：明显更亮
            elif hovered:
                bg = (58, 76, 106)
            else:
                bg = (44, 58, 82)
            pygame.draw.rect(self.screen, bg, r, border_radius=6)
            # 左侧主题色条（选中项更长更亮，强化「已选」反馈）
            pygame.draw.rect(self.screen, color, pygame.Rect(r.x, r.y, 5, r.h), border_radius=3)
            # 模式图标（主题色）置于文字前，一眼可辨
            self._draw_button_glyph(r, 'mode_' + mode, color, r.x + 26, r.y + r.h // 2)
            self._draw_text_left(label, r.x + 46, r.y + r.h // 2, 'small',
                                 (235, 240, 248))
            # 选中勾（用图标绘制，避免依赖系统对 ✓ 字形的支持）
            if sel:
                self._draw_button_glyph(r, 'check', (150, 210, 255),
                                        r.x + r.w - 18, r.y + r.h // 2)
            self.mode_menu_rects.append((r, mode))


    def draw_sidebar(self):
        sb_x = self.board_width
        # 侧栏只延伸到棋盘底部；其下整条区域由底部面板（全宽）覆盖
        y0 = self.board_offset_y + self.board_height
        self._gradient_rect(pygame.Rect(sb_x, self.menu_h, self.sidebar_width,
                                        y0 - self.menu_h),
                            (45, 62, 84), (28, 40, 58))

        # 摆棋（编辑局面）开关 = 第一个侧栏大按钮
        self._draw_button(self.edit_button,
                          '完成编辑' if self.editing else '摆棋', 'large',
                          base=(70, 112, 86) if self.editing else (58, 78, 104),
                          hover=(96, 196, 130), active=self.editing,
                          text_color=(235, 248, 240),
                          disabled=self._controls_disabled)

        if self.editing:
            self._draw_edit_panel(sb_x)
            return

        self.hint_ui = []  # 每帧重建支招区可点击条目

        # 侧栏大按钮：上一步 / 下一步 / 悔棋 / 支招 / 翻转
        for btn in self.side_buttons[1:]:
            if btn['key'] == 'hint':
                # 支招按钮：思考中显示旋转动画；点击可再次点击中断
                if self.is_ai_thinking:
                    # AI 思考中也复用此按钮：动画 + “立即落子”中断
                    base, hover = (120, 96, 40), (170, 132, 50)
                    text_color = (255, 246, 230)
                    label = '思考中…'
                    icon = None
                    active = True
                    spinner = True
                    pulse = True
                elif self.hint_loading:
                    base, hover = (70, 112, 86), (96, 196, 130)
                    text_color = (235, 248, 240)
                    label = '支招中…(点击中断)'
                    icon = btn.get('icon')
                    active = True
                    spinner = True
                    pulse = True
                else:
                    base, hover = (70, 112, 86), (96, 196, 130)
                    text_color = (235, 248, 240)
                    label = btn['label']
                    icon = btn.get('icon')
                    active = False
                    spinner = False
                    pulse = False
            else:
                base, hover = (58, 78, 104), (100, 150, 255)
                text_color = (235, 240, 248)
                label = btn['label']
                icon = btn.get('icon')
                active = False
                spinner = False
                pulse = False
            # 忙碌态（加载中）除「支招」「翻转」外一律置灰禁用，与 ChineseChess 按钮置灰逻辑一致
            btn_disabled = self._controls_disabled and btn['key'] not in ('hint', 'flip')
            # 导航按钮（上一步/下一步/悔棋）另按「棋谱加载 / 偏离」状态置灰：
            #  - 未加载棋谱：上一步/下一步置灰，悔棋可用
            #  - 已加载且未偏离：上一步/下一步可用，悔棋置灰
            #  - 已加载且已偏离：上一步/下一步置灰，悔棋可用
            #  - 悔棋回到偏离点（重新对齐）：上一步/下一步可用，悔棋置灰
            if btn['key'] in ('prev', 'next', 'undo'):
                btn_disabled = btn_disabled or self._nav_button_disabled(btn['key'])
            self._draw_button(btn['rect'], label, 'large',
                              base=base, hover=hover, active=active,
                              text_color=text_color, icon=icon,
                              icon_only=btn.get('icon_only', False),
                              spinner=spinner, pulse=pulse,
                              disabled=btn_disabled)

        # 布局：不显示棋谱列表，对局状态卡片占满侧栏主区域（与侧栏底部对齐），
        # 数据完整显示在框内。
        sb_top = self.side_buttons[-1]['rect'].bottom + 16
        avail_bottom = y0 - 14
        status_h = self._status_card_height()
        # 空间不足时压缩状态卡，保证至少保留一定高度
        status_h = max(160, min(status_h, avail_bottom - sb_top))
        status_card = pygame.Rect(sb_x + 16, sb_top,
                                  self.sidebar_width - 32, avail_bottom - sb_top)
        self._draw_card(status_card, (248, 250, 252))
        self._draw_status_card(status_card)

        # 不显示棋谱列表：清空行点击热区，避免残留的导航点击命中
        self._move_row_rects = []

    # ------------------------------------------------------------------
    # 状态卡片（紧凑排版）
    # ------------------------------------------------------------------
    @staticmethod
    def _format_clock(sec):
        sec = int(sec)
        h = sec // 3600
        m = (sec % 3600) // 60
        s = sec % 60
        if h:
            return f'{h}:{m:02d}:{s:02d}'
        return f'{m:02d}:{s:02d}'

    def _toast_wrap(self, msg):
        """按侧栏内容宽度对提示文字换行，返回 (行列表, 内容宽度)。"""
        font_size = 'xsmall'      # 较小字号，确保长提示也能完整显示
        color = (225, 235, 248)
        cw = self.sidebar_width - 68   # 与 _draw_status_card 中 cw 保持一致
        lines, cur = [], ''
        for ch in msg:
            test = cur + ch
            surf = self._text_surface(test, font_size, color)
            if surf and surf.get_width() > cw and cur:
                lines.append(cur)
                cur = ch
            else:
                cur = test
        if cur:
            lines.append(cur)
        return (lines or ['']), cw

    def _status_card_height(self):
        h = 22 + 34 + 38          # 标题 + 回合色块
        if self.chess_info.is_checked:
            h += 40
        if self._result_info():
            h += 60
        h += 6 * 28               # 评分 / 步数 / 深度 / AI / 线程 / 行棋时间
        if self.toast and time.time() <= self.toast_until:
            # 按实际换行行数预留高度，避免提示文字被截断
            lines, _ = self._toast_wrap(self.toast)
            h += len(lines) * 22 + 22
        h += 18                   # 底部留白
        return h

    def _draw_status_card(self, card):
        cx = card.x + 18
        cw = card.width - 36
        cy = card.y + 22
        # 标题 + 强调下划线
        self._draw_text('对局状态', cx + cw // 2, cy, 'small', (70, 82, 104))
        pygame.draw.rect(self.screen, (96, 156, 236),
                         pygame.Rect(cx + cw // 2 - 22, cy + 16, 44, 3), border_radius=2)
        cy += 38

        # 当前回合：色块指示
        is_red = self.chess_info.is_red_go
        turn_side = '红方' if is_red else '黑方'
        chip = pygame.Rect(cx, cy, cw, 32)
        surf = pygame.Surface((chip.width, chip.height), pygame.SRCALPHA)
        pygame.draw.rect(surf, (244, 208, 202) if is_red else (206, 212, 224),
                         surf.get_rect(), border_radius=8)
        self.screen.blit(surf, chip.topleft)
        pygame.draw.circle(self.screen, (206, 54, 42) if is_red else (40, 44, 52),
                           (chip.x + 16, chip.centery), 6)
        self._draw_text_left(f'{turn_side}行棋', chip.x + 30, chip.centery, 'small', (60, 66, 78))
        cy += 44

        # 将军提示（终局时的将死/困毙不再重复显示“将军”，避免二者同时出现）
        if self.chess_info.is_checked and not self._result_info():
            self._draw_banner(card.x + 14, cy, card.width - 28, 30, (222, 64, 32), '将军！')
            cy += 40

        # 终局结果
        res = self._result_info()
        if res:
            text, color, sub = res
            # 终局原因（将死/困毙/和棋）用获胜方颜色显示，不再用小灰字
            self._draw_banner(card.x + 14, cy, card.width - 28, 50, color, text, sub,
                              sub_color=color)
            cy += 60

        # 信息行（标签左 / 数值右）
        total_moves = len(self.chess_info.move_history)
        if self.browse_index is not None:
            step_info = f' {self.browse_index}/{len(self.board_snapshots) - 1}'
        else:
            step_info = f'{total_moves} 步'
        score_text, score_color = self._format_score(self.eval_score)
        depth = self._current_depth()
        depth_text = f'{depth} 层' if depth else '—'
        ai_status = '思考中…' if self.is_ai_thinking else ' 就绪'
        ai_col = (90, 156, 72) if not self.is_ai_thinking else (230, 132, 32)

        # 当前方行棋时间：每走一步重置，实时累计；终局/模拟/摆棋时冻结
        now = time.time()
        if self._last_red_go is None or self._last_red_go != self.chess_info.is_red_go:
            self._last_red_go = self.chess_info.is_red_go
            self.turn_start_tick = now
        res_info = self._result_info()
        clock_frozen = bool(res_info) or self.simulating or self.editing or self.browse_index is not None
        if clock_frozen:
            elapsed = self._turn_elapsed_frozen
        else:
            elapsed = now - self.turn_start_tick
            self._turn_elapsed_frozen = elapsed
        turn_time_text = self._format_clock(elapsed)
        # 行棋时间颜色跟随当前走子方：红方→红，黑方→近黑（深灰，保证可读）
        turn_color = (214, 69, 59) if self.chess_info.is_red_go else (45, 52, 64)

        threads_text = f'{self.ai.threads}' if self.ai.threads else '—'
        for label, value, vcol in (
            ('评分', score_text, score_color),
            ('步数', step_info, (60, 72, 92)),
            ('深度', depth_text, (60, 72, 92)),
            ('AI', ai_status, ai_col),
            ('线程', threads_text, (60, 72, 92)),
            (f'时间', turn_time_text, turn_color),
        ):
            self._draw_text_left(label, cx, cy + 14, 'small', (110, 122, 142))
            self._draw_text_right(value, cx + cw, cy + 14, 'small', vcol)
            cy += 28

        # 临时提示
        if self.toast and time.time() <= self.toast_until:
            cy += 6
            msg = self.toast
            lines, _ = self._toast_wrap(msg)
            line_h = 22
            box_h = len(lines) * line_h + 16
            box = pygame.Rect(cx - 4, cy, cw + 8, box_h)
            surf = pygame.Surface((box.width, box.height), pygame.SRCALPHA)
            surf.fill((36, 50, 70, 245))
            self.screen.blit(surf, (box.x, box.y))
            pygame.draw.rect(self.screen, (120, 150, 190), box, 1, border_radius=6)
            for i, ln in enumerate(lines):
                self._draw_text_left(ln, cx, cy + 8 + i * line_h,
                                     'xsmall', (225, 235, 248))
            cy += box_h + 4

    def _draw_banner(self, x, y, w, h, color, text, sub=None, sub_color=None):
        surf = pygame.Surface((w, h), pygame.SRCALPHA)
        pygame.draw.rect(surf, (*color, 46), surf.get_rect(), border_radius=8)
        self.screen.blit(surf, (x, y))
        pygame.draw.rect(self.screen, color, pygame.Rect(x, y, w, h), 1, border_radius=8)
        if sub:
            # 主文本（如“红方胜”）与终局原因（如“将死”）均用获胜方颜色，
            # 不再用小灰字；字号适当缩小（xsmall）确保两行能排版下。
            self._draw_text(text, x + w // 2, y + 14, 'xsmall', color)
            self._draw_text(sub, x + w // 2, y + h - 12, 'xsmall', sub_color or color)
        else:
            self._draw_text(text, x + w // 2, y + h // 2, 'xsmall', color)

    # ------------------------------------------------------------------
    # 棋谱列表（填充侧栏剩余空间，可点击跳转复盘 / 滚轮滚动）
    # ------------------------------------------------------------------
    def _ensure_move_strs(self):
        total = len(self.chess_info.move_history)
        if getattr(self, '_move_strs_len', None) == total and getattr(self, '_move_strs', None) is not None:
            return
        self._move_strs_len = total
        self._move_strs = []
        self._move_scroll = 0
        from ..game.notation import move_to_chinese
        if self.board_snapshots:
            piece = [row[:] for row in self.board_snapshots[0]]
        else:
            piece = [row[:] for row in self.chess_info.piece]
        # 由第一步棋子颜色推导整盘先手方：红子(8-14)=红先，黑子(1-7)=黑先
        self._move_start_red = True
        for k, mv in enumerate(self.chess_info.move_history):
            pid = piece[mv.from_pos.y][mv.from_pos.x]
            if k == 0 and not (8 <= pid <= 14):
                self._move_start_red = False
            try:
                cn = move_to_chinese(pid, mv.from_pos.x, mv.from_pos.y,
                                     mv.to_pos.x, mv.to_pos.y, piece)
            except Exception:
                cn = ''
            piece[mv.to_pos.y][mv.to_pos.x] = pid
            piece[mv.from_pos.y][mv.from_pos.x] = 0
            self._move_strs.append(cn)

    def _draw_move_list(self, card):
        self._ensure_move_strs()
        cx = card.x + 16
        cw = card.width - 32
        # 标题
        self._draw_text('棋谱', cx + cw // 2, card.y + 18, 'small', (70, 82, 104))
        pygame.draw.rect(self.screen, (96, 156, 236),
                         pygame.Rect(cx + cw // 2 - 18, card.y + 34, 36, 3), border_radius=2)
        # 列头
        head_y = card.y + 46
        self._draw_text_left('回合', cx, head_y + 8, 'xsmall', (150, 160, 178))
        self._draw_text_left('红方', cx + 44, head_y + 8, 'xsmall', (206, 54, 42))
        self._draw_text_left('黑方', cx + cw // 2 + 6, head_y + 8, 'xsmall', (60, 70, 90))
        pygame.draw.line(self.screen, (224, 228, 236),
                         (cx - 2, head_y + 18), (cx + cw + 2, head_y + 18), 1)

        # 列表区域
        list_top = card.y + 58
        list_h = card.height - 58 - 10
        row_h = 26
        total = len(self._move_strs)
        pairs = (total + 1) // 2
        max_scroll = max(0, pairs * row_h - list_h)
        self._move_max_scroll = max_scroll
        self._move_scroll = max(0, min(max_scroll, self._move_scroll))

        clip = pygame.Rect(card.x + 4, list_top, card.width - 8, list_h)
        self._move_row_rects = []
        prev_clip = self.screen.get_clip()
        self.screen.set_clip(clip)
        for i in range(pairs):
            ry = list_top + i * row_h - self._move_scroll
            if ry + row_h <= list_top or ry >= list_top + list_h:
                continue
            first_idx = 2 * i
            second_idx = 2 * i + 1
            first_str = self._move_strs[first_idx] if first_idx < total else None
            second_str = self._move_strs[second_idx] if second_idx < total else None
            # 先手方放红列、后手方放黑列（红先：先手=红；黑先：先手=黑）
            start_red = getattr(self, '_move_start_red', True)
            if start_red:
                red_idx, red_str = first_idx, first_str
                black_idx, black_str = second_idx, second_str
            else:
                red_idx, red_str = second_idx, second_str
                black_idx, black_str = first_idx, first_str
            # 行号
            self._draw_text_left(str(i + 1), cx, ry + row_h // 2, 'xsmall', (150, 160, 178))
            # 红方格
            if red_str:
                rrect = pygame.Rect(cx + 40, ry + 2, cw // 2 - 44, row_h - 4)
                self._draw_move_cell(rrect, red_str, self.browse_index == red_idx + 1, (206, 54, 42))
                self._move_row_rects.append((rrect, red_idx + 1))
            # 黑方格
            if black_str:
                brect = pygame.Rect(cx + cw // 2 + 4, ry + 2, cw // 2 - 44, row_h - 4)
                self._draw_move_cell(brect, black_str, self.browse_index == black_idx + 1, (60, 70, 90))
                self._move_row_rects.append((brect, black_idx + 1))
        self.screen.set_clip(prev_clip)

        # 滚动条
        if max_scroll > 0:
            self._draw_scrollbar(card, list_top, list_h, self._move_scroll, max_scroll)

    def _draw_move_cell(self, rect, text, active, color):
        if active:
            surf = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
            pygame.draw.rect(surf, (96, 156, 236, 70), surf.get_rect(), border_radius=6)
            self.screen.blit(surf, rect.topleft)
        self._draw_text_left(text, rect.x + 8, rect.y + rect.height // 2, 'xsmall', color)

    def _draw_scrollbar(self, card, top, h, scroll, max_scroll):
        tx = card.right - 8
        thumb_h = max(24, int(h * (h / (h + max_scroll))))
        thumb_y = top + int((h - thumb_h) * (scroll / max_scroll)) if max_scroll else top
        pygame.draw.rect(self.screen, (180, 190, 205),
                         pygame.Rect(tx, thumb_y, 4, thumb_h), border_radius=2)


    def draw_settings(self):
        self._gradient_rect(pygame.Rect(0, 0, self.window_width, self.window_height),
                            (236, 240, 245), (214, 220, 230))

        card_x = (self.window_width - 560) // 2
        card_y = 24
        card_w = 560
        # 内容高度随说明文字增加，低于该值时撑高卡片避免溢出
        card_h = max(self.window_height - 48, 704)
        self._draw_card(pygame.Rect(card_x, card_y, card_w, card_h), (255, 255, 255))

        content_x = card_x + 40
        cx = card_x + card_w // 2

        # ---- 标题区 ----
        self._draw_text('设置', cx, card_y + 32, 'large', (40, 52, 72))
        self._draw_text('对局偏好 · AI 强度', cx, card_y + 58, 'tiny', (150, 162, 180))
        pygame.draw.rect(self.screen, (96, 156, 236),
                         pygame.Rect(cx - 22, card_y + 72, 44, 3), border_radius=2)

        def subcard(r):
            """浅灰圆角分区卡片，浮在白色主卡片之上。"""
            pygame.draw.rect(self.screen, (244, 247, 250), r, border_radius=12)
            pygame.draw.rect(self.screen, (226, 231, 238), r, border_radius=12, width=1)

        # ---- 音效设置 ----
        sub_rect = pygame.Rect(card_x + 24, card_y + 92, card_w - 48, 126)
        subcard(sub_rect)
        self._draw_text_left('音效设置', sub_rect.x + 20, sub_rect.y + 22, 'ssmall', (150, 172, 200))
        pygame.draw.line(self.screen, (140, 160, 185, 130),
                         (sub_rect.x + 20, sub_rect.y + 38), (sub_rect.x + 60, sub_rect.y + 38), 1)
        music_y = sub_rect.y + 76
        self._draw_text_left('背景音乐', sub_rect.x + 20, music_y, 'ssmall', (60, 72, 92))
        music_check_rect = pygame.Rect(sub_rect.right - 72, music_y - 14, 52, 28)
        self._draw_toggle_pill(music_check_rect, self.settings.is_music_play)
        effect_y = sub_rect.y + 112
        self._draw_text_left('音效', sub_rect.x + 20, effect_y, 'ssmall', (60, 72, 92))
        effect_check_rect = pygame.Rect(sub_rect.right - 72, effect_y - 14, 52, 28)
        self._draw_toggle_pill(effect_check_rect, self.settings.is_effect_play)

        # ---- AI 设置 ----
        ai_rect = pygame.Rect(card_x + 24, card_y + 240, card_w - 48, 344)
        subcard(ai_rect)
        self._draw_text_left('AI 设置', ai_rect.x + 20, ai_rect.y + 22, 'ssmall', (150, 172, 200))
        pygame.draw.line(self.screen, (140, 160, 185, 130),
                         (ai_rect.x + 20, ai_rect.y + 38), (ai_rect.x + 56, ai_rect.y + 38), 1)

        # 数值参数：减号(左) / 滑条 / 加号(右)；每项浮于白色 pill 行卡之上，附一行灰色说明
        self.settings_sliders = []
        bw, slider_w, gap = 30, 150, 8
        col_r = ai_rect.right - 24

        def draw_row(y, label, value, vmin, vmax, attr, key, hint='',
                     hint_color=(150, 162, 180)):
            # 行卡片（白色 pill，浮于浅灰分区卡上，强化层次）
            pill = pygame.Rect(ai_rect.x + 14, y - 26, ai_rect.width - 28, 50)
            pygame.draw.rect(self.screen, (255, 255, 255), pill, border_radius=10)
            pygame.draw.rect(self.screen, (232, 236, 242), pill, border_radius=10, width=1)
            self._draw_text_left(f'{label}: {value}', ai_rect.x + 28, y - 6, 'ssmall', (60, 72, 92))
            if hint:
                self._draw_text_left(hint, ai_rect.x + 28, y + 13, 'tiny', hint_color)
            # 固定布局：减号在左、滑条居中、加号在右 → [−][滑条][+]
            plus_rect = pygame.Rect(col_r - bw, y - 15, bw, 30)
            track = pygame.Rect(plus_rect.x - gap - slider_w, y - 4, slider_w, 8)
            minus_rect = pygame.Rect(track.x - gap - bw, y - 15, bw, 30)
            self._draw_button(minus_rect, '-', 'large')
            self._draw_button(plus_rect, '+', 'large')
            self._draw_slider(track, value, vmin, vmax)
            self.settings_sliders.append({'key': key, 'track': track,
                                          'vmin': vmin, 'vmax': vmax, 'attr': attr})
            return minus_rect, plus_rect

        row_top = ai_rect.y + 56
        row_step = 60
        depth_minus_rect, depth_plus_rect = draw_row(
            row_top, '搜索深度 (层)', self.settings.depth, 5, 120, 'depth', 'depth',
            '每步向前推演的层数上限（越大越慢、越准）')
        skill_minus_rect, skill_plus_rect = draw_row(
            row_top + row_step, '技能级别 (级)', self.settings.skill_level, 1, 20,
            'skill_level', 'skill',
            '注意：当前引擎不支持此选项，该设置暂不起作用', (206, 120, 64))
        time_minus_rect, time_plus_rect = draw_row(
            row_top + 2 * row_step, '思考时间 (秒)', self.settings.thinking_time, 1, 180,
            'thinking_time', 'time', '每步思考的最长时间，到达即停（先到先停，最长 180 秒）')
        multi_minus_rect, multi_plus_rect = draw_row(
            row_top + 3 * row_step, 'MultiPV (变)', self.settings.multi_pv, 1, 12,
            'multi_pv', 'multi', '返回候选着法数，用于支招列表展示')

        # 强制变着（胶囊开关）
        force_y = row_top + 4 * row_step
        force_check_rect = pygame.Rect(ai_rect.right - 72, force_y - 14, 52, 28)
        self._draw_text_left('强制变着', ai_rect.x + 20, force_y, 'ssmall', (60, 72, 92))
        self._draw_text_left('开启后尽量偏离常规最优着法，增加对局变化',
                             ai_rect.x + 20, force_y + 18, 'tiny', (150, 162, 180))
        self._draw_toggle_pill(force_check_rect, self.settings.force_variation)

        # ---- 保存 / 取消 ----
        save_y = ai_rect.bottom + 24
        save_rect = pygame.Rect(card_x + 40, save_y, 220, 50)
        self._draw_button(save_rect, '保存设置', 'large',
                          base=(92, 184, 120), hover=(70, 160, 100), text_color=(255, 255, 255))
        cancel_rect = pygame.Rect(card_x + card_w - 40 - 220, save_y, 220, 50)
        self._draw_button(cancel_rect, '取消', 'large',
                          base=(206, 108, 108), hover=(188, 86, 86), text_color=(255, 255, 255))

        self.settings_ui = {
            'music_check': music_check_rect,
            'effect_check': effect_check_rect,
            'depth_minus': depth_minus_rect,
            'depth_plus': depth_plus_rect,
            'skill_minus': skill_minus_rect,
            'skill_plus': skill_plus_rect,
            'time_minus': time_minus_rect,
            'time_plus': time_plus_rect,
            'multi_minus': multi_minus_rect,
            'multi_plus': multi_plus_rect,
            'force_check': force_check_rect,
            'save': save_rect,
            'cancel': cancel_rect
        }


    def _draw_slider(self, track, value, vmin, vmax):
        """在减号/加号之间绘制滑块：粗圆角轨道 + 蓝色填充段 + 带阴影圆形滑块。"""
        ratio = 0.0 if vmax == vmin else (value - vmin) / (vmax - vmin)
        ratio = max(0.0, min(1.0, ratio))
        # 轨道背景
        bg = pygame.Surface((track.width, track.height), pygame.SRCALPHA)
        pygame.draw.rect(bg, (214, 220, 230), bg.get_rect(), border_radius=track.height // 2)
        self.screen.blit(bg, (track.x, track.y))
        # 已填充段（蓝色）
        fw = max(track.height, int(track.width * ratio))
        fill = pygame.Surface((fw, track.height), pygame.SRCALPHA)
        pygame.draw.rect(fill, (92, 156, 236), fill.get_rect(), border_radius=track.height // 2)
        self.screen.blit(fill, (track.x, track.y))
        # 滑块圆点（带阴影 + 白边）
        tx = track.x + int(track.width * ratio)
        ty = track.y + track.height // 2
        kr = track.height // 2 + 5
        shadow = pygame.Surface((kr * 2, kr * 2), pygame.SRCALPHA)
        pygame.draw.circle(shadow, (0, 0, 0, 55), (kr, kr), kr)
        self.screen.blit(shadow, (tx - kr + 1, ty - kr + 2))
        pygame.draw.circle(self.screen, (255, 255, 255), (tx, ty), kr)
        pygame.draw.circle(self.screen, (70, 130, 210), (tx, ty), kr - 2)


    def _settings_slider_down(self, x, y):
        """点击滑块轨道即开始拖拽，返回是否命中滑块。"""
        for s in self.settings_sliders:
            t = s['track']
            hit = pygame.Rect(t.x, t.y - 10, t.width, t.height + 20)
            if hit.collidepoint(x, y):
                self.settings_drag_key = s['key']
                self._apply_slider_drag(x)
                return True
        return False


    def _apply_slider_drag(self, x):
        for s in self.settings_sliders:
            if s['key'] == self.settings_drag_key:
                t = s['track']
                ratio = max(0.0, min(1.0, (x - t.x) / t.width))
                val = int(round(s['vmin'] + ratio * (s['vmax'] - s['vmin'])))
                val = max(s['vmin'], min(s['vmax'], val))
                setattr(self.settings, s['attr'], val)
                break


    def handle_settings_click(self, x: int, y: int):
        if 'music_check' in self.settings_ui and self.settings_ui['music_check'].collidepoint(x, y):
            self.settings.is_music_play = not self.settings.is_music_play
        elif 'effect_check' in self.settings_ui and self.settings_ui['effect_check'].collidepoint(x, y):
            self.settings.is_effect_play = not self.settings.is_effect_play
        elif 'depth_minus' in self.settings_ui and self.settings_ui['depth_minus'].collidepoint(x, y):
            self.settings.depth = max(5, self.settings.depth - 1)
        elif 'depth_plus' in self.settings_ui and self.settings_ui['depth_plus'].collidepoint(x, y):
            self.settings.depth = min(120, self.settings.depth + 1)
        elif 'skill_minus' in self.settings_ui and self.settings_ui['skill_minus'].collidepoint(x, y):
            self.settings.skill_level = max(1, self.settings.skill_level - 1)
        elif 'skill_plus' in self.settings_ui and self.settings_ui['skill_plus'].collidepoint(x, y):
            self.settings.skill_level = min(20, self.settings.skill_level + 1)
        elif 'time_minus' in self.settings_ui and self.settings_ui['time_minus'].collidepoint(x, y):
            self.settings.thinking_time = max(1, self.settings.thinking_time - 1)
        elif 'time_plus' in self.settings_ui and self.settings_ui['time_plus'].collidepoint(x, y):
            self.settings.thinking_time = min(60, self.settings.thinking_time + 1)
        elif 'multi_minus' in self.settings_ui and self.settings_ui['multi_minus'].collidepoint(x, y):
            self.settings.multi_pv = max(1, self.settings.multi_pv - 1)
        elif 'multi_plus' in self.settings_ui and self.settings_ui['multi_plus'].collidepoint(x, y):
            self.settings.multi_pv = min(12, self.settings.multi_pv + 1)
        elif 'force_check' in self.settings_ui and self.settings_ui['force_check'].collidepoint(x, y):
            self.settings.force_variation = not self.settings.force_variation
        elif 'save' in self.settings_ui and self.settings_ui['save'].collidepoint(x, y):
            self.settings.save()
            self._sync_settings()
            self.apply_settings_to_ai()
            self.show_settings = False
        elif 'cancel' in self.settings_ui and self.settings_ui['cancel'].collidepoint(x, y):
            self.show_settings = False


    def apply_settings_to_ai(self):
        if self.ai.initialized:
            self.ai._send_command(f'setoption name Skill Level value {self.settings.skill_level}')
            self.ai._send_command(f'setoption name Contempt value {self.settings.contempt}')
            self.ai._send_command(f'setoption name MultiPV value {self.settings.multi_pv}')
            self.ai._send_command('isready')
        # 同步应用到独立的评估引擎（线程数保持减半，不在此覆盖）
        eval_ai = getattr(self, 'eval_ai', None)
        if eval_ai is not None and eval_ai.initialized:
            eval_ai._send_command(f'setoption name Skill Level value {self.settings.skill_level}')
            eval_ai._send_command(f'setoption name Contempt value {self.settings.contempt}')
            eval_ai._send_command(f'setoption name MultiPV value {self.settings.multi_pv}')
            eval_ai._send_command('isready')


    def _sync_settings(self):
        self.chess_info.setting.is_music_play = self.settings.is_music_play
        self.chess_info.setting.is_effect_play = self.settings.is_effect_play
        self.chess_info.setting.m_level = self.settings.m_level
        self.chess_info.setting.depth = self.settings.depth
        self.chess_info.setting.skill_level = self.settings.skill_level
        self.chess_info.setting.multi_pv = self.settings.multi_pv
        self.chess_info.setting.contempt = self.settings.contempt
        self.chess_info.setting.force_variation = self.settings.force_variation
        self.chess_info.setting.thinking_time = self.settings.thinking_time

