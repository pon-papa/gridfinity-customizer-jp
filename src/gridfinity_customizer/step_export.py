from __future__ import annotations

from pathlib import Path

from .layout import Cell
from .model import GenerationSettings

BASE_PROFILE_HEIGHT = 4.75
ROBUST_BASEFRAME_HEIGHT = 4.75
ROBUST_BASEFRAME_LEVELS = (
    (0.00, 0.80, 6.0),
    (0.80, 2.60, 4.4),
    (2.60, ROBUST_BASEFRAME_HEIGHT, 0.2),
)
LIGHT_BASEFRAME_HEIGHT = 4.25
LIGHT_OUTER_RAIL_INSET = 1.64
LIGHT_INNER_RAIL_OUTSET = 2.66
LIGHT_INNER_RAIL_INSET = 4.30
LIGHT_LOWER_MERGE_Z = 2.50
LIGHT_DOUBLE_RAIL_TOP_Z = 2.67
LIGHT_TOP_OPENING_INSET = 0.82


def _cq():
    try:
        import cadquery as cq
    except ImportError as exc:
        raise RuntimeError(
            "STEP出力にはCadQueryが必要です。install_step.batを実行してから、アプリを再起動してください。"
        ) from exc
    return cq


def _sketch(cq, w: float, d: float, r: float):
    r = max(0.0, min(r, w / 2 - 0.05, d / 2 - 0.05))
    sk = cq.Sketch().rect(w, d)
    if r > 0.01:
        sk = sk.vertices().fillet(r)
    return sk


def _rounded_prism(cq, w: float, d: float, h: float, r: float, z0: float = 0.0, x: float = 0.0, y: float = 0.0):
    return cq.Workplane("XY").placeSketch(_sketch(cq, w, d, r)).extrude(h).translate((x, y, z0))


def _ring_prism(cq, ow: float, od: float, outer_r: float, iw: float, idp: float, inner_r: float, h: float, z0: float, x: float = 0.0, y: float = 0.0):
    outer = _rounded_prism(cq, ow, od, h, outer_r, z0, x, y)
    inner = _rounded_prism(cq, iw, idp, h + 0.2, inner_r, z0 - 0.1, x, y)
    return outer.cut(inner)


def _male_base_cq(cq, cell: Cell, minimum: float):
    if cell.width < minimum or cell.depth < minimum:
        return None
    top_w, top_d = cell.width - 0.5, cell.depth - 0.5
    bottom_w, bottom_d = max(2.0, top_w - 5.9), max(2.0, top_d - 5.9)
    rb = max(0.4, min(1.0, bottom_w / 2 - 0.05, bottom_d / 2 - 0.05))
    result = cq.Workplane("XY").placeSketch(_sketch(cq, bottom_w, bottom_d, rb)).extrude(0.8, taper=-45)
    result = result.faces(">Z").wires().toPending().extrude(1.8)
    result = result.faces(">Z").wires().toPending().extrude(2.15, taper=-45)
    return result.translate((cell.x, cell.y, 0))


def _union(parts):
    result = None
    for part in parts:
        if part is None:
            continue
        result = part if result is None else result.union(part)
    if result is None:
        raise ValueError("STEP生成対象がありません。")
    return result


def build_container_step(settings: GenerationSettings, cells: list[Cell]):
    cq = _cq()
    parts = [_male_base_cq(cq, c, settings.min_partial_cell_mm) for c in cells]
    w, d = settings.finished_width_mm, settings.finished_depth_mm
    r = min(settings.corner_radius_mm, w / 2 - 0.1, d / 2 - 0.1)
    overlap = 0.02 if settings.structure_profile == "lightweight" else 0.08

    if settings.shape_mode == "tile":
        parts.append(_rounded_prism(cq, w, d, settings.height_mm - BASE_PROFILE_HEIGHT + overlap, r, BASE_PROFILE_HEIGHT - overlap))
        return _union(parts)

    floor_top = BASE_PROFILE_HEIGHT + settings.floor_thickness_mm
    parts.append(_rounded_prism(cq, w, d, settings.floor_thickness_mm + overlap, r, BASE_PROFILE_HEIGHT - overlap))
    if settings.walls.any() and settings.height_mm > floor_top + 0.05:
        t = settings.wall_thickness_mm
        wh = settings.height_mm - floor_top + overlap
        z0 = floor_top - overlap
        if all((settings.walls.back, settings.walls.right, settings.walls.front, settings.walls.left)):
            outer = _rounded_prism(cq, w, d, wh, r, z0)
            inner = _rounded_prism(cq, w - 2*t, d - 2*t, wh + 0.2, max(0, r-t), z0 - 0.1)
            parts.append(outer.cut(inner))
        else:
            clip = _rounded_prism(cq, w, d, wh + 0.2, r, z0 - 0.1)
            if settings.walls.left:
                parts.append(cq.Workplane("XY").box(t, d, wh, centered=(True, True, False)).translate((-w/2+t/2, 0, z0)).intersect(clip))
            if settings.walls.right:
                parts.append(cq.Workplane("XY").box(t, d, wh, centered=(True, True, False)).translate((w/2-t/2, 0, z0)).intersect(clip))
            if settings.walls.front:
                parts.append(cq.Workplane("XY").box(w, t, wh, centered=(True, True, False)).translate((0, -d/2+t/2, z0)).intersect(clip))
            if settings.walls.back:
                parts.append(cq.Workplane("XY").box(w, t, wh, centered=(True, True, False)).translate((0, d/2-t/2, z0)).intersect(clip))
    return _union(parts)


def _build_robust_baseframe_step(cq, settings: GenerationSettings, cells: list[Cell]):
    w, d = settings.finished_width_mm, settings.finished_depth_mm
    r0 = min(settings.corner_radius_mm, w / 2 - 0.1, d / 2 - 0.1)
    layers = []
    for z0, z1, reduction in ROBUST_BASEFRAME_LEVELS:
        layer = _rounded_prism(cq, w, d, z1 - z0, r0, z0)
        openings = []
        for cell in cells:
            opening_w = cell.width - reduction
            opening_d = cell.depth - reduction
            if opening_w <= 0.05 or opening_d <= 0.05:
                continue
            openings.append(
                cq.Workplane("XY").box(opening_w, opening_d, z1 - z0 + 0.2, centered=(True, True, False)).translate((cell.x, cell.y, z0 - 0.1))
            )
        if openings:
            layer = layer.cut(_union(openings))
        layers.append(layer)
    return _union(layers)


def _cell_radius(width: float, depth: float) -> float:
    return min(4.0, max(0.8, min(width, depth) / 4.0))


def _build_lightweight_baseframe_step(cq, settings: GenerationSettings, cells: list[Cell]):
    parts = []
    w, d = settings.finished_width_mm, settings.finished_depth_mm
    outer_r = min(4.0, w / 2 - 0.05, d / 2 - 0.05)
    iw, idp = w - LIGHT_OUTER_RAIL_INSET, d - LIGHT_OUTER_RAIL_INSET
    inner_r = max(0.2, outer_r - LIGHT_OUTER_RAIL_INSET / 2.0)
    parts.append(_ring_prism(cq, w, d, outer_r, iw, idp, inner_r, LIGHT_DOUBLE_RAIL_TOP_Z, 0.0))

    for cell in cells:
        ow, od = cell.width - LIGHT_INNER_RAIL_OUTSET, cell.depth - LIGHT_INNER_RAIL_OUTSET
        iwc, idc = cell.width - LIGHT_INNER_RAIL_INSET, cell.depth - LIGHT_INNER_RAIL_INSET
        if min(ow, od, iwc, idc) <= 0.1:
            continue
        orad = _cell_radius(ow, od)
        irad = max(0.2, orad - (LIGHT_INNER_RAIL_INSET - LIGHT_INNER_RAIL_OUTSET) / 2.0)
        parts.append(_ring_prism(cq, ow, od, orad, iwc, idc, irad, LIGHT_LOWER_MERGE_Z, 0.0, cell.x, cell.y))

    z = LIGHT_LOWER_MERGE_Z
    step = 0.10
    span = LIGHT_BASEFRAME_HEIGHT - LIGHT_LOWER_MERGE_Z
    while z < LIGHT_BASEFRAME_HEIGHT - 1e-9:
        z1 = min(LIGHT_BASEFRAME_HEIGHT, z + step)
        ratio = ((z + z1) / 2.0 - LIGHT_LOWER_MERGE_Z) / span
        inset = LIGHT_INNER_RAIL_INSET + (LIGHT_TOP_OPENING_INSET - LIGHT_INNER_RAIL_INSET) * ratio
        layer_parts = []
        for cell in cells:
            iwc, idc = cell.width - inset, cell.depth - inset
            if iwc <= 0.1 or idc <= 0.1:
                continue
            orad = _cell_radius(cell.width, cell.depth)
            irad = max(0.2, orad - inset / 2.0)
            layer_parts.append(_ring_prism(cq, cell.width, cell.depth, orad, iwc, idc, irad, z1 - z, z, cell.x, cell.y))
        if layer_parts:
            parts.append(_union(layer_parts))
        z = z1

    if settings.anti_warp_ears:
        min_x = min(c.x - c.width / 2 for c in cells)
        max_x = max(c.x + c.width / 2 for c in cells)
        min_y = min(c.y - c.depth / 2 for c in cells)
        max_y = max(c.y + c.depth / 2 for c in cells)
        inset = LIGHT_INNER_RAIL_INSET / 2.0
        width = settings.ear_width_mm
        length = settings.ear_length_mm
        h = settings.ear_thickness_mm
        for x_side, y_side in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
            x0 = (min_x + inset + width / 2) if x_side < 0 else (max_x - inset - width / 2)
            y0 = (min_y + inset + width / 2) if y_side < 0 else (max_y - inset - width / 2)
            horizontal = cq.Workplane("XY").box(length, width, h, centered=(True, True, False)).translate((x0 + x_side * length / 2, y0, 0))
            vertical = cq.Workplane("XY").box(width, length, h, centered=(True, True, False)).translate((x0, y0 + y_side * length / 2, 0))
            parts.append(horizontal.union(vertical))

    return _union(parts)


def build_baseplate_step(settings: GenerationSettings, cells: list[Cell], xs, ys):
    cq = _cq()
    if settings.base_frame_style == "lightweight":
        return _build_lightweight_baseframe_step(cq, settings, cells)
    return _build_robust_baseframe_step(cq, settings, cells)


def export_step(shape, path: Path) -> None:
    cq = _cq()
    cq.exporters.export(shape, str(path))
