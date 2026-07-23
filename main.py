import sys
import os
import io
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ['SDL_IME_SHOW_UI'] = '0'
os.environ['SDL_TEXTINPUT_ENABLED'] = '0'

from src.ui.main_window import MainWindow


def main():
    app = MainWindow()
    app.run()


if __name__ == '__main__':
    main()
