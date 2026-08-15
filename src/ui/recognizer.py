"""棋局图片识别：移植自 Android ChessRecognitionService 的双模型流水线。

流水线：
  1) pose 模型 (4_v6-0301.onnx, SimCC) 检测棋盘 4 个角点 (A0 左上 / A8 右上 / J0 左下 / J8 右下)
  2) 透视变换将倾斜棋盘拉伸为标准俯视图 (450x500, padding 50)
  3) layout 模型 (nano_v3-0319.onnx) 对 10x9 共 90 格做 16 分类识别棋子
  4) 类别映射为 ChessInfo 棋子 ID，并按 Android 逻辑做方向自动校正

依赖：numpy / Pillow(已随 pygame 安装) / onnxruntime

注：刻意不依赖 opencv-python，因其自带的 SDL2 与 pygame 在 macOS 上冲突会崩溃。
"""

import os
import numpy as np
from PIL import Image
import onnxruntime as ort

# 模型文件随项目打包：开发时位于 <root>/src/models，
# 打包后（PyInstaller --onefile）解压到 sys._MEIPASS/models，
# 由 resources.resource_path 统一解析。
try:
    from ..resources import resource_path
except ImportError:  # 直接运行本模块时
    from src.resources import resource_path

_POSE_MODEL = resource_path(os.path.join('src', 'models', '4_v6-0301.onnx'))
_LAYOUT_MODEL = resource_path(os.path.join('src', 'models', 'nano_v3-0319.onnx'))

# 与 Android 端保持一致
POSE_INPUT_SIZE = 256
CLS_INPUT_W = 280
CLS_INPUT_H = 315
BOARD_ROWS = 10
BOARD_COLS = 9
NUM_CLASSES = 16
WARP_W = 450
WARP_H = 500
WARP_PADDING = 50

# 模型输出 -> ChessInfo 棋子 ID（0=空）。与 Android PIECE_MAP 完全一致。
# '.'=0 空, 'x'=1 占位/其他, 2-8=红 KABNRCP, 9-15=黑 kabnrcp
_CLASS_INDEX_MAP = [".", "x", "K", "A", "B", "N", "R", "C", "P",
                    "k", "a", "b", "n", "r", "c", "p"]
_PIECE_MAP = {
    "K": 8, "A": 9, "B": 10, "N": 11, "R": 12, "C": 13, "P": 14,
    "k": 1, "a": 2, "b": 3, "n": 4, "r": 5, "c": 6, "p": 7,
}
# 每种棋子的合法最大数量（用于识别后校正）
_MAX_COUNT = {1: 1, 8: 1, 2: 2, 3: 2, 4: 2, 5: 2, 6: 2, 7: 5,
              9: 2, 10: 2, 11: 2, 12: 2, 13: 2, 14: 5}

# ImageNet 归一化参数
_MEAN = np.array([123.675, 116.28, 103.53], dtype=np.float32)
_STD = np.array([58.395, 57.12, 57.375], dtype=np.float32)


def _nchw_input(rgb_img: np.ndarray, w: int, h: int) -> np.ndarray:
    """与 Android prepareNCHWInput 一致：Resize + ImageNet 归一化 -> NCHW。

    rgb_img: HxWx3 的 uint8 RGB numpy 数组（Pillow 约定，非 cv2 的 BGR）。
    """
    pil = Image.fromarray(rgb_img).resize((w, h), Image.BILINEAR)
    rgb = np.asarray(pil, dtype=np.float32)
    # 像素 [0,255] -> (x - mean) / std
    norm = (rgb - _MEAN) / _STD
    # HWC -> NCHW
    nchw = np.transpose(norm, (2, 0, 1))[np.newaxis, ...]
    return nchw.astype(np.float32)


def _decode_simcc(out_x: np.ndarray, out_y: np.ndarray,
                  orig_w: int, orig_h: int) -> np.ndarray:
    """SimCC 解码：对 4 个关键点分别在 x/y 通道 argmax，归一化到 [0,1] 后映射回原图坐标。"""
    # out_x / out_y: shape [1, 4, 512]
    kx = out_x[0]            # [4, 512]
    ky = out_y[0]
    n = kx.shape[0]          # 4
    pts = np.zeros((n, 2), dtype=np.float32)
    for k in range(n):
        mx = int(np.argmax(kx[k]))
        my = int(np.argmax(ky[k]))
        pts[k, 0] = (mx / kx.shape[1]) * orig_w
        pts[k, 1] = (my / ky.shape[1]) * orig_h
    return pts


def _warp(rgb_img: np.ndarray, kp: np.ndarray) -> np.ndarray:
    """透视变换：4 角点映射到 450x500 标准棋盘（padding 50）。

    rgb_img: HxWx3 uint8 RGB 数组。返回同样布局的 warped 数组。
    """
    ax0, ay0 = kp[0]   # 左上
    ax8, ay8 = kp[1]   # 右上
    jx0, jy0 = kp[2]   # 左下
    jx8, jy8 = kp[3]   # 右下
    p = WARP_PADDING
    # 前向映射 src(角点) -> dst(标准棋盘角点)
    src_pts = np.array([[ax0, ay0], [ax8, ay8], [jx0, jy0], [jx8, jy8]],
                       dtype=np.float64)
    dst_pts = np.array([[p, p],
                        [WARP_W - p, p],
                        [p, WARP_H - p],
                        [WARP_W - p, WARP_H - p]], dtype=np.float64)
    # 求解前向 3x3 透视矩阵 H：dst = H * src
    H = _solve_homography(src_pts, dst_pts)
    # Pillow 的 PERSPECTIVE 需要反向矩阵(将输出坐标映射回输入)，故取逆
    H_inv = np.linalg.inv(H)
    # 归一化使 H_inv[2,2]=1
    H_inv = H_inv / H_inv[2, 2]
    data = (
        H_inv[0, 0], H_inv[0, 1], H_inv[0, 2],
        H_inv[1, 0], H_inv[1, 1], H_inv[1, 2],
        H_inv[2, 0], H_inv[2, 1],
    )
    pil = Image.fromarray(rgb_img)
    warped = pil.transform((WARP_W, WARP_H), Image.PERSPECTIVE, data,
                           resample=Image.BILINEAR)
    return np.asarray(warped, dtype=np.uint8)


def _solve_homography(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    """解 src->dst 的 3x3 透视矩阵（src/dst 为 4x2 同序点）。"""
    A = np.zeros((8, 8), dtype=np.float64)
    b = np.zeros((8, 1), dtype=np.float64)
    for i in range(4):
        xs, ys = src[i]
        xd, yd = dst[i]
        A[2 * i] = [xs, ys, 1, 0, 0, 0, -xs * xd, -ys * xd]
        A[2 * i + 1] = [0, 0, 0, xs, ys, 1, -xs * yd, -ys * yd]
        b[2 * i] = xd
        b[2 * i + 1] = yd
    h, *_ = np.linalg.lstsq(A, b, rcond=None)
    h = h.reshape(8)
    H = np.array([
        [h[0], h[1], h[2]],
        [h[3], h[4], h[5]],
        [h[6], h[7], 1.0],
    ], dtype=np.float64)
    return H


def _detect_orientation(board: np.ndarray) -> bool:
    """返回 True 表示方向反了需要翻转（与 Android detectBoardOrientation 一致）。"""
    red_king_y = black_king_y = -1
    for y in range(10):
        for x in range(9):
            p = board[y][x]
            if p == 8:
                red_king_y = y
            elif p == 1:
                black_king_y = y
    red_top = red_king_y >= 5 and red_king_y <= 9
    black_bottom = black_king_y >= 0 and black_king_y <= 4
    if red_king_y >= 0 and black_king_y >= 0:
        return red_top and black_bottom
    if red_king_y >= 0:
        return red_top
    if black_king_y >= 0:
        return black_bottom
    top_red = bottom_red = top_black = bottom_black = 0
    for y in range(10):
        for x in range(9):
            p = board[y][x]
            if 8 <= p <= 14:
                if y <= 4:
                    bottom_red += 1
                else:
                    top_red += 1
            elif 1 <= p <= 7:
                if y <= 4:
                    bottom_black += 1
                else:
                    top_black += 1
    return (top_red > bottom_red) and (bottom_black > top_black) and \
        (top_red + bottom_black > bottom_red + top_black + 2)


def _flip_180(board: np.ndarray) -> None:
    """180°旋转（同时修正 Y 轴与 X 轴镜像）：(x,y)->(8-x,9-y)。"""
    temp = np.zeros((10, 9), dtype=board.dtype)
    for y in range(10):
        for x in range(9):
            temp[9 - y][8 - x] = board[y][x]
    board[:] = temp


def _validate_counts(board: np.ndarray, probs: np.ndarray) -> None:
    """按最大数量约束裁剪多余棋子（保留概率最高的），与 Android 逻辑一致。"""
    for pid, maxc in _MAX_COUNT.items():
        cand = []
        for y in range(10):
            for x in range(9):
                if board[y][x] == pid:
                    model_y = 9 - y
                    if 0 <= model_y < 10 and 0 <= x < 9:
                        prob = probs[model_y][x][pid_to_class(pid)]
                    else:
                        prob = 0.0
                    cand.append((prob, y, x))
        if len(cand) > maxc:
            cand.sort(reverse=True)
            for _, y, x in cand[maxc:]:
                board[y][x] = 0


def pid_to_class(pid: int) -> int:
    for c, ch in enumerate(_CLASS_INDEX_MAP):
        if ch in _PIECE_MAP and _PIECE_MAP[ch] == pid:
            return c
    return 0


class ChessRecognizer:
    def __init__(self):
        self.pose = ort.InferenceSession(_POSE_MODEL, providers=['CPUExecutionProvider'])
        self.cls = ort.InferenceSession(_LAYOUT_MODEL, providers=['CPUExecutionProvider'])
        self._pose_in = self.pose.get_inputs()[0].name
        self._cls_in = self.cls.get_inputs()[0].name
        self._pose_outs = [o.name for o in self.pose.get_outputs()]
        self._cls_out = self.cls.get_outputs()[0].name

    def recognize(self, image_path: str) -> np.ndarray:
        """识别图片，返回 10x9 的 ChessInfo 棋子 ID 矩阵（红 y=0 底部约定）。"""
        try:
            pil = Image.open(image_path).convert('RGB')
        except Exception as e:
            raise ValueError('无法读取图片: ' + image_path + ' (' + str(e) + ')')
        img = np.asarray(pil, dtype=np.uint8)  # HxWx3 RGB
        h, w = img.shape[:2]

        # Step 1: 角点检测
        pose_in = _nchw_input(img, POSE_INPUT_SIZE, POSE_INPUT_SIZE)
        out = self.pose.run(self._pose_outs, {self._pose_in: pose_in})
        ox = oy = None
        for name, val in zip(self._pose_outs, out):
            if 'x' in name:
                ox = val
            elif 'y' in name:
                oy = val
        if ox is None or oy is None:
            ox, oy = out[0], out[1]
        kp = _decode_simcc(ox, oy, w, h)

        # Step 2: 透视变换
        warped = _warp(img, kp)

        # Step 3: 分类
        cls_in = _nchw_input(warped, CLS_INPUT_W, CLS_INPUT_H)
        out = self.cls.run([self._cls_out], {self._cls_in: cls_in})[0]  # 形状可能为 [1,90,16] / [1,C,R,Col] 等
        out = np.asarray(out, dtype=np.float32)

        # 解析为 10x9 类别索引（argmax over 16）
        cls_grid = np.zeros((BOARD_ROWS, BOARD_COLS), dtype=int)
        probs = np.zeros((BOARD_ROWS, BOARD_COLS, NUM_CLASSES), dtype=np.float32)
        if out.ndim == 3 and out.shape[0] == 1 and out.shape[1] == BOARD_ROWS * BOARD_COLS:
            # [1, 90, 16]，row-major: p = y*9 + x
            flat = out[0]  # [90, 16]
            for p in range(BOARD_ROWS * BOARD_COLS):
                y, x = divmod(p, BOARD_COLS)
                cls_grid[y][x] = int(np.argmax(flat[p]))
                probs[y][x] = flat[p]
        elif out.ndim == 4 and out.shape[1] == NUM_CLASSES:
            for y in range(BOARD_ROWS):
                for x in range(BOARD_COLS):
                    cls_grid[y][x] = int(np.argmax(out[0, :, y, x]))
                    probs[y][x] = out[0, :, y, x]
        elif out.ndim == 4:
            for y in range(BOARD_ROWS):
                for x in range(BOARD_COLS):
                    cls_grid[y][x] = int(np.argmax(out[0, y, x, :]))
                    probs[y][x] = out[0, y, x, :]
        else:
            # 兜底
            flat = out.reshape(-1, NUM_CLASSES)
            for y in range(BOARD_ROWS):
                for x in range(BOARD_COLS):
                    cls_grid[y][x] = int(np.argmax(flat[y * BOARD_COLS + x]))

        # Step 4: 类别 -> 棋子 ID，并做 targetY = 9 - y 映射
        board = np.zeros((10, 9), dtype=int)
        for y in range(BOARD_ROWS):
            for x in range(BOARD_COLS):
                ch = _CLASS_INDEX_MAP[cls_grid[y][x]]
                pid = _PIECE_MAP.get(ch, 0)
                ty = 9 - y
                if 0 <= ty < 10:
                    board[ty][x] = pid

        # 数量校正
        _validate_counts(board, probs)

        # 方向自动校正
        if _detect_orientation(board):
            _flip_180(board)

        return board
