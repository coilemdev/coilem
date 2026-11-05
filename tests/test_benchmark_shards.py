"""Parallel collection must preserve full coverage and immutable measurements."""
import copy
import json
import shutil
import tarfile
from pathlib import Path

import pytest

from backend.benchmark_suite.contract import read, sha, write
from tools.benchmark_archive import archive_runtime
from tools.benchmark_shards import balance, plan
from tools.join_benchmark_runs import join_suite

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "benchmarks/windows-v050-20261102-88aae101/native"


def test_plan_is_deterministic_complete_and_nonoverlapping():
    result = plan()
    assert result == plan()
    for kind, expected in (("suite", [c["id"] for c in read(ROOT / result["suite"])["cases"]]),
                           ("prius", result["prius_jobs"])):
        actual = [name for s in result["shards"] if s["kind"] == kind for name in s["cases"]]
        assert sorted(actual) == sorted(expected) and len(actual) == len(set(actual))
    assert len(result["prius_jobs"]) == 17
    assert balance(["a", "b", "c"], {"a": 10, "b": 5, "c": 5}, 2) == [["a"], ["b", "c"]]


@pytest.fixture
def collection(tmp_path):
    spec = read(ROOT / "benchmarks/abcd-v1.6/benchmark_spec.json")
    spec["cases"] = spec["cases"][:2]
    suite = tmp_path / "suite.json"
    write(suite, spec)
    original = read(NATIVE / "run_manifest.json")
    shards = []
    for i, case in enumerate(spec["cases"]):
        folder = tmp_path / f"shard-{i}"
        manifest = copy.deepcopy(original)
        manifest["selection"].update(spec_sha256=sha(suite), case_ids=[case["id"]])
        manifest["jobs"] = [j for j in manifest["jobs"] if j["case_id"] == case["id"]]
        for job in manifest["jobs"]:
            for name in ("request", "result"):
                target = folder / job[name]
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(NATIVE / job[name], target)
        write(folder / "run_manifest.json", manifest)
        shards.append(folder)
    return shards, suite, tmp_path / "joined"


def join(collection):
    shards, suite, out = collection
    return join_suite(shards, suite=suite, bundle=ROOT / "unused", output=out)


def test_join_reproduces_real_registered_measurements_without_fields(collection):
    shards, _, out = collection
    before = [sha(p / "run_manifest.json") for p in shards]
    join(collection)
    manifest = read(out / "run_manifest.json")
    assert len(manifest["jobs"]) == 2 and len(manifest["shard_join"]["inputs"]) == 2
    assert [sha(p / "run_manifest.json") for p in shards] == before
    assert read(out / "report/benchmark_summary.json")["counts"] == {"NOT_COMPARED": 2}


@pytest.mark.parametrize("corruption", ["binary", "dependency", "smoke", "failed", "missing", "duplicate", "request", "path"])
def test_join_rejects_corrupt_or_incomplete_shards_before_writing(collection, corruption):
    shards, _, out = collection
    path = shards[1] / "run_manifest.json"
    manifest = read(path)
    if corruption == "binary":
        manifest["identity"]["binary_sha256"] = "0" * 64
    elif corruption == "dependency":
        manifest["identity"]["dependencies"]["gmsh"] = "changed"
    elif corruption == "smoke":
        manifest["smoke"] = True
    elif corruption == "failed":
        manifest["jobs"][0]["status"] = "ERROR"
    elif corruption == "missing":
        shards.pop()
    elif corruption == "duplicate":
        shards.append(shards[0])
    elif corruption == "request":
        with (shards[1] / manifest["jobs"][0]["request"]).open("a") as stream:
            stream.write(" ")
    else:
        manifest["jobs"][0]["result"] = "../outside.json"
    write(path, manifest)
    with pytest.raises((ValueError, OSError)):
        join(collection)
    assert not out.exists()


def test_archive_verifies_contents_before_removing_runtime(tmp_path):
    runtime = tmp_path / "runtime"
    (runtime / "fields").mkdir(parents=True)
    (runtime / "fields/data").write_bytes(b"original field" * 100)
    archive = tmp_path / "fields.tar.gz"
    receipt = archive_runtime(runtime, archive)
    assert not runtime.exists() and sha(archive) == receipt["sha256"]
    with tarfile.open(archive) as saved:
        assert saved.extractfile("runtime/fields/data").read() == b"original field" * 100
    assert json.loads(archive.with_name(archive.name + ".json").read_text()) == receipt


def test_archive_refuses_links_without_deleting_originals(tmp_path):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    try:
        (runtime / "link").symlink_to(tmp_path / "outside")
    except OSError:
        pytest.skip("This runner cannot create symbolic links")
    with pytest.raises(ValueError, match="symbolic"):
        archive_runtime(runtime, tmp_path / "archive.tar.gz")
    assert runtime.is_dir()
