import os
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
from ..game import pgn as pgn_lib
from ..ai.pikafish import PikafishAI
from .chess_view import ChessView


class GameFlowMixin:
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
        # 重置当前方行棋计时
        self.turn_start_tick = time.time()
        self._last_red_go = self.chess_info.is_red_go
        self._turn_elapsed_frozen = 0.0
        self.ai.close()
        self.is_ai_thinking = False
        self.hint_loading = False
        self.draw_loading = False
        self.toast = None
        self.eval_score = None
        self.eval_history = []
        self.eval_by_step = []
        self.eval_gen += 1
        self.eval_step_gen += 1  # 取消可能仍在运行的批量评分
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
        # 浏览状态下悔棋：从「当前步」往回退 undo_count 步，在该局面分叉进入实时对局，
        # 而非退回到谱的最后一步（之前 browse_index=None 会让棋盘跳到 board_snapshots[-1]）。
        if self.browse_index is not None:
            k = self.browse_index
            undo_count = 2 if self.game_mode in ('pvm_red', 'pvm_black') else 1
            new_k = max(0, k - undo_count)
            self.browse_index = new_k
            self._enter_live_from_browse(undo=True)
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

        # 从初始局面精确重放剩余历史（含吃子，象棋无随机性可完整复原），
        # 同时重建 board_snapshots 使其与 move_history 对齐，保证悔棋后
        # 浏览/评分曲线仍然一致。
        self.board_snapshots = [[row[:] for row in self.chess_info.piece]]
        for move in replay:
            self.chess_info.piece[move.to_pos.y][move.to_pos.x] = \
                self.chess_info.piece[move.from_pos.y][move.from_pos.x]
            self.chess_info.piece[move.from_pos.y][move.from_pos.x] = 0
            self.chess_info.is_red_go = not self.chess_info.is_red_go
            self.board_snapshots.append([row[:] for row in self.chess_info.piece])
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
        # 悔棋后回到实时对局（_reset_snapshots 会重建 board_snapshots），
        # 分步评分数组与实时快照不再对齐，清空后回退到 eval_history 曲线
        self.eval_by_step = []
        self.eval_step_gen += 1
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
        self._sync_eval_to_browse()


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
        self._sync_eval_to_browse()


    def _side_name(self, side):
        """对局头信息用的红/黑方名称（依据当前模式）。"""
        mode = self.game_mode
        if mode == 'pvp':
            return '红方' if side == 'red' else '黑方'
        if mode == 'mvm':
            return '电脑(红)' if side == 'red' else '电脑(黑)'
        if mode == 'pvm_red':
            return '玩家' if side == 'red' else '电脑'
        if mode == 'pvm_black':
            return '电脑' if side == 'red' else '玩家'
        return '红方' if side == 'red' else '黑方'

    def _result_token(self):
        w = getattr(self.chess_info, 'winner', None)
        if w == 'red':
            return '1-0'
        if w == 'black':
            return '0-1'
        if getattr(self.chess_info, 'draw_reason', '') or \
                self.chess_info.get_game_status() == 'draw':
            return '1/2-1/2'
        return '*'

    def _system_file_path(self, mode):
        """打开系统文件管理器对话框确认位置。

        返回选中的路径字符串；用户取消返回 ``None``；系统对话框不可用（如缺少
        tkinter）返回空字符串 ``''``，调用方据此回退到内置逻辑。
        """
        try:
            import tkinter as tk
            from tkinter import filedialog
        except Exception:
            return ''
        try:
            root = tk.Tk()
            root.withdraw()
            try:
                root.attributes('-topmost', True)
            except Exception:
                pass
            if mode == 'save':
                default_name = f'chess_{datetime.now().strftime("%Y%m%d_%H%M%S")}.pgn'
                path = filedialog.asksaveasfilename(
                    title='保存棋谱',
                    defaultextension='.pgn',
                    initialfile=default_name,
                    initialdir=self.save_dir,
                    filetypes=[('棋谱文件 (*.pgn)', '*.pgn'),
                               ('所有文件 (*.*)', '*.*')])
            else:
                path = filedialog.askopenfilename(
                    title='打开棋谱',
                    initialdir=self.save_dir,
                    filetypes=[('棋谱文件 (*.pgn)', '*.pgn'),
                               ('所有文件 (*.*)', '*.*')])
            root.destroy()
            return path or None
        except Exception as e:
            print('文件对话框异常:', e)
            try:
                root.destroy()
            except Exception:
                pass
            return None

    def _prepare_save(self):
        """构造保存所需数据：对局信息、起点局面、起点行棋方、头信息。

        起点行棋方由「第一步的起始子颜色」判定，避免受上一步/下一步浏览状态影响。
        """
        ci = self.chess_info
        hist = list(ci.move_history)
        start_board = (self.board_snapshots[0] if self.board_snapshots
                       else [row[:] for row in ci.piece])
        if hist:
            f0 = hist[0].from_pos
            start_red = start_board[f0.y][f0.x] >= 8
        else:
            start_red = True
        headers = {
            'Red': self._side_name('red'),
            'Black': self._side_name('black'),
            'Result': self._result_token(),
            'Mode': self.game_mode,
        }
        return ci, hist, start_board, start_red, headers

    def save_game(self):
        """保存当前对局为 PGN 棋谱：优先弹出系统保存对话框确认位置，
        无系统对话框的环境回退到默认目录自动命名。"""
        path = self._system_file_path('save')
        if path is None:
            self.show_toast('已取消保存')
            return
        if not path:
            self._save_game_auto()
            return
        self._save_game_to(path)

    def _save_game_to(self, path):
        """将棋谱写入指定路径。"""
        try:
            ci, hist, start_board, start_red, headers = self._prepare_save()
            pgn = pgn_lib.build_pgn(ci, hist, start_board, start_red, headers)

            parent = os.path.dirname(path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(pgn)
            self.show_toast('已保存棋谱')
        except Exception as e:
            self.show_toast('保存失败')
            print('保存失败:', e)

    def _save_game_auto(self):
        """无系统对话框时的回退：自动保存到默认目录，仅保留最近 20 个。"""
        try:
            os.makedirs(self.save_dir, exist_ok=True)
            ci, hist, start_board, start_red, headers = self._prepare_save()
            pgn = pgn_lib.build_pgn(ci, hist, start_board, start_red, headers)

            stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            path = os.path.join(self.save_dir, f'chess_{stamp}.pgn')
            with open(path, 'w', encoding='utf-8') as f:
                f.write(pgn)
            try:
                files = sorted(
                    [os.path.join(self.save_dir, fn) for fn in os.listdir(self.save_dir)
                     if fn.startswith('chess_') and fn.endswith('.pgn')],
                    key=os.path.getmtime, reverse=True)
                for old in files[20:]:
                    os.remove(old)
            except OSError:
                pass
            self.show_toast('已保存棋谱')
        except Exception as e:
            self.show_toast('保存失败')
            print('保存失败:', e)

    def load_game(self):
        """打开系统文件管理器选择要加载的 PGN 棋谱；无系统对话框则回退到内置浏览器。"""
        path = self._system_file_path('open')
        if path is None:
            return
        if not path:
            self._open_save_browser()
            return
        self._apply_pgn_data(path)


    def _open_save_browser(self):
        try:
            os.makedirs(self.save_dir, exist_ok=True)
            files = sorted([fn for fn in os.listdir(self.save_dir)
                            if fn.startswith('chess_') and fn.endswith('.pgn')],
                           reverse=True)
            entries = []
            for fn in files:
                full = os.path.join(self.save_dir, fn)
                try:
                    with open(full, 'r', encoding='utf-8') as f:
                        text = f.read()
                    parsed = pgn_lib.parse_pgn(text)
                    moves = len(parsed['moves'])
                    start_red = True
                    fen = parsed['headers'].get('FEN')
                    if fen:
                        _, start_red = pgn_lib.fen_to_board_array(fen)
                    red = parsed['headers'].get('Red') or ('红方' if start_red else '黑方')
                    black = parsed['headers'].get('Black') or ('黑方' if start_red else '红方')
                    entries.append({
                        'name': fn,
                        'path': full,
                        'saved_at': datetime.fromtimestamp(
                            os.path.getmtime(full)).strftime('%Y-%m-%d %H:%M'),
                        'moves': moves,
                        'is_red_go': start_red,
                        'game_mode': 'pgn',
                        'red': red,
                        'black': black,
                    })
                except Exception:
                    continue
            if not entries:
                self.show_toast('没有可加载的棋谱')
                return
            self.save_browser = {'entries': entries, 'rects': [], 'close_rect': None}
        except Exception as e:
            self.show_toast('读取棋谱失败')
            print('读取棋谱失败:', e)


    def _apply_pgn_data(self, path):
        """读取 PGN 棋谱文件并重放到棋盘。"""
        try:
            with open(path, 'r', encoding='utf-8') as f:
                text = f.read()
            self.load_pgn_into(text)
        except Exception as e:
            self.show_toast('加载失败')
            print('加载棋谱失败:', e)


    def load_pgn_into(self, text):
        """解析 PGN 文本并从初始局面重放全部着法，生成可浏览的棋谱。

        加载完成后停在起始局面（browse_index=0，即第一步/开局），可用
        「下一步」逐步复盘到终局，或用「上一步」回看；走到最新局面后再按
        「下一步」回到引擎实时对局。
        """
        try:
            parsed = pgn_lib.parse_pgn(text)
            headers = parsed['headers']
            move_strs = parsed['moves']
            ci = self.chess_info

            # 起点局面：含 FEN 头则据此复原，否则标准开局（红先）。
            # 注意：不少真实棋谱（如残局排局）只写 [FEN ...] 而无 [Setup "1"]，
            # 因此只要出现 FEN 头即视为起点局面，不强制 Setup 标记。
            if 'FEN' in headers:
                board, start_red = pgn_lib.fen_to_board_array(headers['FEN'])
                if board is None:
                    board = pgn_lib.standard_board()
                    start_red = True
            else:
                board = pgn_lib.standard_board()
                start_red = True

            ci.reset()
            ci.piece = [row[:] for row in board]
            ci.is_red_go = start_red
            # 以加载的起点局面作为本局悔棋基准，避免悔棋退回到标准开局
            # （「新建的局面」），对排局/残局自定义 FEN 尤为重要。
            ci.base_piece = [row[:] for row in ci.piece]
            ci.base_red_go = ci.is_red_go
            ci.move_history = []
            ci.status = 0
            ci.is_checked = False
            ci.winner = None
            ci.draw_reason = ''
            ci.select = Pos(-1, -1)
            ci.ret = []
            ci.position_history = {}

            # 从起点逐着重放（中文记谱 -> 坐标），并记录每一步快照
            snapshots = [[row[:] for row in ci.piece]]
            is_red = start_red
            applied = 0
            for i, s in enumerate(move_strs):
                turn_red = is_red
                coords = pgn_lib.chinese_to_move(ci.piece, turn_red, s)
                if coords is None:
                    self.show_toast(f'棋谱第 {i + 1} 步无法解析：{s}')
                    break
                fx, fy, tx, ty = coords
                pid = ci.piece[fy][fx]
                ci.move_history.append(Move(Pos(fx, fy), Pos(tx, ty)))
                ci.piece[ty][tx] = pid
                ci.piece[fy][fx] = 0
                is_red = not is_red
                snapshots.append([row[:] for row in ci.piece])
                applied += 1

            self.board_snapshots = snapshots
            self.browse_index = 0  # 加载后停在起始局面（第一步）
            self._pgn_start_red = start_red  # 供「浏览时行棋」分叉判定起始行棋方

            # 重放后行棋方应为「下一步轮到谁」，而非起点行棋方
            ci.is_red_go = is_red

            # 复位交互 / 引擎瞬时状态
            self.editing = False
            self.edit_piece = None
            self.edit_drag_pid = None
            self.edit_drag_pos = None
            self.edit_drag_moved = False
            self.is_ai_thinking = False
            self.hint_window = None
            self.save_browser = None
            self._clear_hint()
            ci.suggest_moves = []
            ci.suggest_move_labels = []
            ci.suggest_replies = []
            ci.suggest = None
            ci.is_machine = False
            ci.setting = self.settings

            # 重置当前方行棋计时
            self.turn_start_tick = time.time()
            self._last_red_go = ci.is_red_go
            self._turn_elapsed_frozen = 0.0



            # 恢复保存时的对局模式（含人机 / 双机），让「行棋」符合预期：
            # 轮到 AI 时自动接手，轮到玩家时等待手动走子。已终局的棋谱改为
            # 双人复盘，避免 AI 在已分胜负的局面上继续走子。
            result = headers.get('Result', '*')
            finished = result in ('1-0', '0-1', '1/2-1/2')
            mode = headers.get('Mode')
            if mode not in ('pvp', 'mvm', 'pvm_red', 'pvm_black'):
                mode = 'pvp'
            if finished:
                mode = 'pvp'
            self.set_game_mode(mode)

            self.chess_info.peace_round = 0
            self.chess_info.consecutive_check_red = 0
            self.chess_info.consecutive_check_black = 0
            self.chess_info.consecutive_attack_red = 0
            self.chess_info.consecutive_attack_black = 0
            self.chess_info.last_attacked_pos = None
            self.chess_info.last_attacked_type = 0
            self.chess_info.draw_offer = None
            self.chess_info.draw_offer_pending = None
            self.chess_info.draw_hint = ''
            self.chess_info.draw_offer_suppressed = False
            self.chess_info.attack_num_r = 0
            self.chess_info.attack_num_b = 0

            self.eval_history = []
            self.eval_by_step = []
            self.eval_score = None
            self.eval_gen += 1

            from ..game.rule import is_king_danger
            self.chess_info.is_checked = is_king_danger(
                self.chess_info.piece, self.chess_info.is_red_go)

            # 为整局棋谱预计算分步评分（与 board_snapshots 对齐），
            # 曲线随「下一步」增加、「上一步」减少；后台线程逐步填充。
            self.request_eval_batch()
            if applied == 0:
                self.show_toast('已加载棋谱（仅局面，无着法）')
            else:
                self.show_toast(f'已加载棋谱（{applied} 步，可点「下一步」复盘）')
        except Exception as e:
            self.show_toast('加载失败')
            print('加载棋谱失败:', e)


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
            # 终局结果改在对局状态卡片的终局横幅中展示，不再弹出浮窗提示
            res_text = self._result_info()[0] if self._result_info() else ''
            _ = res_text
        elif self.game_mode == 'mvm':
            self.start_ai_turn()

