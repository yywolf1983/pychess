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


class WidgetsMixin:
    def _gradient_rect(self, rect, top, bottom):
        surface = pygame.Surface((rect.width, rect.height))
        for i in range(rect.height):
            t = i / max(1, rect.height - 1)
            r = int(top[0] + (bottom[0] - top[0]) * t)
            g = int(top[1] + (bottom[1] - top[1]) * t)
            b = int(top[2] + (bottom[2] - top[2]) * t)
            pygame.draw.line(surface, (r, g, b), (0, i), (rect.width, i))
        self.screen.blit(surface, (rect.x, rect.y))


    def _draw_button(self, rect, label, font_size='small', base=(58, 78, 104),
                     hover=(100, 150, 255), active=False, text_color=(235, 240, 248),
                     icon=None, icon_only=False, badge=None, spinner=False):
        # 顶部「模式」菜单展开时，鼠标落在菜单面板上不应触发其下方按钮的悬停高亮
        captured = bool(getattr(self, 'mode_menu_open', False)) and \
            getattr(self, 'mode_menu_panel_rect', None) is not None and \
            self.mode_menu_panel_rect.collidepoint(self.mouse_pos)
        hovered = rect.collidepoint(self.mouse_pos) and not captured
        color = hover if (hovered or active) else base
        # 阴影
        shadow = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
        pygame.draw.rect(shadow, (0, 0, 0, 50), shadow.get_rect(), border_radius=12)
        self.screen.blit(shadow, (rect.x + 2, rect.y + 3))
        # 主体
        pygame.draw.rect(self.screen, color, rect, border_radius=12)
        # 顶部高光
        if hovered or active:
            hi = pygame.Surface((rect.width, rect.height // 2), pygame.SRCALPHA)
            pygame.draw.rect(hi, (255, 255, 255, 45), hi.get_rect(), border_radius=12)
            self.screen.blit(hi, (rect.x, rect.y))
        label_color = (255, 255, 255) if (hovered or active) else text_color
        if icon:
            if icon_only:
                # 仅图标按钮：图标居中偏上，下方附小号文字说明，保证可辨识
                self._draw_button_glyph(rect, icon, label_color, rect.centerx, rect.centery - 12)
                cap = self._text_surface(label, 'tiny', label_color)
                if cap:
                    self.screen.blit(cap, (rect.centerx - cap.get_width() // 2,
                                           rect.bottom - cap.get_height() - 8))
                return
            icon_cx = rect.x + 16
            self._draw_button_glyph(rect, icon, label_color, icon_cx)
        surf = self._text_surface(label, font_size, label_color)
        if surf:
            if icon:
                self.screen.blit(surf, (rect.x + 36, rect.centery - surf.get_height() // 2))
            elif badge is not None:
                # 带模式色块按钮：文字靠左、右侧绘制当前模式色块，一眼可辨
                self.screen.blit(surf, (rect.x + 16, rect.centery - surf.get_height() // 2))
                chip = pygame.Rect(rect.right - 26, rect.centery - 8, 16, 16)
                pygame.draw.rect(self.screen, badge, chip, border_radius=4)
                pygame.draw.rect(self.screen, (255, 255, 255, 90), chip, 1, border_radius=4)
            else:
                self.screen.blit(surf, (rect.centerx - surf.get_width() // 2,
                                        rect.centery - surf.get_height() // 2))
        if spinner:
            # 旋转加载环：约 300° 弧随时间旋转，表示正在思考
            phase = time.time() * 6.0
            self._draw_spinner(rect.right - 22, rect.centery, 9, label_color, phase)


    def _draw_button_glyph(self, rect, kind, color, cx=None, cy=None):
        if cx is None:
            cx = rect.x + 16
        if cy is None:
            cy = rect.centery
        s = 8
        if kind in ('prev', 'next'):
            d = -1 if kind == 'prev' else 1
            pygame.draw.line(self.screen, color, (cx - d * s, cy), (cx + d * s, cy), 3)
            pygame.draw.polygon(self.screen, color,
                                [(cx + d * s, cy), (cx + d * s - d * 6, cy - 6), (cx + d * s - d * 6, cy + 6)])
        elif kind == 'undo':
            # 回退：逆时针 3/4 圈弧形箭头，箭头在左侧，指向「后退」方向
            self._draw_circular_arrow(cx, cy, 9, 180, 290, ccw=True, color=color,
                                      width=3, ah=7)
        elif kind == 'restart':
            pygame.draw.arc(self.screen, color, (cx - 9, cy - 9, 18, 18), 0.4, 5.6, 3)
            pygame.draw.polygon(self.screen, color,
                                [(cx + 9, cy), (cx + 3, cy - 5), (cx + 3, cy + 5)])
        elif kind == 'hint':
            self._draw_star(cx, cy, s + 1, s * 0.45, color)
        elif kind == 'save':
            pygame.draw.rect(self.screen, color, (cx - 8, cy - 8, 16, 16), 2)
            pygame.draw.rect(self.screen, color, (cx - 5, cy - 8, 10, 6))
        elif kind == 'load':
            pygame.draw.rect(self.screen, color, (cx - 8, cy - 6, 16, 12), 2)
            pygame.draw.rect(self.screen, color, (cx - 8, cy - 9, 7, 4), 2)
        elif kind == 'settings':
            pygame.draw.circle(self.screen, color, (cx, cy), 7, 2)
            for a in range(8):
                ang = a * math.pi / 4
                x1, y1 = cx + 7 * math.cos(ang), cy + 7 * math.sin(ang)
                x2, y2 = cx + 10 * math.cos(ang), cy + 10 * math.sin(ang)
                pygame.draw.line(self.screen, color, (x1, y1), (x2, y2), 2)
        elif kind == 'flip':
            # 翻转棋盘：顺时针双箭头圆环（刷新/旋转意象），明确区别于「悔棋」单箭头
            self._draw_circular_arrow(cx, cy, 9, 60, 300, ccw=False, color=color,
                                      width=3, ah=7, double=True)
        elif kind == 'check':
            # 勾选标记：表示当前选中的对战模式
            pygame.draw.line(self.screen, color, (cx - 7, cy), (cx - 1, cy + 7), 3)
            pygame.draw.line(self.screen, color, (cx - 1, cy + 7), (cx + 8, cy - 7), 3)
        else:
            pygame.draw.circle(self.screen, color, (cx, cy), s, 2)


    def _arrow_head(self, hx, hy, tx, ty, px, py, color, ah):
        """在 (hx,hy) 处画箭头：tx,ty 为运动切线方向，px,py 为径向。"""
        pygame.draw.polygon(self.screen, color, [
            (hx, hy),
            (hx - ah * tx + ah * 0.5 * px, hy - ah * ty + ah * 0.5 * py),
            (hx - ah * tx - ah * 0.5 * px, hy - ah * ty - ah * 0.5 * py),
        ])

    def _draw_circular_arrow(self, cx, cy, r, head_deg, span_deg, ccw, color,
                             width=3, ah=7, double=False):
        """绘制圆环弧形箭头。head_deg 为箭头所在角度（度），span_deg 为弧跨度，
        ccw=True 表示逆时针行进（角度递增）。double=True 时两端都画箭头，呈刷新/旋转意象。"""
        head = math.radians(head_deg)
        span = math.radians(span_deg)
        start = head
        end = head + span if ccw else head - span
        pygame.draw.arc(self.screen, color,
                        (cx - r, cy - r, 2 * r, 2 * r), start, end, width)
        # 起点（head）箭头，沿运动切向
        if ccw:
            htx, hty = -math.sin(head), math.cos(head)
        else:
            htx, hty = math.sin(head), -math.cos(head)
        hpx, hpy = math.cos(head), math.sin(head)
        self._arrow_head(cx + r * hpx, cy + r * hpy, htx, hty, hpx, hpy, color, ah)
        if double:
            # 终点箭头，运动方向相反
            if ccw:
                ttx, tty = -math.sin(end), math.cos(end)
            else:
                ttx, tty = math.sin(end), -math.cos(end)
            tpx, tpy = math.cos(end), math.sin(end)
            self._arrow_head(cx + r * tpx, cy + r * tpy, ttx, tty, tpx, tpy, color, ah)


    def _draw_star(self, cx, cy, r_out, r_in, color):
        import math
        pts = []
        for i in range(10):
            ang = -math.pi / 2 + i * math.pi / 5
            r = r_out if i % 2 == 0 else r_in
            pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
        pygame.draw.polygon(self.screen, color, pts)


    def _draw_spinner(self, cx, cy, r, color, phase):
        """绘制旋转加载环（约 300° 弧，phase 随时间推进形成旋转动画）。"""
        start = phase
        end = phase + math.radians(300)
        pygame.draw.arc(self.screen, color,
                        (cx - r, cy - r, 2 * r, 2 * r), start, end, 3)


    def _draw_card(self, rect, fill=(255, 255, 255)):
        shadow = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
        pygame.draw.rect(shadow, (0, 0, 0, 40), shadow.get_rect(), border_radius=14)
        self.screen.blit(shadow, (rect.x + 2, rect.y + 3))
        pygame.draw.rect(self.screen, fill, rect, border_radius=14)


    def _draw_section(self, x, y, title):
        self._draw_text_left(title, x, y, 'small', (150, 172, 200))
        pygame.draw.line(self.screen, (140, 160, 185, 130),
                         (x, y + 16), (x + self.sidebar_width - 40, y + 16), 1)


    def _draw_checkmark(self, rect, color):
        p1 = (rect.x + rect.width * 0.22, rect.y + rect.height * 0.55)
        p2 = (rect.x + rect.width * 0.43, rect.y + rect.height * 0.73)
        p3 = (rect.x + rect.width * 0.80, rect.y + rect.height * 0.27)
        pygame.draw.lines(self.screen, color, False, [p1, p2, p3], 3)


    def _draw_toggle(self, rect, checked):
        fill = (96, 196, 130) if checked else (206, 212, 222)
        pygame.draw.rect(self.screen, fill, rect, border_radius=8)
        if checked:
            self._draw_checkmark(rect, (255, 255, 255))


    def _draw_rounded_card(self, rect, top, bottom, border, radius=14):
        """暗色圆角卡片 + 垂直渐变（参照 Android ScoreCurveView 卡片）。"""
        surf = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
        for row in range(rect.height):
            t = row / max(1, rect.height - 1)
            col = (int(top[0] + (bottom[0] - top[0]) * t),
                   int(top[1] + (bottom[1] - top[1]) * t),
                   int(top[2] + (bottom[2] - top[2]) * t))
            pygame.draw.line(surf, col, (0, row), (rect.width, row))
        mask = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
        pygame.draw.rect(mask, (255, 255, 255), (0, 0, rect.width, rect.height), border_radius=radius)
        surf.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
        self.screen.blit(surf, (rect.x, rect.y))
        if border:
            pygame.draw.rect(self.screen, border, rect, border_radius=radius, width=1)

