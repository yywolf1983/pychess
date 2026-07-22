import subprocess
import os
import sys
import threading
import time
from typing import Optional, List
from ..game.board import ChessInfo, Setting
from ..game.move import Move
from ..game.pos import Pos
from ..game.rule import (
    BLACK_KING, BLACK_ADVISOR, BLACK_ELEPHANT, BLACK_KNIGHT, BLACK_ROOK, BLACK_CANNON, BLACK_PAWN,
    RED_KING, RED_ADVISOR, RED_ELEPHANT, RED_KNIGHT, RED_ROOK, RED_CANNON, RED_PAWN
)


def _make_executable(engine_path: str):
    """类 Unix 系统下确保引擎二进制具备可执行权限（仓库克隆后执行位可能丢失）。"""
    if sys.platform == 'win32':
        return
    try:
        mode = os.stat(engine_path).st_mode
        os.chmod(engine_path, mode | 0o111)
    except Exception:
        pass


class MoveWithScore:
    def __init__(self, move: Move = None, score: int = 0, reply_move: Move = None,
                 pv_uci: list = None):
        self.move = move if move else Move()
        self.score = score
        self.reply_move = reply_move
        self.pv_uci = pv_uci if pv_uci else []


class PikafishAI:
    def __init__(self):
        self.process = None
        self.reader = None
        self.writer = None
        self.initialized = False
        self.is_searching = False
        self.should_stop = False
        self.current_depth = 0
        self.threads = 0  # 当前引擎实际使用的线程数（按 CPU 核心自动分配）
        self.last_info_score = None  # 引擎实时分数（行棋方视角，供 UI 实时更新曲线）
        self.engine_supports_multi_pv = True  # pikafish 引擎支持 MultiPV（多路提示）
        self.lock = threading.Lock()
        
    # 跨实例缓存：先探测成功的引擎路径，避免每次初始化都重新探测
    _cached_engine_path = None

    def _get_engine_path(self):
        # 基于本模块文件定位引擎目录（相对路径，跨系统/跨安装位置均可用）
        base_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), '../../engine'))

        candidates = []
        if sys.platform == 'darwin':
            arm_path = os.path.join(base_dir, 'MacOS', 'pikafish-apple-silicon')
            if os.path.exists(arm_path):
                candidates.append(arm_path)
        elif sys.platform == 'linux':
            candidates = [
                os.path.join(base_dir, 'Linux', 'pikafish-avx512'),
                os.path.join(base_dir, 'Linux', 'pikafish-avx512icl'),
                os.path.join(base_dir, 'Linux', 'pikafish-avxvnni'),
                os.path.join(base_dir, 'Linux', 'pikafish-vnni512'),
                os.path.join(base_dir, 'Linux', 'pikafish-avx2'),
                os.path.join(base_dir, 'Linux', 'pikafish-bmi2'),
                os.path.join(base_dir, 'Linux', 'pikafish-sse41-popcnt')
            ]
        elif sys.platform == 'win32':
            # 注意：avx512 / avxvnni 等变体在部分机器上能通过 uci 握手，
            # 但真正开始搜索(go)时会崩溃，因此必须放到后面，由 _probe_engine
            # 通过实际搜索来筛选。优先尝试更通用的稳定变体。
            candidates = [
                os.path.join(base_dir, 'Windows', 'pikafish-avx2.exe'),
                os.path.join(base_dir, 'Windows', 'pikafish-bmi2.exe'),
                os.path.join(base_dir, 'Windows', 'pikafish-sse41-popcnt.exe'),
                os.path.join(base_dir, 'Windows', 'pikafish-avx512.exe'),
                os.path.join(base_dir, 'Windows', 'pikafish-avx512icl.exe'),
                os.path.join(base_dir, 'Windows', 'pikafish-avxvnni.exe'),
                os.path.join(base_dir, 'Windows', 'pikafish-vnni512.exe')
            ]

        # 优先复用已探测成功的引擎
        if PikafishAI._cached_engine_path and os.path.exists(PikafishAI._cached_engine_path):
            return PikafishAI._cached_engine_path

        # 逐个探测：只选在本机 CPU 上真正能启动并响应 uci 的引擎
        # （例如部分机器不支持 AVX512，对应 exe 会直接崩溃，必须跳过）
        for path in candidates:
            if os.path.exists(path) and self._probe_engine(path):
                PikafishAI._cached_engine_path = path
                return path

        fallback = os.path.join(base_dir, 'pikafish')
        if os.path.exists(fallback) and self._probe_engine(fallback):
            PikafishAI._cached_engine_path = fallback
            return fallback

        return None

    def _default_threads(self) -> int:
        """根据 CPU 核心数分配引擎线程数：预留部分算力给操作系统与界面线程，
        避免引擎占满所有核心导致界面卡顿。核心越多预留比例越小。"""
        cpu = os.cpu_count() or 1
        if cpu <= 2:
            return 1
        reserve = 2 if cpu <= 8 else max(2, cpu // 8)
        return max(1, cpu - reserve)

    def _probe_engine(self, engine_path: str) -> bool:
        """探测引擎是否真正可用：不仅握手 uci，还要实际跑一次搜索(go)。
        有些变体(如 avxvnni)能通过 uci 握手，但开始搜索时会崩溃，
        只有能返回 bestmove 且不崩溃的引擎才被认为是可用的。"""
        try:
            _make_executable(engine_path)
            proc = subprocess.Popen(
                [engine_path],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=os.path.dirname(engine_path),
            )
        except Exception:
            return False

        # 计算 NNUE 权重路径（搜索需要加载权重，否则同样可能崩溃）
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
        nnue_path = os.path.join(project_root, 'engine', 'pikafish.nnue')
        if not os.path.exists(nnue_path):
            nnue_path = os.path.join(project_root, 'pikafish.nnue')
        nnue_ok = os.path.exists(nnue_path)

        def send(s):
            try:
                proc.stdin.write(s + '\n')
                proc.stdin.flush()
            except Exception:
                return False
            return True

        try:
            if not send('uci'):
                return False
            start = time.time()
            while time.time() - start <= 5:
                line = proc.stdout.readline()
                if line.strip() == 'uciok':
                    break
                if not line:  # 进程已退出（崩溃）
                    return False
            else:
                return False

            if nnue_ok:
                # 统一为正斜杠，跨平台兼容 UCI 协议中的路径
                ep = os.path.abspath(nnue_path).replace('\\', '/')
                send(f'setoption name EvalFile value {ep}')
                send(f'setoption name Threads value {self._default_threads()}')
                send('setoption name Hash value 64')
            send('isready')
            start = time.time()
            while time.time() - start <= 8:
                line = proc.stdout.readline()
                if line.strip() == 'readyok':
                    break
                if not line:
                    return False

            # 真正发起一次短搜索，验证不会崩溃且能返回着法
            start_fen = ('rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/'
                         'P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1')
            send(f'position fen {start_fen}')
            send('go movetime 600')
            start = time.time()
            while time.time() - start <= 8:
                line = proc.stdout.readline()
                if not line:  # 管道关闭 = 搜索中崩溃
                    return False
                if line.strip().startswith('bestmove'):
                    return True
            return False
        except Exception:
            return False
        finally:
            try:
                proc.stdin.write('quit\n')
                proc.stdin.flush()
            except Exception:
                pass
            try:
                proc.kill()
            except Exception:
                pass
            try:
                proc.wait(timeout=2)
            except Exception:
                pass
    
    def initialize(self, engine_path: str = None):
        if engine_path is None:
            engine_path = self._get_engine_path()
            if engine_path is None:
                return
        
        try:
            _make_executable(engine_path)
            self.process = subprocess.Popen(
                [engine_path],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=os.path.dirname(engine_path)
            )
            
            self.reader = self.process.stdout
            self.writer = self.process.stdin
            
            self._send_command('uci')
            
            uci_ok_received = False
            start_time = time.time()
            while not uci_ok_received and time.time() - start_time <= 10:
                line = self._read_line()
                if line and line == 'uciok':
                    uci_ok_received = True
                    self.initialized = True
                    break
                time.sleep(0.05)
            
            if self.initialized:
                # 获取项目根目录
                project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
                nnue_path = os.path.join(project_root, 'engine', 'pikafish.nnue')
                if not os.path.exists(nnue_path):
                    nnue_path = os.path.join(project_root, 'pikafish.nnue')
                if os.path.exists(nnue_path):
                    nnue_path = os.path.abspath(nnue_path).replace('\\', '/')
                    self._send_command(f'setoption name EvalFile value {nnue_path}')
                # 引擎资源类参数（线程/哈希内存）；不属于设置里的 AI 强度参数，
                # 真正的棋力/Contempt/MultiPV 等每次搜索前会按设置重新下发。
                # 线程数按 CPU 核心数自动分配，预留部分算力给系统与界面。
                threads = self._default_threads()
                self.threads = threads
                self._send_command(f'setoption name Threads value {threads}')
                self._send_command('setoption name Hash value 128')
                self._send_command('isready')
                
                ready_ok_received = False
                start_time = time.time()
                while not ready_ok_received and time.time() - start_time <= 10:
                    line = self._read_line()
                    if line and line == 'readyok':
                        ready_ok_received = True
                        break
                    time.sleep(0.05)
            
        except Exception as e:
            print(f"PikafishAI初始化失败: {e}")
            self.close()
    
    def _send_command(self, command: str):
        if self.writer:
            try:
                self.writer.write(command + '\n')
                self.writer.flush()
            except Exception:
                pass
    
    def _read_line(self) -> Optional[str]:
        if self.reader:
            try:
                return self.reader.readline().strip()
            except Exception:
                return None

    def _stop_and_drain(self):
        """中断搜索：让引擎停止并排空其因 stop 产生的残留 bestmove 行，避免污染下次搜索。"""
        self._send_command('stop')
        for _ in range(40):
            line = self._read_line()
            if not line or line.startswith('bestmove'):
                break
        return None
    
    def get_best_move(self, chess_info: ChessInfo, settings=None) -> Move:
        result = self.get_best_move_with_score(chess_info, settings)
        return result.move
    
    def get_best_move_with_score(self, chess_info: ChessInfo, settings=None) -> MoveWithScore:
        if not self.initialized:
            self.initialize()
            if not self.initialized:
                return MoveWithScore(self._get_default_move(chess_info), 0)

        # 第一次搜索
        result = self._search_once(chess_info, settings)
        if result.move.is_valid():
            return result

        # 若引擎在搜索中崩溃(self.initialized 会被 _search_once 置 False)，
        # 清空缓存的（坏的）引擎路径，重新探测可用引擎并重试一次。
        if not self.initialized:
            print('引擎搜索异常，尝试重新探测可用引擎...')
            self.close()
            PikafishAI._cached_engine_path = None
            self.initialize()
            if self.initialized:
                result = self._search_once(chess_info, settings)
                if result.move.is_valid():
                    return result

        return MoveWithScore(self._get_default_move(chess_info), 0)

    def _search_once(self, chess_info: ChessInfo, settings=None) -> MoveWithScore:
        """在已初始化且持有 self.lock 的前提下执行一次搜索。
        若引擎进程在搜索中崩溃，会将 self.initialized 置为 False 以便上层重试。"""
        with self.lock:
            self.should_stop = True
            if self.is_searching:
                self._send_command('stop')
                time.sleep(0.1)

            self.should_stop = False
            self.is_searching = True
            self.current_depth = 0

            fen = self._board_to_fen(chess_info)
            self._send_command(f'position fen {fen}')

            if settings:
                depth = settings.depth
                time_ms = settings.thinking_time * 1000
                skill_level = settings.skill_level
                contempt = settings.contempt
                multi_pv = settings.multi_pv
                force_variation = settings.force_variation
            elif chess_info.setting:
                depth = chess_info.setting.depth
                time_ms = chess_info.setting.thinking_time * 1000
                skill_level = chess_info.setting.skill_level
                contempt = chess_info.setting.contempt
                multi_pv = chess_info.setting.multi_pv
                force_variation = chess_info.setting.force_variation
            else:
                # 兜底：无任何设置对象时，从 Setting 默认值取（与设置文件同源，避免硬编码）
                d = Setting()
                depth = d.depth
                time_ms = d.thinking_time * 1000
                skill_level = d.skill_level
                contempt = d.contempt
                multi_pv = d.multi_pv
                force_variation = d.force_variation

            self._send_command(f'setoption name Skill Level value {skill_level}')
            self._send_command(f'setoption name Contempt value {contempt}')
            self._send_command(f'setoption name MultiPV value {multi_pv}')

            if force_variation:
                # MultiPV 至少 2 路，才能取出与最优着法不同的变着（尊重设置里的 multi_pv）
                self._send_command(f'setoption name MultiPV value {max(multi_pv, 2)}')

            # 以“思考时间”为主控：深度按用户设置上限（depth）作为兜底，movetime 控制实际思考时长；
            # 当设置深度较高（如 120）时时间先到，引擎会思考满设定时长。
            go_cmd = f'go depth {depth} movetime {time_ms}'
            print(f'[GO] {go_cmd}')
            self._send_command(go_cmd)

            best_move = None
            score = 0
            possible_moves = []

            max_search_time = time_ms + 5000
            start_time = time.time()

            timeout_thread = threading.Thread(target=self._timeout_check, args=(max_search_time,))
            timeout_thread.daemon = True
            timeout_thread.start()

            engine_died = False
            try:
                while not self.should_stop and time.time() - start_time < max_search_time / 1000:
                    line = self._read_line()
                    if not line:
                        # 管道无数据：判断引擎进程是否已退出（崩溃）
                        if self.process is not None and self.process.poll() is not None:
                            engine_died = True
                            print('引擎进程在搜索中退出（崩溃）')
                            break
                        time.sleep(0.01)
                        continue

                    if line.startswith('info'):
                        parts = line.split()
                        info_multi_pv = 1

                        for i in range(len(parts)):
                            if parts[i] == 'multipv' and i + 1 < len(parts):
                                try:
                                    info_multi_pv = int(parts[i + 1])
                                except:
                                    pass
                                break

                        for i in range(len(parts)):
                            if parts[i] == 'depth' and i + 1 < len(parts):
                                try:
                                    new_depth = int(parts[i + 1])
                                    if new_depth > self.current_depth:
                                        self.current_depth = new_depth
                                except:
                                    pass

                            elif info_multi_pv == 1 and parts[i] == 'score' and i + 2 < len(parts):
                                if parts[i + 1] == 'cp':
                                    try:
                                        score = int(parts[i + 2])
                                    except:
                                        pass
                                elif parts[i + 1] == 'mate':
                                    try:
                                        mate_in = int(parts[i + 2])
                                        if mate_in > 0:
                                            score = 1000 - mate_in * 10
                                        else:
                                            score = -1000 + mate_in * 10
                                    except:
                                        pass
                                self.last_info_score = score  # 实时分数（行棋方视角）

                            elif info_multi_pv == 1 and parts[i] == 'pv' and i + 1 < len(parts):
                                move_str = parts[i + 1]
                                if best_move is None:
                                    best_move = move_str

                            elif parts[i] == 'pv' and i + 1 < len(parts):
                                if chess_info.force_variation:
                                    move_str = parts[i + 1]
                                    if move_str not in possible_moves:
                                        possible_moves.append(move_str)

                    elif line.startswith('bestmove'):
                        parts = line.split()
                        if len(parts) > 1:
                            best_move = parts[1]
                        break

            except Exception as e:
                print(f"读取AI响应失败: {e}")

            finally:
                if self.should_stop:
                    try:
                        self._stop_and_drain()
                    except Exception:
                        pass
                self.is_searching = False
                if engine_died:
                    self.initialized = False
                    PikafishAI._cached_engine_path = None

            if chess_info.force_variation and possible_moves and best_move:
                alternatives = [m for m in possible_moves if m != best_move]
                if alternatives:
                    import random
                    best_move = random.choice(alternatives)

            if best_move:
                print(f"Raw UCI: {best_move}")
                move = self._uci_to_move(best_move)
                return MoveWithScore(move, score)

        return MoveWithScore(self._get_default_move(chess_info), 0)
    
    def get_top_moves(self, chess_info: ChessInfo, settings=None, top_n: int = 3):
        """返回当前局面下 top_n 个最佳着法（多路提示），分数均为行棋方视角。"""
        if not self.initialized:
            self.initialize()
            if not self.initialized:
                return []
        top_n = max(1, min(top_n, 20))
        with self.lock:
            self.should_stop = True
            if self.is_searching:
                self._send_command('stop')
                time.sleep(0.1)
            self.should_stop = False
            self.is_searching = True
            self.current_depth = 0

            fen = self._board_to_fen(chess_info)
            self._send_command(f'position fen {fen}')

            if settings:
                depth = settings.depth
                time_ms = settings.thinking_time * 1000
                skill_level = settings.skill_level
                contempt = settings.contempt
                force_variation = settings.force_variation
            else:
                # 兜底：无任何设置对象时，从 Setting 默认值取（与设置文件同源，避免硬编码）
                d = Setting()
                depth = d.depth
                time_ms = d.thinking_time * 1000
                skill_level = d.skill_level
                contempt = d.contempt
                force_variation = d.force_variation

            self._send_command(f'setoption name Skill Level value {skill_level}')
            self._send_command(f'setoption name Contempt value {contempt}')
            multipv_value = top_n
            if force_variation:
                # 强制变着：至少开 2 路以取得变化着法
                multipv_value = max(top_n, 2)
            self._send_command(f'setoption name MultiPV value {multipv_value}')
            # 以“思考时间”为主控：深度按用户设置上限（depth）作为兜底，movetime 控制实际思考时长
            go_cmd = f'go depth {depth} movetime {time_ms}'
            print(f'[GO] {go_cmd}')
            self._send_command(go_cmd)

            candidates = {}  # multipv -> (move_uci, score)
            max_search_time = time_ms + 5000
            start_time = time.time()
            timeout_thread = threading.Thread(target=self._timeout_check, args=(max_search_time,))
            timeout_thread.daemon = True
            timeout_thread.start()

            try:
                while not self.should_stop and time.time() - start_time < max_search_time / 1000:
                    line = self._read_line()
                    if not line:
                        time.sleep(0.01)
                        continue
                    if line.startswith('info'):
                        parts = line.split()
                        mp = 1
                        for i in range(len(parts)):
                            if parts[i] == 'multipv' and i + 1 < len(parts):
                                try:
                                    mp = int(parts[i + 1])
                                except Exception:
                                    pass
                                break
                        if mp > multipv_value:
                            continue
                        sc = None
                        pv_list = None
                        for i in range(len(parts)):
                            if parts[i] == 'depth' and i + 1 < len(parts):
                                try:
                                    nd = int(parts[i + 1])
                                    if nd > self.current_depth:
                                        self.current_depth = nd
                                except Exception:
                                    pass
                            elif parts[i] == 'score' and i + 2 < len(parts):
                                if parts[i + 1] == 'cp':
                                    try:
                                        sc = int(parts[i + 2])
                                    except Exception:
                                        pass
                                elif parts[i + 1] == 'mate':
                                    try:
                                        mate_in = int(parts[i + 2])
                                        sc = 1000 - mate_in * 10 if mate_in > 0 else -1000 + mate_in * 10
                                    except Exception:
                                        pass
                            elif parts[i] == 'pv' and i + 1 < len(parts):
                                if pv_list is None:
                                    pv_list = parts[i + 1:]
                        if pv_list is not None and sc is not None and len(pv_list) >= 1:
                            candidates[mp] = (pv_list, sc)
                    elif line.startswith('bestmove'):
                        break
            except Exception as e:
                print(f"读取多路着法失败: {e}")
            finally:
                if self.should_stop:
                    try:
                        self._stop_and_drain()
                    except Exception:
                        pass
                self.is_searching = False

            results = []
            for mp in sorted(candidates):
                pv_list, sc = candidates[mp]
                try:
                    mv = self._uci_to_move(pv_list[0])
                except Exception:
                    continue
                reply = None
                if len(pv_list) >= 2:
                    try:
                        reply = self._uci_to_move(pv_list[1])
                    except Exception:
                        reply = None
                results.append(MoveWithScore(mv, sc, reply_move=reply, pv_uci=pv_list))
            results = results[:top_n]
            if force_variation and len(results) >= 2:
                # 强制变着：把引擎最优着法移到末尾，优先展示变化着法
                results = results[1:] + [results[0]]
            return results

    def _timeout_check(self, max_time_ms: int):
        time.sleep(max_time_ms / 1000)
        if self.is_searching:
            self._send_command('stop')
    
    def _get_default_move(self, chess_info: ChessInfo) -> Move:
        from ..game.rule import possible_moves, is_red
        
        for y in range(10):
            for x in range(9):
                piece = chess_info.piece[y][x]
                if piece == 0:
                    continue
                
                piece_is_red = is_red(piece)
                if piece_is_red != chess_info.is_red_go:
                    continue
                
                moves = possible_moves(chess_info.piece, x, y, piece)
                if moves:
                    return Move(Pos(x, y), moves[0])
        
        return Move()
    
    def _board_to_fen(self, chess_info: ChessInfo) -> str:
        fen = []
        
        for y in range(9, -1, -1):
            empty_count = 0
            row = []
            for x in range(9):
                piece = chess_info.piece[y][x]
                if piece == 0:
                    empty_count += 1
                else:
                    if empty_count > 0:
                        row.append(str(empty_count))
                        empty_count = 0
                    row.append(self._piece_to_fen(piece))
            if empty_count > 0:
                row.append(str(empty_count))
            fen.append(''.join(row))
        
        fen_str = '/'.join(fen)
        # 与 Pikafish 引擎约定一致：红方（大写）先行，行棋方红=w、黑=b。
        turn = 'w' if chess_info.is_red_go else 'b'
        
        return f'{fen_str} {turn} - - 0 1'
    
    def _piece_to_fen(self, piece: int) -> str:
        # 与引擎(及 Android)约定一致：红方=大写，黑方=小写；
        # 行棋方映射: is_red_go -> 'w', else -> 'b'（'w' 代表红方先行）。
        mapping = {
            BLACK_KING: 'k',
            BLACK_ADVISOR: 'a',
            BLACK_ELEPHANT: 'b',
            BLACK_KNIGHT: 'n',
            BLACK_ROOK: 'r',
            BLACK_CANNON: 'c',
            BLACK_PAWN: 'p',
            RED_KING: 'K',
            RED_ADVISOR: 'A',
            RED_ELEPHANT: 'B',
            RED_KNIGHT: 'N',
            RED_ROOK: 'R',
            RED_CANNON: 'C',
            RED_PAWN: 'P'
        }
        return mapping.get(piece, ' ')
    
    def _uci_to_move(self, uci: str) -> Move:
        if not uci or len(uci) < 4:
            return Move()
        
        try:
            import re
            
            match = re.match(r'([a-i])(\d{1,2})([a-i])(\d{1,2})', uci)
            if not match:
                return Move()
            
            from_file = match.group(1)
            from_rank = int(match.group(2))
            to_file = match.group(3)
            to_rank = int(match.group(4))
            
            from_x = ord(from_file) - ord('a')
            from_y = from_rank
            
            to_x = ord(to_file) - ord('a')
            to_y = to_rank
            
            if (0 <= from_x < 9 and 0 <= from_y < 10 and
                    0 <= to_x < 9 and 0 <= to_y < 10):
                return Move(Pos(from_x, from_y), Pos(to_x, to_y))
        except:
            pass
        
        return Move()
    
    def is_initialized(self) -> bool:
        return self.initialized
    
    def interrupt(self):
        self.should_stop = True
        if self.is_searching:
            self._send_command('stop')
    
    def close(self):
        self.interrupt()
        if self.process:
            try:
                self._send_command('quit')
                self.process.wait(timeout=3)
            except:
                self.process.kill()
            self.process = None
        self.reader = None
        self.writer = None
        self.initialized = False
