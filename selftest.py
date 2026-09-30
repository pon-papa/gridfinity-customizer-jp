from __future__ import annotations

import importlib.abc
import struct
import sys
import tempfile
from pathlib import Path
import zipfile
from xml.etree import ElementTree as ET


class _BlockHeavyOptionalDependencies(importlib.abc.MetaPathFinder):
    """Prove that standard generation does not import SciPy or NetworkX."""

    BLOCKED = {"scipy", "networkx"}

    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".", 1)[0] in self.BLOCKED:
            raise ModuleNotFoundError(f"Blocked by Gridfinity self-test: {fullname}")
        return None


sys.meta_path.insert(0, _BlockHeavyOptionalDependencies())

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gridfinity_customizer.exporters import export_all
from gridfinity_customizer.generator import generate_models
from gridfinity_customizer.model import GenerationSettings, WallSettings

CORE_NS = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
PROD_NS = "http://schemas.microsoft.com/3dmanufacturing/production/2015/06"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
MODEL_REL_TYPE = "http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"


def _check_3mf(path: Path, expected_objects: int) -> None:
    with zipfile.ZipFile(path, "r") as archive:
        names = set(archive.namelist())
        required = {
            "[Content_Types].xml",
            "_rels/.rels",
            "3D/3dmodel.model",
            "3D/_rels/3dmodel.model.rels",
        }
        geometry_ids = [index * 2 - 1 for index in range(1, expected_objects + 1)]
        required.update({f"3D/Objects/object_{geometry_id}.model" for geometry_id in geometry_ids})
        if not required.issubset(names):
            raise RuntimeError(f"3MF package is incomplete: {path.name}")

        main = ET.fromstring(archive.read("3D/3dmodel.model"))
        wrappers = main.findall(f"./{{{CORE_NS}}}resources/{{{CORE_NS}}}object")
        items = main.findall(f"./{{{CORE_NS}}}build/{{{CORE_NS}}}item")
        if len(wrappers) != expected_objects or len(items) != expected_objects:
            raise RuntimeError(f"Unexpected assembly/build count: {path.name}")

        rels = ET.fromstring(archive.read("3D/_rels/3dmodel.model.rels"))
        targets = {
            rel.attrib.get("Target")
            for rel in rels.findall(f"{{{REL_NS}}}Relationship")
            if rel.attrib.get("Type") == MODEL_REL_TYPE
        }

        extents: list[tuple[float, float, float]] = []
        for index, wrapper in enumerate(wrappers, start=1):
            geometry_id = index * 2 - 1
            component = wrapper.find(f"./{{{CORE_NS}}}components/{{{CORE_NS}}}component")
            if component is None:
                raise RuntimeError(f"Missing component: {path.name}")
            object_path = component.attrib.get(f"{{{PROD_NS}}}path")
            expected_path = f"/3D/Objects/object_{geometry_id}.model"
            if object_path != expected_path or expected_path not in targets:
                raise RuntimeError(f"Broken object relationship: {path.name}")
            submodel = ET.fromstring(archive.read(expected_path.lstrip("/")))
            mesh = submodel.find(f"./{{{CORE_NS}}}resources/{{{CORE_NS}}}object/{{{CORE_NS}}}mesh")
            if mesh is None:
                raise RuntimeError(f"Missing mesh: {path.name}")
            vertices = mesh.findall(f"./{{{CORE_NS}}}vertices/{{{CORE_NS}}}vertex")
            triangles = mesh.findall(f"./{{{CORE_NS}}}triangles/{{{CORE_NS}}}triangle")
            if not vertices or not triangles:
                raise RuntimeError(f"Empty mesh: {path.name}")
            coords = [(float(v.attrib["x"]), float(v.attrib["y"]), float(v.attrib["z"])) for v in vertices]
            mins = [min(row[a] for row in coords) for a in range(3)]
            maxs = [max(row[a] for row in coords) for a in range(3)]
            extents.append(tuple(round(maxs[a] - mins[a], 5) for a in range(3)))
            for tri in triangles:
                ids = [int(tri.attrib[k]) for k in ("v1", "v2", "v3")]
                if min(ids) < 0 or max(ids) >= len(vertices):
                    raise RuntimeError(f"Invalid triangle index: {path.name}")

        if expected_objects > 1 and len(set(extents)) < 2:
            raise RuntimeError(f"Distinct set meshes collapsed: {path.name}")


def _check_binary_stl(path: Path) -> None:
    data = path.read_bytes()
    if len(data) < 84:
        raise RuntimeError(f"STL is too small: {path.name}")
    count = struct.unpack_from("<I", data, 80)[0]
    if count == 0 or len(data) != 84 + count * 50:
        raise RuntimeError(f"Invalid binary STL: {path.name}")


def _settings(profile: str, output_dir: str) -> GenerationSettings:
    light = profile == "lightweight"
    return GenerationSettings(
        name=f"setup_selftest_{profile}",
        dimension_input_mode="units_plus_mm",
        width_units=2,
        width_extra_mm=29.0,
        depth_units=4,
        depth_extra_mm=0.0,
        height_mm=21.0,
        anchor="left_back",
        walls=WallSettings(back=True, right=True, front=True, left=True),
        structure_profile=profile,
        base_frame_style=profile,
        wall_thickness_mm=1.9 if light else 1.2,
        floor_thickness_mm=0.225 if light else 1.2,
        corner_radius_mm=4.0 if light else 1.5,
        anti_warp_ears=light,
        generate_baseplate=True,
        export_3mf=True,
        export_stl=True,
        export_step=False,
        output_dir=output_dir,
    )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="gridfinity_customizer_test_") as td:
        light_settings = _settings("lightweight", td)
        robust_settings = _settings("robust", td)
        light = generate_models(light_settings)
        robust = generate_models(robust_settings)

        if light.container is None or light.baseplate is None or robust.container is None or robust.baseplate is None:
            raise RuntimeError("Expected models were not generated")
        if tuple(round(v, 3) for v in light.container.extents) != (112.6, 167.6, 21.0):
            raise RuntimeError("Lightweight container dimensions changed")
        if round(float(light.baseplate.extents[2]), 3) != 4.25:
            raise RuntimeError("Lightweight base-frame height must be 4.25 mm")
        if round(float(robust.baseplate.extents[2]), 3) != 4.75:
            raise RuntimeError("Robust v1.1.5 base-frame height changed")
        if abs(float(light.container.volume)) >= abs(float(robust.container.volume)) * 0.93:
            raise RuntimeError("Lightweight container is not materially lighter")
        if abs(float(light.baseplate.volume)) >= abs(float(robust.baseplate.volume)) * 0.85:
            raise RuntimeError("Lightweight base frame is not materially lighter")

        no_ear_settings = _settings("lightweight", td)
        no_ear_settings.anti_warp_ears = False
        no_ear = generate_models(no_ear_settings)
        if no_ear.baseplate is None or abs(float(light.baseplate.volume)) <= abs(float(no_ear.baseplate.volume)):
            raise RuntimeError("Anti-warp ears were not added")
        if tuple(round(v, 3) for v in no_ear.baseplate.extents[:2]) != tuple(round(v, 3) for v in light.baseplate.extents[:2]):
            raise RuntimeError("Anti-warp ears must stay inside the requested outline")

        paths = export_all(light_settings, light)
        by_name = {p.name: p for p in paths}
        prefix = light_settings.name
        _check_3mf(by_name[f"{prefix}_container.3mf"], 1)
        _check_3mf(by_name[f"{prefix}_baseplate.3mf"], 1)
        _check_3mf(by_name[f"{prefix}_set.3mf"], 2)
        _check_binary_stl(by_name[f"{prefix}_container.stl"])
        _check_binary_stl(by_name[f"{prefix}_baseplate.stl"])

        if "scipy" in sys.modules or "networkx" in sys.modules:
            raise RuntimeError("A blocked optional dependency was imported")

    print("Gridfinity Customizer self-test: OK (lightweight + robust profiles, ears, Bambu 3MF/STL)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
