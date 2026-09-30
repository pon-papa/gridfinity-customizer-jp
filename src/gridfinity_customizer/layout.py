from __future__ import annotations

from dataclasses import dataclass
import math

from .model import Anchor

GRID_PITCH = 42.0


@dataclass(frozen=True, slots=True)
class AxisSegment:
    start: float
    size: float
    is_partial: bool

    @property
    def center(self) -> float:
        return self.start + self.size / 2.0


@dataclass(frozen=True, slots=True)
class Cell:
    x: float
    y: float
    width: float
    depth: float
    partial_x: bool
    partial_y: bool

    @property
    def is_partial(self) -> bool:
        return self.partial_x or self.partial_y


def split_axis(total: float, anchor_at_start: bool) -> list[AxisSegment]:
    full_count = int(math.floor((total + 1e-9) / GRID_PITCH))
    remainder = total - full_count * GRID_PITCH
    if remainder < 1e-6:
        remainder = 0.0

    sizes: list[tuple[float, bool]] = [(GRID_PITCH, False)] * full_count
    if remainder > 0:
        partial = (remainder, True)
        sizes = sizes + [partial] if anchor_at_start else [partial] + sizes

    if not sizes:
        sizes = [(total, True)]

    cursor = -total / 2.0
    result: list[AxisSegment] = []
    for size, is_partial in sizes:
        result.append(AxisSegment(cursor, size, is_partial))
        cursor += size
    return result


def build_cells(width: float, depth: float, anchor: Anchor) -> tuple[list[Cell], list[AxisSegment], list[AxisSegment]]:
    # Xは左→右。Yは手前→奥。
    x_anchor_left = anchor.startswith("left")
    y_anchor_front = anchor.endswith("front")

    xs = split_axis(width, anchor_at_start=x_anchor_left)
    ys = split_axis(depth, anchor_at_start=y_anchor_front)

    cells = [
        Cell(x=x.center, y=y.center, width=x.size, depth=y.size,
             partial_x=x.is_partial, partial_y=y.is_partial)
        for y in ys
        for x in xs
    ]
    return cells, xs, ys


def layout_summary(width: float, depth: float, anchor: Anchor) -> dict:
    cells, xs, ys = build_cells(width, depth, anchor)
    return {
        "x_segments_mm": [round(s.size, 3) for s in xs],
        "y_segments_mm_front_to_back": [round(s.size, 3) for s in ys],
        "cell_count": len(cells),
        "partial_cell_count": sum(c.is_partial for c in cells),
    }
