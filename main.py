import sys
import os
import io
import tempfile
import logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ['SDL_IME_SHOW_UI'] = '0'
os.environ['SDL_TEXTINPUT_ENABLED'] = '0'

# 统一日志：WARNING 及以上输出到 stderr（等价于原先的异常 print），
# 调试期可设置环境变量 PYCHESS_LOG=DEBUG 开启引擎/走子流程的 debug 日志。
_log_level = logging.DEBUG if os.environ.get('PYCHESS_LOG', '').upper() == 'DEBUG' else logging.WARNING
logging.basicConfig(
    level=_log_level,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    stream=sys.stderr,
)

from src.ui.main_window import MainWindow


def main():
    app = MainWindow()
    app.run()


if __name__ == '__main__':
    main()
