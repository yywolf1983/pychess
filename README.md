# PyChess · 中国象棋

基于 **Pygame** 的中国象棋图形界面，内置 **Pikafish** 开源象棋引擎（UCI 风格）。
支持人机对弈、AI 支招（多候选着法分析）、模拟推演、悔棋 / 重做、音效与设置面板。

## 功能特性

- **图形棋盘**：9×10 标准中国象棋棋盘，棋子/走子高亮、选子提示。
- **人机对弈**：可选 AI 难度（`skill_level`）、搜索深度（`depth`）、思考时间（`thinking_time`）。
- **AI 支招**：一键分析当前局面，列出引擎给出的多条候选着法（红黑分色、首着暖橙强调），每条按窗口宽度自适应显示尽可能多的后续变化。
- **模拟推演**：在候选着法上展开多步模拟，观察引擎推演走向。
- **悔棋 / 重做**：支持对局回退与前进。
- **音效与音乐**：可在设置中开关背景音乐与落子音效。
- **设置面板**：难度、深度、候选数（`multi_pv`）、`contempt`、强制变化等。

## 目录结构

```
pychess/
├── main.py                 # 程序入口
├── requirements.txt        # Python 依赖
├── test_fen.py             # 棋盘 <-> FEN / 引擎联调测试脚本
├── config/
│   └── settings.json       # 运行配置（难度、深度、音效等）
├── engine/                 # Pikafish 引擎（按平台分目录）
│   ├── Windows/  Linux/  MacOS/  Android/
│   ├── pikafish            # 非 Windows 启动脚本 / 二进制
│   └── pikafish.nnue       # 神经网络权重模型
├── pikafish.nnue           # 根目录模型副本（供加载）
└── src/
    ├── ui/                 # 界面层（main_window 等）
    ├── game/               # 棋盘与规则（board 等）
    ├── ai/                 # 引擎封装（pikafish.py）
    ├── config/             # 设置加载
    ├── resources/          # 图片资源（棋子、棋盘等）
    └── utils/              # 工具函数
```

## 环境要求

- Python 3.8+
- [pygame](https://www.pygame.org/) `2.5.2`
- [Pillow](https://python-pillow.org/)（**推荐**；用于中文着法名渲染，缺失时自动降级为默认字体）

## 安装与运行

```bash
# 1. 安装依赖
pip install -r requirements.txt
# 中文着法名渲染建议同时安装：
pip install Pillow

# 2. 启动
python main.py
```

> 引擎按当前系统自动选择对应平台的二进制。Windows 下会从 `engine/Windows/`
> 中挑选合适的 AVX/AVX2/AVX-512 变体；其余平台使用 `engine/` 顶层或对应子目录的二进制。
> 请确保 `pikafish.nnue` 模型文件存在（根目录或 `engine/` 下），否则引擎无法加载权重。

## 使用说明

- **对弈**：点击棋子选择，再点击目标位置落子；轮到 AI 时自动思考。
- **支招**：点击「支招」按钮，底部面板显示引擎候选着法，点击任一候选可在棋盘上联动高亮；滚轮可滚动候选列表。
- **模拟**：在候选行上可展开「模拟」推演，观察后续变化。
- **设置**：通过侧栏设置面板调整难度、搜索深度、候选数、音效等；

## 配置说明（`config/settings.json`）

| 字段 | 说明 | 默认 |
| --- | --- | --- |
| `is_music_play` | 是否播放背景音乐 | `true` |
| `is_effect_play` | 是否播放落子音效 | `true` |
| `m_level` | 界面难度档位 | `3` |
| `depth` | 引擎搜索深度 | `10` |
| `skill_level` | 引擎强度（0–20，越高越强） | `20` |
| `multi_pv` | 支招候选着法数 | `1` |
| `contempt` | 局势倾向（正值偏进攻） | `20` |
| `force_variation` | 是否强制输出变化线 | `true` |
| `thinking_time` | 单步思考时限（秒） | `3` |

## 测试

```bash
python test_fen.py
```

该脚本会重置棋盘、打印棋盘状态、生成 FEN、并直接向引擎发送 `go` 命令验证联调。

## 许可证

本项目仅用于学习与交流。引擎相关二进制与模型文件版权归各自上游项目所有。
