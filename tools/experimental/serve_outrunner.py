"""Serve the opt-in source checkout UI locally for the outrunner workstream."""
from pathlib import Path

import uvicorn

from backend.experimental.outrunner_runtime import enabled
from backend.public_main import create_app

if __name__ == "__main__":
    if not enabled():
        raise SystemExit("Start with COILEM_EXPERIMENTAL_OUTRUNNER=1 in this source checkout")
    root = Path(__file__).resolve().parents[2]
    uvicorn.run(create_app(bound_port=58151, ui_bundle=root/"frontend/dist-public-boundary"), host="127.0.0.1", port=58151)
