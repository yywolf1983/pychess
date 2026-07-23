"""跨平台文件对话框（纯 pygame 实现，不依赖 tkinter）。

用于在不同操作系统 / 打包环境下一致地「打开」与「保存」棋谱(.pgn)，
支持浏览任意目录、进入子目录、返回上级、跳到主目录，以及自定义文件名。
"""

import os
import time

import pygame

from ..game import pgn as pgn_lib


class FileDialogMixin:
    # ------------------------------------------------------------------ #
    # 公开入口
    # ------------------------------------------------------------------ #
    def _open_file_dialog(self, mode):
        """打开文件对话框。mode 为 'open'（打开棋谱）或 'save'（保存棋谱）。"""
        init_dir = self.save_dir
        if not os.path.isdir(init_dir):
            try:
                os.makedirs(init_dir, exist_ok=True)
            except OSError:
                init_dir = os.path.expanduser('~')
        if not os.path.isdir(init_dir):
            init_dir = os.path.expanduser('~')

        from datetime import datetime
        default_name = f'chess_{datetime.now().strftime("%Y%m%d_%H%M%S")}.pgn'

        self.file_dialog = {
            'mode': mode,
            'dir': init_dir,
            'entries': [],
            'selected': None,           # open 模式选中的文件名
            'filename': default_name if mode == 'save' else '',
            'input_active': (mode == 'save'),
            'scroll': 0,
            'max_scroll': 0,
            'last_sel_t': 0,
            'rects': [],
        }
        self._refresh_file_dialog()
        try:
            pygame.key.start_text_input()
        except Exception:
            pass

    def _close_file_dialog(self):
        try:
            pygame.key.stop_text_input()
        except Exception:
            pass
        self.file_dialog = None

    # ------------------------------------------------------------------ #
    # 内部：目录扫描与布局
    # ------------------------------------------------------------------ #
    def _refresh_file_dialog(self):
        fd = self.file_dialog
        fd['entries'] = self._scan_dir(fd['dir'])
        fd['selected'] = None
        fd['scroll'] = 0
        fd['max_scroll'] = 0

    def _scan_dir(self, path):
        dirs, files = [], []
        try:
            names = os.listdir(path)
        except OSError:
            names = []
        for name in names:
            full = os.path.join(path, name)
            try:
                if os.path.isdir(full):
                    if name.startswith('.'):
                        continue
                    dirs.append({'name': name, 'is_dir': True, 'path': full, 'meta': ''})
                else:
                    if self.file_dialog['mode'] == 'open' and \
                            not name.lower().endswith('.pgn'):
                        continue
                    meta = ''
                    if name.lower().endswith('.pgn'):
                        try:
                            with open(full, 'r', encoding='utf-8') as f:
                                txt = f.read()
                            p = pgn_lib.parse_pgn(txt)
                            moves = len(p['moves'])
                            fen = p['headers'].get('FEN')
                            start_red = True
                            if fen:
                                _, start_red = pgn_lib.fen_to_board_array(fen)
                            red = p['headers'].get('Red') or ('红方' if start_red else '黑方')
                            black = p['headers'].get('Black') or ('黑方' if start_red else '红方')
                            meta = f'{moves}步 · {red} vs {black}'
                        except Exception:
                            meta = ''
                    files.append({'name': name, 'is_dir': False, 'path': full, 'meta': meta})
            except OSError:
                continue
        dirs.sort(key=lambda e: e['name'].lower())
        files.sort(key=lambda e: e['name'].lower())
        return dirs + files

    def _fd_layout(self):
        fd = self.file_dialog
        mode = fd['mode']
        W, H = self.screen.get_size()
        card_w = 580
        card_h = 560 if mode == 'save' else 510
        cx, cy = W // 2, H // 2
        card = pygame.Rect(cx - card_w // 2, cy - card_h // 2, card_w, card_h)

        btn_w, btn_h = 34, 30
        close_rect = pygame.Rect(card.right - 34, card.y + 12, 22, 22)
        up_rect = pygame.Rect(card.right - 18 - btn_w, card.y + 56, btn_w, btn_h)
        home_rect = pygame.Rect(up_rect.x - btn_w - 8, card.y + 56, btn_w, btn_h)

        btn_h2 = 36
        btn_y = card.y + card_h - 44
        list_top = card.y + 100
        if mode == 'save':
            input_h = 34
            input_y = btn_y - 14 - input_h
            list_bottom = input_y - 10
            input_rect = pygame.Rect(card.x + 18, input_y, card_w - 36, input_h)
        else:
            list_bottom = btn_y - 16
            input_rect = None

        cancel_rect = pygame.Rect(cx - 160, btn_y, 140, btn_h2)
        ok_rect = pygame.Rect(cx + 20, btn_y, 140, btn_h2)
        return {
            'card': card, 'close_rect': close_rect, 'up_rect': up_rect,
            'home_rect': home_rect, 'list_top': list_top, 'list_bottom': list_bottom,
            'row_h': 42, 'input_rect': input_rect, 'cancel_rect': cancel_rect,
            'ok_rect': ok_rect,
        }

    def _fd_rows(self, layout):
        fd = self.file_dialog
        row_h = layout['row_h']
        scroll = fd['scroll']
        res = []
        for i, e in enumerate(fd['entries']):
            ry = layout['list_top'] - scroll + i * row_h
            rect = pygame.Rect(layout['card'].x + 12, ry, layout['card'].width - 24, row_h - 4)
            res.append((i, e, rect))
        return res

    def _fd_fit(self, text, max_w, size):
        surf = self._text_surface(text, size)
        if surf is None or surf.get_width() <= max_w:
            return text
        left = '…'
        t = text
        while t and self._text_surface(left + t, size).get_width() > max_w:
            t = t[1:]
        return left + t

    # ------------------------------------------------------------------ #
    # 绘制
    # ------------------------------------------------------------------ #
    def _draw_file_dialog(self):
        fd = self.file_dialog
        if not fd:
            return
        W, H = self.screen.get_size()
        overlay = pygame.Surface((W, H), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 150))
        self.screen.blit(overlay, (0, 0))

        layout = self._fd_layout()
        fd['_layout'] = layout
        card = layout['card']
        mode = fd['mode']

        # 卡片
        pygame.draw.rect(self.screen, (26, 33, 50), card, border_radius=14)
        pygame.draw.rect(self.screen, (90, 120, 160), card, width=1, border_radius=14)

        # 标题
        title = '打开棋谱' if mode == 'open' else '保存棋谱'
        self._draw_text(title, card.centerx, card.y + 28, 'large', (235, 240, 248))
        # 关闭按钮
        cr = layout['close_rect']
        pygame.draw.rect(self.screen, (60, 72, 92), cr, border_radius=6)
        self._draw_text('×', cr.centerx, cr.centery, 'small', (220, 226, 236))

        # 路径栏 + 导航按钮
        ur = layout['up_rect']
        hr = layout['home_rect']
        pygame.draw.rect(self.screen, (46, 58, 80), ur, border_radius=8)
        self._draw_text('↑', ur.centerx, ur.centery, 'small', (220, 226, 236))
        pygame.draw.rect(self.screen, (46, 58, 80), hr, border_radius=8)
        self._draw_text('主', hr.centerx, hr.centery, 'ssmall', (220, 226, 236))
        path_x = card.x + 18
        path_w = hr.x - 10 - path_x
        self._draw_text_left(self._fd_fit(fd['dir'], path_w, 'xsmall'),
                             path_x, card.y + 71, 'xsmall', (170, 190, 215))
        # 路径栏底边
        pygame.draw.line(self.screen, (60, 72, 92),
                         (card.x + 18, card.y + 92), (card.right - 18, card.y + 92))

        # 列表（裁剪）
        list_h = layout['list_bottom'] - layout['list_top']
        clip = self.screen.get_clip()
        self.screen.set_clip(pygame.Rect(card.x + 8, layout['list_top'],
                                         card.width - 16, list_h))
        fd['rects'] = []
        sel_name = fd['filename'] if mode == 'save' else fd['selected']
        for i, e, rect in self._fd_rows(layout):
            if rect.bottom < layout['list_top'] or rect.top > layout['list_bottom']:
                fd['rects'].append({'index': i, 'rect': rect, 'entry': e})
                continue
            if e['name'] == sel_name:
                pygame.draw.rect(self.screen, (56, 92, 140), rect, border_radius=8)
            elif i % 2 == 0:
                pygame.draw.rect(self.screen, (34, 42, 60), rect, border_radius=8)
            label = ('▸ ' + e['name']) if e['is_dir'] else e['name']
            self._draw_text_left(label, rect.x + 12, rect.centery, 'small',
                                 (235, 240, 248) if not e['is_dir'] else (255, 220, 150))
            if e['meta']:
                self._draw_text_right(e['meta'], rect.right - 12, rect.centery, 'xsmall',
                                      (160, 180, 205))
            fd['rects'].append({'index': i, 'rect': rect, 'entry': e})
        self.screen.set_clip(clip)

        # 滚动条
        if fd['max_scroll'] > 0:
            bar_h = max(30, int(list_h * list_h /
                                (list_h + fd['max_scroll'])))
            bar_y = layout['list_top'] + int(list_h * fd['scroll'] /
                                             (fd['max_scroll'] + list_h))
            pygame.draw.rect(self.screen, (120, 140, 170),
                             pygame.Rect(card.right - 10, bar_y, 5, bar_h),
                             border_radius=3)

        # 保存模式的文件名输入框
        if mode == 'save' and layout['input_rect']:
            ir = layout['input_rect']
            pygame.draw.rect(self.screen, (18, 24, 38), ir, border_radius=8)
            border_col = (120, 170, 255) if fd['input_active'] else (70, 90, 120)
            pygame.draw.rect(self.screen, border_col, ir, width=1, border_radius=8)
            self._draw_text_right('文件名:', ir.x - 4, ir.centery, 'xsmall',
                                  (190, 205, 225))
            text = fd['filename']
            if fd['input_active'] and int(time.time() * 2) % 2 == 0:
                text += '|'
            self._draw_text_left(text, ir.x + 10, ir.centery, 'small',
                                 (235, 240, 248))

        # 底部按钮
        cancel = layout['cancel_rect']
        ok = layout['ok_rect']
        ok_label = '打开' if mode == 'open' else '保存'
        self._draw_button(cancel, '取消', 'small',
                          base=(70, 82, 100), hover=(95, 110, 135),
                          text_color=(225, 232, 242))
        self._draw_button(ok, ok_label, 'small',
                          base=(46, 120, 80), hover=(60, 160, 105),
                          text_color=(235, 245, 238))

    # ------------------------------------------------------------------ #
    # 事件
    # ------------------------------------------------------------------ #
    def _handle_file_dialog_click(self, x, y):
        fd = self.file_dialog
        if not fd:
            return False
        layout = self._fd_layout()
        card = layout['card']

        if not card.collidepoint(x, y):
            self._close_file_dialog()
            return True
        if layout['close_rect'].collidepoint(x, y):
            self._close_file_dialog()
            return True
        if layout['up_rect'].collidepoint(x, y):
            parent = os.path.dirname(fd['dir'])
            if parent and os.path.isdir(parent):
                fd['dir'] = parent
                self._refresh_file_dialog()
            return True
        if layout['home_rect'].collidepoint(x, y):
            fd['dir'] = os.path.expanduser('~')
            self._refresh_file_dialog()
            return True
        if layout['cancel_rect'].collidepoint(x, y):
            self._close_file_dialog()
            return True
        if layout['ok_rect'].collidepoint(x, y):
            self._confirm_file_dialog()
            return True
        if fd['mode'] == 'save' and layout['input_rect'] and \
                layout['input_rect'].collidepoint(x, y):
            fd['input_active'] = True
            return True

        # 列表项
        for item in fd['rects']:
            rect = item['rect']
            if not rect.collidepoint(x, y):
                continue
            e = item['entry']
            if e['is_dir']:
                fd['dir'] = e['path']
                fd['scroll'] = 0
                self._refresh_file_dialog()
            else:
                if fd['mode'] == 'save':
                    fd['filename'] = e['name']
                    fd['selected'] = e['name']
                else:
                    now = time.time()
                    if fd['selected'] == e['name'] and (now - fd['last_sel_t']) < 0.4:
                        self._confirm_file_dialog()
                        return True
                    fd['selected'] = e['name']
                    fd['last_sel_t'] = now
            return True
        return True  # 卡片内空白处吞掉点击

    def _handle_file_dialog_wheel(self, event):
        fd = self.file_dialog
        if not fd:
            return
        layout = self._fd_layout()
        list_h = layout['list_bottom'] - layout['list_top']
        max_scroll = max(0, len(fd['entries']) * layout['row_h'] - list_h)
        fd['max_scroll'] = max_scroll
        d = getattr(event, 'y', 0)
        fd['scroll'] = max(0, min(max_scroll, fd['scroll'] - d * layout['row_h']))

    def _handle_file_dialog_key(self, event):
        fd = self.file_dialog
        if not fd:
            return
        if event.key == pygame.K_ESCAPE:
            self._close_file_dialog()
            return
        if fd['mode'] == 'save' and fd.get('input_active'):
            if event.key == pygame.K_BACKSPACE:
                fd['filename'] = fd['filename'][:-1]
            elif event.key == pygame.K_RETURN:
                self._confirm_file_dialog()

    def _file_dialog_input(self, text):
        fd = self.file_dialog
        if not fd or fd['mode'] != 'save':
            return
        text = text.replace('/', '').replace('\\', '')
        if len(fd['filename']) + len(text) <= 120:
            fd['filename'] += text

    def _confirm_file_dialog(self):
        fd = self.file_dialog
        if not fd:
            return
        mode = fd['mode']
        name = (fd['filename'].strip() if mode == 'save' else (fd['selected'] or ''))
        if not name:
            self.show_toast('请输入文件名' if mode == 'save' else '请选择棋谱文件')
            return
        path = os.path.join(fd['dir'], name)
        if mode == 'save' and not path.lower().endswith('.pgn'):
            path += '.pgn'
        self._close_file_dialog()
        if mode == 'save':
            self._save_game_to(path)
        else:
            self._apply_pgn_data(path)
