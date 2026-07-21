from .pos import Pos


class Move:
    def __init__(self, from_pos: Pos = None, to_pos: Pos = None):
        self.from_pos = from_pos if from_pos else Pos()
        self.to_pos = to_pos if to_pos else Pos()

    def __eq__(self, other):
        if isinstance(other, Move):
            return self.from_pos == other.from_pos and self.to_pos == other.to_pos
        return False

    def __repr__(self):
        return f"Move({self.from_pos} -> {self.to_pos})"

    def is_valid(self):
        return self.from_pos.x >= 0 and self.to_pos.x >= 0
