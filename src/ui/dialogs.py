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


class DialogsMixin:
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
                # 双机对战：玩家选择“继续对局”后恢复 AI 自动行棋
                if self.game_mode == 'mvm' and self.chess_info.get_game_status() == 'playing':
                    self.start_ai_turn()
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


    def _result_info(self):
        """返回 (文本, 颜色, 副文本) 表示当前对局结果；对局进行中返回 None。

        文案与配色参照 Android 端 RoundView：红方胜用朱红、黑方胜用深黑、和棋用灰。
        """
        status = self.chess_info.get_game_status()
        if status == 'checkmate':
            # 将死的行棋方为负，对方获胜
            winner = '红方' if not self.chess_info.is_red_go else '黑方'
            color = (214, 56, 56) if winner == '红方' else (74, 84, 100)
            return f'{winner}获胜！', color, '将死'
        if status == 'stalemate':
            # 中国象棋规则：困毙（无棋可走且未被将军）判负，敌方获胜，而非和棋
            winner = '红方' if not self.chess_info.is_red_go else '黑方'
            color = (214, 56, 56) if winner == '红方' else (74, 84, 100)
            return f'{winner}获胜！', color, '困毙'
        if status == 'draw':
            reason = self.chess_info.draw_reason or '协议和棋'
            return '和棋！', (128, 128, 128), reason
        return None


    def _draw_game_over(self):
        """对局结束后在棋盘区叠加半透明遮罩与醒目结果提示。

        按需求不显示该浮窗（结果仍在对局状态卡片的终局横幅中展示），直接返回。
        """
        return
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

        self._draw_text('加载棋谱', cx + card_w // 2, cy + 30, 'large', (150, 200, 255))
        self._draw_text_left('选择要加载的棋谱（点击行加载，点击取消关闭）',
                              cx + 24, cy + 64, 'small', (150, 162, 184))

        rects = []
        row_y = cy + 88
        for i, e in enumerate(entries):
            rrect = pygame.Rect(cx + 20, row_y, card_w - 40, 48)
            hovered = rrect.collidepoint(self.mouse_pos)
            pygame.draw.rect(self.screen,
                             (44, 66, 100) if hovered else (28, 38, 54),
                             rrect, border_radius=10)
            red = e.get('red') or '红方'
            black = e.get('black') or '黑方'
            self._draw_text_left(e['name'], cx + 34, row_y + 16, 'small', (235, 240, 248))
            self._draw_text_left(
                f'{red} vs {black} · {e["moves"]}步 · {"红先" if e.get("is_red_go") else "黑先"}',
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
                self._apply_pgn_data(path)
                return True
        # 遮罩与卡片空白区域也吸收点击，避免穿透到下层按钮
        return True

