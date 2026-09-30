# -*- coding: utf-8 -*-
"""Gridfinity Customizer JP を画面なしで使う入口（ToolDock Connector v1 / JSON CLI）。

    .venv\\Scripts\\python.exe tooldock_cli.py capabilities         --input-json -
    .venv\\Scripts\\python.exe tooldock_cli.py generate             --input-json -
    .venv\\Scripts\\python.exe tooldock_cli.py generate_from_preset --input-json -

- 引数は標準入力の JSON オブジェクト1つ。標準出力には JSON を1行だけ出す
    成功: {"ok": true, "result": {...}}
    失敗: {"ok": false, "error": {"code": "...", "message": "..."}}
- 形状の生成と書き出しは、画面と同じ処理（generate_models / export_all）をそのまま使う。
  入力は画面で設定できる項目だけで、既定値も画面と同じ
- 生成は OS の一時フォルダーで行い、出来上がったファイルだけを保存先へ移す。
  同じ名前のファイルが1つでもあれば、overwrite を指定しない限り何も書かない
- プリセット JSON は読むだけ。プリセットに書かれた出力先（output_dir）は使わない

終了コード: 0=成功 / 1=処理できなかった / 2=使い方の誤り
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gridfinity_customizer import __version__                          # noqa: E402
from gridfinity_customizer.exporters import export_all, safe_name      # noqa: E402
from gridfinity_customizer.generator import generate_models            # noqa: E402
from gridfinity_customizer.model import (GRID_PITCH_MM, GenerationSettings,  # noqa: E402
                                         WallSettings)
from gridfinity_customizer.presets import load_preset, save_preset     # noqa: E402

SHAPES = ("box", "tile", "baseplate_only")
ANCHORS = ("left_back", "right_back", "left_front", "right_front")
DIMENSION_MODES = ("millimeters", "units_plus_mm")
PROFILES = ("lightweight", "robust", "custom")
BASE_FRAME_STYLES = ("lightweight", "robust")
FORMATS = ("3mf", "stl", "step")
HEIGHT_PRESETS_MM = (7, 14, 21, 28, 35, 42)

# 構造プロファイルを選んだときに画面が入れる値（app.py _profile_selected と同じ）。
# custom は画面の初期値のまま = lightweight と同じ値から始まる。
PROFILE_DEFAULTS = {
    "lightweight": {"wall_thickness_mm": 1.9, "floor_thickness_mm": 0.225, "corner_radius_mm": 4.0,
                    "base_frame_style": "lightweight", "anti_warp_ears": True},
    "robust": {"wall_thickness_mm": 1.2, "floor_thickness_mm": 1.2, "corner_radius_mm": 1.5,
               "base_frame_style": "robust", "anti_warp_ears": False},
    "custom": {"wall_thickness_mm": 1.9, "floor_thickness_mm": 0.225, "corner_radius_mm": 4.0,
               "base_frame_style": "lightweight", "anti_warp_ears": True},
}
# 画面の初期値（app.py _make_vars）。
COMMON_DEFAULTS = {
    "height_mm": 21.0, "anchor": "left_back", "shape": "box",
    "wall_back": True, "wall_right": True, "wall_front": True, "wall_left": True,
    "generate_baseplate": True, "clearance_total_mm": 0.4, "min_partial_cell_mm": 12.0,
    "ear_thickness_mm": 0.20, "ear_width_mm": 3.0, "ear_length_mm": 13.0,
}
# 数値の範囲。下限と、アプリにある上限は GenerationSettings.validate() と同じ。
# アプリに上限が無い項目の上限は、この入口だけの暴走防止（CONNECTOR_LIMIT）。
LIMITS = {
    "width_mm": (0.0, 600.0), "depth_mm": (0.0, 600.0),
    "width_units": (0, 14), "depth_units": (0, 14),
    "width_extra_mm": (0.0, 600.0), "depth_extra_mm": (0.0, 600.0),
    "height_mm": (4.75, 300.0),
    "clearance_total_mm": (0.0, 5.0),
    "wall_thickness_mm": (0.4, 5.0),
    "floor_thickness_mm": (0.16, 5.0),
    "corner_radius_mm": (0.0, 20.0),
    "min_partial_cell_mm": (4.0, 42.0),
    "ear_thickness_mm": (0.12, 1.0),
    "ear_width_mm": (1.0, 8.0),
    "ear_length_mm": (3.0, 25.0),
}
CONNECTOR_LIMIT = ("width_mm", "depth_mm", "width_units", "depth_units", "width_extra_mm",
                   "depth_extra_mm", "height_mm", "clearance_total_mm", "min_partial_cell_mm")
MAX_REQUESTED_MM = 600.0
MAX_PRESET_BYTES = 256 * 1024
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}

GENERATE_KEYS = {"name", "output_folder", "shape", "dimension_input_mode", "width_mm", "depth_mm",
                 "width_units", "width_extra_mm", "depth_units", "depth_extra_mm", "height_mm",
                 "anchor", "wall_back", "wall_right", "wall_front", "wall_left",
                 "structure_profile", "base_frame_style", "clearance_total_mm", "wall_thickness_mm",
                 "floor_thickness_mm", "corner_radius_mm", "min_partial_cell_mm", "anti_warp_ears",
                 "ear_thickness_mm", "ear_width_mm", "ear_length_mm", "generate_baseplate",
                 "formats", "overwrite"}
PRESET_KEYS = {"preset", "output_folder", "overwrite"}


class CliError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _step_available() -> bool:
    return importlib.util.find_spec("cadquery") is not None


# ---------------------------------------------------------------- capabilities
def capabilities(args: dict) -> dict:
    if args:
        raise CliError("invalid_arguments", "capabilities に引数はありません。")
    formats = ["3mf", "stl"] + (["step"] if _step_available() else [])
    return {
        "tool": "gridfinity-customizer-jp",
        "version": __version__,
        "grid_pitch_mm": GRID_PITCH_MM,
        "shapes": {"box": "箱／トレー（壁を個別指定）",
                   "tile": "壁なしタイル／かさ上げ台",
                   "baseplate_only": "ベースフレームのみ（格子枠）"},
        "anchors": list(ANCHORS),
        "dimension_input_modes": {"millimeters": "実寸 mm（width_mm / depth_mm）",
                                  "units_plus_mm": "ユニット数＋追加 mm（1U = 42 mm）"},
        "structure_profiles": {k: dict(v) for k, v in PROFILE_DEFAULTS.items()},
        "base_frame_styles": list(BASE_FRAME_STYLES),
        "height_presets_mm": list(HEIGHT_PRESETS_MM),
        "defaults": dict(COMMON_DEFAULTS, structure_profile="lightweight", formats=["3mf"]),
        "limits": {k: list(v) for k, v in LIMITS.items()},
        "connector_limits": list(CONNECTOR_LIMIT),
        "formats": formats,
        "step_available": "step" in formats,
        "outputs": ["<name>_container.*（箱）", "<name>_baseplate.*（ベースフレーム）",
                    "<name>_set.3mf（箱とベースを並べたもの）", "<name>_parameters.json",
                    "<name>_validation.json", "<name>_layout.svg"],
        "notes": ["外周クリアランスは、指定した全体寸法から差し引いて完成寸法になる",
                  "旧版（v1.1.5 以前）のプリセットは、しっかり版として読み込まれる",
                  "connector_limits の上限はこの入口だけの制限（アプリ本体には上限なし）",
                  "STEP は CadQuery が入っているときだけ使える"],
    }


# ---------------------------------------------------------------- checks
def _number(args: dict, key: str, default=None, integer: bool = False):
    value = args.get(key, default)
    if value is None:
        raise CliError("invalid_arguments", f"{key} が必要です。")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or \
            (isinstance(value, float) and not math.isfinite(value)):
        raise CliError("invalid_arguments", f"{key} は数値です。")
    if integer and int(value) != value:
        raise CliError("invalid_arguments", f"{key} は整数です。")
    low, high = LIMITS[key]
    if not low <= value <= high:
        raise CliError("invalid_arguments", f"{key} は {low}〜{high} です。")
    return int(value) if integer else float(value)


def _choice(args: dict, key: str, choices, default):
    value = args.get(key, default)
    if value not in choices:
        raise CliError("invalid_arguments", f"{key} は {list(choices)} のどれかです。")
    return value


def _flag(args: dict, key: str, default: bool) -> bool:
    value = args.get(key, default)
    if not isinstance(value, bool):
        raise CliError("invalid_arguments", f"{key} は true / false です。")
    return value


def _name(value) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 60:
        raise CliError("invalid_arguments", "name は1〜60文字です。")
    if any(ord(ch) < 32 for ch in value):
        raise CliError("invalid_arguments", "name に制御文字は使えません。")
    base = safe_name(value)
    if base.startswith(".") or base.rstrip(". ") != base or base.split(".")[0].upper() in _RESERVED:
        raise CliError("invalid_arguments", "name はファイル名として使えない形です。")
    return value.strip()


def _output_folder(value) -> Path:
    if not isinstance(value, str) or not os.path.isabs(value):
        raise CliError("invalid_arguments", "output_folder は保存先フォルダーの絶対パスです。")
    folder = Path(os.path.abspath(value))
    if not folder.is_dir():
        raise CliError("invalid_output", f"保存先のフォルダーがありません: {folder}")
    inside_app = folder == ROOT or ROOT in folder.parents
    inside_output = folder == ROOT / "output" or (ROOT / "output") in folder.parents
    if inside_app and not inside_output:
        raise CliError("invalid_output", "アプリ自身のフォルダーには保存しません（output フォルダーは可）。")
    return folder


def _formats(args: dict) -> list[str]:
    formats = args.get("formats", ["3mf"])
    if not isinstance(formats, list) or not formats or len(set(formats)) != len(formats) \
            or set(formats) - set(FORMATS):
        raise CliError("invalid_arguments", f"formats は {list(FORMATS)} から重複なく選びます。")
    if "step" in formats and not _step_available():
        raise CliError("step_unavailable",
                       "STEP には CadQuery が必要です（install_step.bat）。3mf / stl を選んでください。")
    return formats


# ---------------------------------------------------------------- settings
def _settings_from_arguments(args: dict) -> tuple[GenerationSettings, list[str]]:
    unknown = set(args) - GENERATE_KEYS
    if unknown:
        raise CliError("invalid_arguments", f"使えない項目があります: {sorted(unknown)}")
    notes = []
    name = _name(args.get("name"))
    shape = _choice(args, "shape", SHAPES, COMMON_DEFAULTS["shape"])
    mode = _choice(args, "dimension_input_mode", DIMENSION_MODES, "millimeters")
    if mode == "units_plus_mm":
        for key in ("width_mm", "depth_mm"):
            if key in args:
                raise CliError("invalid_arguments", f"units_plus_mm では {key} ではなく *_units / *_extra_mm を使います。")
        width_units = _number(args, "width_units", integer=True)
        depth_units = _number(args, "depth_units", integer=True)
        width_extra = _number(args, "width_extra_mm", 0.0)
        depth_extra = _number(args, "depth_extra_mm", 0.0)
        width = width_units * GRID_PITCH_MM + width_extra
        depth = depth_units * GRID_PITCH_MM + depth_extra
    else:
        for key in ("width_units", "depth_units", "width_extra_mm", "depth_extra_mm"):
            if key in args:
                raise CliError("invalid_arguments", f"millimeters では {key} ではなく width_mm / depth_mm を使います。")
        width = _number(args, "width_mm")
        depth = _number(args, "depth_mm")
        # 画面と同じ分解（app.py _decompose）
        width_units = int(math.floor((width + 1e-9) / GRID_PITCH_MM))
        depth_units = int(math.floor((depth + 1e-9) / GRID_PITCH_MM))
        width_extra = width - width_units * GRID_PITCH_MM
        depth_extra = depth - depth_units * GRID_PITCH_MM
        width_extra = 0.0 if abs(width_extra) < 1e-9 else width_extra
        depth_extra = 0.0 if abs(depth_extra) < 1e-9 else depth_extra
    if width > MAX_REQUESTED_MM or depth > MAX_REQUESTED_MM:
        raise CliError("invalid_arguments", f"横幅と奥行はそれぞれ {MAX_REQUESTED_MM:g} mm までです（入口の上限）。")

    profile = _choice(args, "structure_profile", PROFILES, "lightweight")
    pd = PROFILE_DEFAULTS[profile]
    base_style = _choice(args, "base_frame_style", BASE_FRAME_STYLES, pd["base_frame_style"])
    ears_default = pd["anti_warp_ears"] if base_style == "lightweight" else False
    ears = _flag(args, "anti_warp_ears", ears_default)
    if ears and base_style == "robust":
        # 画面でも、しっかり版のベースフレームでは耳を選べない
        raise CliError("invalid_arguments", "しっかり版（robust）のベースフレームには、はがれ防止耳を付けられません。")
    generate_baseplate = _flag(args, "generate_baseplate", COMMON_DEFAULTS["generate_baseplate"])
    if shape == "baseplate_only" and not generate_baseplate:
        raise CliError("invalid_arguments", "baseplate_only ではベースフレームを必ず作ります（generate_baseplate は true）。")
    walls = WallSettings(**{side: _flag(args, f"wall_{side}", True)
                            for side in ("back", "right", "front", "left")})
    if shape != "box" and any(f"wall_{s}" in args for s in ("back", "right", "front", "left")):
        notes.append("壁の指定は shape が box のときだけ使われます（画面と同じ）。")
    formats = _formats(args)

    settings = GenerationSettings(
        name=name, width_mm=width, depth_mm=depth, dimension_input_mode=mode,
        width_units=width_units, width_extra_mm=width_extra,
        depth_units=depth_units, depth_extra_mm=depth_extra,
        height_mm=_number(args, "height_mm", COMMON_DEFAULTS["height_mm"]),
        anchor=_choice(args, "anchor", ANCHORS, COMMON_DEFAULTS["anchor"]),
        shape_mode=shape, walls=walls,
        structure_profile=profile, base_frame_style=base_style,
        clearance_total_mm=_number(args, "clearance_total_mm", COMMON_DEFAULTS["clearance_total_mm"]),
        wall_thickness_mm=_number(args, "wall_thickness_mm", pd["wall_thickness_mm"]),
        floor_thickness_mm=_number(args, "floor_thickness_mm", pd["floor_thickness_mm"]),
        corner_radius_mm=_number(args, "corner_radius_mm", pd["corner_radius_mm"]),
        min_partial_cell_mm=_number(args, "min_partial_cell_mm", COMMON_DEFAULTS["min_partial_cell_mm"]),
        anti_warp_ears=ears,
        ear_thickness_mm=_number(args, "ear_thickness_mm", COMMON_DEFAULTS["ear_thickness_mm"]),
        ear_width_mm=_number(args, "ear_width_mm", COMMON_DEFAULTS["ear_width_mm"]),
        ear_length_mm=_number(args, "ear_length_mm", COMMON_DEFAULTS["ear_length_mm"]),
        generate_baseplate=generate_baseplate,
        export_3mf="3mf" in formats, export_stl="stl" in formats, export_step="step" in formats,
        output_dir="",
    )
    return settings, notes


def _settings_from_preset(value) -> GenerationSettings:
    if not isinstance(value, str) or not os.path.isabs(value):
        raise CliError("invalid_arguments", "preset はプリセット JSON の絶対パスです。")
    path = Path(value)
    if path.suffix.lower() != ".json":
        raise CliError("invalid_arguments", "preset は .json のファイルです。")
    if not path.is_file():
        raise CliError("invalid_preset", f"プリセットが見つかりません: {path}")
    if path.stat().st_size > MAX_PRESET_BYTES:
        raise CliError("invalid_preset", "プリセットが大きすぎます。")
    try:
        settings = load_preset(path)                    # 読むだけ
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise CliError("invalid_preset", f"プリセットとして読めません: {exc}") from None
    if not isinstance(settings.name, str):
        raise CliError("invalid_preset", "プリセットの name が文字列ではありません。")
    _name(settings.name)
    return settings


# ---------------------------------------------------------------- generation
def _write_new(source: Path, target: Path, overwrite: bool) -> None:
    """途中で止まっても壊れたファイルを残さないよう、一時名で書いてから置き換える。"""
    if target.exists() and not overwrite:
        raise CliError("output_exists", f"同じ名前のファイルがあります: {target}")
    fd, tmp = tempfile.mkstemp(prefix=".tooldock_", suffix=".part", dir=str(target.parent))
    os.close(fd)
    try:
        shutil.copyfile(source, tmp)
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _produce(settings: GenerationSettings, folder: Path, overwrite: bool, notes: list[str]) -> dict:
    try:
        settings.validate()                              # アプリ自身の検査（画面と同じ）
    except (ValueError, TypeError) as exc:
        raise CliError("invalid_dimensions", str(exc)) from None
    if settings.requested_width_mm > MAX_REQUESTED_MM or settings.requested_depth_mm > MAX_REQUESTED_MM \
            or settings.height_mm > LIMITS["height_mm"][1]:
        raise CliError("invalid_dimensions", "寸法が入口の上限を超えています（capabilities の limits）。")
    if settings.export_step and not _step_available():
        raise CliError("step_unavailable", "STEP には CadQuery が必要です（install_step.bat）。")

    started = time.time()
    base = safe_name(settings.name)
    with tempfile.TemporaryDirectory(prefix="gridfinity_tooldock_") as work:
        settings.output_dir = work
        models = generate_models(settings)
        produced = export_all(settings, models)
        # parameters.json には保存先を記録する（一時フォルダーの場所を残さない）
        settings.output_dir = str(folder)
        save_preset(settings, Path(work) / f"{base}_parameters.json")

        targets = [(Path(p), folder / Path(p).name) for p in produced]
        clashes = [str(t) for _, t in targets if t.exists()]
        if clashes and not overwrite:                    # 1つでもあれば何も書かない
            raise CliError("output_exists", f"同じ名前のファイルがあります: {clashes[0]}"
                           + (f" ほか {len(clashes) - 1} 件" if len(clashes) > 1 else ""))
        created: list[Path] = []
        try:
            for source, target in targets:
                existed = target.exists()
                _write_new(source, target, overwrite)
                if not existed:
                    created.append(target)
        except BaseException:
            for path in created:                         # この呼び出しで新しく作ったものだけ戻す
                path.unlink(missing_ok=True)
            raise

    files = []
    for _, target in targets:
        kind = target.stem[len(base) + 1:] if target.stem.startswith(base + "_") else target.stem
        files.append({"kind": kind, "format": target.suffix.lstrip(".").lower(),
                      "path": str(target), "bytes": target.stat().st_size})
    summary = models.summary
    meshes = {k: summary[k] for k in ("container", "baseplate") if summary.get(k)}
    return {
        "status": "READY",
        "name": settings.name,
        "shape": settings.shape_mode,
        "files": files,
        "requested_mm": summary["requested_mm"],
        "finished_mm": summary["finished_mm"],
        "layout": summary["layout"],
        "meshes": meshes,
        "watertight": all(m["watertight_components"] for m in meshes.values()),
        "structure_profile": settings.structure_profile,
        "base_frame_style": settings.base_frame_style,
        "anti_warp_ears": settings.anti_warp_ears,
        "notes": notes,
        "version": __version__,
        "elapsed_s": round(time.time() - started, 2),
    }


def generate(args: dict) -> dict:
    settings, notes = _settings_from_arguments(args)
    folder = _output_folder(args.get("output_folder"))
    return _produce(settings, folder, _flag(args, "overwrite", False), notes)


def generate_from_preset(args: dict) -> dict:
    unknown = set(args) - PRESET_KEYS
    if unknown:
        raise CliError("invalid_arguments", f"使えない項目があります: {sorted(unknown)}")
    settings = _settings_from_preset(args.get("preset"))
    folder = _output_folder(args.get("output_folder"))
    notes = ["プリセットの output_dir は使わず、output_folder に保存しました。"]
    return _produce(settings, folder, _flag(args, "overwrite", False), notes)


COMMANDS = {"capabilities": capabilities, "generate": generate,
            "generate_from_preset": generate_from_preset}


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise CliError("usage_error", message)


def emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=True) + "\n")
    sys.stdout.flush()


def main(argv: list[str] | None = None) -> int:
    parser = Parser(prog="tooldock_cli", description="Gridfinity Customizer JP JSON CLI")
    parser.add_argument("command", choices=sorted(COMMANDS))
    parser.add_argument("--input-json", required=True, metavar="-",
                        help="引数の JSON。- で標準入力から読む")
    try:
        ns = parser.parse_args(sys.argv[1:] if argv is None else argv)
        if ns.input_json != "-":
            raise CliError("usage_error", "--input-json には - だけを指定します。")
        try:
            # 標準入力は常に UTF-8（Windows の既定 cp932 に左右されない）
            args = json.loads(sys.stdin.buffer.read().decode("utf-8") or "{}")
        except ValueError:
            raise CliError("usage_error", "標準入力が JSON ではありません。") from None
        if not isinstance(args, dict):
            raise CliError("usage_error", "引数は JSON オブジェクトです。")
        result = COMMANDS[ns.command](args)
    except CliError as e:
        emit({"ok": False, "error": {"code": e.code, "message": e.message}})
        return 2 if e.code == "usage_error" else 1
    except KeyboardInterrupt:
        emit({"ok": False, "error": {"code": "cancelled", "message": "処理を中止しました。"}})
        return 130
    except Exception as e:
        import traceback
        traceback.print_exc(file=sys.stderr)
        emit({"ok": False, "error": {"code": "internal_error", "message": f"{type(e).__name__}: {e}"}})
        return 1
    emit({"ok": True, "result": result})
    return 0


if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(errors="replace")
    raise SystemExit(main())
