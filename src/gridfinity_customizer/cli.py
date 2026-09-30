from __future__ import annotations

import argparse
from pathlib import Path

from .exporters import export_all
from .generator import generate_models
from .presets import load_preset


def main() -> int:
    parser = argparse.ArgumentParser(description="Gridfinity Customizer JP CLI")
    parser.add_argument("preset", type=Path, help="parameters.json またはプリセットJSON")
    args = parser.parse_args()
    settings = load_preset(args.preset)
    models = generate_models(settings)
    for path in export_all(settings, models, print):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
