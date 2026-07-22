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
                     icon=None, icon_only=False):
        hovered = rect.collidepoint(self.mouse_pos)
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
            icon_cx = rect.centerx if icon_only else rect.x + 16
            self._draw_button_glyph(rect, icon, label_color, icon_cx)
            if icon_only:
                return
        surf = self._text_surface(label, font_size, label_color)
        if surf:
            if icon:
                self.screen.blit(surf, (rect.x + 36, rect.centery - surf.get_height() // 2))
            else:
                self.screen.blit(surf, (rect.centerx - surf.get_width() // 2,
                                        rect.centery - surf.get_height() // 2))


    def _draw_button_glyph(self, rect, kind, color, cx=None):
        import math
        if cx is None:
            cx = rect.x + 16
        cy = rect.centery
        s = 8
        if kind in ('prev', 'next'):
            d = -1 if kind == 'prev' else 1
            pygame.draw.line(self.screen, color, (cx - d * s, cy), (cx + d * s, cy), 3)
            pygame.draw.polygon(self.screen, color,
                                [(cx + d * s, cy), (cx + d * s - d * 6, cy - 6), (cx + d * s - d * 6, cy + 6)])
        elif kind == 'undo':
            pygame.draw.arc(self.screen, color, (cx - 9, cy - 7, 18, 14), 0.5, 5.4, 3)
            pygame.draw.polygon(self.screen, color,
                                [(cx - 9, cy), (cx - 3, cy - 5), (cx - 3, cy + 5)])
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
            # 旋转箭头（↻）：约 3/4 圈弧线 + 末端箭头，表示翻转棋盘
            r = 9
            start = math.radians(40)
            end = math.radians(320)
            pygame.draw.arc(self.screen, color, (cx - r, cy - r, 2 * r, 2 * r), start, end, 3)
            ex, ey = cx + r * math.cos(end), cy + r * math.sin(end)
            tx, ty = -math.sin(end), math.cos(end)   # 切向（运动方向）
            px, py = math.cos(end), math.sin(end)    # 径向
            ah = 6
            pygame.draw.polygon(self.screen, color, [
                (ex, ey),
                (ex - ah * tx + ah * 0.5 * px, ey - ah * ty + ah * 0.5 * py),
                (ex - ah * tx - ah * 0.5 * px, ey - ah * ty - ah * 0.5 * py),
            ])
        else:
            pygame.draw.circle(self.screen, color, (cx, cy), s, 2)


    def _draw_star(self, cx, cy, r_out, r_in, color):
        import math
        pts = []
        for i in range(10):
            ang = -math.pi / 2 + i * math.pi / 5
            r = r_out if i % 2 == 0 else r_in
            pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
        pygame.draw.polygon(self.screen, color, pts)


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

