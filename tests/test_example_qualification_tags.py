"""The Examples menu tags a motor example Experimental exactly when Design Health rates its design experimental.

frontend/src/public/exampleDesigns.ts flags those examples with
``experimentalDesign: true``; every benchmark is tagged regardless. This test
reads the flags and the bundled design files and classifies each design with
backend/qualification.py, so a menu tag cannot drift from the app's own rating.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import backend.qualification as qualification_module
from backend.models import MotorConfig

EXAMPLES_SOURCE = Path("frontend/src/public/exampleDesigns.ts")
# Built from the app's default configuration, not from a bundled file.
DEFAULT_CONFIG_EXAMPLE = "spm-8p12s"


def _motor_examples() -> list[tuple[str, Path, bool]]:
    """(id, design file, tagged) for every motor (non-benchmark) example."""

    source = EXAMPLES_SOURCE.read_text(encoding="utf-8")
    imports = dict(re.findall(r"^import (\w+) from '\./(examples/[^?']+)\?raw';$", source, re.MULTILINE))
    files_block = source.split("const BUNDLED_EXAMPLE_FILES", 1)[1].split("};", 1)[0]
    files = {example_id: imports[name] for example_id, name in re.findall(r"'([\w-]+)': (\w+),", files_block)}
    options_block = source.split("export const PUBLIC_EXAMPLE_OPTIONS", 1)[1].split("\n];", 1)[0]
    examples = []
    for example_id, body in re.findall(r"\{\s*id: '([\w-]+)',([^{}]*)\}", options_block):
        if "benchmark: true" in body or example_id == DEFAULT_CONFIG_EXAMPLE:
            continue
        examples.append((example_id, Path("frontend/src/public") / files[example_id], "experimentalDesign: true" in body))
    return examples


def _design_config(path: Path) -> dict:
    def find(node):
        if isinstance(node, dict):
            if "stator" in node and "rotor" in node:
                return node
            for value in node.values():
                found = find(value)
                if found is not None:
                    return found
        return None

    config = find(json.loads(path.read_text(encoding="utf-8")))
    assert config is not None, f"{path} holds no motor configuration"
    return config


def test_the_menu_lists_the_motor_examples_this_test_checks() -> None:
    ids = {example_id for example_id, _, _ in _motor_examples()}
    assert {"spm-outrunner-14p12s", "ipm-10p-v-shape-medium", "spm-24p-small", "rotating-field-6p36s"} <= ids


@pytest.mark.parametrize("example_id,path,tagged", [pytest.param(*example, id=example[0]) for example in _motor_examples()])
def test_a_motor_example_is_tagged_experimental_exactly_when_its_design_is(monkeypatch, example_id, path, tagged) -> None:
    # Rate the design, not this build: a build whose physics differ from the record rates everything experimental.
    monkeypatch.setattr(qualification_module, "evidence_matches_runtime", lambda: True)
    rating = qualification_module.classify_qualification(MotorConfig.model_validate(_design_config(path)))
    assert rating["status"] in {"qualified", "experimental"}, f"{example_id}: {rating['reason']}"
    assert tagged == (rating["status"] == "experimental"), f"{example_id}: Design Health says {rating['status']}: {rating['reason']}"
