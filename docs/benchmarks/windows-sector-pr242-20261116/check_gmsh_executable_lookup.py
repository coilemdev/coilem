"""Reproduce Windows executable lookup after Gmsh without editing PR sources."""
import json
from pathlib import Path
import shutil
import subprocess
import traceback

RUN = Path(__file__).resolve().parent
paths = {name: shutil.which(name) for name in ("node", "git")}
results = []


def check(phase):
    for name, absolute in paths.items():
        for mode, command in (("bare_name", name), ("absolute_path", absolute)):
            entry = {"phase": phase, "name": name, "mode": mode}
            try:
                result = subprocess.run([command, "--version"], capture_output=True, text=True, check=True)
                entry.update(returncode=result.returncode, stdout=result.stdout.strip())
            except Exception as error:
                entry.update(error=str(error), traceback=traceback.format_exc())
            results.append(entry)


check("before_gmsh")
import gmsh
gmsh.initialize()
gmsh.finalize()
check("after_gmsh")
(RUN / "gmsh-executable-lookup.json").write_text(json.dumps(results, indent=2))
for entry in results:
    print(entry["phase"], entry["name"], entry["mode"], entry.get("stdout", entry.get("error")))
