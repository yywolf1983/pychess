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


class TextRenderMixin:
    def _resolve_cjk_font(self):
        """解析一个可用（含中文字形）的字体路径。

        优先返回随项目打包的相对路径字体（相对本模块文件定位），
        因此无论项目放在哪个系统、哪个目录下都能稳定找到；
        其次回退到各系统常见的中文字体绝对路径。找不到则返回 None。
        """
        here = os.path.dirname(os.path.abspath(__file__))
        candidates = [
            # 1) 随项目打包（相对路径，跨系统保证可用）
            os.path.join(here, '..', 'resources', 'fonts', 'cjk.ttf'),
            os.path.join(here, '..', '..', 'src', 'resources', 'fonts', 'cjk.ttf'),
            # 2) Windows 常见中文字体
            'C:/Windows/Fonts/msyh.ttc',
            'C:/Windows/Fonts/simhei.ttf',
            'C:/Windows/Fonts/simsun.ttc',
            'C:/Windows/Fonts/msyhbd.ttc',
            # 3) macOS 常见中文字体
            '/System/Library/Fonts/STHeiti Light.ttc',
            '/System/Library/Fonts/PingFang.ttc',
            '/System/Library/Fonts/Supplemental/Songti.ttc',
            # 4) Linux 及其它常见中文字体
            '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
            '/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc',
            '/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc',
            '/usr/share/fonts/truetype/wqy/wqy-microhei.ttc',
            '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc',
            '/usr/share/fonts/opentype/wqy/wqy-zenhei.ttc',
        ]
        # PIL 可用时，用 truetype 实际打开来校验字体确实可用
        can_open = None
        if self.pil_available if hasattr(self, 'pil_available') else False:
            try:
                from PIL import ImageFont  # noqa
                can_open = lambda fp: ImageFont.truetype(fp, 36) or True
            except Exception:
                can_open = None
        for fp in candidates:
            try:
                fp = os.path.normpath(fp)
            except Exception:
                pass
            if not fp or not os.path.exists(fp):
                continue
            if can_open is not None:
                try:
                    can_open(fp)
                except Exception:
                    continue
            return fp
        return None


    def _text_surface(self, text, font_size='large', color=(0, 0, 0)):
        """获取文字 Surface：优先用解析到的中文字体（PIL 高质量 / pygame 兜底），
        保证所有系统下中文正常显示；若该字体缺失才回退到西文默认字体。"""
        if not text:
            return None

        # 各档位对应的像素字号
        size_map = {'large': 42, 'medium': 34, 'small': 28, 'xsmall': 18}
        px = size_map.get(font_size, 28)

        # 路径1：PIL 高质量 CJK 渲染（使用随项目打包 / 系统解析出的中文字体）
        if self.pil_available and self.cjk_font_path:
            try:
                from PIL import Image, ImageDraw, ImageFont
                font = ImageFont.truetype(self.cjk_font_path, px)
                # 画布宽度按文本长度估算，避免长字符串（如 FEN）被裁切
                est_w = max(1200, int(len(str(text)) * px * 1.2) + 80)
                est_h = max(120, px * 2 + 60)
                canvas = Image.new('RGBA', (est_w, est_h), (0, 0, 0, 0))
                draw = ImageDraw.Draw(canvas)
                draw.text((20, 20), text, font=font, fill=color)

                # textbbox 仅 Pillow ≥8.2 支持，低版本回退 textsize
                try:
                    bbox = draw.textbbox((20, 20), text, font=font)
                except AttributeError:
                    w, h = draw.textsize(text, font=font)
                    bbox = (20, 20, 20 + w, 20 + h)

                canvas = canvas.crop((max(0, bbox[0] - 4), max(0, bbox[1] - 4),
                                      bbox[2] + 4, bbox[3] + 4))
                return pygame.image.fromstring(
                    canvas.tobytes(), canvas.size, canvas.mode
                ).convert_alpha()
            except Exception:
                pass  # 回退到 pygame 路径

        # 路径2：pygame 字体兜底（优先使用同一中文字体，确保中文可用）
        try:
            if not hasattr(self, '_pg_fonts'):
                pygame.font.init()
                self._pg_fonts = {}
            if font_size not in self._pg_fonts:
                if self.cjk_font_path:
                    try:
                        self._pg_fonts[font_size] = pygame.font.Font(self.cjk_font_path, px)
                    except Exception:
                        self._pg_fonts[font_size] = pygame.font.SysFont(None, px)
                else:
                    self._pg_fonts[font_size] = pygame.font.SysFont(None, px)
            return self._pg_fonts[font_size].render(str(text), True, color).convert_alpha()
        except Exception:
            return None


    def _draw_text(self, text, x, y, font_size='large', color=(0, 0, 0)):
        """以 (x, y) 为中心绘制文字。"""
        surf = self._text_surface(text, font_size, color)
        if not surf:
            return
        self.screen.blit(surf, (x - surf.get_width() // 2, y - surf.get_height() // 2))


    def _draw_text_left(self, text, x, y, font_size='small', color=(0, 0, 0)):
        surf = self._text_surface(text, font_size, color)
        if not surf:
            return
        self.screen.blit(surf, (x, y - surf.get_height() // 2))


    def _draw_text_right(self, text, x, y, font_size='small', color=(0, 0, 0)):
        surf = self._text_surface(text, font_size, color)
        if not surf:
            return
        self.screen.blit(surf, (x - surf.get_width(), y - surf.get_height() // 2))


    def _draw_wrapped_text(self, text, x, y, max_w, line_h, color, font_size='small'):
        """按像素宽度自动换行绘制（用于摆棋 FEN 等长字符串）。"""
        lines, cur = [], ''
        for ch in text:
            test = cur + ch
            surf = self._text_surface(test, font_size, color)
            if surf and surf.get_width() > max_w and cur:
                lines.append(cur)
                cur = ch
            else:
                cur = test
        if cur:
            lines.append(cur)
        for i, ln in enumerate(lines):
            self._draw_text_left(ln, x, y + i * line_h, font_size, color)
        return len(lines)

