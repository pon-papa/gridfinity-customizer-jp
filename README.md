# gridfinity-customizer-jp
半端寸法に対応した軽量Gridfinity箱・ベースフレーム生成アプリ

## このリポジトリの内容

配布版 1.2.1 のソースです。使い方と画面の説明は [README_JA.md](README_JA.md) と
[manual_ja.html](manual_ja.html) にあります。

- `src/gridfinity_customizer/` — 寸法モデル・レイアウト・形状生成・3MF/STL/STEP 書き出し
- `app.py` — 画面（Tkinter）
- `src/gridfinity_customizer/cli.py` — プリセット JSON から生成する CLI
- `presets/sample_*.json` — 見本プリセット
- `selftest.py` — 3MF/STL の実生成試験（出力は OS の一時フォルダー）

```
setup.bat          初回だけ（.venv を作り numpy / shapely / trimesh を入れる）
launch.bat         画面を開く
run_cli.bat presets\sample_units_plus_mm.json
```

STEP 出力は任意で、CadQuery（`install_step.bat`）が入っているときだけ使えます。

生成物（`output/` の 3MF / STL / STEP）と見本 3MF（`samples/`）は Git では管理せず、
配布 ZIP に同梱しています。
