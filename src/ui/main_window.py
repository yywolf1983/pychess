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


class MainWindow:
    GAME_MODES = {
        'pvp': '双人对战',
        'pvm_red': '人机对战（红方）',
        'pvm_black': '人机对战（黑方）',
        'mvm': '双机对战'
    }
    
    def __init__(self):
        pygame.init()
        
        self.board_width = int(750 * 0.72)
        self.board_height = int(909 * 0.72)
        self.sidebar_width = 250
        # 顶部菜单栏（新局/加载/保存/设置/对战模式）
        self.menu_h = 54
        # 菜单栏下方的一条加粗评分条
        self.eval_top_h = 24
        self.eval_bottom_h = 200
        self.board_offset_y = self.menu_h + self.eval_top_h
        self.window_width = self.board_width + self.sidebar_width
        self.window_height = self.menu_h + self.eval_top_h + self.board_height + self.eval_bottom_h
        
        self.screen = pygame.display.set_mode((self.window_width, self.window_height))
        pygame.display.set_caption('中国象棋')
        
        self.chess_info = ChessInfo()
        self.chess_view = ChessView(
            self.screen.subsurface((0, self.board_offset_y, self.board_width, self.board_height)),
            self.chess_info)
        self.ai = PikafishAI()
        self.settings = Setting()
        self.settings.load()
        self._sync_settings()
        
        self.game_mode = 'pvp'
        self.player_color = 'red'
        self.is_ai_thinking = False
        self.ai_thread = None
        self.ai_result_queue = queue.Queue()
        self._ai_no_result = object()
        self.hint_queue = queue.Queue()
        self._hint_no_result = object()
        self.hint_loading = False
        self.hint_ui = []          # 支招区可点击条目（侧栏渲染时填充）
        self.hint_selected = -1    # 当前选中的支招序号（-1 表示未选）
        self.hint_window = None    # 多步支招窗口（候选着法列表）
        self.candidate_ui = []     # 底部候选着法面板可点击条目
        self.candidate_scroll = 0  # 候选列表纵向滚动偏移（像素）
        self.candidate_dragging = False  # 候选滚动条拖拽中
        self.candidate_max_scroll = 0
        self.candidate_scrollbar_track = None
        self.candidate_scrollbar_thumb = None

        # 模拟行棋（演示引擎推荐线，不污染真实对局）
        self.simulating = False
        self.sim_pv = []           # 当前模拟线的 Move 序列
        self.sim_pv_cn = []        # 当前模拟线的中文记谱
        self.sim_index = 0         # 已演示步数
        self.sim_restore = None    # 进入模拟前的完整局面副本
        self.sim_ui = {}           # 模拟面板按钮命中区
        self.sim_scroll = 0

        self.browse_index = None   # 局面浏览：None=实时对局；int=正在查看第 index 步
        self.board_snapshots = []  # 每一步（含初始）的棋盘快照，供上一步/下一步使用

        self.save_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config', 'saves')
        self.save_browser = None   # 存档浏览器窗口

        self.mouse_pos = (0, 0)
        self.show_settings = False
        self.settings_sliders = []
        self.settings_drag_key = None
        self.modal = None
        self.draw_response_queue = queue.Queue()
        self._draw_no_result = object()
        self.draw_loading = False
        self.toast = None
        self.toast_until = 0
        # 实时评分（红方视角，单位 centipawn：正=红优 / 负=黑优）
        self.eval_score = None
        self.eval_history = []
        self.eval_depth = 0
        self.eval_gen = 0
        self.eval_loading = False
        self.ai_lines = []  # 支招/分析浮层：每条候选 = {score, my, opp, my_is_red}
        # 摆棋（局面编辑）状态
        self.editing = False
        self.edit_piece = None  # 选中的棋子 piece_id；None 表示未选中
        self.edit_ui = {}
        self.edit_scroll = 0  # 摆棋面板滚动偏移（像素）
        self.edit_vp = None   # 摆棋面板滚动视口
        self._edit_dragging = False      # 滚动条滑块拖拽中
        self.edit_drag_pid = None        # 从摆棋区拖拽到棋盘的棋子 pid
        self.edit_drag_pos = None        # 拖拽时鼠标位置（屏幕坐标）
        self.edit_drag_start = None      # 拖拽起点（屏幕坐标）
        self.edit_drag_moved = False     # 本次拖拽是否已移动（区分点击与拖拽）
        self._edit_last_click = None     # (cell, time, kind) 用于双击删除判定
        self._edit_pickup_cell = None    # 拾起棋子时的原格子（区分移动 / 删除）
        self.edit_history = []           # 摆棋操作撤销栈：每项可还原一次编辑
        self._candidate_last_click = None  # (index, tick) 候选着法双击进入模拟判定
        # 支招「跟线」跟踪状态：玩家按推荐线行棋时持续提示剩余着法
        self._track_pv = None        # 当前正在跟踪的推荐线（Move 列表）
        self._track_idx = 0          # 下一个待校验的 PV 步索引
        self._track_my_is_red = True # 该推荐线首步方颜色
        self._edit_img_cache = {}  # 摆棋调色板棋子图片缓存 (piece_id, size) -> Surface
        
        try:
            from PIL import Image, ImageDraw, ImageFont
            self.pil_available = True
            cjk_font_paths = [
                # Windows
                'C:/Windows/Fonts/msyh.ttc',
                'C:/Windows/Fonts/simhei.ttf',
                'C:/Windows/Fonts/simsun.ttc',
                'C:/Windows/Fonts/msyhbd.ttc',
                # macOS
                '/System/Library/Fonts/STHeiti Light.ttc',
                '/System/Library/Fonts/PingFang.ttc',
                # Linux
                '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
                '/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc',
                '/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc',
            ]
            loaded = False
            for fp in cjk_font_paths:
                if os.path.exists(fp):
                    try:
                        self.pil_font = ImageFont.truetype(fp, 36)
                        self.pil_small_font = ImageFont.truetype(fp, 24)
                        self.pil_xs_font = ImageFont.truetype(fp, 14)
                        loaded = True
                        break
                    except Exception:
                        continue
            if not loaded:
                self.pil_font = ImageFont.load_default()
                self.pil_small_font = ImageFont.load_default()
                self.pil_xs_font = ImageFont.load_default()
        except:
            self.pil_available = False
        
        self.menu_buttons = []   # 头部菜单：新局/加载/保存/设置 + 模式（下拉）
        self.side_buttons = []   # 侧栏大按钮：摆棋/上一步/下一步/悔棋/支招
        self.mode_menu_open = False
        self.mode_menu_rects = []
        self._init_buttons()
        
        self.running = True
        self.clock = pygame.time.Clock()
    
    def _init_buttons(self):
        # ===== 头部菜单栏：功能项 + 对战模式 =====
        menu_items = [
            ('act:restart', '新局', 'restart', 'action'),
            ('act:load', '加载', 'load', 'action'),
            ('act:save', '保存', 'save', 'action'),
            ('act:settings', '设置', 'settings', 'action'),
            ('mode', '模式', None, 'mode'),
        ]
        pad = 10
        gap = 8
        n = len(menu_items)
        bw = (self.window_width - 2 * pad - (n - 1) * gap) / n
        bh = 38
        by = (self.menu_h - bh) // 2
        for i, (key, label, icon, kind) in enumerate(menu_items):
            x = pad + i * (bw + gap)
            self.menu_buttons.append({
                'rect': pygame.Rect(int(x), by, int(bw), bh),
                'key': key, 'label': label, 'icon': icon, 'kind': kind
            })

        # ===== 侧栏大按钮：摆棋 / 上一步 / 下一步 / 悔棋 / 支招 =====
        sx = self.board_width + 20
        sw = self.sidebar_width - 40
        sy0 = self.menu_h + 72   # 侧栏标题之下
        big_h = 58
        big_gap = 14
        nav_w = (sw - 12) // 2
        self.side_buttons = []
        # 摆棋（整行）
        self.side_buttons.append({
            'rect': pygame.Rect(sx, sy0, sw, big_h),
            'key': 'edit', 'label': '摆棋', 'icon': None
        })
        # 上一步 / 下一步（同一行，仅图标）
        nav_y = sy0 + big_h + big_gap
        self.side_buttons.append({
            'rect': pygame.Rect(sx, nav_y, nav_w, big_h),
            'key': 'prev', 'label': '上一步', 'icon': 'prev', 'icon_only': True
        })
        self.side_buttons.append({
            'rect': pygame.Rect(sx + nav_w + 12, nav_y, nav_w, big_h),
            'key': 'next', 'label': '下一步', 'icon': 'next', 'icon_only': True
        })
        # 悔棋（整行）
        undo_y = nav_y + big_h + big_gap
        self.side_buttons.append({
            'rect': pygame.Rect(sx, undo_y, sw, big_h),
            'key': 'undo', 'label': '悔棋', 'icon': 'undo'
        })
        # 支招（整行）
        hint_y = undo_y + big_h + big_gap
        self.side_buttons.append({
            'rect': pygame.Rect(sx, hint_y, sw, big_h),
            'key': 'hint', 'label': '支招', 'icon': 'hint'
        })
        # 摆棋开关沿用第一个大按钮
        self.edit_button = self.side_buttons[0]['rect']
    
    def _text_surface(self, text, font_size='large', color=(0, 0, 0)):
        if not self.pil_available:
            return None
        from PIL import Image, ImageDraw
        if font_size == 'large':
            font = self.pil_font
        elif font_size == 'xsmall':
            font = self.pil_xs_font
        else:
            font = self.pil_small_font
        canvas = Image.new('RGBA', (1000, 200), (0, 0, 0, 0))
        draw = ImageDraw.Draw(canvas)
        draw.text((20, 20), text, font=font, fill=color)
        bbox = draw.textbbox((20, 20), text, font=font)
        canvas = canvas.crop((max(0, bbox[0] - 4), max(0, bbox[1] - 4),
                              bbox[2] + 4, bbox[3] + 4))
        return pygame.image.fromstring(canvas.tobytes(), canvas.size, canvas.mode).convert_alpha()

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

    def draw_menu_bar(self):
        """顶部菜单栏：新局 / 加载 / 保存 / 设置 + 对战模式。"""
        bar = pygame.Rect(0, 0, self.window_width, self.menu_h)
        self._gradient_rect(bar, (40, 54, 74), (26, 36, 52))
        pygame.draw.line(self.screen, (64, 82, 108),
                         (0, self.menu_h - 1), (self.window_width, self.menu_h - 1), 1)
        mode_label = {'pvp': '双人', 'pvm_red': '人机红', 'pvm_black': '人机黑', 'mvm': '双机'}
        for btn in self.menu_buttons:
            key = btn['key']
            if btn['kind'] == 'mode':
                label = '模式：' + mode_label.get(self.game_mode, '双人')
                active = self.mode_menu_open
                base, hover = (54, 72, 98), (216, 168, 80)
            else:
                label = btn['label']
                active = False
                base, hover = (54, 72, 98), (100, 150, 255)
            self._draw_button(btn['rect'], label, 'small',
                              base=base, hover=hover, active=active,
                              text_color=(235, 240, 248), icon=btn.get('icon'))

    def _draw_mode_menu(self):
        """点击头部「模式」按钮后弹出的选择列表（覆盖在侧栏上方）。"""
        if not self.mode_menu_open:
            self.mode_menu_rects = []
            return
        # 以头部「模式」按钮为锚点，向下展开
        anchor = next(b['rect'] for b in self.menu_buttons if b['key'] == 'mode')
        items = [
            ('pvp', '双人对战', (76, 175, 80)),
            ('pvm_red', '玩家执红', (200, 60, 60)),
            ('pvm_black', '玩家执黑', (60, 60, 70)),
            ('mvm', '双机对战', (90, 150, 235)),
        ]
        row_h = 46
        pad = 6
        w = 240
        x = anchor.x
        y = anchor.y + anchor.h + 4
        panel = pygame.Rect(x, y, w, len(items) * row_h + pad * 2)
        # 半透明遮罩（捕获外部点击关闭），仅覆盖侧栏右侧区域
        self._gradient_rect(panel, (40, 54, 74), (28, 38, 54))
        pygame.draw.rect(self.screen, (120, 150, 190), panel, 1, border_radius=8)
        self.mode_menu_rects = []
        for i, (mode, label, color) in enumerate(items):
            ry = y + pad + i * row_h
            r = pygame.Rect(x + pad, ry, w - 2 * pad, row_h - 6)
            sel = mode == self.game_mode
            bg = (60, 80, 110) if sel else (50, 66, 92)
            pygame.draw.rect(self.screen, bg, r, border_radius=6)
            # 左侧主题色条
            pygame.draw.rect(self.screen, color, pygame.Rect(r.x, r.y, 5, r.h), border_radius=3)
            # 选中勾
            if sel:
                self._draw_text('✓', r.x + r.w - 16, r.y + r.h // 2, 'small', color)
            self._draw_text_left(label, r.x + 16, r.y + r.h // 2, 'small',
                                 (235, 240, 248))
            self.mode_menu_rects.append((r, mode))

    def draw_sidebar(self):
        sb_x = self.board_width
        # 侧栏只延伸到棋盘底部；其下整条区域由底部面板（全宽）覆盖
        y0 = self.board_offset_y + self.board_height
        self._gradient_rect(pygame.Rect(sb_x, self.menu_h, self.sidebar_width,
                                        y0 - self.menu_h),
                            (45, 62, 84), (28, 40, 58))

        # 标题（菜单栏下方）
        self._draw_text('中国象棋', sb_x + self.sidebar_width // 2,
                        self.menu_h + 30, 'large', (245, 212, 132))

        # 摆棋（编辑局面）开关 = 第一个侧栏大按钮
        self._draw_button(self.edit_button,
                          '完成编辑' if self.editing else '摆棋', 'large',
                          base=(70, 112, 86) if self.editing else (58, 78, 104),
                          hover=(96, 196, 130), active=self.editing,
                          text_color=(235, 248, 240))

        if self.editing:
            self._draw_edit_panel(sb_x)
            return

        self.hint_ui = []  # 每帧重建支招区可点击条目

        # 侧栏大按钮：上一步 / 下一步 / 悔棋 / 支招
        for btn in self.side_buttons[1:]:
            if btn['key'] == 'hint':
                base, hover = (70, 112, 86), (96, 196, 130)
                text_color = (235, 248, 240)
            else:
                base, hover = (58, 78, 104), (100, 150, 255)
                text_color = (235, 240, 248)
            active = (btn['key'] == 'hint' and self.hint_loading)
            self._draw_button(btn['rect'], btn['label'], 'large',
                              base=base, hover=hover, active=active,
                              text_color=text_color, icon=btn.get('icon'),
                              icon_only=btn.get('icon_only', False))

        # 状态卡片（起始于侧栏按钮区之后，延伸至底部面板之前）
        status_y0 = self.side_buttons[-1]['rect'].bottom + 16
        y0 = self.board_offset_y + self.board_height
        card = pygame.Rect(sb_x + 16, status_y0, self.sidebar_width - 32,
                            y0 - status_y0 - 16)
        self._draw_card(card, (248, 250, 252))
        cx = card.x + 18
        cw = card.width - 36
        cy = card.y + 24
        self._draw_text('对局状态', cx + cw // 2, cy, 'small', (70, 82, 104))
        cy += 34
        # 当前回合（归属方）提示
        turn_side = '红方' if self.chess_info.is_red_go else '黑方'
        turn_color = (210, 64, 52) if self.chess_info.is_red_go else (40, 44, 52)
        self._draw_text_left('当前回合', cx, cy, 'small', (70, 82, 104))
        self._draw_text_left(turn_side, cx + 72, cy, 'small', turn_color)
        cy += 28
        if self.chess_info.is_checked:
            self._draw_text('将军!', cx + cw // 2, cy, 'large', (222, 64, 32))
            cy += 34
        status = self.chess_info.get_game_status()
        result = self._result_info()
        if result:
            text, color, sub = result
            if status == 'checkmate':
                text = '将死 ' + text
            self._draw_text(text, cx + cw // 2, cy, 'large', color)
            cy += 32
            if sub:
                self._draw_text(sub, cx + cw // 2, cy, 'small', (110, 122, 144))
                cy += 26
        # 实时评分（顶部评分条为图形化展示，此处以文字呈现于对局状态）
        score_text, score_color = self._format_score(self.eval_score)
        self._draw_text_left(f'评分: {score_text}', cx, cy, 'small', score_color)
        cy += 26
        self._draw_text_left(f'步数: {len(self.chess_info.move_history)}', cx, cy, 'small', (90, 102, 124))
        cy += 26
        depth = self._current_depth()
        self._draw_text_left(f'深度: {depth if depth else "-"}', cx, cy, 'small', (90, 102, 124))
        cy += 26
        ai_status = 'AI 思考中...' if self.is_ai_thinking else 'AI 就绪'
        ai_color = (90, 156, 72) if not self.is_ai_thinking else (230, 132, 32)
        self._draw_text_left(ai_status, cx, cy, 'small', ai_color)
        cy += 26
    
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

    def draw_settings(self):
        self._gradient_rect(pygame.Rect(0, 0, self.window_width, self.window_height),
                            (236, 240, 245), (214, 220, 230))

        card_x = (self.window_width - 560) // 2
        card_y = 24
        card_w = 560
        card_h = self.window_height - 48
        self._draw_card(pygame.Rect(card_x, card_y, card_w, card_h), (255, 255, 255))

        content_x = card_x + 40
        cx = card_x + card_w // 2

        self._draw_text('设置', cx, card_y + 38, 'large', (40, 52, 72))
        pygame.draw.line(self.screen, (220, 224, 232), (content_x, card_y + 62),
                         (card_x + card_w - 40, card_y + 62), 1)

        # 音效设置
        self._draw_section(content_x, card_y + 96, '音效设置')
        music_check_rect = pygame.Rect(card_x + card_w - 90, card_y + 110, 42, 42)
        self._draw_text_left('背景音乐', content_x, card_y + 132, 'small', (60, 72, 92))
        self._draw_toggle(music_check_rect, self.settings.is_music_play)

        effect_check_rect = pygame.Rect(card_x + card_w - 90, card_y + 160, 42, 42)
        self._draw_text_left('音效', content_x, card_y + 182, 'small', (60, 72, 92))
        self._draw_toggle(effect_check_rect, self.settings.is_effect_play)

        # AI 设置（参数对齐 Android 版）
        self._draw_section(content_x, card_y + 234, 'AI 设置')

        # 数值参数：减号(左) / 滑条 / 加号(右) 三部分，滑条用于在加减之间连续调整
        self.settings_sliders = []
        minus_w, plus_w = 36, 36
        slider_w = 150
        gap = 10
        col_r = card_x + card_w - 40

        def draw_row(y, label, value, vmin, vmax, attr, key):
            self._draw_text_left(f'{label}: {value}', content_x, y, 'small', (60, 72, 92))
            # 固定布局：减号在左、滑条居中、加号在右 → [−][滑条][+]
            plus_rect = pygame.Rect(col_r - plus_w, y - 18, plus_w, 36)
            track = pygame.Rect(plus_rect.x - gap - slider_w, y - 9, slider_w, 6)
            minus_rect = pygame.Rect(track.x - gap - minus_w, y - 18, minus_w, 36)
            self._draw_button(minus_rect, '-', 'large')
            self._draw_button(plus_rect, '+', 'large')
            self._draw_slider(track, value, vmin, vmax)
            self.settings_sliders.append({'key': key, 'track': track,
                                          'vmin': vmin, 'vmax': vmax, 'attr': attr})
            return minus_rect, plus_rect

        depth_minus_rect, depth_plus_rect = draw_row(card_y + 290, '搜索深度 (层)',
                                                     self.settings.depth, 5, 120, 'depth', 'depth')
        skill_minus_rect, skill_plus_rect = draw_row(card_y + 340, '技能级别 (级)',
                                                     self.settings.skill_level, 1, 20, 'skill_level', 'skill')
        time_minus_rect, time_plus_rect = draw_row(card_y + 390, '思考时间 (秒)',
                                                   self.settings.thinking_time, 1, 60, 'thinking_time', 'time')
        multi_minus_rect, multi_plus_rect = draw_row(card_y + 440, 'MultiPV (变)',
                                                     self.settings.multi_pv, 1, 12, 'multi_pv', 'multi')

        # 强制变着（对齐 Android）
        force_check_rect = pygame.Rect(card_x + card_w - 90, card_y + 462, 42, 42)
        self._draw_text_left('强制变着', content_x, card_y + 484, 'small', (60, 72, 92))
        self._draw_toggle(force_check_rect, self.settings.force_variation)

        save_rect = pygame.Rect(content_x, card_y + 540, 230, 52)
        self._draw_button(save_rect, '保存设置', 'large',
                          base=(92, 184, 120), hover=(70, 160, 100), text_color=(255, 255, 255))
        cancel_rect = pygame.Rect(card_x + card_w - 40 - 230, card_y + 540, 230, 52)
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
        """在减号/加号之间绘制评分滑块：轨道 + 已填充段 + 圆形滑块。"""
        ratio = 0.0 if vmax == vmin else (value - vmin) / (vmax - vmin)
        ratio = max(0.0, min(1.0, ratio))
        # 轨道背景
        bg = pygame.Surface((track.width, track.height), pygame.SRCALPHA)
        pygame.draw.rect(bg, (205, 211, 220), bg.get_rect(), border_radius=track.height // 2)
        self.screen.blit(bg, (track.x, track.y))
        # 已填充段（蓝色）
        fw = max(track.height, int(track.width * ratio))
        fill = pygame.Surface((fw, track.height), pygame.SRCALPHA)
        pygame.draw.rect(fill, (92, 156, 236), fill.get_rect(), border_radius=track.height // 2)
        self.screen.blit(fill, (track.x, track.y))
        # 滑块圆点
        tx = track.x + int(track.width * ratio)
        ty = track.y + track.height // 2
        pygame.draw.circle(self.screen, (255, 255, 255), (tx, ty), track.height // 2 + 4)
        pygame.draw.circle(self.screen, (70, 130, 210), (tx, ty), track.height // 2 + 1)

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
    
    def handle_click(self, x: int, y: int):
        if self.modal:
            rects = self._modal_button_rects()
            for i, btn in enumerate(self.modal['buttons']):
                if rects[i].collidepoint(x, y):
                    self._on_modal_button(btn['id'])
                    return
            return

        # 存档浏览器优先消费点击
        if self._handle_save_browser_click(x, y):
            return

        # 顶部菜单栏：新局 / 加载 / 保存 / 设置 + 模式（下拉）
        if self.mode_menu_open:
            # 选中模式项：切换并关闭
            for r, mode in self.mode_menu_rects:
                if r.collidepoint(x, y):
                    self.set_game_mode(mode)
                    self.mode_menu_open = False
                    return
            # 点中模式按钮本身则仅关闭；点别处也关闭
            mode_btn = next(b['rect'] for b in self.menu_buttons if b['key'] == 'mode')
            if mode_btn.collidepoint(x, y):
                self.mode_menu_open = False
            else:
                self.mode_menu_open = False
            return

        if y < self.menu_h:
            for btn in self.menu_buttons:
                if btn['rect'].collidepoint(x, y):
                    key = btn['key']
                    if key == 'mode':
                        self.mode_menu_open = not self.mode_menu_open
                    elif key.startswith('act:'):
                        self.handle_action(key.split(':')[1])
                    return
            return

        # 底部面板（占整个窗口宽度，优先于侧栏处理）
        if y >= self.board_offset_y + self.board_height:
            if self.simulating:
                self._handle_sim_click(x, y)
            else:
                self._handle_candidate_click(x, y)
            return

        if x < self.board_width:
            if self.editing:
                self._handle_edit_click(x, y)
                return
            board_pos = self.chess_view.get_board_coordinates(x, y - self.board_offset_y)
            if board_pos.x >= 0:
                self.handle_board_click(board_pos)
                return
        else:
            # 摆棋（编辑局面）开关
            if self.edit_button.collidepoint(x, y):
                self.toggle_edit()
                return

            if self.editing:
                # 先判断是否点中滚动条滑块，若是则进入拖拽
                if self.edit_vp is not None and x >= self.edit_vp.right - 10:
                    max_scroll = max(0, self.edit_content_bottom - self.edit_vp.bottom)
                    thumb = self._edit_scrollbar_rect(self.edit_vp, max_scroll)
                    if thumb and thumb.collidepoint(x, y):
                        self._edit_dragging = True
                        self._edit_drag_offset = y - thumb.y
                    return
                # 摆棋面板：点中棋子则进入“拖拽到棋盘”（无移动则视为选中）
                item = self._palette_item_at(x, y)
                if item and item[0] == 'piece':
                    self.edit_drag_pid = item[1]
                    self.edit_drag_pos = (x, y)
                    self.edit_drag_start = (x, y)
                    self.edit_drag_moved = False
                    return
                if item and item[0] == 'clear':
                    # 记录清空前的完整局面，便于悔棋一步还原
                    self.edit_history.append({
                        'type': 'clear',
                        'prev': [row[:] for row in self.chess_info.piece]})
                    for r in range(10):
                        for c in range(9):
                            self.chess_info.piece[r][c] = 0
                    self._after_edit()
                    return
                if item and item[0] == 'copy_fen':
                    self._copy_text(self.ai._board_to_fen(self.chess_info))
                    return
                # 点空白/置灰区域：取消当前选中
                self.edit_piece = None
                return

            # 侧栏大按钮：上一步 / 下一步 / 悔棋 / 支招（摆棋已单独处理）
            for btn in self.side_buttons[1:]:
                if btn['rect'].collidepoint(x, y):
                    self.handle_action(btn['key'])
                    return

            # 支招区域：点击候选着法即选中其起点棋子
            for entry in self.hint_ui:
                if entry['rect'].collidepoint(x, y):
                    self._select_hint(entry['index'])
                    return

    # ============ 摆棋（编辑局面） ============

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
        self.eval_score = None
        self.eval_gen += 1

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

    def handle_board_click(self, pos: Pos):
        if self.browse_index is not None:
            return  # 局面浏览中，棋盘不可落子
        if self.chess_info.get_game_status() != 'playing':
            return
        
        if self.is_ai_thinking:
            return
        
        if self.game_mode == 'mvm':
            return
        
        if self.game_mode == 'pvm_red' and not self.chess_info.is_red_go:
            return
        
        if self.game_mode == 'pvm_black' and self.chess_info.is_red_go:
            return
        
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
                self.request_eval()
                self._record_snapshot()
                if not self._update_hint_after_move(from_pos, pos):
                    self._clear_hint()
                else:
                    # 已开始跟线：收起着法选择框（曲线重新露出），跟线箭头仍保留
                    self.ai_lines = []
                self.hint_window = None
                self.check_ai_turn()
                status = self.chess_info.get_game_status()
                if status != 'playing':
                    res_text = self._result_info()[0] if self._result_info() else ''
                    if status == 'checkmate':
                        self.show_toast('将死！' + res_text)
                    elif status == 'stalemate':
                        self.show_toast('困毙！' + res_text)
                    else:
                        self.show_toast(res_text)
            else:
                # 改选其它棋子 -> 结束支招提示
                self._clear_hint()
                self.chess_info.select_piece(pos.x, pos.y)
        else:
            self.chess_info.select_piece(pos.x, pos.y)
    
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
        if not keep_lines:
            self.ai_lines = []

    # ============ 支招「跟线」跟踪 ============
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
        """在支招区域点击某候选着法：选中其起点棋子（棋盘落子即结束）。"""
        if index < 0 or index >= len(self.chess_info.suggest_moves):
            return
        mv = self.chess_info.suggest_moves[index]
        self.hint_selected = index
        self.chess_info.select_piece(mv.from_pos.x, mv.from_pos.y)

    def _handle_candidate_click(self, x, y):
        """底部候选着法面板：单击某路候选选中其起点棋子（棋盘联动高亮）。"""
        if not getattr(self, 'ai_lines', None):
            return
        for entry in self.candidate_ui:
            if entry['rect'].collidepoint(x, y):
                self._select_hint(entry['index'])
                return
    
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

    # ============ 规则触发的和棋 ============

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

    # ============ 实时评分 ============

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

    def _draw_eval_bar(self, x, y, w, score, bar_h=12):
        """评分条：从两端开始，左红右黑（参照 Android RoundView.drawScoreBar）。

        均势(score=0)时左右各占一半；某方占优则其色块向对方一侧延伸，
        分隔线随评分在正中左右偏移。满刻度 1000cp（与 Android 一致）。
        """
        h = bar_h
        rect = pygame.Rect(x, y, w, h)
        # 圆角兜底底（灰）
        bg_surf = pygame.Surface((w, h), pygame.SRCALPHA)
        pygame.draw.rect(bg_surf, (200, 205, 212), (0, 0, w, h), border_radius=h // 2)
        self.screen.blit(bg_surf, (x, y))

        # 分隔点：均势在正中；红优向右、黑优向左
        mid = x + w / 2
        total = w / 2
        if score is None:
            ratio = 0.0
        else:
            scale = 1000.0  # 满刻度 1000cp，与 Android 一致
            ratio = max(-1.0, min(1.0, score / scale))
        if ratio >= 0:
            div = mid + total * ratio
        else:
            div = mid - total * (-ratio)
        div = max(x, min(x + w, div))

        red_w = int(div - x)
        black_x = int(div)
        black_w = x + w - black_x

        # 红(左) / 黑(右) 填充到同一圆角遮罩内
        bar = pygame.Surface((w, h), pygame.SRCALPHA)
        if red_w > 0:
            pygame.draw.rect(bar, (214, 56, 56), (0, 0, red_w, h))
        if black_w > 0:
            pygame.draw.rect(bar, (45, 45, 48), (red_w, 0, black_w, h))
        mask = pygame.Surface((w, h), pygame.SRCALPHA)
        pygame.draw.rect(mask, (255, 255, 255), (0, 0, w, h), border_radius=h // 2)
        bar.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
        self.screen.blit(bar, (x, y))

        # 边框
        pygame.draw.rect(self.screen, (150, 158, 170), rect, border_radius=h // 2, width=1)

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

    def _catmull_rom(self, points, samples=14):
        """Catmull-Rom 平滑插值（参照 Android 曲线平滑）。"""
        if len(points) < 2:
            return list(points)
        pts = [points[0]] + list(points) + [points[-1]]
        out = []
        for i in range(len(pts) - 3):
            p0, p1, p2, p3 = pts[i], pts[i + 1], pts[i + 2], pts[i + 3]
            for s in range(samples):
                t = s / samples
                t2 = t * t
                t3 = t2 * t
                x = 0.5 * ((2 * p1[0]) + (-p0[0] + p2[0]) * t
                          + (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2
                          + (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3)
                y = 0.5 * ((2 * p1[1]) + (-p0[1] + p2[1]) * t
                          + (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2
                          + (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3)
                out.append((x, y))
        out.append(points[-1])
        return out

    def _draw_dashed_line(self, x1, y1, x2, y2, color, width=2, dash=8, gap=6):
        dx = x2 - x1
        dy = y2 - y1
        dist = max(1.0, (dx * dx + dy * dy) ** 0.5)
        nx, ny = dx / dist, dy / dist
        pos = 0.0
        while pos < dist:
            d = min(dash, dist - pos)
            ax = x1 + nx * pos
            ay = y1 + ny * pos
            bx = x1 + nx * (pos + d)
            by = y1 + ny * (pos + d)
            pygame.draw.line(self.screen, color, (ax, ay), (bx, by), width)
            pos += dash + gap

    def _draw_eval_curve(self, x, y, w, h):
        """整局评分曲线（参照 Android ScoreCurveView 美化版）。"""
        card = pygame.Rect(x, y, w, h)
        self._draw_rounded_card(card, (26, 30, 42), (12, 15, 22), (46, 56, 72))

        pad = 16
        plot = pygame.Rect(x + pad, y + pad, w - 2 * pad, h - 2 * pad)
        hist = self.eval_history
        cy = plot.y + plot.height // 2

        if not hist:
            self._draw_text('暂无评分数据', plot.centerx, cy, 'small', (150, 162, 180))
            return

        # 自适应缩放（参照 Android ADAPTIVE_MAX=100 / SC_MAX=400）
        max_abs = 1
        for v in hist:
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

        n = len(hist)
        pts = []
        for i, v in enumerate(hist):
            px = plot.x + (plot.width * i / (n - 1)) if n > 1 else plot.centerx
            pts.append((px, to_y(v)))

        last_val = hist[-1]
        line_col = (236, 92, 92) if last_val >= 0 else (82, 150, 236)
        fill_col = (236, 92, 92) if last_val >= 0 else (82, 150, 236)

        if n >= 2:
            # 渐变填充
            smooth = self._catmull_rom(pts, 14)
            fill_surf = pygame.Surface((plot.width, plot.height), pygame.SRCALPHA)
            poly = [(p[0] - plot.x, p[1] - plot.y) for p in
                    ([(plot.x, cy)] + smooth + [(plot.x + plot.width, cy)])]
            pygame.draw.polygon(fill_surf, (*fill_col, 50), poly)
            self.screen.blit(fill_surf, (plot.x, plot.y))
            # 每步竖线（颜色按优势）
            for i, (px, py) in enumerate(pts):
                c = (220, 70, 70) if hist[i] >= 0 else (70, 130, 220)
                pygame.draw.line(self.screen, c, (px, cy), (px, py), 2 if i == n - 1 else 1)
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

    def _draw_eval_top(self):
        """界面顶部：左侧文字评分（红方视角）+ 右侧评分滚动条。"""
        h = self.eval_top_h
        w = self.board_width
        y0 = self.menu_h
        status = self.chess_info.get_game_status()
        if status in ('checkmate', 'stalemate', 'draw'):
            info = self._result_info()
            text = info[0] if info else '对局结束'
            if status == 'checkmate':
                text = '将死 · ' + text
            bg = pygame.Surface((w, h), pygame.SRCALPHA)
            bg.fill((150, 40, 40, 235))
            self.screen.blit(bg, (0, y0))
            self._draw_text(text, w // 2, y0 + h // 2, 'small', (255, 240, 240))
            return
        bg = pygame.Surface((w, h), pygame.SRCALPHA)
        bg.fill((24, 34, 50, 235))
        self.screen.blit(bg, (0, y0))

        # 评分条（整条铺满顶部，不显示文字评分）
        bar_w = w - 24
        if bar_w > 60:
            self._draw_eval_bar(12, y0 + h // 2 - 5, bar_w, self.eval_score, 10)

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
        list_x = 4
        list_w = w - 8 - scroll_w

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
        gap = 2
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

        cx = rect.x + 6
        cyy = rect.y + rect.height // 2

        # 序号圆形徽标（最佳用金色）
        badge_r = 7
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
        chip_x = cx + badge_r * 2 + 2
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
        txt_x = chip_x + 3
        if best:
            # 最优着法前面加星（原位置），左侧已压缩以腾出空间保证首行也能显示 8 步
            self._draw_text_left('★', txt_x, rect.y + rect.height // 2, 'xsmall', (240, 200, 120))
            txt_x += 12
        max_w = rect.right - txt_x - 3
        self._draw_colored_pv(full_pv, txt_x, rect.y, rect.height, max(60, max_w), is_red, False)

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

    # ---------- 模拟行棋 ----------
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
        self.show_toast('支招演示：▶/◀ 逐步演示，✕ 退出；不影响真实对局')

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
        ci.pre_pos = mv.from_pos
        ci.cur_pos = mv.to_pos

    def _rebuild_sim(self):
        """从保存副本重建当前局面，并应用前 sim_index 步。"""
        self._copy_chess_state(self.chess_info, self.sim_restore)
        for k in range(self.sim_index):
            self._sim_apply_move(self.sim_pv[k])

    def sim_step_forward(self):
        if self.simulating and self.sim_index < len(self.sim_pv):
            self.sim_index += 1
            self._rebuild_sim()

    def sim_step_back(self):
        if self.simulating and self.sim_index > 0:
            self.sim_index -= 1
            self._rebuild_sim()

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
        self._draw_text('支招演示 · 引擎推荐线', w // 2, y0 + 16, 'small', (150, 200, 255))
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
            txt = f'{i+1}. {pv_cn[i]}{side}'
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

    def _show_modal(self, kind: str, title: str, message: str, buttons):
        self.modal = {'kind': kind, 'title': title, 'message': message, 'buttons': buttons}

    def _modal_button_rects(self):
        n = len(self.modal['buttons'])
        card_w, card_h = 440, 210
        cx = self.window_width // 2
        cy = self.window_height // 2
        card = pygame.Rect(cx - card_w // 2, cy - card_h // 2, card_w, card_h)
        btn_w, btn_h = 150, 46
        gap = 30
        total_w = n * btn_w + (n - 1) * gap
        start_x = card.x + (card_w - total_w) // 2
        y = card.y + card_h - 72
        return [pygame.Rect(start_x + i * (btn_w + gap), y, btn_w, btn_h) for i in range(n)]

    def _draw_modal(self):
        if not self.modal:
            return
        overlay = pygame.Surface((self.window_width, self.window_height), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 150))
        self.screen.blit(overlay, (0, 0))

        card_w, card_h = 440, 210
        cx = self.window_width // 2
        cy = self.window_height // 2
        card = pygame.Rect(cx - card_w // 2, cy - card_h // 2, card_w, card_h)
        self._draw_card(card, (250, 251, 253))

        self._draw_text(self.modal['title'], card.centerx, card.y + 42, 'large', (40, 52, 72))

        msg_surf = self._text_surface(self.modal['message'], 'small', (70, 82, 104))
        if msg_surf:
            self.screen.blit(msg_surf, (card.centerx - msg_surf.get_width() // 2, card.y + 86))

        rects = self._modal_button_rects()
        for i, btn in enumerate(self.modal['buttons']):
            if 'base' in btn:
                base = btn['base']
                hover = btn.get('hover', base)
                tcol = btn.get('text_color', (255, 255, 255))
            else:
                positive = btn['id'] in ('yes', 'ok')
                base = (92, 184, 120) if positive else (206, 108, 108)
                hover = (70, 160, 100) if positive else (188, 86, 86)
                tcol = (255, 255, 255)
            self._draw_button(rects[i], btn['label'], 'small',
                              base=base, hover=hover, text_color=tcol)

    def _on_modal_button(self, btn_id: str):
        kind = self.modal['kind']
        if kind == 'draw_rule':
            if btn_id == 'yes':
                self.chess_info.accept_draw()
            else:
                # 拒绝后抑制重复弹窗，直到和棋条件真正改变
                self.chess_info.draw_offer_suppressed = True
            self.modal = None
        elif kind == 'draw_response':
            self.modal = None
        elif kind == 'edit_first_move':
            # 摆棋完成后选择先手方
            self.chess_info.is_red_go = (btn_id == 'red')
            # 记录摆棋后的局面为基准局面，悔棋时据此重放而非标准开局
            self.chess_info.base_piece = [row[:] for row in self.chess_info.piece]
            self.chess_info.base_red_go = self.chess_info.is_red_go
            self.modal = None
            self.request_eval()
        elif kind == 'confirm_restart':
            if btn_id == 'yes':
                self.editing = False
                self.reset_game()
            self.modal = None

    # ============ 提示条（强制变着等） ============

    def show_toast(self, text: str, duration: float = 2.6):
        self.toast = text
        self.toast_until = time.time() + duration

    def _copy_text(self, text: str):
        """复制文本到系统剪贴板；不可用时退回提示条展示。"""
        try:
            import pygame.scrap as scrap
            scrap.init()
            scrap.put(scrap.SCRAP_TEXT, text.encode('utf-8'))
            self.show_toast('FEN 已复制到剪贴板')
        except Exception:
            # 剪贴板不可用时，直接以提示条展示 FEN 供手动复制
            self.show_toast('FEN: ' + text)

    def _draw_toast(self):
        if not self.toast or time.time() > self.toast_until:
            self.toast = None
            return
        alpha = min(1.0, (self.toast_until - time.time()) / 0.5)
        surf = self._text_surface(self.toast, 'small', (255, 255, 255))
        if not surf:
            return
        pad_x, pad_y = 22, 12
        w = surf.get_width() + pad_x * 2
        h = surf.get_height() + pad_y * 2
        x = (self.board_width - w) // 2
        y = self.board_offset_y + 18
        banner = pygame.Surface((w, h), pygame.SRCALPHA)
        banner.fill((28, 40, 58, int(225 * alpha)))
        pygame.draw.rect(banner, (255, 255, 255, int(40 * alpha)),
                         banner.get_rect(), border_radius=10)
        banner.blit(surf, (pad_x, pad_y))
        self.screen.blit(banner, (x, y))

    def _result_info(self):
        """返回 (文本, 颜色, 副文本) 表示当前对局结果；对局进行中返回 None。

        文案与配色参照 Android 端 RoundView：红方胜用朱红、黑方胜用深黑、和棋用灰。
        """
        status = self.chess_info.get_game_status()
        if status == 'checkmate':
            # 将死的行棋方为负，对方获胜
            winner = '红方' if not self.chess_info.is_red_go else '黑方'
            color = (214, 56, 56) if winner == '红方' else (45, 45, 48)
            return f'{winner}获胜！', color, None
        if status == 'stalemate':
            return '和棋！', (128, 128, 128), '困毙'
        if status == 'draw':
            reason = self.chess_info.draw_reason or '协议和棋'
            return '和棋！', (128, 128, 128), reason
        return None

    def _draw_game_over(self):
        """对局结束后在棋盘区叠加半透明遮罩与醒目结果提示。"""
        status = self.chess_info.get_game_status()
        # 仅“将死/困毙/和棋”才视为终局；AI 思考中(status=thinking)不算结束
        if status in ('playing', 'thinking'):
            return
        info = self._result_info()
        if not info:
            return
        text, color, sub = info
        sub = sub or '对局结束'

        board_x, board_y = 0, self.board_offset_y
        bw, bh = self.board_width, self.board_height

        # 半透明遮罩
        ov = pygame.Surface((bw, bh), pygame.SRCALPHA)
        ov.fill((8, 10, 14, 165))
        self.screen.blit(ov, (board_x, board_y))

        cx = board_x + bw // 2
        cy = board_y + bh // 2

        # 主结果文字
        t_surf = self._text_surface(text, 'large', color)
        if t_surf:
            self.screen.blit(t_surf, (cx - t_surf.get_width() // 2,
                                      cy - 54 - t_surf.get_height() // 2))
        # 副标题
        s_surf = self._text_surface(sub, 'small', (214, 222, 236))
        if s_surf:
            self.screen.blit(s_surf, (cx - s_surf.get_width() // 2,
                                      cy + 6 - s_surf.get_height() // 2))
        # 操作提示
        h_surf = self._text_surface('点击右侧「重新开始」开始新对局', 'small', (150, 162, 182))
        if h_surf:
            self.screen.blit(h_surf, (cx - h_surf.get_width() // 2,
                                      cy + 58 - h_surf.get_height() // 2))

    # ============ 存档浏览器 ============
    def _draw_save_browser(self):
        if not self.save_browser:
            return
        entries = self.save_browser['entries']
        overlay = pygame.Surface((self.window_width, self.window_height), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 150))
        self.screen.blit(overlay, (0, 0))

        card_w = 520
        card_h = min(self.window_height - 120, 120 + len(entries) * 56 + 60)
        cx = (self.window_width - card_w) // 2
        cy = (self.window_height - card_h) // 2
        card = pygame.Surface((card_w, card_h), pygame.SRCALPHA)
        card.fill((20, 26, 36, 248))
        self.screen.blit(card, (cx, cy))
        pygame.draw.rect(self.screen, (70, 110, 170),
                         pygame.Rect(cx, cy, card_w, card_h), border_radius=16, width=2)

        self._draw_text('加载存档', cx + card_w // 2, cy + 30, 'large', (150, 200, 255))
        self._draw_text_left('选择要加载的存档（点击行加载，点击取消关闭）',
                              cx + 24, cy + 64, 'small', (150, 162, 184))

        rects = []
        row_y = cy + 88
        for i, e in enumerate(entries):
            rrect = pygame.Rect(cx + 20, row_y, card_w - 40, 48)
            hovered = rrect.collidepoint(self.mouse_pos)
            pygame.draw.rect(self.screen,
                             (44, 66, 100) if hovered else (28, 38, 54),
                             rrect, border_radius=10)
            side = '红方' if e['is_red_go'] else '黑方'
            mode_text = {'pvp': '双人', 'pvm_red': '人机(红)', 'pvm_black': '人机(黑)',
                         'mvm': '双机'}.get(e['game_mode'], e['game_mode'])
            self._draw_text_left(e['name'], cx + 34, row_y + 16, 'small', (235, 240, 248))
            self._draw_text_left(f'{e["saved_at"]} · {e["moves"]}步 · {side}先 · {mode_text}',
                                  cx + 34, row_y + 34, 'small', (150, 162, 184))
            rects.append(rrect)
            row_y += 56

        crect = pygame.Rect(cx + 20, cy + card_h - 52, card_w - 40, 40)
        ch = crect.collidepoint(self.mouse_pos)
        pygame.draw.rect(self.screen, (60, 40, 44) if ch else (44, 30, 34),
                         crect, border_radius=10)
        self._draw_text('取消', cx + card_w // 2, crect.y + crect.height // 2,
                        'small', (235, 200, 200))

        self.save_browser['rects'] = rects
        self.save_browser['close_rect'] = crect
        self.save_browser['card_rect'] = pygame.Rect(cx, cy, card_w, card_h)

    def _handle_save_browser_click(self, x, y):
        """返回 True 表示点击已被存档浏览器消费。"""
        if not self.save_browser:
            return False
        sb = self.save_browser
        if sb.get('close_rect') and sb['close_rect'].collidepoint(x, y):
            self.save_browser = None
            return True
        for i, rrect in enumerate(sb.get('rects', [])):
            if rrect.collidepoint(x, y):
                path = sb['entries'][i]['path']
                self.save_browser = None
                self._apply_save_data(path)
                return True
        # 遮罩与卡片空白区域也吸收点击，避免穿透到下层按钮
        return True

    def set_game_mode(self, mode: str):
        self.game_mode = mode
        
        self.is_ai_thinking = False
        self.ai.close()
        
        if self.game_mode != 'pvp':
            self.ai.initialize()
        
        if self.game_mode == 'mvm':
            if self.chess_info.get_game_status() == 'playing':
                self.start_ai_turn()
        elif self.game_mode == 'pvm_black' and self.chess_info.is_red_go:
            # 人机(黑方)模式：AI 执红先行
            if self.chess_info.get_game_status() == 'playing':
                self.start_ai_turn()
        elif self.game_mode == 'pvm_red' and not self.chess_info.is_red_go:
            # 人机(红方)模式：切换到红方时若已轮到黑方(AI)，立即行棋
            if self.chess_info.get_game_status() == 'playing':
                self.start_ai_turn()
    
    def reset_game(self):
        self.chess_info.reset()
        self.ai.close()
        self.is_ai_thinking = False
        self.hint_loading = False
        self.draw_loading = False
        self.toast = None
        self.eval_score = None
        self.eval_history = []
        self.eval_gen += 1
        self.eval_loading = False
        self._clear_hint()
        self.editing = False
        self.edit_piece = None
        self.edit_ui = {}
        self._reset_snapshots()

        if self.game_mode != 'pvp':
            self.ai.initialize()
            print(f"AI initialized: {self.ai.is_initialized()}")

        if self.game_mode == 'mvm':
            print("Starting MVM mode, AI's turn")
            self.start_ai_turn()
        elif self.game_mode == 'pvm_black' and self.chess_info.is_red_go:
            # 人机(黑方)模式：AI 执红先行
            self.start_ai_turn()

        # 初始局面评估（必要时惰性初始化引擎），让评分曲线从开局即有数据
        self.request_eval()
    
    def undo_move(self):
        # 浏览状态下先退出浏览，再执行悔棋
        if self.browse_index is not None:
            self.browse_index = None
            self.show_toast('已退出局面浏览')
            return
        # AI 思考中不允许悔棋，避免状态错乱
        if self.is_ai_thinking or self.hint_loading:
            return

        history = list(self.chess_info.move_history)
        if not history:
            return

        # 人机模式一次撤销「玩家 + AI」两步，退回玩家可操作的局面；
        # 双人/双机模式撤销一步。
        undo_count = 2 if self.game_mode in ('pvm_red', 'pvm_black') else 1
        undo_count = min(undo_count, len(history))
        replay = history[:len(history) - undo_count]

        # 仅重置棋盘状态到本局基准局面（标准开局或摆棋自定义局面），
        # 不触碰引擎（避免重启 AI / 触发 AI 先手）。
        # 用 restore_base 而非 reset：reset 会回到标准开局，导致摆棋删除的
        # 棋子被重新填回棋盘。
        self.chess_info.restore_base()

        # 从初始局面精确重放剩余历史（含吃子，象棋无随机性可完整复原）
        for move in replay:
            self.chess_info.piece[move.to_pos.y][move.to_pos.x] = \
                self.chess_info.piece[move.from_pos.y][move.from_pos.x]
            self.chess_info.piece[move.from_pos.y][move.from_pos.x] = 0
            self.chess_info.is_red_go = not self.chess_info.is_red_go
        self.chess_info.move_history = replay

        # 复位选择/提示/将军等交互状态
        self.chess_info.select = Pos(-1, -1)
        self.chess_info.ret = []
        self.chess_info.status = 0
        self.chess_info.is_machine = False
        self._clear_hint()
        self.chess_info.peace_round = 0
        self.chess_info.position_history = {}
        self.chess_info.consecutive_check_red = 0
        self.chess_info.consecutive_check_black = 0
        self.chess_info.consecutive_attack_red = 0
        self.chess_info.consecutive_attack_black = 0
        self.chess_info.last_attacked_pos = None
        self.chess_info.last_attacked_type = 0
        self.chess_info.draw_reason = ''
        self.chess_info.draw_offer = None
        self.chess_info.draw_offer_pending = None
        self.chess_info.draw_hint = ''
        self.chess_info.draw_offer_suppressed = False
        self.chess_info.attack_num_r = 0
        self.chess_info.attack_num_b = 0
        self.chess_info.winner = None
        self.toast = None
        self.eval_score = None
        # 悔棋保留评分曲线：仅回退与撤销步数对应的评分点，避免整条曲线重置
        for _ in range(undo_count):
            if self.eval_history:
                self.eval_history.pop()
        self.eval_gen += 1
        from ..game.rule import is_king_danger
        self.chess_info.is_checked = is_king_danger(self.chess_info.piece, self.chess_info.is_red_go)
        # 悔棋后重新评估当前局面（保障每一步都有 AI 评分）
        self.request_eval(force=True)
        self._reset_snapshots()

    def undo_edit(self):
        """摆棋模式下的悔棋：撤销上一次编辑操作（放置 / 移动 / 删除 / 清空），
        而非对局走子，避免把被删除的棋子重新复位出来。"""
        if not self.edit_history:
            self.show_toast('无可撤销的摆棋操作')
            return
        op = self.edit_history.pop()
        if op['type'] == 'delete':
            x, y = op['pos']
            self.chess_info.piece[y][x] = op['pid']
        elif op['type'] == 'place':
            x, y = op['pos']
            self.chess_info.piece[y][x] = 0
        elif op['type'] == 'move':
            fx, fy = op['from']
            tx, ty = op['to']
            self.chess_info.piece[ty][tx] = 0
            self.chess_info.piece[fy][fx] = op['pid']
        elif op['type'] == 'clear':
            self.chess_info.piece = [row[:] for row in op['prev']]
        self.edit_piece = None
        self._edit_pickup_cell = None
        self._after_edit()

    # ============ 上一步 / 下一步（局面浏览） ============
    def _reset_snapshots(self):
        """以当前棋盘作为初始快照，并退出浏览状态。"""
        self.browse_index = None
        self.board_snapshots = [[row[:] for row in self.chess_info.piece]]

    def _record_snapshot(self):
        """一步走完后记录当前棋盘快照；并退出浏览回到最新局面。"""
        self.board_snapshots.append([row[:] for row in self.chess_info.piece])
        self.browse_index = None

    def prev_step(self):
        """查看上一步局面（从最新后退；到初始后给出提示）。"""
        if not self.board_snapshots:
            return
        self._clear_hint()
        self.hint_window = None
        if self.browse_index is None:
            self.browse_index = max(0, len(self.board_snapshots) - 2)
        elif self.browse_index > 0:
            self.browse_index -= 1
        else:
            self.show_toast('已经是第一步')
            return
        self.show_toast(f'正在查看第 {self.browse_index} 步')

    def next_step(self):
        """查看下一步局面（到最新后回到实时对局）。"""
        if not self.board_snapshots:
            return
        self._clear_hint()
        self.hint_window = None
        if self.browse_index is None:
            self.show_toast('已经是最新局面')
            return
        if self.browse_index < len(self.board_snapshots) - 1:
            self.browse_index += 1
            self.show_toast(f'正在查看第 {self.browse_index} 步')
        else:
            self.browse_index = None
            self.show_toast('已回到实时对局')
            self.check_ai_turn()

    # ============ 保存 / 加载 ============
    def save_game(self):
        """将完整对局状态保存为 JSON 存档（含棋盘、历史、设置、评分曲线等）。"""
        try:
            os.makedirs(self.save_dir, exist_ok=True)
            ci = self.chess_info
            data = {
                'format': 1,
                'saved_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'game_mode': self.game_mode,
                'player_color': self.player_color,
                'piece': [row[:] for row in ci.piece],
                'is_red_go': ci.is_red_go,
                'move_history': [[m.from_pos.x, m.from_pos.y, m.to_pos.x, m.to_pos.y]
                                 for m in ci.move_history],
                'status': getattr(ci, 'status', 0),
                'is_checked': getattr(ci, 'is_checked', False),
                'peace_round': getattr(ci, 'peace_round', 0),
                'winner': getattr(ci, 'winner', None),
                'draw_reason': getattr(ci, 'draw_reason', None),
                'eval_history': list(self.eval_history),
                'eval_depth': self.eval_depth,
                'board_snapshots': self.board_snapshots,
                'settings': {
                    'depth': self.settings.depth,
                    'skill_level': self.settings.skill_level,
                    'thinking_time': self.settings.thinking_time,
                    'multi_pv': self.settings.multi_pv,
                    'contempt': self.settings.contempt,
                },
            }
            stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            path = os.path.join(self.save_dir, f'chess_{stamp}.json')
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            # 仅保留最近 20 个存档
            try:
                files = sorted(
                    [os.path.join(self.save_dir, fn) for fn in os.listdir(self.save_dir)
                     if fn.startswith('chess_') and fn.endswith('.json')],
                    key=os.path.getmtime, reverse=True)
                for old in files[20:]:
                    os.remove(old)
            except OSError:
                pass
            self.show_toast('已保存存档')
        except Exception as e:
            self.show_toast('保存失败')
            print('保存失败:', e)

    def load_game(self):
        """打开存档浏览器，选择要加载的存档。"""
        self._open_save_browser()

    def _open_save_browser(self):
        try:
            os.makedirs(self.save_dir, exist_ok=True)
            files = sorted([fn for fn in os.listdir(self.save_dir)
                            if fn.startswith('chess_') and fn.endswith('.json')],
                           reverse=True)
            entries = []
            for fn in files:
                full = os.path.join(self.save_dir, fn)
                try:
                    with open(full, 'r', encoding='utf-8') as f:
                        d = json.load(f)
                    entries.append({
                        'name': fn,
                        'path': full,
                        'saved_at': d.get('saved_at', ''),
                        'moves': len(d.get('move_history', [])),
                        'is_red_go': d.get('is_red_go', True),
                        'game_mode': d.get('game_mode', 'pvp'),
                    })
                except Exception:
                    continue
            if not entries:
                self.show_toast('没有可加载的存档')
                return
            self.save_browser = {'entries': entries, 'rects': [], 'close_rect': None}
        except Exception as e:
            self.show_toast('读取存档失败')
            print('读取存档失败:', e)

    def _apply_save_data(self, path):
        """将存档数据应用到当前对局并恢复完整状态。"""
        try:
            with open(path, 'r', encoding='utf-8') as f:
                d = json.load(f)
            ci = self.chess_info
            ci.reset()
            ci.piece = [row[:] for row in d['piece']]
            ci.is_red_go = d.get('is_red_go', True)
            ci.move_history = [Move(Pos(a, b), Pos(c, e))
                               for (a, b, c, e) in d.get('move_history', [])]
            ci.status = d.get('status', 0)
            ci.is_checked = d.get('is_checked', False)
            ci.peace_round = d.get('peace_round', 0)
            ci.winner = d.get('winner')
            ci.draw_reason = d.get('draw_reason')

            self.eval_history = list(d.get('eval_history', []))
            self.eval_depth = d.get('eval_depth', 0)
            self.eval_gen = 0
            self.board_snapshots = [[row[:] for row in snap]
                                    for snap in d.get('board_snapshots',
                                                      [[row[:] for row in ci.piece]])]
            self.game_mode = d.get('game_mode', self.game_mode)
            self.player_color = d.get('player_color', self.player_color)

            s = d.get('settings')
            if s:
                self.settings.depth = s.get('depth', self.settings.depth)
                self.settings.skill_level = s.get('skill_level', self.settings.skill_level)
                self.settings.thinking_time = s.get('thinking_time', self.settings.thinking_time)
                self.settings.multi_pv = s.get('multi_pv', self.settings.multi_pv)
                self.settings.contempt = s.get('contempt', self.settings.contempt)
                self.settings.save()
                if self.game_mode != 'pvp' and self.ai.initialized:
                    self.ai._send_command(
                        f'setoption name Skill Level value {self.settings.skill_level}')
                    self.ai._send_command(
                        f'setoption name Contempt value {self.settings.contempt}')
                    self.ai._send_command(
                        f'setoption name MultiPV value {self.settings.multi_pv}')

            # 复位瞬时状态
            self.editing = False
            self.edit_piece = None
            self.edit_drag_pid = None
            self.edit_drag_pos = None
            self.edit_drag_moved = False
            self.is_ai_thinking = False
            self.browse_index = None
            self.hint_window = None
            self.save_browser = None
            self._clear_hint()
            ci.select = Pos(-1, -1)
            ci.ret = []
            ci.suggest_moves = []
            ci.suggest_move_labels = []
            ci.suggest_replies = []
            ci.suggest = None
            ci.is_machine = (self.game_mode != 'pvp')
            ci.setting = self.settings

            # 重新评估并视情况开启 AI
            self.ai.close()
            if self.game_mode != 'pvp':
                self.ai.initialize()
            self.request_eval()
            self.check_ai_turn()
            self.show_toast('已加载存档')
        except Exception as e:
            self.show_toast('加载失败')
            print('加载失败:', e)

    def check_ai_turn(self):
        if self.simulating:
            return
        if self.chess_info.get_game_status() != 'playing':
            return
        
        if self.game_mode == 'pvm_red' and not self.chess_info.is_red_go:
            self.start_ai_turn()
        elif self.game_mode == 'pvm_black' and self.chess_info.is_red_go:
            self.start_ai_turn()
        elif self.game_mode == 'mvm':
            self.start_ai_turn()
    
    def start_ai_turn(self):
        if self.is_ai_thinking:
            return
        
        self.is_ai_thinking = True
        self.chess_info.status = 1
        self.chess_info.is_machine = True
        
        self.ai_thread = threading.Thread(target=self.ai_move)
        self.ai_thread.daemon = True
        self.ai_thread.start()
    
    def ai_move(self):
        try:
            print(f"ai_move called. is_red_go={self.chess_info.is_red_go}, game_mode={self.game_mode}, player_color={self.player_color}")

            move = self.ai.get_best_move(self.chess_info, self.settings)
            print(f"AI returned move: from ({move.from_pos.x},{move.from_pos.y}) to ({move.to_pos.x},{move.to_pos.y}), valid={move.is_valid()}")

            if not move.is_valid():
                # 引擎结果异常时回退到规则引擎，保证 AI 始终能走子
                move = self._fallback_ai_move()
                print(f"Fallback move: from ({move.from_pos.x},{move.from_pos.y}) to ({move.to_pos.x},{move.to_pos.y}), valid={move.is_valid()}")

            # 通过线程安全队列回传主循环，避免跨线程 post pygame 事件导致丢失
            self.ai_result_queue.put(move)
        except Exception as e:
            print(f'AI移动失败: {e}')
            self.ai_result_queue.put(None)

    def _fallback_ai_move(self) -> Move:
        """引擎不可用时，用规则引擎挑选一个不送将的合法走法。"""
        from ..game.rule import possible_moves, is_red, is_king_danger
        info = self.chess_info
        for y in range(10):
            for x in range(9):
                piece = info.piece[y][x]
                if piece == 0 or is_red(piece) != info.is_red_go:
                    continue
                for m in possible_moves(info.piece, x, y, piece):
                    temp = [row[:] for row in info.piece]
                    temp[m.y][m.x] = piece
                    temp[y][x] = 0
                    if not is_king_danger(temp, is_red(piece)):
                        return Move(Pos(x, y), m)
        return Move()
    
    def handle_ai_move(self, move: Move):
        # 支招跟线中：AI 应招与推荐一致则推进提示线，否则取消提示线；
        # 未跟线时按原逻辑清除上一步提示
        if getattr(self.chess_info, 'suggest_track', False) and self._track_pv is not None:
            self._advance_hint_after_move(move.from_pos, move.to_pos)
        else:
            # 清除上一步的支招提示
            self._clear_hint()

        print(f"handle_ai_move called. from ({move.from_pos.x},{move.from_pos.y}) to ({move.to_pos.x},{move.to_pos.y})")
        
        piece_at_from = self.chess_info.get_piece_at(move.from_pos.x, move.from_pos.y)
        print(f"Piece at from: {piece_at_from}, is_red_go: {self.chess_info.is_red_go}")
        
        is_valid = self.chess_info.is_valid_move(move.from_pos.x, move.from_pos.y, move.to_pos.x, move.to_pos.y)
        print(f"is_valid_move: {is_valid}")
        
        if is_valid:
            self.chess_info.select_piece(move.from_pos.x, move.from_pos.y)
            # 先恢复为“进行中”，让 move_piece 正常判定将死/困毙/和棋（含和棋检测）
            self.chess_info.status = 0
            self.chess_info.move_piece(move.to_pos.x, move.to_pos.y)
            self._record_snapshot()
            print("Move executed successfully")
        else:
            print("Move is NOT valid!")
        
        self.is_ai_thinking = False
        self.chess_info.is_machine = False
        # 仅当本步未分胜负（status 仍为“思考中=1”）时恢复为进行中；
        # 若 move_piece 已判定将死/困毙/和棋，则保留终局状态以正确显示“对局结束”
        if self.chess_info.status == 1:
            self.chess_info.status = 0

        # AI 走子后更新局面评分（引擎此时空闲，无冲突）
        self.request_eval()

        status = self.chess_info.get_game_status()
        if status != 'playing':
            res_text = self._result_info()[0] if self._result_info() else ''
            if status == 'checkmate':
                self.show_toast('将死！' + res_text)
            elif status == 'stalemate':
                self.show_toast('困毙！' + res_text)
            else:
                self.show_toast(res_text)
        elif self.game_mode == 'mvm':
            self.start_ai_turn()
    
    def run(self):
        while self.running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                elif event.type == pygame.MOUSEMOTION:
                    self.mouse_pos = event.pos
                    # 设置面板滑块拖拽
                    if self.settings_drag_key is not None and self.show_settings:
                        self._apply_slider_drag(event.pos[0])
                    # 摆棋面板滚动条拖拽
                    if self._edit_dragging and self.edit_vp is not None:
                        max_scroll = max(0, self.edit_content_bottom - self.edit_vp.bottom)
                        thumb = self._edit_scrollbar_rect(self.edit_vp, max_scroll)
                        if thumb and max_scroll > 0:
                            ty = y - self._edit_drag_offset
                            ratio = (ty - self.edit_vp.y) / (self.edit_vp.height - thumb.height)
                            self.edit_scroll = max(0, min(max_scroll, int(ratio * max_scroll)))
                    # 摆棋区棋子拖拽：更新鼠标位置，移动超过阈值判定为拖拽
                    if self.edit_drag_pid is not None:
                        self.edit_drag_pos = event.pos
                        if (abs(event.pos[0] - self.edit_drag_start[0]) > 6 or
                                abs(event.pos[1] - self.edit_drag_start[1]) > 6):
                            self.edit_drag_moved = True
                    # 候选列表滚动条拖拽
                    if self.candidate_dragging and self.candidate_max_scroll > 0:
                        self._candidate_scroll_to_y(event.pos[1])
                elif event.type == pygame.MOUSEBUTTONUP:
                    self.settings_drag_key = None
                    self._edit_dragging = False
                    self.candidate_dragging = False
                    # 摆棋区拖拽落子：松手时若在棋盘上则放置
                    if self.edit_drag_pid is not None:
                        pid = self.edit_drag_pid
                        mx, my = event.pos
                        placed = False
                        if mx < self.board_width:
                            pos = self.chess_view.get_board_coordinates(mx, my - self.board_offset_y)
                            if pos.x >= 0 and self._piece_count(pid) < self._piece_max_count(pid):
                                self.chess_info.piece[pos.y][pos.x] = pid
                                # 从调色板拖拽放置：记录可撤销项
                                self.edit_history.append(
                                    {'type': 'place', 'pos': (pos.x, pos.y), 'pid': pid})
                                self._after_edit()
                                placed = True
                        # 放置到棋盘后取消选中（只选择一次）；仅在摆棋区点击未拖到棋盘时保持选中，便于随后点棋盘放置
                        if placed:
                            self.edit_piece = None
                        else:
                            self.edit_piece = pid if self._piece_count(pid) < self._piece_max_count(pid) else None
                        self.edit_drag_pid = None
                        self.edit_drag_pos = None
                        self.edit_drag_moved = False
                elif event.type == pygame.MOUSEWHEEL:
                    if self.editing and self.edit_vp is not None:
                        max_scroll = max(0, self.edit_content_bottom - self.edit_vp.bottom)
                        if max_scroll > 0:
                            self.edit_scroll = max(0, min(max_scroll, self.edit_scroll - event.y * 40))
                    elif self.simulating:
                        # 模拟面板：滚轮滚动推荐线列表
                        y0 = self.board_offset_y + self.board_height
                        if y0 <= self.mouse_pos[1] <= y0 + self.eval_bottom_h:
                            self.sim_scroll = max(0, self.sim_scroll - event.y * 24)
                    elif getattr(self, 'ai_lines', None) and self.candidate_max_scroll > 0:
                        # 候选列表滚轮滚动
                        y0 = self.board_offset_y + self.board_height
                        if y0 <= self.mouse_pos[1] <= y0 + self.eval_bottom_h:
                            self.candidate_scroll = max(
                                0, min(self.candidate_max_scroll,
                                       self.candidate_scroll - event.y * 30))
                elif event.type == pygame.KEYDOWN:
                    if self.simulating:
                        if event.key in (pygame.K_RIGHT, pygame.K_SPACE):
                            self.sim_step_forward()
                        elif event.key == pygame.K_LEFT:
                            self.sim_step_back()
                        elif event.key == pygame.K_ESCAPE:
                            self.end_simulation()
                elif event.type == pygame.MOUSEBUTTONDOWN:
                    # 忽略滚轮按键（4/5），避免被误判为点击而触发选择/模拟
                    if event.button in (4, 5):
                        continue
                    x, y = event.pos
                    if self.show_settings:
                        if not self._settings_slider_down(x, y):
                            self.handle_settings_click(x, y)
                    else:
                        # 优先判定候选列表滚动条，命中则吞掉本次点击
                        if not self._candidate_scrollbar_down(x, y):
                            self.handle_click(x, y)

            # 消费 AI 线程的计算结果（线程安全，避免跨线程派发 pygame 事件丢失）
            try:
                ai_result = self.ai_result_queue.get_nowait()
            except queue.Empty:
                ai_result = self._ai_no_result

            if ai_result is not self._ai_no_result:
                if ai_result is None:
                    # 引擎异常：释放思考锁，避免界面卡死
                    self.is_ai_thinking = False
                    self.chess_info.status = 0
                    self.chess_info.is_machine = False
                else:
                    self.handle_ai_move(ai_result)

            # 实时评分：AI 思考且对局仍在进行时，用引擎不断深化的分数刷新曲线末点与评估值
            # （对局结束后冻结，避免曲线继续滚动）
            if self.is_ai_thinking and self.chess_info.get_game_status() == 'playing':
                raw = getattr(self.ai, 'last_info_score', None)
                if raw is not None:
                    red_persp = raw if self.chess_info.is_red_go else -raw
                    self.eval_score = red_persp
                    if self.eval_history:
                        self.eval_history[-1] = red_persp

            # 消费支招结果
            self._consume_hint_result()

            # 消费和棋应答结果
            try:
                draw_resp = self.draw_response_queue.get_nowait()
            except queue.Empty:
                draw_resp = self._draw_no_result

            if draw_resp is not self._draw_no_result:
                self.draw_loading = False
                if draw_resp:
                    self.chess_info.accept_draw()
                else:
                    # 拒绝后抑制重复询问，直到和棋条件真正改变
                    self.chess_info.draw_offer_suppressed = True
                    self._show_modal('draw_response', '电脑拒绝和棋',
                                     '电脑认为局势占优，拒绝和棋。',
                                     [{'id': 'ok', 'label': '继续对局'}])

            # 规则触发的和棋提示：有人类参与时弹窗询问“是否和棋”；仅双机对战交给电脑判定
            if (self.chess_info.draw_offer_pending and not self.modal
                    and not self.draw_loading and not self.is_ai_thinking):
                reason = self.chess_info.draw_offer_pending
                self.chess_info.draw_offer_pending = None
                if self.game_mode == 'mvm':
                    self.query_ai_rule_draw()
                else:
                    self._show_modal('draw_rule', '和棋', reason,
                                     [{'id': 'yes', 'label': '同意和棋'},
                                      {'id': 'no', 'label': '继续对局'}])

            # 强制变着提示（重复局面 / 长将 / 长捉）：以提示条呈现
            if (self.chess_info.draw_hint and not self.modal
                    and not self.is_ai_thinking and not self.draw_loading):
                self.show_toast(self.chess_info.draw_hint)
                self.chess_info.draw_hint = ''

            self.screen.fill((225, 230, 238))

            if self.show_settings:
                self.draw_settings()
            else:
                # 棋盘装饰边框
                frame = pygame.Rect(0, self.board_offset_y, self.board_width, self.board_height)
                pygame.draw.rect(self.screen, (60, 42, 28), frame.inflate(8, 8), border_radius=6)
                # 局面浏览：临时渲染指定步数的快照，避免叠加实时高亮/箭头
                real = (self.chess_info.piece, self.chess_info.select,
                        self.chess_info.ret, self.chess_info.suggest_moves,
                        self.chess_info.suggest_move_labels, self.chess_info.suggest,
                        self.chess_info.suggest_track)
                if self.browse_index is not None and 0 <= self.browse_index < len(self.board_snapshots):
                    self.chess_info.piece = self.board_snapshots[self.browse_index]
                    self.chess_info.select = Pos(-1, -1)
                    self.chess_info.ret = []
                    self.chess_info.suggest_moves = []
                    self.chess_info.suggest_move_labels = []
                    self.chess_info.suggest = None
                    self.chess_info.suggest_track = False
                self.chess_view.draw()
                (self.chess_info.piece, self.chess_info.select, self.chess_info.ret,
                 self.chess_info.suggest_moves, self.chess_info.suggest_move_labels,
                 self.chess_info.suggest, self.chess_info.suggest_track) = real
                self.draw_sidebar()
                self._draw_eval_top()
                self._draw_eval_bottom()
                self.draw_menu_bar()
                self._draw_mode_menu()
                self._draw_edit_drag_ghost()
                self._draw_game_over()
                self._draw_save_browser()

            # 弹窗覆盖在最上层
            self._draw_modal()
            self._draw_toast()

            pygame.display.flip()
            self.clock.tick(30)

        self.ai.close()
        pygame.quit()
