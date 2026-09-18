"""跨平台一键构建脚本（PyInstaller --onefile）。

与直接 `pyinstaller main.py` 不同，本脚本把全部外部资源通过
`--add-data` 显式传入，避免 PyInstaller 重新生成默认 spec 而漏掉资源。

用法：
    pip install pyinstaller
    python build.py
构建产物位于 dist/main（或 dist/main.exe）。
"""

import os
import sys

import PyInstaller.__main__

ROOT = os.path.dirname(os.path.abspath(__file__))

# (源路径, 打包内相对路径)
DATAS = [
    ('src/resources', 'src/resources'),   # 棋子/棋盘/背景图 + fonts/cjk.ttf
    ('src/models', 'src/models'),         # 识别 onnx 模型
    ('config', 'config'),                 # settings.json + 手写体字体
    ('engine', 'engine'),                 # 各平台 Pikafish 引擎 + 引擎自带 nnue
    ('pikafish.nnue', '.'),               # 根目录权重副本（代码回退用）
    ('1七星聚会.pgn', '.'),               # 内置棋谱
    ('logo.png', '.'),                    # 程序 logo
]

# 启动前校验资源是否存在，缺失则明确报错而不是静默打包
missing = [src for src, _ in DATAS if not os.path.exists(os.path.join(ROOT, src))]
if missing:
    print('[构建中止] 以下资源不存在：')
    for m in missing:
        print('  -', m)
    sys.exit(1)

args = [
    'main.py',
    '--onefile',
    '--windowed',
    '--icon=logo.ico',
    '--name=main',
    # 不要对引擎二进制做 UPX 压缩，避免损坏导致无法启动
    '--upx-exclude=pikafish*',
    '--hidden-import=onnxruntime',
    '--hidden-import=numpy',
    '--hidden-import=PIL',
]

for src, dst in DATAS:
    args.append('--add-data=%s%s%s' % (src, os.pathsep, dst))

print('[构建] 资源清单：')
for src, dst in DATAS:
    print('  +', src, '->', dst)
print()

PyInstaller.__main__.run(args)
