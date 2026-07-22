import os
import json
import pygame
import threading
import time
import queue
from datetime import datetime
from typing import Optional
from ..game.board import ChessInfo, Setting
from ..game.pos import Pos
from ..game.move import Move
from ..game.rule import is_king_danger
from ..ai.pikafish import PikafishAI
from .chess_view import ChessView


class DrawHelpersMixin:
    def _catmull_rom(self, points, samples=14):
        """Catmull-Rom 平滑插值（参照 Android 曲线平滑）。"""
        if len(points) < 2:
            return list(points)
        pts = [points[0]] + list(points) + [points[-1]]
        out = []
        for i in range(len(pts) - 3):
            p0, p1, p2, p3 = pts[i], pts[i + 1], pts[i + 2], pts[i + 3]
            for s in range(samples):
                t = s / samples
                t2 = t * t
                t3 = t2 * t
                x = 0.5 * ((2 * p1[0]) + (-p0[0] + p2[0]) * t
                          + (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2
                          + (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3)
                y = 0.5 * ((2 * p1[1]) + (-p0[1] + p2[1]) * t
                          + (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2
                          + (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3)
                out.append((x, y))
        out.append(points[-1])
        return out


    def _draw_dashed_line(self, x1, y1, x2, y2, color, width=2, dash=8, gap=6):
        dx = x2 - x1
        dy = y2 - y1
        dist = max(1.0, (dx * dx + dy * dy) ** 0.5)
        nx, ny = dx / dist, dy / dist
        pos = 0.0
        while pos < dist:
            d = min(dash, dist - pos)
            ax = x1 + nx * pos
            ay = y1 + ny * pos
            bx = x1 + nx * (pos + d)
            by = y1 + ny * (pos + d)
            pygame.draw.line(self.screen, color, (ax, ay), (bx, by), width)
            pos += dash + gap

