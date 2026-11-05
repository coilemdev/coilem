"""Serve the opt-in source checkout UI locally for the outrunner workstream."""
import argparse
from pathlib import Path

import uvicorn

from backend.experimental.outrunner_runtime import enabled
from backend.public_main import create_app

if __name__ == "__main__":
    if not enabled():
        raise SystemExit("Start with COILEM_EXPERIMENTAL_OUTRUNNER=1 in this source checkout")
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=58151)
    parser.add_argument("--bundle", type=Path, default=root/"frontend/dist-public-boundary")
    args = parser.parse_args()
    uvicorn.run(create_app(bound_port=args.port, ui_bundle=args.bundle.resolve()), host="127.0.0.1", port=args.port)
