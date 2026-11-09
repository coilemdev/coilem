"""The public policy only accepts or rejects a request, so it is not a physics source (#194).

`backend/public_policy.py` left the hashed physics sources on this guarantee:
for every registered benchmark request, the config that is solved is exactly
what `MotorConfig` validation gives, and every one of them is accepted.
A policy change that alters either fails here instead of passing unmeasured.
"""

import pytest

from backend.benchmark_suite.cli import inputs
from backend.benchmark_suite.contract import ROOT, SPEC
from backend.benchmark_suite.physics import physics_sources
from backend.benchmark_suite.references import load_suite
from backend.models.config import MotorConfig
from backend.public_policy import parse_public_motor_config, parse_public_solve_request
from tools.benchmark_prius import jobs as prius_jobs
from tools.release.qualification import PRIUS_EXTRA_PHYSICS

POLICY = "backend/public_policy.py"
# The registered A-D suite, and the proposed cogging and outer-rotor suites measured with it.
SUITES = (SPEC, ROOT / "benchmarks/abcd-v1.7/benchmark_spec.json", ROOT / "benchmarks/abcd-v1.8/benchmark_spec.json")
# No registered request is planned as unsupported: protocol 1.10.0 retired the
# ORNL Prius placeholder, and tests/test_benchmark_protocol_1_10.py keeps its rejection covered.


def _requests():
    for path in SUITES:
        spec = load_suite(path)
        configs, _, _ = inputs(spec, spec["cases"])
        for case in spec["cases"]:
            for job in case["jobs"]:
                yield pytest.param(case, configs[case["id"], job["stage"]], id=f"{path.parent.name}:{case['id']}:{job['stage']}")


def test_the_policy_is_outside_the_physics_identity():
    assert POLICY not in physics_sources(ROOT) and POLICY not in PRIUS_EXTRA_PHYSICS


@pytest.mark.parametrize(("case", "request_config"), list(_requests()))
def test_the_policy_accepts_each_registered_request_and_leaves_its_config_alone(case, request_config):
    experimental = bool(case.get("experimental_rotor"))
    config, mesh_key, solver = parse_public_solve_request(request_config, allow_experimental_rotors=experimental)
    assert config == MotorConfig.model_validate(request_config)
    assert (mesh_key, solver) == (None, "magneto2d")


def test_the_policy_accepts_each_prius_job_and_leaves_its_config_alone():
    names = []
    for name, body in prius_jobs(curve=True, refinement=True):
        assert parse_public_motor_config(body) == MotorConfig.model_validate(body)
        names.append(name)
    assert len(names) == len(set(names)) == 17
