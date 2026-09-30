from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

Anchor = Literal["left_back", "right_back", "left_front", "right_front"]
ShapeMode = Literal["box", "tile", "baseplate_only"]
DimensionInputMode = Literal["millimeters", "units_plus_mm"]
StructureProfile = Literal["lightweight", "robust", "custom"]
BaseFrameStyle = Literal["lightweight", "robust"]
GRID_PITCH_MM = 42.0


@dataclass(slots=True)
class WallSettings:
    back: bool = True
    right: bool = True
    front: bool = True
    left: bool = True

    def any(self) -> bool:
        return self.back or self.right or self.front or self.left


@dataclass(slots=True)
class GenerationSettings:
    name: str = "gridfinity_custom"
    width_mm: float = 103.0
    depth_mm: float = 71.0
    dimension_input_mode: DimensionInputMode = "millimeters"
    width_units: int = 2
    width_extra_mm: float = 19.0
    depth_units: int = 1
    depth_extra_mm: float = 29.0
    height_mm: float = 21.0
    anchor: Anchor = "left_back"
    shape_mode: ShapeMode = "box"
    walls: WallSettings = field(default_factory=WallSettings)

    # v1.2.0: both the earlier robust construction and the material-saving
    # construction based on the user's existing Gridfinity series are retained.
    structure_profile: StructureProfile = "lightweight"
    base_frame_style: BaseFrameStyle = "lightweight"
    clearance_total_mm: float = 0.4
    wall_thickness_mm: float = 1.9
    floor_thickness_mm: float = 0.225
    corner_radius_mm: float = 4.0
    min_partial_cell_mm: float = 12.0

    # First-layer anti-warp anchors used by the user's lightweight base frames.
    anti_warp_ears: bool = True
    ear_thickness_mm: float = 0.20
    ear_width_mm: float = 3.0
    ear_length_mm: float = 13.0

    generate_baseplate: bool = True
    export_3mf: bool = True
    export_stl: bool = False
    export_step: bool = False
    output_dir: str = "output"

    @property
    def requested_width_mm(self) -> float:
        if self.dimension_input_mode == "units_plus_mm":
            return self.width_units * GRID_PITCH_MM + self.width_extra_mm
        return self.width_mm

    @property
    def requested_depth_mm(self) -> float:
        if self.dimension_input_mode == "units_plus_mm":
            return self.depth_units * GRID_PITCH_MM + self.depth_extra_mm
        return self.depth_mm

    @property
    def finished_width_mm(self) -> float:
        return self.requested_width_mm - self.clearance_total_mm

    @property
    def finished_depth_mm(self) -> float:
        return self.requested_depth_mm - self.clearance_total_mm

    def validate(self) -> None:
        if not self.name.strip():
            raise ValueError("ファイル名を入力してください。")
        if self.dimension_input_mode not in ("millimeters", "units_plus_mm"):
            raise ValueError("寸法入力方式が不正です。")
        if self.structure_profile not in ("lightweight", "robust", "custom"):
            raise ValueError("構造プロファイルが不正です。")
        if self.base_frame_style not in ("lightweight", "robust"):
            raise ValueError("ベースフレーム形式が不正です。")
        if self.dimension_input_mode == "units_plus_mm":
            if isinstance(self.width_units, bool) or int(self.width_units) != self.width_units or self.width_units < 0:
                raise ValueError("横幅のユニット数は0以上の整数にしてください。")
            if isinstance(self.depth_units, bool) or int(self.depth_units) != self.depth_units or self.depth_units < 0:
                raise ValueError("奥行のユニット数は0以上の整数にしてください。")
            if self.width_extra_mm < 0 or self.depth_extra_mm < 0:
                raise ValueError("追加mmは0以上にしてください。")
        if self.requested_width_mm <= 0 or self.requested_depth_mm <= 0:
            raise ValueError("横幅と奥行は0より大きい値が必要です。")
        if self.clearance_total_mm < 0:
            raise ValueError("外周クリアランスは0以上にしてください。")
        if self.finished_width_mm <= 5 or self.finished_depth_mm <= 5:
            raise ValueError("クリアランスを差し引いた完成寸法が小さすぎます。")
        if self.height_mm < 4.75:
            raise ValueError("高さは4.75 mm以上にしてください。")
        if not 0.4 <= self.wall_thickness_mm <= 5.0:
            raise ValueError("壁厚は0.4〜5.0 mmの範囲にしてください。")
        if not 0.16 <= self.floor_thickness_mm <= 5.0:
            raise ValueError("床厚は0.16〜5.0 mmの範囲にしてください。")
        if not 0.0 <= self.corner_radius_mm <= 20.0:
            raise ValueError("角丸半径は0〜20 mmの範囲にしてください。")
        if self.min_partial_cell_mm < 4:
            raise ValueError("部分セル最小幅は4 mm以上にしてください。")
        if not 0.12 <= self.ear_thickness_mm <= 1.0:
            raise ValueError("はがれ防止耳の厚さは0.12〜1.0 mmの範囲にしてください。")
        if not 1.0 <= self.ear_width_mm <= 8.0:
            raise ValueError("はがれ防止耳の幅は1.0〜8.0 mmの範囲にしてください。")
        if not 3.0 <= self.ear_length_mm <= 25.0:
            raise ValueError("はがれ防止耳の長さは3.0〜25.0 mmの範囲にしてください。")
        if not (self.export_3mf or self.export_stl or self.export_step):
            raise ValueError("出力形式を1つ以上選択してください。")
        if self.shape_mode == "baseplate_only":
            self.generate_baseplate = True

    def to_dict(self) -> dict:
        data = asdict(self)
        # width_mm/depth_mm are kept as resolved values so old readers and the CLI
        # can still understand presets created with the unit-plus-mm mode.
        data["width_mm"] = self.requested_width_mm
        data["depth_mm"] = self.requested_depth_mm
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "GenerationSettings":
        copied = dict(data)
        copied["walls"] = WallSettings(**copied.get("walls", {}))
        copied.setdefault("dimension_input_mode", "millimeters")
        width = float(copied.get("width_mm", 103.0))
        depth = float(copied.get("depth_mm", 71.0))
        copied.setdefault("width_units", int(width // GRID_PITCH_MM))
        copied.setdefault("width_extra_mm", width - int(width // GRID_PITCH_MM) * GRID_PITCH_MM)
        copied.setdefault("depth_units", int(depth // GRID_PITCH_MM))
        copied.setdefault("depth_extra_mm", depth - int(depth // GRID_PITCH_MM) * GRID_PITCH_MM)

        # Presets created before v1.2.0 describe the robust v1.1.5 geometry.
        # Keep that interpretation instead of silently changing old prints.
        copied.setdefault("structure_profile", "robust")
        copied.setdefault("base_frame_style", "robust")
        copied.setdefault("anti_warp_ears", False)
        copied.setdefault("ear_thickness_mm", 0.20)
        copied.setdefault("ear_width_mm", 3.0)
        copied.setdefault("ear_length_mm", 13.0)
        return cls(**copied)

    def output_path(self) -> Path:
        return Path(self.output_dir).expanduser().resolve()
