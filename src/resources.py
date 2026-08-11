"""运行时资源路径解析。

打包（PyInstaller --onefile）后，所有外部资源（图片、字体、引擎二进制、
.nnue 权重、棋谱）会被解压到临时目录 sys._MEIPASS 下。开发环境下则位于
项目根目录。本模块统一提供 resource_path() 让代码无论开发还是打包都能
正确找到资源。
"""

import os
import sys


def resource_path(relative_path: str) -> str:
    """将相对项目根目录的资源路径，解析为实际可访问的绝对路径。

    - 打包后（sys._MEIPASS 存在）：返回临时解压目录下的路径；
    - 开发时：返回以本仓库根目录（src 的上一级）为基准的路径。
    """
    if getattr(sys, '_MEIPASS', None):
        base = sys._MEIPASS
    else:
        # 本文件位于 <root>/src/resources.py，父目录即项目根目录
        base = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    return os.path.normpath(os.path.join(base, relative_path))
