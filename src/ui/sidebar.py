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
        # 实时评分（文字呈现于对局状态；顶部不再保留浮动评分条）
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

        # 临时提示信息：集中显示在「对局状态」中（不再浮动于棋盘之上）
        if self.toast and time.time() <= self.toast_until:
            cy += 8
            msg = self.toast
            chars_per_line = max(1, cw // 26)
            nlines = max(1, math.ceil(len(msg) / chars_per_line))
            box_h = nlines * 24 + 16
            box = pygame.Rect(cx - 4, cy, cw + 8, box_h)
            surf = pygame.Surface((box.width, box.height), pygame.SRCALPHA)
            surf.fill((36, 50, 70, 245))
            self.screen.blit(surf, (box.x, box.y))
            pygame.draw.rect(self.screen, (120, 150, 190), box, 1, border_radius=6)
            self._draw_wrapped_text(msg, cx, cy + 10, cw, 24, (225, 235, 248), 'small')
            cy += box_h + 4


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

