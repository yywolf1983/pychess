import pygame
import os
import math
from typing import List
from ..game.board import ChessInfo
from ..game.pos import Pos
from ..game.rule import is_red

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


class ChessView:
    def __init__(self, screen: pygame.Surface, chess_info: ChessInfo):
        self.screen = screen
        self.chess_info = chess_info
        # 以棋盘图片【实测真实网格线】为基准对齐（图片网格并非均匀间距）。
        # 用实测网格线数组 + 线性插值定位，棋子精确落在图片真实格点，消除累积错位。
        self.scale = 0.72
        # 实测内部网格线（原图像素坐标）
        self.gx_raw = [33, 125, 208, 291, 374, 457, 540, 623, 706]
        self.gy_raw = [70, 163, 245, 328, 411, 494, 577, 661, 743, 827]
        self.padding_left = self.gx_raw[0] * self.scale
        self.padding_top = self.gy_raw[0] * self.scale
        # 棋子尺寸与棋盘缩放等比联动（原 scale=0.9 时为 72）
        self.piece_size = int(80 * self.scale)
        self.board_width = int(750 * self.scale)
        self.board_height = int(909 * self.scale)
        # 棋子以【中心】对齐图片格线交点（象棋棋子落在线点中心）
        self._piece_cx_off = -self.piece_size // 2
        self._piece_cy_off = -self.piece_size // 2

        self.images = self._load_images()
        
        self.think_index = 0
        self.think_flag = 0
    
    def _load_images(self):
        images = {}
        
        resources_dir = os.path.join(os.path.dirname(__file__), '../../src/resources')
        
        def load_image_safe(path):
            if not os.path.exists(path):
                return None
            try:
                return pygame.image.load(path).convert_alpha()
            except:
                if PIL_AVAILABLE:
                    try:
                        pil_image = Image.open(path).convert('RGBA')
                        mode = pil_image.mode
                        size = pil_image.size
                        data = pil_image.tobytes()
                        pygame_image = pygame.image.fromstring(data, size, mode)
                        return pygame_image.convert_alpha()
                    except:
                        return None
                return None
        
        board_path = os.path.join(resources_dir, 'chessboard.png')
        images['board'] = load_image_safe(board_path)
        
        box_paths = {
            'b_box': os.path.join(resources_dir, 'b_box.png'),
            'r_box': os.path.join(resources_dir, 'r_box.png'),
            'pot': os.path.join(resources_dir, 'pot.png')
        }
        
        for name, path in box_paths.items():
            images[name] = load_image_safe(path)
        
        black_pieces = {
            'b_jiang': 0, 'b_shi': 1, 'b_xiang': 2, 'b_ma': 3,
            'b_ju': 4, 'b_pao': 5, 'b_zu': 6
        }
        red_pieces = {
            'r_shuai': 0, 'r_shi': 1, 'r_xiang': 2, 'r_ma': 3,
            'r_ju': 4, 'r_pao': 5, 'r_bing': 6
        }
        
        images['black'] = []
        for name, idx in black_pieces.items():
            path = os.path.join(resources_dir, f'{name}.png')
            images['black'].append(load_image_safe(path))
        
        images['red'] = []
        for name, idx in red_pieces.items():
            path = os.path.join(resources_dir, f'{name}.png')
            images['red'].append(load_image_safe(path))
        
        if not images['board'] or None in images['black'] or None in images['red']:
            images = self._create_fallback_images()
        
        return images
    
    def _create_fallback_images(self):
        images = {}
        images['board'] = None
        
        box_size = self.piece_size
        b_box = pygame.Surface((box_size, box_size), pygame.SRCALPHA)
        pygame.draw.circle(b_box, (100, 150, 255, 100), (box_size//2, box_size//2), box_size//2 - 2)
        images['b_box'] = b_box
        
        r_box = pygame.Surface((box_size, box_size), pygame.SRCALPHA)
        pygame.draw.circle(r_box, (255, 150, 100, 100), (box_size//2, box_size//2), box_size//2 - 2)
        images['r_box'] = r_box
        
        pot = pygame.Surface((box_size, box_size), pygame.SRCALPHA)
        pygame.draw.circle(pot, (0, 200, 100, 80), (box_size//2, box_size//2), 15)
        images['pot'] = pot
        
        piece_size = self.piece_size
        
        def create_piece(color_dark, color_light, icon_type):
            piece = pygame.Surface((piece_size, piece_size), pygame.SRCALPHA)
            pygame.draw.circle(piece, color_dark, (piece_size//2, piece_size//2), piece_size//2 - 3)
            pygame.draw.circle(piece, color_light, (piece_size//2, piece_size//2), piece_size//2 - 5)
            cx, cy = piece_size//2, piece_size//2
            s = piece_size // 5
            
            if icon_type == 0:
                pygame.draw.rect(piece, (255, 255, 255), (cx-s, cy-s, s*2, s*2))
            elif icon_type == 1:
                pygame.draw.polygon(piece, (255, 255, 255), [(cx, cy-s*2), (cx-s, cy), (cx+s, cy)])
            elif icon_type == 2:
                pygame.draw.circle(piece, (255, 255, 255), (cx, cy), s)
            elif icon_type == 3:
                pygame.draw.polygon(piece, (255, 255, 255), [(cx, cy-s*2), (cx-s*1.5, cy-s), (cx-s*1.5, cy+s), (cx, cy), (cx+s*1.5, cy+s), (cx+s*1.5, cy-s)])
            elif icon_type == 4:
                pygame.draw.rect(piece, (255, 255, 255), (cx-s, cy-s*2, s*2, s*4))
            elif icon_type == 5:
                pygame.draw.circle(piece, (255, 255, 255), (cx, cy), s*1.5)
                pygame.draw.circle(piece, color_light, (cx, cy), s*0.5)
            elif icon_type == 6:
                pygame.draw.polygon(piece, (255, 255, 255), [(cx, cy-s*2), (cx-s, cy), (cx, cy+s), (cx+s, cy)])
            
            return piece
        
        images['black'] = []
        for i in range(7):
            images['black'].append(create_piece((20, 20, 20), (60, 60, 60), i))
        
        images['red'] = []
        for i in range(7):
            images['red'].append(create_piece((180, 30, 30), (220, 60, 60), i))
        
        return images
    
    def draw(self):
        if self.images['board']:
            scaled_board = pygame.transform.scale(
                self.images['board'], 
                (self.board_width, self.board_height)
            )
            self.screen.blit(scaled_board, (0, 0))
        else:
            self._draw_chessboard_grid()
        
        self._draw_coordinates()
        
        self._draw_pieces()
        self._draw_selected()
        self._draw_possible_moves()
        self._draw_move_trail()
        self._draw_suggestions()
        self._draw_thinking()
    
    def _gx(self, x):
        """第 x 条竖线（0..8）在缩放后棋盘上的 x 像素（基于图片实测网格线线性插值）。"""
        if x <= 0:
            return self.gx_raw[0] * self.scale
        if x >= 8:
            return self.gx_raw[8] * self.scale
        return self.gx_raw[x] * self.scale

    def _gy(self, y):
        """第 y 条横线（0..9）在缩放后棋盘上的 y 像素（基于图片实测网格线线性插值）。"""
        if y <= 0:
            return self.gy_raw[0] * self.scale
        if y >= 9:
            return self.gy_raw[9] * self.scale
        return self.gy_raw[y] * self.scale

    def _draw_chessboard_grid(self):
        # 棋盘底图已自带网格/底色；此处仅用图片真实格点重绘黑色网格线，覆盖底图误差。
        for x in range(9):
            lx = self._gx(x)
            pygame.draw.line(self.screen, (0, 0, 0), (lx, self._gy(0)), (lx, self._gy(9)), 1)
        for y in range(10):
            ly = self._gy(y)
            pygame.draw.line(self.screen, (0, 0, 0), (self._gx(0), ly), (self._gx(8), ly), 1)
        self._draw_palace()

    def _draw_palace(self):
        pl = self.padding_left
        pt = self.padding_top
        # 九宫斜线用图片真实格点（列3-5、行0-2、行7-9）
        pygame.draw.line(self.screen, (0, 0, 0),
                         (self._gx(3), self._gy(0)), (self._gx(5), self._gy(2)), 2)
        pygame.draw.line(self.screen, (0, 0, 0),
                         (self._gx(5), self._gy(0)), (self._gx(3), self._gy(2)), 2)
        pygame.draw.line(self.screen, (0, 0, 0),
                         (self._gx(3), self._gy(7)), (self._gx(5), self._gy(9)), 2)
        pygame.draw.line(self.screen, (0, 0, 0),
                         (self._gx(5), self._gy(7)), (self._gx(3), self._gy(9)), 2)

    def _draw_coordinates(self):
        pass
    
    def _draw_pieces(self):
        for y in range(10):
            for x in range(9):
                piece_id = self.chess_info.piece[y][x]
                if piece_id > 0:
                    draw_y = 9 - y
                    screen_x = self._gx(x) + self._piece_cx_off
                    screen_y = self._gy(draw_y) + self._piece_cy_off
                    
                    if piece_id <= 7:
                        idx = piece_id - 1
                        if idx >= 0 and idx < len(self.images['black']) and self.images['black'][idx]:
                            piece_img = pygame.transform.scale(
                                self.images['black'][idx], (self.piece_size, self.piece_size))
                            self.screen.blit(piece_img, (screen_x, screen_y))
                    else:
                        idx = piece_id - 8
                        if idx >= 0 and idx < len(self.images['red']) and self.images['red'][idx]:
                            piece_img = pygame.transform.scale(
                                self.images['red'][idx], (self.piece_size, self.piece_size))
                            self.screen.blit(piece_img, (screen_x, screen_y))
    
    def _draw_selected(self):
        if self.chess_info.select.x >= 0 and self.chess_info.select.y >= 0:
            x = self.chess_info.select.x
            y = self.chess_info.select.y
            piece_id = self.chess_info.piece[y][x]
            
            if piece_id > 0:
                draw_y = 9 - y
                screen_x = self._gx(x) + self._piece_cx_off
                screen_y = self._gy(draw_y) + self._piece_cy_off
                
                is_red_piece = piece_id >= 8
                # 颜色提示：选中格子叠加半透明底色（红方暖色 / 黑方冷色）
                overlay_color = (255, 196, 0) if is_red_piece else (90, 170, 255)
                ov = pygame.Surface((self.piece_size, self.piece_size), pygame.SRCALPHA)
                ov.fill((*overlay_color, 64))
                self.screen.blit(ov, (screen_x, screen_y))

                box_img = self.images['r_box'] if is_red_piece else self.images['b_box']
                
                if box_img:
                    box_scaled = pygame.transform.scale(box_img, (self.piece_size, self.piece_size))
                    self.screen.blit(box_scaled, (screen_x, screen_y))
    
    def _draw_possible_moves(self):
        if self.chess_info.ret:
            for pos in self.chess_info.ret:
                draw_y = 9 - pos.y
                screen_x = self._gx(pos.x) + self._piece_cx_off
                screen_y = self._gy(draw_y) + self._piece_cy_off
                
                if self.images['pot']:
                    pot_scaled = pygame.transform.scale(
                        self.images['pot'], (self.piece_size, self.piece_size))
                    self.screen.blit(pot_scaled, (screen_x, screen_y))
    
    def _draw_move_trail(self):
        if (self.chess_info.pre_pos.x >= 0 and self.chess_info.cur_pos.x >= 0 and
                not self.chess_info.is_checked):
            pre_x = self.chess_info.pre_pos.x
            pre_y = self.chess_info.pre_pos.y
            cur_x = self.chess_info.cur_pos.x
            cur_y = self.chess_info.cur_pos.y
            
            piece_id = self.chess_info.piece[cur_y][cur_x]
            
            draw_pre_y = 9 - pre_y
            draw_cur_y = 9 - cur_y
            
            pre_screen_x = self._gx(pre_x) + self._piece_cx_off
            pre_screen_y = self._gy(draw_pre_y) + self._piece_cy_off
            cur_screen_x = self._gx(cur_x) + self._piece_cx_off
            cur_screen_y = self._gy(draw_cur_y) + self._piece_cy_off
            
            is_black_piece = piece_id >= 1 and piece_id <= 7
            box_img = self.images['b_box'] if is_black_piece else self.images['r_box']
            
            if box_img:
                box_scaled = pygame.transform.scale(box_img, (self.piece_size, self.piece_size))
                self.screen.blit(box_scaled, (cur_screen_x, cur_screen_y))
                self.screen.blit(box_scaled, (pre_screen_x, pre_screen_y))
                
                overlay_color = (20, 200, 255) if is_black_piece else (255, 200, 0)
                overlay_surface = pygame.Surface((self.piece_size, self.piece_size), pygame.SRCALPHA)
                overlay_surface.fill((*overlay_color, 20))
                self.screen.blit(overlay_surface, (cur_screen_x, cur_screen_y))
    
    def _draw_suggestions(self):
        if self.chess_info.suggest_moves and self.chess_info.suggest_move_labels:
            # 线条粗细 / 端点圆随棋盘等比缩放（基准 scale=0.9）
            f = self.scale / 0.9
            step_colors = [
                (255, 0, 0), (0, 128, 255), (0, 180, 0), (255, 128, 0),
                (180, 0, 255), (255, 0, 128), (128, 128, 0), (0, 180, 180)
            ]
            track = getattr(self.chess_info, 'suggest_track', False)
            if track:
                # 跟线模式：将整条推荐线（剩余着法）逐段绘出，提示玩家续走
                for i, move in enumerate(self.chess_info.suggest_moves):
                    color = step_colors[i % len(step_colors)]
                    self._draw_step(move, color, solid=True,
                                    width=max(3, int(5 * f)), radius=max(10, int(20 * f)))
                return
            # 仅高亮“当前选中”的那一路支招（参照 Android 单步高亮，避免线条混乱）
            sel_index = getattr(self.chess_info, 'suggest_sel_index', 0)
            if sel_index < 0 or sel_index >= len(self.chess_info.suggest_moves):
                sel_index = 0
            replies = getattr(self.chess_info, 'suggest_replies', None)
            move = self.chess_info.suggest_moves[sel_index]
            color = step_colors[sel_index % len(step_colors)]

            # 当前方一步（实线箭头 + 起点高亮圆圈）
            self._draw_step(move, color, solid=True,
                            width=max(3, int(5 * f)), radius=max(10, int(20 * f)))

            # 对方一步（虚线箭头，表示应招）
            if replies is not None and sel_index < len(replies):
                rep = replies[sel_index]
                if rep is not None and rep.is_valid():
                    opp_color = tuple(max(0, int(c * 0.65)) for c in color)
                    self._draw_step(rep, opp_color, solid=False,
                                    width=max(2, int(4 * f)), radius=max(8, int(15 * f)))

    def _draw_step(self, move, color, solid=True, width=5, radius=18):
        from_x, from_y = move.from_pos.x, move.from_pos.y
        to_x, to_y = move.to_pos.x, move.to_pos.y

        draw_from_y = 9 - from_y
        draw_to_y = 9 - to_y

        # 棋子以网格交点为中心绘制，支招线条也应落在交点，避免半格错位
        from_center_x = self._gx(from_x)
        from_center_y = self._gy(draw_from_y)
        to_center_x = self._gx(to_x)
        to_center_y = self._gy(draw_to_y)

        f = self.scale / 0.9
        dx = to_center_x - from_center_x
        dy = to_center_y - from_center_y
        dist = math.hypot(dx, dy)
        head_len = max(18, int(30 * f))
        if dist > head_len + 4:
            ux, uy = dx / dist, dy / dist
            base_x = to_center_x - ux * head_len
            base_y = to_center_y - uy * head_len
        else:
            base_x, base_y = to_center_x, to_center_y

        outline = (16, 16, 16)
        if solid:
            pygame.draw.line(self.screen, outline,
                             (from_center_x, from_center_y), (base_x, base_y), width + 3)
            pygame.draw.line(self.screen, color,
                             (from_center_x, from_center_y), (base_x, base_y), width)
        else:
            self._draw_dashed_line(from_center_x, from_center_y, base_x, base_y, outline, width + 3)
            self._draw_dashed_line(from_center_x, from_center_y, base_x, base_y, color, width)

        if radius:
            # 起点高亮圆圈：半透明，避免遮挡底层棋子
            r = int(radius + 2)
            dot = pygame.Surface((2 * r, 2 * r), pygame.SRCALPHA)
            dcx = dcy = r
            pygame.draw.circle(dot, (*outline, 130), (dcx, dcy), r)
            pygame.draw.circle(dot, (*color, 110), (dcx, dcy), radius)
            self.screen.blit(dot, (from_center_x - dcx, from_center_y - dcy))

        self._draw_arrow(from_center_x, from_center_y, to_center_x, to_center_y, color, outline)

    def _draw_arrow(self, from_x, from_y, to_x, to_y, color, outline):
        """填充三角箭头 + 细描边，落在着法终点。"""
        dx = to_x - from_x
        dy = to_y - from_y
        dist = math.hypot(dx, dy)
        if dist < 1:
            return
        f = self.scale / 0.9
        head_len = max(18, int(30 * f))
        head_half = max(7, int(12 * f))
        end_x, end_y = to_x, to_y
        ux, uy = dx / dist, dy / dist
        perp_x, perp_y = -uy, ux
        base_x = end_x - ux * head_len
        base_y = end_y - uy * head_len
        p1 = (end_x, end_y)
        p2 = (base_x + perp_x * head_half, base_y + perp_y * head_half)
        p3 = (base_x - perp_x * head_half, base_y - perp_y * head_half)
        of = max(2, int(3 * f))
        pygame.draw.polygon(self.screen, outline, [
            (end_x + ux * of, end_y + uy * of),
            (p2[0] + perp_x * of, p2[1] + perp_y * of),
            (p3[0] - perp_x * of, p3[1] - perp_y * of),
        ])
        pygame.draw.polygon(self.screen, color, [p1, p2, p3])

    def _draw_dashed_line(self, from_x, from_y, to_x, to_y, color, width=6):
        dx = to_x - from_x
        dy = to_y - from_y
        length = math.hypot(dx, dy)
        dash_length = 12
        gap_length = 8

        num_dashes = int(length / (dash_length + gap_length))

        for i in range(num_dashes):
            start_ratio = i * (dash_length + gap_length) / length
            end_ratio = (i * (dash_length + gap_length) + dash_length) / length

            line_start_x = from_x + dx * start_ratio
            line_start_y = from_y + dy * start_ratio
            line_end_x = from_x + dx * end_ratio
            line_end_y = from_y + dy * end_ratio

            pygame.draw.line(self.screen, color, (line_start_x, line_start_y), (line_end_x, line_end_y), width)
    
    def _draw_thinking(self):
        pass
    
    def get_board_coordinates(self, screen_x: int, screen_y: int) -> Pos:
        screen_x = int(screen_x)
        screen_y = int(screen_y)
        if screen_x < 0 or screen_x >= self.board_width:
            return Pos(-1, -1)
        
        adjusted_y = screen_y
        if adjusted_y < 0 or adjusted_y >= self.board_height:
            return Pos(-1, -1)

        # 绘制时 y 轴被翻转（draw_y = 9 - y，红方在底部），
        # 因此点击坐标需要反向映射，与显示保持一致。
        # 直接匹配棋子绘制所用的图片实测格点（应对非均匀间距）。
        # 注：screen_x/screen_y 已是棋盘子表面坐标（调用方已减 board_offset_y），
        #     而 _gx/_gy 也是相对子表面左上角，故此处不再减 padding_top。
        xs = [self._gx(i) for i in range(9)]
        ys = [self._gy(i) for i in range(10)]
        x = min(range(9), key=lambda i: abs(screen_x - xs[i]))
        ry = min(range(10), key=lambda i: abs(adjusted_y - ys[i]))
        board_y = 9 - ry

        if 0 <= x < 9 and 0 <= board_y < 10:
            return Pos(int(x), int(board_y))

        return Pos(-1, -1)
    
    def set_chess_info(self, chess_info: ChessInfo):
        self.chess_info = chess_info
