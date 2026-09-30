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

## AI・自動化から使う（任意）

**通常の利用には何も追加する必要はありません。**画面（`launch.bat`）と CLI は、
これまでどおり単体で動きます。ToolDock・MCP・AI は不要です。

AI（MCP クライアント）や自動化から使いたい場合だけ、別プロジェクトの ToolDock が
次の入口を呼び出します。アプリ本体は ToolDock を読み込みません。

```
.venv\Scripts\python.exe tooldock_cli.py capabilities         --input-json -
.venv\Scripts\python.exe tooldock_cli.py generate             --input-json -
.venv\Scripts\python.exe tooldock_cli.py generate_from_preset --input-json -
```

- 引数は標準入力の JSON、結果は標準出力に JSON で1行返します
- できることは `tooldock.tool.json`（ToolDock Connector v1）に書いてあります。
  このファイルが無くても、画面と CLI の動作には影響しません
- 出力できるのは実機で検証した 3MF / STL だけです（STEP は画面から出力してください）
- 生成は画面と同じ処理です。プリセットは読むだけで、同じ名前のファイルは
  `overwrite` を指定しない限り上書きしません

試験: `.venv\Scripts\python.exe -B tests\test_tooldock_cli.py`
