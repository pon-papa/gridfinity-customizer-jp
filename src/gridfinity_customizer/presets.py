from __future__ import annotations

import json
from pathlib import Path

from .model import GenerationSettings


def save_preset(settings: GenerationSettings, path: str | Path) -> None:
    Path(path).write_text(json.dumps(settings.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


def load_preset(path: str | Path) -> GenerationSettings:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return GenerationSettings.from_dict(data)
