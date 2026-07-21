from src.game.board import ChessInfo
from src.ai.pikafish import PikafishAI

board = ChessInfo()
board.reset()

print('Board state:')
for y in range(10):
    row = []
    for x in range(9):
        piece = board.piece[y][x]
        row.append(str(piece).rjust(2))
    print(f'  y={y}: {" ".join(row)}')

ai = PikafishAI()
ai.initialize()

fen = ai._board_to_fen(board)
print(f'Generated FEN: {fen}')

print('Testing UCI conversion (FEN rank == board y, see _uci_to_move):')
for uci in ['b2e2', 'e9e8', 'b9c7']:
    from_rank = uci[1]
    to_rank = uci[3]
    from_y = int(from_rank)
    to_y = int(to_rank)
    print(f'  UCI {uci}: from_rank={from_rank} -> from_y={from_y}, to_rank={to_rank} -> to_y={to_y}')

ai._send_command(f'position fen {fen}')
ai._send_command('go depth 3 movetime 1000')

import time
time.sleep(2)
line = ai._read_line()
while line:
    print(f'Engine: {line}')
    if 'bestmove' in line:
        break
    line = ai._read_line()
    time.sleep(0.1)
