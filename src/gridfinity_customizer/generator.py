from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import trimesh
from shapely.geometry import LineString, box
from shapely.ops import unary_union

from .layout import Cell, build_cells, layout_summary
from .mesh_utils import (
    concatenate,
    extrude_geometry,
    face_component_count,
    loft_rounded_rect,
    loft_rounded_ring,
    rounded_rectangle,
)
from .model import GenerationSettings

GRID_PITCH = 42.0
BASE_PROFILE_HEIGHT = 4.75

# v1.1.5 robust base-frame profile.  Kept unchanged.
ROBUST_BASEFRAME_HEIGHT = 4.75
ROBUST_BASEFRAME_LEVELS = (
    (0.00, 0.80, 6.0),
    (0.80, 2.60, 4.4),
    (2.60, ROBUST_BASEFRAME_HEIGHT, 0.2),
)

# Lightweight profile measured from the supplied "gridfinity simple set".
LIGHT_BASEFRAME_HEIGHT = 4.25
LIGHT_OUTER_RAIL_INSET = 1.64      # 42.00 -> 40.36 opening
LIGHT_INNER_RAIL_OUTSET = 2.66     # 42.00 -> 39.34 outer edge
LIGHT_INNER_RAIL_INSET = 4.30      # 42.00 -> 37.70 opening
LIGHT_LOWER_MERGE_Z = 2.50
LIGHT_DOUBLE_RAIL_TOP_Z = 2.67
LIGHT_TOP_OPENING_INSET = 0.82     # 42.00 -> 41.18 opening


@dataclass(slots=True)
class GeneratedModels:
    container: trimesh.Trimesh | None
    baseplate: trimesh.Trimesh | None
    summary: dict


def _cell_radius(width: float, depth: float) -> float:
    return min(4.0, max(0.8, min(width, depth) / 4.0))


def _male_base(cell: Cell, minimum: float) -> trimesh.Trimesh | None:
    if cell.width < minimum or cell.depth < minimum:
        return None
    top_w = max(4.0, cell.width - 0.5)
    top_d = max(4.0, cell.depth - 0.5)
    mid_w = max(3.0, top_w - 4.3)
    mid_d = max(3.0, top_d - 4.3)
    bottom_w = max(2.0, top_w - 5.9)
    bottom_d = max(2.0, top_d - 5.9)
    top_r = min(_cell_radius(top_w, top_d), top_w / 2 - 0.05, top_d / 2 - 0.05)
    mid_r = max(0.6, min(top_r - 2.15, mid_w / 2 - 0.05, mid_d / 2 - 0.05))
    bottom_r = max(0.4, min(mid_r - 0.8, bottom_w / 2 - 0.05, bottom_d / 2 - 0.05))
    return loft_rounded_rect(
        [
            (0.0, bottom_w, bottom_d, bottom_r),
            (0.8, mid_w, mid_d, mid_r),
            (2.6, mid_w, mid_d, mid_r),
            (BASE_PROFILE_HEIGHT, top_w, top_d, top_r),
        ],
        cx=cell.x,
        cy=cell.y,
    )


def _full_wall_polygon(settings: GenerationSettings):
    w, d = settings.finished_width_mm, settings.finished_depth_mm
    r = min(settings.corner_radius_mm, w / 2 - 0.1, d / 2 - 0.1)
    outer = rounded_rectangle(w, d, r)
    iw = w - 2 * settings.wall_thickness_mm
    idp = d - 2 * settings.wall_thickness_mm
    if iw <= 0 or idp <= 0:
        raise ValueError("壁厚に対して箱の寸法が小さすぎます。")
    inner = rounded_rectangle(iw, idp, max(0.0, r - settings.wall_thickness_mm))
    return outer.difference(inner)


def _selective_wall_polygon(settings: GenerationSettings):
    w, d = settings.finished_width_mm, settings.finished_depth_mm
    t = settings.wall_thickness_mm
    outer = rounded_rectangle(w, d, min(settings.corner_radius_mm, w / 2 - 0.1, d / 2 - 0.1))
    parts = []
    if settings.walls.left:
        parts.append(box(-w / 2, -d / 2, -w / 2 + t, d / 2))
    if settings.walls.right:
        parts.append(box(w / 2 - t, -d / 2, w / 2, d / 2))
    if settings.walls.front:
        parts.append(box(-w / 2, -d / 2, w / 2, -d / 2 + t))
    if settings.walls.back:
        parts.append(box(-w / 2, d / 2 - t, w / 2, d / 2))
    if not parts:
        return None
    return unary_union(parts).intersection(outer)


def generate_container(settings: GenerationSettings, cells: list[Cell]) -> trimesh.Trimesh:
    meshes: list[trimesh.Trimesh] = []
    for cell in cells:
        base = _male_base(cell, settings.min_partial_cell_mm)
        if base is not None:
            meshes.append(base)

    w, d = settings.finished_width_mm, settings.finished_depth_mm
    r = min(settings.corner_radius_mm, w / 2 - 0.1, d / 2 - 0.1)
    outer = rounded_rectangle(w, d, r)

    if settings.shape_mode == "tile":
        z1 = max(settings.height_mm, BASE_PROFILE_HEIGHT + 0.2)
        overlap = 0.02 if settings.structure_profile == "lightweight" else 0.08
        meshes.extend(extrude_geometry(outer, BASE_PROFILE_HEIGHT - overlap, z1))
        return concatenate(meshes)

    # The lightweight series uses a one-layer floor.  Keep only a tiny overlap
    # with the Gridfinity feet; the robust profile retains the v1.1.5 overlap.
    overlap = 0.02 if settings.structure_profile == "lightweight" else 0.08
    floor_top = BASE_PROFILE_HEIGHT + settings.floor_thickness_mm
    meshes.extend(extrude_geometry(outer, BASE_PROFILE_HEIGHT - overlap, floor_top))

    if settings.walls.any() and settings.height_mm > floor_top + 0.05:
        all_walls = all((settings.walls.back, settings.walls.right, settings.walls.front, settings.walls.left))
        wall_poly = _full_wall_polygon(settings) if all_walls else _selective_wall_polygon(settings)
        if wall_poly is not None:
            meshes.extend(extrude_geometry(wall_poly, floor_top - overlap, settings.height_mm))

    return concatenate(meshes)


# ---------------------------------------------------------------------------
# Robust base frame (v1.1.5, unchanged)
# ---------------------------------------------------------------------------
def _robust_baseframe_polygon(settings: GenerationSettings, cells: list[Cell], reduction: float):
    w, d = settings.finished_width_mm, settings.finished_depth_mm
    r = min(settings.corner_radius_mm, w / 2 - 0.1, d / 2 - 0.1)
    outer = rounded_rectangle(w, d, r)
    openings = []
    for cell in cells:
        opening_w = cell.width - reduction
        opening_d = cell.depth - reduction
        if opening_w <= 0.05 or opening_d <= 0.05:
            continue
        openings.append(
            box(
                cell.x - opening_w / 2.0,
                cell.y - opening_d / 2.0,
                cell.x + opening_w / 2.0,
                cell.y + opening_d / 2.0,
            )
        )
    if not openings:
        return outer
    return outer.difference(unary_union(openings))


def _generate_robust_baseframe(settings: GenerationSettings, cells: list[Cell]) -> trimesh.Trimesh:
    meshes: list[trimesh.Trimesh] = []
    for z0, z1, reduction in ROBUST_BASEFRAME_LEVELS:
        frame = _robust_baseframe_polygon(settings, cells, reduction)
        meshes.extend(extrude_geometry(frame, z0, z1))
    return concatenate(meshes)


# ---------------------------------------------------------------------------
# Lightweight base frame based on the supplied simple-series STL files
# ---------------------------------------------------------------------------
def _rounded_ring_polygon(cell: Cell, outer_inset: float, inner_inset: float):
    ow = cell.width - outer_inset
    od = cell.depth - outer_inset
    iw = cell.width - inner_inset
    idp = cell.depth - inner_inset
    if ow <= 0.1 or od <= 0.1 or iw <= 0.1 or idp <= 0.1:
        return None
    outer_r = min(_cell_radius(ow, od), ow / 2 - 0.02, od / 2 - 0.02)
    # Offsetting a rounded rectangle inward reduces both size and radius.
    inset_each_side = max(0.0, (inner_inset - outer_inset) / 2.0)
    inner_r = max(0.2, min(outer_r - inset_each_side, iw / 2 - 0.02, idp / 2 - 0.02))
    outer = rounded_rectangle(ow, od, outer_r, cx=cell.x, cy=cell.y, resolution=10)
    inner = rounded_rectangle(iw, idp, inner_r, cx=cell.x, cy=cell.y, resolution=10)
    return outer.difference(inner)


def _lightweight_lower_rails(settings: GenerationSettings, cells: list[Cell]) -> list[trimesh.Trimesh]:
    meshes: list[trimesh.Trimesh] = []

    # The reference series uses one thin ring around the *whole* frame, not a
    # complete lower outer ring around every cell.  Internal cells only carry
    # the second (inner) rail.  This is the main material-saving detail.
    w, d = settings.finished_width_mm, settings.finished_depth_mm
    outer_r = min(4.0, w / 2 - 0.02, d / 2 - 0.02)
    iw, idp = w - LIGHT_OUTER_RAIL_INSET, d - LIGHT_OUTER_RAIL_INSET
    if iw > 0.1 and idp > 0.1:
        inner_r = max(0.2, min(outer_r - LIGHT_OUTER_RAIL_INSET / 2.0, iw / 2 - 0.02, idp / 2 - 0.02))
        perimeter = rounded_rectangle(w, d, outer_r).difference(rounded_rectangle(iw, idp, inner_r))
        meshes.extend(extrude_geometry(perimeter, 0.0, LIGHT_DOUBLE_RAIL_TOP_Z))

    inner_rail_parts = [
        p for cell in cells
        if (p := _rounded_ring_polygon(cell, LIGHT_INNER_RAIL_OUTSET, LIGHT_INNER_RAIL_INSET)) is not None
    ]
    if inner_rail_parts:
        meshes.extend(extrude_geometry(unary_union(inner_rail_parts), 0.0, LIGHT_LOWER_MERGE_Z))
    return meshes


def _lightweight_upper_layers(cells: list[Cell]) -> list[trimesh.Trimesh]:
    """Build the sloped upper socket as thin, fused manufacturing layers.

    The reference STL uses a continuous slope.  A 0.10 mm staircase is below
    the layer height normally used for this utility part, avoids overlapping
    per-cell solids, and preserves the shared internal rails that make the
    simple series materially efficient.
    """
    meshes: list[trimesh.Trimesh] = []
    z = LIGHT_LOWER_MERGE_Z
    step = 0.10
    span = LIGHT_BASEFRAME_HEIGHT - LIGHT_LOWER_MERGE_Z
    while z < LIGHT_BASEFRAME_HEIGHT - 1e-9:
        z1 = min(LIGHT_BASEFRAME_HEIGHT, z + step)
        mid = (z + z1) / 2.0
        ratio = (mid - LIGHT_LOWER_MERGE_Z) / span
        inset = LIGHT_INNER_RAIL_INSET + (LIGHT_TOP_OPENING_INSET - LIGHT_INNER_RAIL_INSET) * ratio
        parts = [
            p for cell in cells
            if (p := _rounded_ring_polygon(cell, 0.0, inset)) is not None
        ]
        if parts:
            meshes.extend(extrude_geometry(unary_union(parts), z, z1))
        z = z1
    return meshes


def _corner_cells(cells: list[Cell]) -> dict[str, Cell]:
    """Return cells containing the four finished-layout corners."""
    return {
        "left_front": min(cells, key=lambda c: (c.x - c.width / 2.0) + (c.y - c.depth / 2.0)),
        "right_front": max(cells, key=lambda c: (c.x + c.width / 2.0) - (c.y - c.depth / 2.0)),
        "left_back": min(cells, key=lambda c: (c.x - c.width / 2.0) - (c.y + c.depth / 2.0)),
        "right_back": max(cells, key=lambda c: (c.x + c.width / 2.0) + (c.y + c.depth / 2.0)),
    }


def _ear_polygon(cell: Cell, corner: str, settings: GenerationSettings):
    """Create the first-layer L-shaped anti-warp anchor inside a corner cell.

    The supplied frames use two short rounded arms extending into the corner
    opening.  They remain inside the requested outside dimensions and touch the
    lower inner rail, so they peel away cleanly after printing.
    """
    inset = LIGHT_INNER_RAIL_INSET / 2.0
    left = cell.x - cell.width / 2.0 + inset
    right = cell.x + cell.width / 2.0 - inset
    front = cell.y - cell.depth / 2.0 + inset
    back = cell.y + cell.depth / 2.0 - inset
    opening_w = max(0.0, right - left)
    opening_d = max(0.0, back - front)
    width = settings.ear_width_mm
    overlap = min(0.25, width * 0.12)
    x_len = min(settings.ear_length_mm, max(0.0, opening_w - width * 1.5))
    y_len = min(settings.ear_length_mm, max(0.0, opening_d - width * 1.5))
    if x_len < width or y_len < width:
        return None

    if corner == "left_front":
        x0, y0, sx, sy = left + width / 2.0 - overlap, front + width / 2.0 - overlap, 1.0, 1.0
    elif corner == "right_front":
        x0, y0, sx, sy = right - width / 2.0 + overlap, front + width / 2.0 - overlap, -1.0, 1.0
    elif corner == "left_back":
        x0, y0, sx, sy = left + width / 2.0 - overlap, back - width / 2.0 + overlap, 1.0, -1.0
    else:  # right_back
        x0, y0, sx, sy = right - width / 2.0 + overlap, back - width / 2.0 + overlap, -1.0, -1.0

    path = LineString([
        (x0, y0 + sy * y_len),
        (x0, y0),
        (x0 + sx * x_len, y0),
    ])
    return path.buffer(width / 2.0, cap_style=1, join_style=1, quad_segs=10)


def _lightweight_ears(settings: GenerationSettings, cells: list[Cell]) -> list[trimesh.Trimesh]:
    if not settings.anti_warp_ears:
        return []
    parts = []
    for corner, cell in _corner_cells(cells).items():
        ear = _ear_polygon(cell, corner, settings)
        if ear is not None and not ear.is_empty:
            parts.append(ear)
    if not parts:
        return []
    return extrude_geometry(unary_union(parts), 0.0, settings.ear_thickness_mm)


def _generate_lightweight_baseframe(settings: GenerationSettings, cells: list[Cell]) -> trimesh.Trimesh:
    meshes = _lightweight_lower_rails(settings, cells)
    meshes.extend(_lightweight_upper_layers(cells))
    meshes.extend(_lightweight_ears(settings, cells))
    return concatenate(meshes)


def generate_baseplate(settings: GenerationSettings, cells: list[Cell], xs, ys) -> trimesh.Trimesh:
    if settings.base_frame_style == "lightweight":
        return _generate_lightweight_baseframe(settings, cells)
    return _generate_robust_baseframe(settings, cells)


def generate_models(settings: GenerationSettings) -> GeneratedModels:
    settings.validate()
    cells, xs, ys = build_cells(settings.finished_width_mm, settings.finished_depth_mm, settings.anchor)
    container = None
    baseplate = None
    if settings.shape_mode != "baseplate_only":
        container = generate_container(settings, cells)
    if settings.generate_baseplate or settings.shape_mode == "baseplate_only":
        baseplate = generate_baseplate(settings, cells, xs, ys)

    summary = {
        "requested_mm": [settings.requested_width_mm, settings.requested_depth_mm, settings.height_mm],
        "finished_mm": [settings.finished_width_mm, settings.finished_depth_mm, settings.height_mm],
        "anchor": settings.anchor,
        "shape_mode": settings.shape_mode,
        "structure_profile": settings.structure_profile,
        "base_frame_style": settings.base_frame_style,
        "anti_warp_ears": settings.anti_warp_ears,
        "layout": layout_summary(settings.finished_width_mm, settings.finished_depth_mm, settings.anchor),
        "container": _mesh_summary(container),
        "baseplate": _mesh_summary(baseplate),
    }
    return GeneratedModels(container=container, baseplate=baseplate, summary=summary)


def _mesh_summary(mesh: trimesh.Trimesh | None) -> dict | None:
    if mesh is None:
        return None
    extents = np.asarray(mesh.extents, dtype=float)
    return {
        "vertices": int(len(mesh.vertices)),
        "faces": int(len(mesh.faces)),
        "watertight_components": bool(mesh.is_watertight),
        "body_count": int(face_component_count(mesh)),
        "extents_mm": [round(float(x), 4) for x in extents],
        "volume_mm3": round(abs(float(mesh.volume)), 3),
    }
