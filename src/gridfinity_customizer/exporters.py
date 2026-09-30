from __future__ import annotations

from pathlib import Path
import json
import re
import struct
import uuid
import zipfile
from xml.etree import ElementTree as ET

import numpy as np
import trimesh

from .generator import GeneratedModels
from .layout import build_cells
from .model import GenerationSettings
from .step_export import build_baseplate_step, build_container_step, export_step

CORE_NS = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
PROD_NS = "http://schemas.microsoft.com/3dmanufacturing/production/2015/06"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
XML_NS = "http://www.w3.org/XML/1998/namespace"
MODEL_REL_TYPE = "http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"
APP_NAME = "Gridfinity Customizer JP 1.2.1"

ET.register_namespace("", CORE_NS)
ET.register_namespace("p", PROD_NS)


def safe_name(name: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|]+', "_", name.strip())
    return cleaned or "gridfinity_custom"


def _fmt(value: float) -> str:
    # Six decimals is far finer than FDM resolution and keeps XML manageable.
    text = f"{float(value):.6f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def _mesh_arrays(mesh: trimesh.Trimesh) -> tuple[np.ndarray, np.ndarray]:
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    if vertices.ndim != 2 or vertices.shape[1] != 3 or len(vertices) == 0:
        raise ValueError("3MF/STLへ出力できる頂点がありません。")
    if faces.ndim != 2 or faces.shape[1] != 3 or len(faces) == 0:
        raise ValueError("3MF/STLへ出力できる三角形がありません。")
    if int(faces.min()) < 0 or int(faces.max()) >= len(vertices):
        raise ValueError("メッシュの三角形インデックスが不正です。")
    if not np.isfinite(vertices).all():
        raise ValueError("メッシュに有限値でない座標が含まれています。")
    return vertices, faces


def _uuid(seed: str) -> str:
    # Deterministic UUIDs make an identical model byte-for-byte reproducible.
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"gridfinity-customizer-jp:{seed}"))


def _transform(tx: float = 0.0, ty: float = 0.0, tz: float = 0.0) -> str:
    # 3MF affine 4x3 matrix: identity followed by translation.
    return f"1 0 0 0 1 0 0 0 1 {_fmt(tx)} {_fmt(ty)} {_fmt(tz)}"


def _xml_bytes(root: ET.Element) -> bytes:
    # Bambu Studio accepts normal XML declarations; use uppercase UTF-8 to
    # match the files it writes itself as closely as practical.
    payload = ET.tostring(root, encoding="utf-8", xml_declaration=False)
    return b'<?xml version="1.0" encoding="UTF-8"?>\n' + payload + b"\n"


def _add_metadata(model: ET.Element, title: str, include_title: bool = True) -> None:
    app = ET.SubElement(model, f"{{{CORE_NS}}}metadata", {"name": "Application"})
    app.text = APP_NAME
    if include_title:
        title_meta = ET.SubElement(model, f"{{{CORE_NS}}}metadata", {"name": "Title"})
        title_meta.text = safe_name(title)


def _add_inline_mesh_object(
    resources: ET.Element,
    object_id: int,
    object_uuid: str,
    name: str,
    mesh: trimesh.Trimesh,
) -> None:
    vertices, faces = _mesh_arrays(mesh)
    obj = ET.SubElement(
        resources,
        f"{{{CORE_NS}}}object",
        {
            "id": str(object_id),
            "type": "model",
            "name": safe_name(name),
            f"{{{PROD_NS}}}UUID": object_uuid,
        },
    )
    mesh_el = ET.SubElement(obj, f"{{{CORE_NS}}}mesh")
    vertices_el = ET.SubElement(mesh_el, f"{{{CORE_NS}}}vertices")
    for x, y, z in vertices:
        ET.SubElement(
            vertices_el,
            f"{{{CORE_NS}}}vertex",
            {"x": _fmt(x), "y": _fmt(y), "z": _fmt(z)},
        )
    triangles_el = ET.SubElement(mesh_el, f"{{{CORE_NS}}}triangles")
    for v1, v2, v3 in faces:
        ET.SubElement(
            triangles_el,
            f"{{{CORE_NS}}}triangle",
            {"v1": str(int(v1)), "v2": str(int(v2)), "v3": str(int(v3))},
        )


def _new_model(lang: str = "ja-JP") -> ET.Element:
    return ET.Element(
        f"{{{CORE_NS}}}model",
        {
            "unit": "millimeter",
            f"{{{XML_NS}}}lang": lang,
            "requiredextensions": "p",
        },
    )


def _geometry_object_id(entry_index: int) -> int:
    """Return a package-global geometry id.

    Bambu Studio resolves split Production-3MF components using both p:path and
    objectid, but in practice it caches geometry by objectid.  Reusing objectid
    1 in every sub-model therefore makes a multi-object set display the first
    mesh more than once.  Bambu-generated projects avoid this by assigning a
    distinct object id to each geometry resource.  Odd ids are used here for
    geometry; the matching even ids are reserved for top-level wrappers.
    """
    return entry_index * 2 - 1


def _wrapper_object_id(entry_index: int) -> int:
    return entry_index * 2


def _object_model_xml(
    title: str,
    object_index: int,
    geometry_object_id: int,
    name: str,
    mesh: trimesh.Trimesh,
) -> bytes:
    """Geometry sub-model used by Bambu/Orca-style Production 3MF packages."""
    model = _new_model()
    _add_metadata(model, title, include_title=False)
    resources = ET.SubElement(model, f"{{{CORE_NS}}}resources")
    _add_inline_mesh_object(
        resources,
        object_id=geometry_object_id,
        object_uuid=_uuid(f"{title}:submodel:{object_index}:mesh:{geometry_object_id}"),
        name=name,
        mesh=mesh,
    )
    return _xml_bytes(model)


def _main_model_xml(
    title: str,
    entries: list[tuple[str, trimesh.Trimesh, tuple[float, float, float]]],
) -> bytes:
    """Write the top-level assembly model.

    Bambu Studio's own 3MF projects use the Production Extension and keep each
    printable mesh in 3D/Objects/object_N.model.  The main model references the
    geometry using p:path components.  Using the same package topology avoids
    the 'no geometry data' rejection seen with some bare core-only 3MF files.
    """
    model = _new_model()
    _add_metadata(model, title)
    resources = ET.SubElement(model, f"{{{CORE_NS}}}resources")

    wrapper_ids: list[int] = []
    for index, (name, _mesh, _translation) in enumerate(entries, start=1):
        geometry_id = _geometry_object_id(index)
        wrapper_id = _wrapper_object_id(index)
        wrapper_ids.append(wrapper_id)
        wrapper = ET.SubElement(
            resources,
            f"{{{CORE_NS}}}object",
            {
                "id": str(wrapper_id),
                "type": "model",
                "name": safe_name(name),
                f"{{{PROD_NS}}}UUID": _uuid(f"{title}:wrapper:{index}:{wrapper_id}"),
            },
        )
        components = ET.SubElement(wrapper, f"{{{CORE_NS}}}components")
        ET.SubElement(
            components,
            f"{{{CORE_NS}}}component",
            {
                f"{{{PROD_NS}}}path": f"/3D/Objects/object_{geometry_id}.model",
                "objectid": str(geometry_id),
                f"{{{PROD_NS}}}UUID": _uuid(f"{title}:component:{index}:{geometry_id}"),
                "transform": _transform(),
            },
        )

    build = ET.SubElement(
        model,
        f"{{{CORE_NS}}}build",
        {f"{{{PROD_NS}}}UUID": _uuid(f"{title}:build")},
    )
    for index, ((name, _mesh, translation), wrapper_id) in enumerate(zip(entries, wrapper_ids), start=1):
        ET.SubElement(
            build,
            f"{{{CORE_NS}}}item",
            {
                "objectid": str(wrapper_id),
                f"{{{PROD_NS}}}UUID": _uuid(f"{title}:build-item:{index}"),
                "transform": _transform(*translation),
                "printable": "1",
                "partnumber": safe_name(name),
            },
        )
    return _xml_bytes(model)


def _content_types_xml() -> bytes:
    # Keep the package support files byte-shape close to Bambu Studio output.
    return (
        b'<?xml version="1.0" encoding="UTF-8"?>\n'
        b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n'
        b' <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>\n'
        b' <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>\n'
        b'</Types>\n'
    )


def _root_relationships_xml() -> bytes:
    return (
        b'<?xml version="1.0" encoding="UTF-8"?>\n'
        b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
        b' <Relationship Target="/3D/3dmodel.model" Id="rel-1" '
        b'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>\n'
        b'</Relationships>\n'
    )


def _model_relationships_xml(geometry_ids: list[int]) -> bytes:
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">',
    ]
    for rel_index, geometry_id in enumerate(geometry_ids, start=1):
        lines.append(
            f' <Relationship Target="/3D/Objects/object_{geometry_id}.model" Id="rel-{rel_index}" '
            f'Type="{MODEL_REL_TYPE}"/>'
        )
    lines.append('</Relationships>')
    return ("\n".join(lines) + "\n").encode("utf-8")


def write_3mf(path: Path, title: str, entries: list[tuple[str, trimesh.Trimesh, tuple[float, float, float]]]) -> None:
    """Write a Bambu-compatible Production Extension 3MF directly.

    No Trimesh exporter is used, therefore SciPy and NetworkX remain optional.
    Geometry is stored in split object-model files, matching the package layout
    used by Bambu Studio and OrcaSlicer rather than relying on a minimal inline
    core-only package.
    """
    if not entries:
        raise ValueError("3MFへ出力するオブジェクトがありません。")
    # Validate every mesh before creating a partially written package.
    for _name, mesh, _translation in entries:
        _mesh_arrays(mesh)

    geometry_ids = [_geometry_object_id(index) for index in range(1, len(entries) + 1)]
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        archive.writestr("[Content_Types].xml", _content_types_xml())
        archive.writestr("_rels/.rels", _root_relationships_xml())
        archive.writestr("3D/3dmodel.model", _main_model_xml(title, entries))
        archive.writestr("3D/_rels/3dmodel.model.rels", _model_relationships_xml(geometry_ids))
        for index, ((name, mesh, _translation), geometry_id) in enumerate(zip(entries, geometry_ids), start=1):
            archive.writestr(
                f"3D/Objects/object_{geometry_id}.model",
                _object_model_xml(title, index, geometry_id, name, mesh),
            )


def write_binary_stl(path: Path, mesh: trimesh.Trimesh, title: str) -> None:
    """Write binary STL directly, avoiding optional Trimesh exporter modules."""
    vertices, faces = _mesh_arrays(mesh)
    triangles = vertices[faces]
    edges_a = triangles[:, 1] - triangles[:, 0]
    edges_b = triangles[:, 2] - triangles[:, 0]
    normals = np.cross(edges_a, edges_b)
    lengths = np.linalg.norm(normals, axis=1)
    nonzero = lengths > 1e-20
    normals[nonzero] /= lengths[nonzero, None]
    normals[~nonzero] = 0.0

    header_text = f"{APP_NAME} | {safe_name(title)}"
    header = header_text.encode("ascii", errors="replace")[:80].ljust(80, b"\0")
    face_count = len(faces)
    if face_count > 0xFFFFFFFF:
        raise ValueError("STLの三角形数が上限を超えています。")

    path.parent.mkdir(parents=True, exist_ok=True)
    record = struct.Struct("<12fH")
    with path.open("wb") as stream:
        stream.write(header)
        stream.write(struct.pack("<I", face_count))
        for normal, tri in zip(normals.astype(np.float32), triangles.astype(np.float32)):
            stream.write(record.pack(
                float(normal[0]), float(normal[1]), float(normal[2]),
                float(tri[0, 0]), float(tri[0, 1]), float(tri[0, 2]),
                float(tri[1, 0]), float(tri[1, 1]), float(tri[1, 2]),
                float(tri[2, 0]), float(tri[2, 1]), float(tri[2, 2]),
                0,
            ))


def export_all(settings: GenerationSettings, models: GeneratedModels, log=lambda _: None) -> list[Path]:
    out = settings.output_path()
    out.mkdir(parents=True, exist_ok=True)
    base = safe_name(settings.name)
    written: list[Path] = []

    if settings.export_3mf:
        if models.container is not None:
            p = out / f"{base}_container.3mf"
            write_3mf(p, f"{base}_container", [("container", models.container, (0.0, 0.0, 0.0))])
            written.append(p)
        if models.baseplate is not None:
            p = out / f"{base}_baseplate.3mf"
            write_3mf(p, f"{base}_baseplate", [("baseplate", models.baseplate, (0.0, 0.0, 0.0))])
            written.append(p)
        if models.container is not None and models.baseplate is not None:
            gap = 10.0
            shift = (settings.finished_width_mm + gap) / 2.0
            p = out / f"{base}_set.3mf"
            write_3mf(
                p,
                f"{base}_set",
                [
                    ("container", models.container, (-shift, 0.0, 0.0)),
                    ("baseplate", models.baseplate, (shift, 0.0, 0.0)),
                ],
            )
            written.append(p)

    if settings.export_stl:
        if models.container is not None:
            p = out / f"{base}_container.stl"
            write_binary_stl(p, models.container, f"{base}_container")
            written.append(p)
        if models.baseplate is not None:
            p = out / f"{base}_baseplate.stl"
            write_binary_stl(p, models.baseplate, f"{base}_baseplate")
            written.append(p)

    if settings.export_step:
        cells, xs, ys = build_cells(settings.finished_width_mm, settings.finished_depth_mm, settings.anchor)
        if models.container is not None:
            log("STEP用BREPを生成しています…")
            shape = build_container_step(settings, cells)
            p = out / f"{base}_container.step"
            export_step(shape, p)
            written.append(p)
        if models.baseplate is not None:
            log("ベースフレームのSTEP用BREPを生成しています…")
            shape = build_baseplate_step(settings, cells, xs, ys)
            p = out / f"{base}_baseplate.step"
            export_step(shape, p)
            written.append(p)

    p_json = out / f"{base}_parameters.json"
    p_json.write_text(json.dumps(settings.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    written.append(p_json)

    p_report = out / f"{base}_validation.json"
    p_report.write_text(json.dumps(models.summary, ensure_ascii=False, indent=2), encoding="utf-8")
    written.append(p_report)

    p_svg = out / f"{base}_layout.svg"
    p_svg.write_text(make_layout_svg(settings), encoding="utf-8")
    written.append(p_svg)
    return written


def make_layout_svg(settings: GenerationSettings) -> str:
    cells, _, _ = build_cells(settings.finished_width_mm, settings.finished_depth_mm, settings.anchor)
    scale = min(700 / settings.finished_width_mm, 500 / settings.finished_depth_mm)
    margin = 55
    wpx = settings.finished_width_mm * scale
    hpx = settings.finished_depth_mm * scale
    total_w, total_h = wpx + margin*2, hpx + margin*2
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{total_w:.0f}" height="{total_h:.0f}" viewBox="0 0 {total_w:.1f} {total_h:.1f}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="{margin}" y="28" font-family="sans-serif" font-size="16">{safe_name(settings.name)} / 基準点: {settings.anchor}</text>',
    ]
    for c in cells:
        x = margin + (c.x - c.width/2 + settings.finished_width_mm/2)*scale
        # SVGは下向きY。奥を上に表示。
        y = margin + (settings.finished_depth_mm/2 - (c.y + c.depth/2))*scale
        dash = ' stroke-dasharray="5 3"' if c.is_partial else ''
        parts.append(f'<rect x="{x:.2f}" y="{y:.2f}" width="{c.width*scale:.2f}" height="{c.depth*scale:.2f}" fill="none" stroke="black" stroke-width="1.2"{dash}/>')
        parts.append(f'<text x="{x+c.width*scale/2:.2f}" y="{y+c.depth*scale/2:.2f}" text-anchor="middle" dominant-baseline="middle" font-family="sans-serif" font-size="12">{c.width:.1f}×{c.depth:.1f}</text>')
    parts.extend([
        f'<text x="{margin-8}" y="{margin-12}" text-anchor="end" font-family="sans-serif" font-size="13">奥</text>',
        f'<text x="{margin-8}" y="{margin+hpx+18}" text-anchor="end" font-family="sans-serif" font-size="13">手前</text>',
        f'<text x="{margin}" y="{margin+hpx+40}" font-family="sans-serif" font-size="13">完成外形: {settings.finished_width_mm:.2f} × {settings.finished_depth_mm:.2f} mm</text>',
        '</svg>'
    ])
    return "\n".join(parts)
