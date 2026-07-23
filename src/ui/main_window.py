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


from .board_interaction import BoardInteractionMixin
from .dialogs import DialogsMixin
from .draw_helpers import DrawHelpersMixin
from .edit_panel import EditPanelMixin
from .game_flow import GameFlowMixin
from .hint_eval import HintEvalMixin
from .sidebar import SidebarMixin
from .simulation import SimulationMixin
from .text_render import TextRenderMixin
from .widgets import WidgetsMixin

class MainWindow(BoardInteractionMixin, DialogsMixin, DrawHelpersMixin, EditPanelMixin, GameFlowMixin, HintEvalMixin, SidebarMixin, SimulationMixin, TextRenderMixin, WidgetsMixin):

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
        # 顶部不再保留浮动评分条；评分等一并归入右侧「对局状态」卡片
        self.eval_top_h = 0
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
        # 独立于行棋引擎的“评估引擎”：评分/曲线/和棋判定都走它，
        # 与 self.ai（AI 行棋、支招）完全隔离，互不影响、互不抢占线程。
        self.eval_ai = PikafishAI()
        self.settings = Setting()
        self.settings.load()
        self._sync_settings()
        
        self.game_mode = 'pvp'
        self.player_color = 'red'
        self.is_ai_thinking = False
        self.ai_thread = None
        self.ai_result_queue = queue.Queue()
        self._ai_no_result = object()
        # 用户主动中断 AI 行棋的请求标记：置位后主循环丢弃 AI 返回的着法，
        # 把行棋权交还人类（而非让 AI 立即落子）。
        self._ai_abort_requested = False
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
        self.eval_skip_append = False   # 退出模拟/恢复时评估不写入曲线
        # 与 board_snapshots 对齐的分步评分（红方视角；None=未计算），用于加载棋谱后的评分曲线
        self.eval_by_step = []
        self.eval_step_gen = 0  # 批量评分代际号，用于取消过期的后台批量评分
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
        self._edit_drag_from = None      # 拖拽来源格（None 表示来自调色板）
        self.edit_move_from = None       # 点击移动：待移动棋子源格（None 表示未选中）
        self._edit_last_click = None     # (cell, time, kind) 用于双击删除判定
        self._edit_pickup_cell = None    # 拾起棋子时的原格子（区分移动 / 删除）
        self.edit_history = []           # 摆棋操作撤销栈：每项可还原一次编辑
        self._candidate_last_click = None  # (index, tick) 候选着法双击进入模拟判定
        self.hint_gen = 0                  # 支招请求代号：用于中断时丢弃过期结果
        self.hint_browse_index = -1         # 支招对应的棋谱快照步（-1 表示实时对局）
        self.hint_depth = 0                # 最近一次支招使用的搜索深度（展示在对局状态·深度）
        self.last_depth = 0                 # 最近一次搜索（AI 行棋 / 支招）达到的最大深度，展示为状态卡“最大深度”
        # 当前方行棋时间（每走一步重置，实时累计；单位秒）
        self.turn_start_tick = time.time()
        self._last_red_go = None            # 上一帧行棋方，用于检测换边重置计时
        self._turn_elapsed_frozen = 0.0     # 终局/模拟/摆棋时冻结的时间
        # 支招「跟线」跟踪状态：玩家按推荐线行棋时持续提示剩余着法
        self._track_pv = None        # 当前正在跟踪的推荐线（Move 列表）
        self._track_idx = 0          # 下一个待校验的 PV 步索引
        self._track_my_is_red = True # 该推荐线首步方颜色
        self._edit_img_cache = {}  # 摆棋调色板棋子图片缓存 (piece_id, size) -> Surface
        
        # 解析中文字体：优先使用随项目打包的相对路径字体，保证所有系统下中文正常显示；
        # 再依次回退到各系统常见的中文字体；都找不到则降级为无中文字形的默认字体（仅西文可用）。
        self.cjk_font_path = self._resolve_cjk_font()

        try:
            from PIL import Image, ImageDraw, ImageFont  # noqa: F401
            self.pil_available = True
        except Exception:
            self.pil_available = False
        
        self.menu_buttons = []   # 头部菜单：新局/加载/保存/设置 + 模式（下拉）
        self.side_buttons = []   # 侧栏大按钮：摆棋/上一步/下一步/悔棋/支招
        self.mode_menu_open = False
        self.mode_menu_rects = []
        self.mode_menu_panel_rect = None
        # 棋谱列表（侧栏）状态
        self._move_scroll = 0
        self._move_row_rects = []
        self._move_strs = []
        self._move_strs_len = -1
        self._move_max_scroll = 0
        self._init_buttons()
        
        self.running = True
        self.clock = pygame.time.Clock()

        # 启动即后台完整预初始化引擎（进程启动 + NNUE 权重加载），
        # 使玩家第一步落子时引擎已就绪，不会因冷启动加载 NNUE 而卡顿。
        self._warmup_engines()


    def _init_buttons(self):
        # ===== 头部菜单栏：功能项 + 对战模式 =====
        menu_items = [
            ('act:restart', '新局', 'restart', 'action'),
            ('act:load', '读谱', 'load', 'action'),
            ('act:save', '存谱', 'save', 'action'),
            ('act:settings', '设置', 'settings', 'action'),
            ('mode', '模式', None, 'mode'),
        ]
        pad = 10
        gap = 8
        n = len(menu_items)
        # 品牌移到窗口最右侧，菜单按钮利用品牌左侧的整段空间，使每个按钮适度加宽
        brand_w_est = 170   # 「中国象棋」(large 字号) 估算宽度
        brand_x = self.window_width - brand_w_est - 16
        menu_right = brand_x - 16
        bw = (menu_right - pad - (n - 1) * gap) / n
        bh = 40
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
        sy0 = self.menu_h + 16   # 菜单栏已含品牌，侧栏顶部直接放置按钮
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
        # 悔棋 / 翻转棋盘（同一行，仅图标）
        undo_y = nav_y + big_h + big_gap
        self.side_buttons.append({
            'rect': pygame.Rect(sx, undo_y, nav_w, big_h),
            'key': 'undo', 'label': '悔棋', 'icon': 'undo', 'icon_only': True
        })
        self.side_buttons.append({
            'rect': pygame.Rect(sx + nav_w + 12, undo_y, nav_w, big_h),
            'key': 'flip', 'label': '翻转棋盘', 'icon': 'flip', 'icon_only': True
        })
        # 支招（整行）
        hint_y = undo_y + big_h + big_gap
        self.side_buttons.append({
            'rect': pygame.Rect(sx, hint_y, sw, big_h),
            'key': 'hint', 'label': '支招', 'icon': 'hint'
        })
        # 摆棋开关沿用第一个大按钮
        self.edit_button = self.side_buttons[0]['rect']


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

            # 侧栏大按钮（优先于摆棋面板判断，确保任意模式下均可点击，如翻转棋盘）
            # 摆棋模式下面板覆盖下方按钮，必须优先让面板消费点击，否则会穿透到背后按钮
            if not self.editing:
                for btn in self.side_buttons[1:]:
                    if btn['rect'].collidepoint(x, y):
                        self.handle_action(btn['key'])
                        return

            # 棋谱列表：点击某步跳转复盘（非摆棋模式）
            if not self.editing:
                for rect, step in getattr(self, '_move_row_rects', []):
                    if rect.collidepoint(x, y):
                        self.browse_index = step
                        self._sync_eval_to_browse()
                        self.show_toast(f'跳至第 {step} 步')
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
                # 摆棋面板：点中棋子即选中（点击式摆棋：再点棋盘放置 / 移动）
                item = self._palette_item_at(x, y)
                if item and item[0] == 'piece':
                    self.edit_piece = item[1]
                    self.edit_move_from = None
                    self.chess_info.select = Pos(-1, -1)
                    return
                if item and item[0] == 'clear':
                    # 记录清空前的完整局面，便于悔棋一步还原
                    self.edit_history.append({
                        'type': 'clear',
                        'prev': [row[:] for row in self.chess_info.piece]})
                    for r in range(10):
                        for c in range(9):
                            self.chess_info.piece[r][c] = 0
                    self.edit_move_from = None
                    self._after_edit()
                    return
                # 点空白/置灰区域：取消当前选中
                self.edit_piece = None
                return

            # 支招区域：点击候选着法即选中其起点棋子
            for entry in self.hint_ui:
                if entry['rect'].collidepoint(x, y):
                    self._select_hint(entry['index'])
                    return


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
                    # 候选列表滚动条拖拽
                    if self.candidate_dragging and self.candidate_max_scroll > 0:
                        self._candidate_scroll_to_y(event.pos[1])
                elif event.type == pygame.MOUSEBUTTONUP:
                    self.settings_drag_key = None
                    self._edit_dragging = False
                    self.candidate_dragging = False
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
                    elif getattr(self, '_move_row_rects', None) and self._move_max_scroll > 0:
                        # 棋谱列表滚轮滚动（鼠标位于侧栏区域时）
                        if self.mouse_pos[0] >= self.board_width:
                            self._move_scroll = max(
                                0, min(self._move_max_scroll,
                                       self._move_scroll - event.y * 28))
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
                if self._ai_abort_requested:
                    # 用户中断 AI：丢弃本次着法，切换为双人模式，行棋方保持不变
                    self._ai_abort_requested = False
                    self.is_ai_thinking = False
                    self.chess_info.is_machine = False
                    self.chess_info.status = 0
                    self.game_mode = 'pvp'
                    # 丢弃 AI 思考时实时覆盖的最后一步评分，避免曲线出现半成品分值
                    if self.eval_history:
                        self.eval_history.pop()
                    self.show_toast('已中断 AI，切换为双人对战')
                elif ai_result is None:
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
                    # 若当前查看的快照恰好是刚支招的局面，则保留支招箭头 / 候选标签
                    keep_hint = (self.hint_browse_index == self.browse_index)
                    if not keep_hint:
                        self.chess_info.suggest_moves = []
                        self.chess_info.suggest_move_labels = []
                        self.chess_info.suggest = None
                        self.chess_info.suggest_track = False
                self.chess_view.draw()
                (self.chess_info.piece, self.chess_info.select, self.chess_info.ret,
                 self.chess_info.suggest_moves, self.chess_info.suggest_move_labels,
                 self.chess_info.suggest, self.chess_info.suggest_track) = real
                self.draw_sidebar()
                self._draw_eval_bottom()
                self.draw_menu_bar()
                self._draw_mode_menu()
                self._draw_edit_drag_ghost()
                self._draw_game_over()
                self._draw_save_browser()

            # 弹窗覆盖在最上层
            self._draw_modal()

            pygame.display.flip()
            self.clock.tick(30)

        self.ai.close()
        self.eval_ai.close()
        pygame.quit()

