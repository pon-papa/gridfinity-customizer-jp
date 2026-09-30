from __future__ import annotations

import json
import importlib.util
import math
import os
from pathlib import Path
import queue
import sys
import threading
import traceback
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gridfinity_customizer.exporters import export_all
from gridfinity_customizer.generator import generate_models
from gridfinity_customizer.model import GRID_PITCH_MM, GenerationSettings, WallSettings
from gridfinity_customizer.presets import load_preset, save_preset

ANCHORS = {
    "左奥": "left_back",
    "右奥": "right_back",
    "左手前": "left_front",
    "右手前": "right_front",
}
ANCHOR_LABEL = {v: k for k, v in ANCHORS.items()}
MODES = {
    "箱／トレー（壁を個別指定）": "box",
    "壁なしタイル／かさ上げ台": "tile",
    "ベースフレームのみ（格子枠）": "baseplate_only",
}
MODE_LABEL = {v: k for k, v in MODES.items()}
DIMENSION_MODES = {
    "実寸mm": "millimeters",
    "ユニット数＋追加mm": "units_plus_mm",
}
DIMENSION_MODE_LABEL = {v: k for k, v in DIMENSION_MODES.items()}
STRUCTURE_PROFILES = {
    "軽量・共有シリーズ準拠": "lightweight",
    "しっかり・v1.1.5": "robust",
    "カスタム": "custom",
}
STRUCTURE_PROFILE_LABEL = {v: k for k, v in STRUCTURE_PROFILES.items()}
BASE_FRAME_STYLES = {
    "軽量シリーズ（細枠）": "lightweight",
    "しっかり版（太枠）": "robust",
}
BASE_FRAME_STYLE_LABEL = {v: k for k, v in BASE_FRAME_STYLES.items()}
HEIGHT_PRESETS = ["7", "14", "21", "28", "35", "42", "任意"]
CADQUERY_AVAILABLE = importlib.util.find_spec("cadquery") is not None


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Gridfinity Customizer JP 1.2.1")
        self.minsize(1040, 900)
        self.queue: queue.Queue = queue.Queue()
        self._syncing_dimensions = False
        self._last_dimension_mode = "実寸mm"
        self._make_vars()
        self._build()
        self.after(100, self._poll_queue)

    def _make_vars(self):
        self.name_var = tk.StringVar(value="gridfinity_custom")
        self.dimension_mode_var = tk.StringVar(value="実寸mm")
        self.width_var = tk.StringVar(value="103.0")
        self.depth_var = tk.StringVar(value="71.0")
        self.width_units_var = tk.StringVar(value="2")
        self.width_extra_var = tk.StringVar(value="19.0")
        self.depth_units_var = tk.StringVar(value="1")
        self.depth_extra_var = tk.StringVar(value="29.0")
        self.width_preview_var = tk.StringVar(value="= 103.0 mm")
        self.depth_preview_var = tk.StringVar(value="= 71.0 mm")
        self.height_preset_var = tk.StringVar(value="21")
        self.height_custom_var = tk.StringVar(value="21.0")
        self.anchor_var = tk.StringVar(value="左奥")
        self.mode_var = tk.StringVar(value="箱／トレー（壁を個別指定）")
        self.wall_back = tk.BooleanVar(value=True)
        self.wall_right = tk.BooleanVar(value=True)
        self.wall_front = tk.BooleanVar(value=True)
        self.wall_left = tk.BooleanVar(value=True)
        self.baseplate_var = tk.BooleanVar(value=True)
        self.structure_profile_var = tk.StringVar(value="軽量・共有シリーズ準拠")
        self.base_frame_style_var = tk.StringVar(value="軽量シリーズ（細枠）")
        self.anti_warp_ears_var = tk.BooleanVar(value=True)
        self.clearance_var = tk.StringVar(value="0.4")
        self.wall_thickness_var = tk.StringVar(value="1.9")
        self.floor_thickness_var = tk.StringVar(value="0.225")
        self.corner_radius_var = tk.StringVar(value="4.0")
        self.min_partial_var = tk.StringVar(value="12.0")
        self.ear_thickness_var = tk.StringVar(value="0.20")
        self.ear_width_var = tk.StringVar(value="3.0")
        self.ear_length_var = tk.StringVar(value="13.0")
        self.export_3mf = tk.BooleanVar(value=True)
        self.export_stl = tk.BooleanVar(value=False)
        self.export_step = tk.BooleanVar(value=False)
        self.output_var = tk.StringVar(value=str(ROOT / "output"))
        self.status_var = tk.StringVar(value="設定を入力し、出力先を指定してから［生成スタート］を押してください。")

        for var in (self.width_var, self.depth_var, self.width_units_var, self.width_extra_var, self.depth_units_var, self.depth_extra_var):
            var.trace_add("write", self._dimension_value_changed)

    def _build(self):
        outer = ttk.Frame(self, padding=12)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(4, weight=1)

        basic = ttk.LabelFrame(outer, text="基本寸法", padding=10)
        basic.grid(row=0, column=0, sticky="ew")
        for i in range(8):
            basic.columnconfigure(i, weight=1 if i in (1, 3, 5, 7) else 0)
        ttk.Label(basic, text="名前").grid(row=0, column=0, sticky="w")
        ttk.Entry(basic, textvariable=self.name_var).grid(row=0, column=1, columnspan=3, sticky="ew", padx=(6, 12))
        ttk.Label(basic, text="基準点").grid(row=0, column=4, sticky="w")
        ttk.Combobox(basic, textvariable=self.anchor_var, values=list(ANCHORS), state="readonly", width=10).grid(row=0, column=5, sticky="ew", padx=6)
        ttk.Label(basic, text="形状").grid(row=0, column=6, sticky="w")
        mode = ttk.Combobox(basic, textvariable=self.mode_var, values=list(MODES), state="readonly")
        mode.grid(row=0, column=7, sticky="ew", padx=(6, 0))
        mode.bind("<<ComboboxSelected>>", lambda e: self._update_mode())

        dimension = ttk.LabelFrame(basic, text="横・奥行の指定", padding=8)
        dimension.grid(row=1, column=0, columnspan=8, sticky="ew", pady=(10, 0))
        dimension.columnconfigure(7, weight=1)
        ttk.Label(dimension, text="入力方式").grid(row=0, column=0, sticky="w")
        dm = ttk.Combobox(dimension, textvariable=self.dimension_mode_var, values=list(DIMENSION_MODES), state="readonly", width=20)
        dm.grid(row=0, column=1, columnspan=2, sticky="w", padx=(8, 16))
        dm.bind("<<ComboboxSelected>>", lambda e: self._dimension_mode_selected())
        ttk.Label(dimension, text="1U = 42 mm。外周クリアランスは、ここで求めた全体寸法から差し引きます。", foreground="#444").grid(row=0, column=3, columnspan=5, sticky="w")

        ttk.Label(dimension, text="横幅 X").grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.width_mm_entry = ttk.Entry(dimension, textvariable=self.width_var, width=11)
        self.width_mm_entry.grid(row=1, column=1, sticky="w", padx=(8, 2), pady=(8, 0))
        ttk.Label(dimension, text="mm").grid(row=1, column=2, sticky="w", pady=(8, 0))
        self.width_units_entry = ttk.Entry(dimension, textvariable=self.width_units_var, width=7)
        self.width_units_entry.grid(row=1, column=3, sticky="e", padx=(20, 2), pady=(8, 0))
        ttk.Label(dimension, text="U ＋").grid(row=1, column=4, sticky="w", pady=(8, 0))
        self.width_extra_entry = ttk.Entry(dimension, textvariable=self.width_extra_var, width=9)
        self.width_extra_entry.grid(row=1, column=5, sticky="w", padx=(4, 2), pady=(8, 0))
        ttk.Label(dimension, text="mm").grid(row=1, column=6, sticky="w", pady=(8, 0))
        ttk.Label(dimension, textvariable=self.width_preview_var).grid(row=1, column=7, sticky="w", padx=(14, 0), pady=(8, 0))

        ttk.Label(dimension, text="奥行 Y").grid(row=2, column=0, sticky="w", pady=(6, 0))
        self.depth_mm_entry = ttk.Entry(dimension, textvariable=self.depth_var, width=11)
        self.depth_mm_entry.grid(row=2, column=1, sticky="w", padx=(8, 2), pady=(6, 0))
        ttk.Label(dimension, text="mm").grid(row=2, column=2, sticky="w", pady=(6, 0))
        self.depth_units_entry = ttk.Entry(dimension, textvariable=self.depth_units_var, width=7)
        self.depth_units_entry.grid(row=2, column=3, sticky="e", padx=(20, 2), pady=(6, 0))
        ttk.Label(dimension, text="U ＋").grid(row=2, column=4, sticky="w", pady=(6, 0))
        self.depth_extra_entry = ttk.Entry(dimension, textvariable=self.depth_extra_var, width=9)
        self.depth_extra_entry.grid(row=2, column=5, sticky="w", padx=(4, 2), pady=(6, 0))
        ttk.Label(dimension, text="mm").grid(row=2, column=6, sticky="w", pady=(6, 0))
        ttk.Label(dimension, textvariable=self.depth_preview_var).grid(row=2, column=7, sticky="w", padx=(14, 0), pady=(6, 0))

        ttk.Label(basic, text="高さプリセット").grid(row=2, column=0, sticky="w", pady=(10, 0))
        hp = ttk.Combobox(basic, textvariable=self.height_preset_var, values=HEIGHT_PRESETS, state="readonly", width=8)
        hp.grid(row=2, column=1, sticky="ew", padx=(6, 12), pady=(10, 0))
        hp.bind("<<ComboboxSelected>>", lambda e: self._height_selected())
        ttk.Label(basic, text="完成高さ [mm]").grid(row=2, column=2, sticky="w", pady=(10, 0))
        ttk.Entry(basic, textvariable=self.height_custom_var, width=12).grid(row=2, column=3, sticky="ew", padx=(6, 12), pady=(10, 0))
        ttk.Label(basic, text="例：2U＋19 mm × 1U＋29 mm ＝ 103 × 71 mm", foreground="#444").grid(row=2, column=4, columnspan=4, sticky="w", pady=(10, 0))

        middle = ttk.Frame(outer)
        middle.grid(row=1, column=0, sticky="ew", pady=10)
        middle.columnconfigure(0, weight=1)
        middle.columnconfigure(1, weight=1)

        walls = ttk.LabelFrame(middle, text="壁と生成物", padding=10)
        walls.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        self.wall_checks = []
        for idx, (label, var) in enumerate([
            ("奥側", self.wall_back), ("右側", self.wall_right),
            ("手前側", self.wall_front), ("左側", self.wall_left),
        ]):
            cb = ttk.Checkbutton(walls, text=label, variable=var)
            cb.grid(row=0, column=idx, padx=8, sticky="w")
            self.wall_checks.append(cb)
        self.baseplate_check = ttk.Checkbutton(walls, text="対応ベースフレームも生成（底板なし格子枠）", variable=self.baseplate_var)
        self.baseplate_check.grid(row=1, column=0, columnspan=4, sticky="w", pady=(12, 0))

        ttk.Label(walls, text="構造プロファイル").grid(row=2, column=0, sticky="w", pady=(12, 0))
        profile = ttk.Combobox(walls, textvariable=self.structure_profile_var, values=list(STRUCTURE_PROFILES), state="readonly", width=24)
        profile.grid(row=2, column=1, columnspan=3, sticky="ew", padx=(8, 0), pady=(12, 0))
        profile.bind("<<ComboboxSelected>>", lambda e: self._profile_selected())

        ttk.Label(walls, text="ベースフレーム形式").grid(row=3, column=0, sticky="w", pady=(8, 0))
        self.base_style_combo = ttk.Combobox(walls, textvariable=self.base_frame_style_var, values=list(BASE_FRAME_STYLES), state="readonly", width=24)
        self.base_style_combo.grid(row=3, column=1, columnspan=3, sticky="ew", padx=(8, 0), pady=(8, 0))
        self.base_style_combo.bind("<<ComboboxSelected>>", lambda e: self._base_style_selected())
        self.ears_check = ttk.Checkbutton(walls, text="四隅にはがれ防止耳を付ける（軽量ベース・初層のみ）", variable=self.anti_warp_ears_var)
        self.ears_check.grid(row=4, column=0, columnspan=4, sticky="w", pady=(8, 0))

        ttk.Label(walls, text="※軽量版は薄床＋細枠。しっかり版はv1.1.5の形状を維持します。\n　壁を全て外すと薄い床だけの壁なしトレーになります。", foreground="#444").grid(row=5, column=0, columnspan=4, sticky="w", pady=(8, 0))

        dims = ttk.LabelFrame(middle, text="詳細寸法", padding=10)
        dims.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        labels_vars = [
            ("外周クリアランス 合計 [mm]", self.clearance_var),
            ("壁厚 [mm]", self.wall_thickness_var),
            ("床厚 [mm]", self.floor_thickness_var),
            ("角丸半径 [mm]", self.corner_radius_var),
            ("部分セル最小幅 [mm]", self.min_partial_var),
            ("耳の厚さ [mm]", self.ear_thickness_var),
            ("耳の幅 [mm]", self.ear_width_var),
            ("耳の長さ [mm]", self.ear_length_var),
        ]
        for i, (label, var) in enumerate(labels_vars):
            ttk.Label(dims, text=label).grid(row=i, column=0, sticky="w", pady=2)
            ttk.Entry(dims, textvariable=var, width=12).grid(row=i, column=1, sticky="ew", padx=(10, 0), pady=2)
        dims.columnconfigure(1, weight=1)

        out = ttk.LabelFrame(outer, text="出力", padding=10)
        out.grid(row=2, column=0, sticky="ew")
        out.columnconfigure(1, weight=1)
        ttk.Label(out, text="出力先").grid(row=0, column=0, sticky="w")
        ttk.Entry(out, textvariable=self.output_var).grid(row=0, column=1, sticky="ew", padx=8)
        ttk.Button(out, text="参照…", command=self._browse_output).grid(row=0, column=2)
        ttk.Checkbutton(out, text="3MF（基本）", variable=self.export_3mf).grid(row=1, column=0, sticky="w", pady=(10, 0))
        ttk.Checkbutton(out, text="STL", variable=self.export_stl).grid(row=1, column=1, sticky="w", pady=(10, 0))
        step_text = "STEP（CadQuery使用）" if CADQUERY_AVAILABLE else "STEP（CadQuery未導入）"
        self.step_check = ttk.Checkbutton(out, text=step_text, variable=self.export_step)
        self.step_check.grid(row=1, column=2, sticky="w", pady=(10, 0))
        if not CADQUERY_AVAILABLE:
            self.step_check.configure(state="disabled")

        actions = ttk.Frame(outer)
        actions.grid(row=3, column=0, sticky="ew", pady=10)
        ttk.Button(actions, text="プリセットを開く", command=self._load).pack(side="left")
        ttk.Button(actions, text="プリセットを保存", command=self._save).pack(side="left", padx=6)
        ttk.Button(actions, text="使い方説明書", command=self._manual).pack(side="left")
        self.start_button = ttk.Button(actions, text="生成スタート", command=self._start)
        self.start_button.pack(side="right")

        logf = ttk.LabelFrame(outer, text="処理ログ", padding=8)
        logf.grid(row=4, column=0, sticky="nsew")
        logf.rowconfigure(0, weight=1)
        logf.columnconfigure(0, weight=1)
        self.log = tk.Text(logf, height=12, wrap="word")
        self.log.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(logf, command=self.log.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=scroll.set)
        ttk.Label(outer, textvariable=self.status_var).grid(row=5, column=0, sticky="ew", pady=(8, 0))
        self._update_dimension_controls()
        self._update_mode()
        self._base_style_selected()

    @staticmethod
    def _fmt(value: float) -> str:
        text = f"{value:.3f}".rstrip("0").rstrip(".")
        return text if text else "0"

    @staticmethod
    def _decompose(value: float) -> tuple[int, float]:
        if value < 0:
            return 0, 0.0
        units = int(math.floor((value + 1e-9) / GRID_PITCH_MM))
        extra = value - units * GRID_PITCH_MM
        if abs(extra) < 1e-9:
            extra = 0.0
        return units, extra

    @staticmethod
    def _parse_unit_count(text: str, axis: str) -> int:
        stripped = text.strip()
        if not stripped:
            raise ValueError(f"{axis}のユニット数を入力してください。")
        value = int(stripped)
        if str(value) != stripped and stripped not in (f"+{value}",):
            # int('02') is valid and harmless; accept it. Reject decimal strings.
            if any(ch in stripped for ch in ".eE"):
                raise ValueError(f"{axis}のユニット数は整数で入力してください。")
        if value < 0:
            raise ValueError(f"{axis}のユニット数は0以上にしてください。")
        return value

    def _dimension_mode_selected(self):
        new_mode = self.dimension_mode_var.get()
        self._syncing_dimensions = True
        try:
            if new_mode == "ユニット数＋追加mm" and self._last_dimension_mode != new_mode:
                try:
                    wu, we = self._decompose(float(self.width_var.get()))
                    du, de = self._decompose(float(self.depth_var.get()))
                    self.width_units_var.set(str(wu))
                    self.width_extra_var.set(self._fmt(we))
                    self.depth_units_var.set(str(du))
                    self.depth_extra_var.set(self._fmt(de))
                except ValueError:
                    pass
            elif new_mode == "実寸mm" and self._last_dimension_mode != new_mode:
                try:
                    width = int(self.width_units_var.get()) * GRID_PITCH_MM + float(self.width_extra_var.get())
                    depth = int(self.depth_units_var.get()) * GRID_PITCH_MM + float(self.depth_extra_var.get())
                    self.width_var.set(self._fmt(width))
                    self.depth_var.set(self._fmt(depth))
                except ValueError:
                    pass
        finally:
            self._syncing_dimensions = False
        self._last_dimension_mode = new_mode
        self._update_dimension_controls()
        self._dimension_value_changed()

    def _update_dimension_controls(self):
        unit_mode = self.dimension_mode_var.get() == "ユニット数＋追加mm"
        self.width_mm_entry.configure(state="disabled" if unit_mode else "normal")
        self.depth_mm_entry.configure(state="disabled" if unit_mode else "normal")
        for entry in (self.width_units_entry, self.width_extra_entry, self.depth_units_entry, self.depth_extra_entry):
            entry.configure(state="normal" if unit_mode else "disabled")

    def _dimension_value_changed(self, *_):
        if self._syncing_dimensions:
            return
        self._syncing_dimensions = True
        try:
            if self.dimension_mode_var.get() == "ユニット数＋追加mm":
                try:
                    width = int(self.width_units_var.get()) * GRID_PITCH_MM + float(self.width_extra_var.get())
                    self.width_var.set(self._fmt(width))
                    self.width_preview_var.set(f"= {self._fmt(width)} mm")
                except ValueError:
                    self.width_preview_var.set("= — mm")
                try:
                    depth = int(self.depth_units_var.get()) * GRID_PITCH_MM + float(self.depth_extra_var.get())
                    self.depth_var.set(self._fmt(depth))
                    self.depth_preview_var.set(f"= {self._fmt(depth)} mm")
                except ValueError:
                    self.depth_preview_var.set("= — mm")
            else:
                try:
                    width = float(self.width_var.get())
                    wu, we = self._decompose(width)
                    self.width_units_var.set(str(wu))
                    self.width_extra_var.set(self._fmt(we))
                    self.width_preview_var.set(f"= {self._fmt(width)} mm")
                except ValueError:
                    self.width_preview_var.set("= — mm")
                try:
                    depth = float(self.depth_var.get())
                    du, de = self._decompose(depth)
                    self.depth_units_var.set(str(du))
                    self.depth_extra_var.set(self._fmt(de))
                    self.depth_preview_var.set(f"= {self._fmt(depth)} mm")
                except ValueError:
                    self.depth_preview_var.set("= — mm")
        finally:
            self._syncing_dimensions = False

    def _height_selected(self):
        value = self.height_preset_var.get()
        if value != "任意":
            self.height_custom_var.set(value)

    def _update_mode(self):
        mode = MODES[self.mode_var.get()]
        enabled = mode == "box"
        for cb in self.wall_checks:
            cb.configure(state="normal" if enabled else "disabled")
        if mode == "baseplate_only":
            self.baseplate_var.set(True)
            self.baseplate_check.configure(state="disabled")
        else:
            self.baseplate_check.configure(state="normal")

    def _profile_selected(self):
        profile = STRUCTURE_PROFILES[self.structure_profile_var.get()]
        if profile == "lightweight":
            self.wall_thickness_var.set("1.9")
            self.floor_thickness_var.set("0.225")
            self.corner_radius_var.set("4.0")
            self.base_frame_style_var.set("軽量シリーズ（細枠）")
            self.anti_warp_ears_var.set(True)
        elif profile == "robust":
            self.wall_thickness_var.set("1.2")
            self.floor_thickness_var.set("1.2")
            self.corner_radius_var.set("1.5")
            self.base_frame_style_var.set("しっかり版（太枠）")
            self.anti_warp_ears_var.set(False)
        self._base_style_selected()

    def _base_style_selected(self):
        lightweight = BASE_FRAME_STYLES[self.base_frame_style_var.get()] == "lightweight"
        self.ears_check.configure(state="normal" if lightweight else "disabled")
        if not lightweight:
            self.anti_warp_ears_var.set(False)

    def _browse_output(self):
        path = filedialog.askdirectory(initialdir=self.output_var.get() or ROOT)
        if path:
            self.output_var.set(path)

    def _settings(self) -> GenerationSettings:
        input_mode = DIMENSION_MODES[self.dimension_mode_var.get()]
        if input_mode == "units_plus_mm":
            width_units = self._parse_unit_count(self.width_units_var.get(), "横幅")
            depth_units = self._parse_unit_count(self.depth_units_var.get(), "奥行")
            width_extra = float(self.width_extra_var.get())
            depth_extra = float(self.depth_extra_var.get())
            width = width_units * GRID_PITCH_MM + width_extra
            depth = depth_units * GRID_PITCH_MM + depth_extra
        else:
            width = float(self.width_var.get())
            depth = float(self.depth_var.get())
            width_units, width_extra = self._decompose(width)
            depth_units, depth_extra = self._decompose(depth)

        return GenerationSettings(
            name=self.name_var.get(), width_mm=width, depth_mm=depth,
            dimension_input_mode=input_mode,
            width_units=width_units, width_extra_mm=width_extra,
            depth_units=depth_units, depth_extra_mm=depth_extra,
            height_mm=float(self.height_custom_var.get()), anchor=ANCHORS[self.anchor_var.get()],
            shape_mode=MODES[self.mode_var.get()],
            walls=WallSettings(back=self.wall_back.get(), right=self.wall_right.get(), front=self.wall_front.get(), left=self.wall_left.get()),
            structure_profile=STRUCTURE_PROFILES[self.structure_profile_var.get()],
            base_frame_style=BASE_FRAME_STYLES[self.base_frame_style_var.get()],
            clearance_total_mm=float(self.clearance_var.get()), wall_thickness_mm=float(self.wall_thickness_var.get()),
            floor_thickness_mm=float(self.floor_thickness_var.get()), corner_radius_mm=float(self.corner_radius_var.get()),
            min_partial_cell_mm=float(self.min_partial_var.get()),
            anti_warp_ears=self.anti_warp_ears_var.get(),
            ear_thickness_mm=float(self.ear_thickness_var.get()), ear_width_mm=float(self.ear_width_var.get()),
            ear_length_mm=float(self.ear_length_var.get()), generate_baseplate=self.baseplate_var.get(),
            export_3mf=self.export_3mf.get(), export_stl=self.export_stl.get(), export_step=self.export_step.get(),
            output_dir=self.output_var.get(),
        )

    def _apply(self, s: GenerationSettings):
        self._syncing_dimensions = True
        try:
            self.name_var.set(s.name)
            self.dimension_mode_var.set(DIMENSION_MODE_LABEL.get(s.dimension_input_mode, "実寸mm"))
            self.width_var.set(self._fmt(s.requested_width_mm))
            self.depth_var.set(self._fmt(s.requested_depth_mm))
            self.width_units_var.set(str(s.width_units))
            self.width_extra_var.set(self._fmt(s.width_extra_mm))
            self.depth_units_var.set(str(s.depth_units))
            self.depth_extra_var.set(self._fmt(s.depth_extra_mm))
            self.height_custom_var.set(str(s.height_mm))
            self.height_preset_var.set(str(int(s.height_mm)) if s.height_mm in (7, 14, 21, 28, 35, 42) else "任意")
            self.anchor_var.set(ANCHOR_LABEL[s.anchor])
            self.mode_var.set(MODE_LABEL[s.shape_mode])
            self.wall_back.set(s.walls.back)
            self.wall_right.set(s.walls.right)
            self.wall_front.set(s.walls.front)
            self.wall_left.set(s.walls.left)
            self.structure_profile_var.set(STRUCTURE_PROFILE_LABEL.get(s.structure_profile, "カスタム"))
            self.base_frame_style_var.set(BASE_FRAME_STYLE_LABEL.get(s.base_frame_style, "しっかり版（太枠）"))
            self.anti_warp_ears_var.set(s.anti_warp_ears)
            self.clearance_var.set(str(s.clearance_total_mm))
            self.wall_thickness_var.set(str(s.wall_thickness_mm))
            self.floor_thickness_var.set(str(s.floor_thickness_mm))
            self.corner_radius_var.set(str(s.corner_radius_mm))
            self.min_partial_var.set(str(s.min_partial_cell_mm))
            self.ear_thickness_var.set(str(s.ear_thickness_mm))
            self.ear_width_var.set(str(s.ear_width_mm))
            self.ear_length_var.set(str(s.ear_length_mm))
            self.baseplate_var.set(s.generate_baseplate)
            self.export_3mf.set(s.export_3mf)
            self.export_stl.set(s.export_stl)
            self.export_step.set(s.export_step)
            self.output_var.set(s.output_dir)
            self._last_dimension_mode = self.dimension_mode_var.get()
        finally:
            self._syncing_dimensions = False
        self._update_dimension_controls()
        self._dimension_value_changed()
        self._update_mode()
        self._base_style_selected()

    def _save(self):
        try:
            s = self._settings()
            s.validate()
        except Exception as e:
            messagebox.showerror("設定エラー", str(e))
            return
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON", "*.json")], initialdir=ROOT / "presets", initialfile=f"{s.name}.json")
        if path:
            save_preset(s, path)
            self._write(f"プリセット保存: {path}")

    def _load(self):
        path = filedialog.askopenfilename(filetypes=[("JSON", "*.json")], initialdir=ROOT / "presets")
        if not path:
            return
        try:
            self._apply(load_preset(path))
            self._write(f"プリセット読込: {path}")
        except Exception as e:
            messagebox.showerror("読込エラー", str(e))

    def _manual(self):
        candidates = [ROOT / "manual_ja.html", ROOT / "docs" / "manual.html"]
        for manual in candidates:
            if manual.exists():
                os.startfile(manual)
                return
        messagebox.showinfo("説明書", str(ROOT / "README_JA.md"))

    def _start(self):
        try:
            settings = self._settings()
            settings.validate()
        except Exception as e:
            messagebox.showerror("設定エラー", str(e))
            return
        self.start_button.configure(state="disabled")
        self.log.delete("1.0", "end")
        self.status_var.set("生成中…")
        threading.Thread(target=self._worker, args=(settings,), daemon=True).start()

    def _worker(self, settings: GenerationSettings):
        try:
            if settings.dimension_input_mode == "units_plus_mm":
                self.queue.put(("log", f"指定寸法: X={settings.width_units}U＋{self._fmt(settings.width_extra_mm)} mm / Y={settings.depth_units}U＋{self._fmt(settings.depth_extra_mm)} mm"))
            else:
                self.queue.put(("log", f"指定寸法: {settings.requested_width_mm:.3f} × {settings.requested_depth_mm:.3f} mm"))
            self.queue.put(("log", f"完成外形: {settings.finished_width_mm:.3f} × {settings.finished_depth_mm:.3f} mm"))
            self.queue.put(("log", f"基準点: {ANCHOR_LABEL[settings.anchor]} / 形状: {MODE_LABEL[settings.shape_mode]}"))
            self.queue.put(("log", f"構造: {STRUCTURE_PROFILE_LABEL[settings.structure_profile]} / ベース: {BASE_FRAME_STYLE_LABEL[settings.base_frame_style]} / 耳: {'あり' if settings.anti_warp_ears else 'なし'}"))
            models = generate_models(settings)
            self.queue.put(("log", json.dumps(models.summary["layout"], ensure_ascii=False)))
            paths = export_all(settings, models, lambda x: self.queue.put(("log", x)))
            self.queue.put(("done", paths))
        except Exception:
            self.queue.put(("error", traceback.format_exc()))

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "log":
                    self._write(payload)
                elif kind == "done":
                    for p in payload:
                        self._write(f"出力: {p}")
                    self.status_var.set(f"完了。{len(payload)}ファイルを出力しました。")
                    self.start_button.configure(state="normal")
                    messagebox.showinfo("生成完了", f"出力先:\n{self.output_var.get()}")
                elif kind == "error":
                    self._write(payload)
                    self.status_var.set("生成に失敗しました。ログを確認してください。")
                    self.start_button.configure(state="normal")
                    messagebox.showerror("生成エラー", payload.splitlines()[-1])
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)

    def _write(self, text):
        self.log.insert("end", str(text) + "\n")
        self.log.see("end")


if __name__ == "__main__":
    App().mainloop()
