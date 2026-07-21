class Pos:
    def __init__(self, x: int = -1, y: int = -1):
        self.x = x
        self.y = y

    def __eq__(self, other):
        if isinstance(other, Pos):
            return self.x == other.x and self.y == other.y
        return False

    def __hash__(self):
        return hash((self.x, self.y))

    def __repr__(self):
        return f"Pos({self.x}, {self.y})"

    def clone(self):
        return Pos(self.x, self.y)
