"""Export the pinned Pyleecan Prius analytic curves; optional Pyleecan runtime."""

import argparse
import cmath
import hashlib
import json
import math
import re
from pathlib import Path

from pyleecan.Functions.load import load

MACHINE_SHA256 = "a8922c4f712c38696e6dcf7e800ad5615a0b22dd45a802574f749a59945c8036"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--machine", type=Path, required=True)
    ap.add_argument("--fem", type=Path, required=True, help="Retained zero-angle no-load FEMM drawing")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    assert hashlib.sha256(args.machine.read_bytes()).hexdigest() == MACHINE_SHA256
    machine = load(str(args.machine))
    raw = args.fem.read_text(encoding="latin-1")
    blocks = re.findall(r"<BeginBlock>(.*?)<EndBlock>", raw, re.S)
    magnetic = {i + 1 for i, b in enumerate(blocks) if float(re.search(r"<H_c>\s*=\s*([^\n]+)", b)[1]) != 0}
    labels = [[float(x) for x in row.split()] for row in raw.split("[NumBlockLabels]")[1].splitlines()[1:] if row.strip()]
    rotation = cmath.exp(-1j * math.pi / 48)

    def xy(z):
        z = complex(z) * rotation * 1000
        return [z.real, z.imag]

    def line_export(line):
        start, end = line.get_begin(), line.get_end()
        if not hasattr(line, "get_center"):
            return [{"kind": "line", "start": xy(start), "end": xy(end)}]
        center = line.get_center()
        angle = line.get_angle()
        n = max(1, math.ceil(abs(angle) / (math.pi / 2 + 1e-10)))
        points = [start] + [center + (start - center) * cmath.exp(1j * angle * i / n) for i in range(1, n)] + [end]
        return [{"kind": "arc", "start": xy(a), "end": xy(b), "center": xy(center),
                 "radius_mm": abs(start - center) * 1000, "sweep_deg": math.degrees(angle) / n}
                for a, b in zip(points, points[1:])]

    def loop_export(surface):
        return [segment for line in surface.line_list for segment in line_export(line)]

    surfaces = []
    for side in ("stator", "rotor"):
        for surface in getattr(machine, side).build_geometry(sym=1):
            if hasattr(surface, "out_surf"):
                surfaces.append({"label": surface.label, "side": side,
                                 "loops": [loop_export(surface.out_surf), loop_export(surface.in_surf)]})
                continue
            entry = {"label": surface.label, "side": side, "loops": [loop_export(surface)]}
            if "Winding" in surface.label:
                slot = int(re.search(r"-S(\d+)$", surface.label)[1])
                entry["label"] = re.sub(r"-S(\d+)$", r"-slot\1", surface.label)
                values = machine.stator.winding.wind_mat[0, 0, slot, :]
                phase = next(i for i, value in enumerate(values) if value)
                entry["winding"] = {"slot": slot, "phase": "ABC"[phase], "direction": "in" if values[phase] > 0 else "out"}
            elif "HoleMag" in surface.label:
                ref = complex(surface.point_ref)
                nearest = min((v for v in labels if int(v[2]) in magnetic), key=lambda v: abs(complex(v[0], v[1]) - ref))
                assert abs(complex(nearest[0], nearest[1]) - ref) < 1e-8
                entry["magnetization_angle_deg"] = (nearest[5] - 3.75) % 360
            surfaces.append(entry)
    # SlotW11 H1=0 puts the copper top and the shoe ledges on the same
    # straight line. Partition their shared lines at every incident endpoint
    # so independent region loops share exact edges instead of overlapping
    # partially. This changes topology bookkeeping, not the analytic shape.
    points = {tuple(round(v, 8) for v in s[p]): s[p] for surface in surfaces for loop in surface["loops"]
              for s in loop for p in ("start", "end")}
    for surface in surfaces:
        for index, loop in enumerate(surface["loops"]):
            partitioned = []
            for segment in loop:
                if segment["kind"] == "arc":
                    partitioned.append(segment)
                    continue
                a, b = complex(*segment["start"]), complex(*segment["end"])
                cuts = [(0., segment["start"]), (1., segment["end"])]
                for point in points.values():
                    t = (complex(*point) - a) / (b - a)
                    if abs(t.imag) * abs(b - a) < 1e-8 and 1e-8 < t.real < 1 - 1e-8:
                        cuts.append((t.real, point))
                cuts.sort(key=lambda item: item[0])
                partitioned.extend({"kind": "line", "start": x[1], "end": y[1]} for x, y in zip(cuts, cuts[1:]))
            surface["loops"][index] = partitioned
    output = {"schema": "coilem.published_prius_geometry/v1", "source_machine_sha256": MACHINE_SHA256,
              "license": "Apache-2.0", "attribution": "Copyright 2018 EOMYS ENGINEERING, 2019-2020 Pyleecan developers",
              "modification_notice": ("coilEM: converted SI analytic surfaces to mm, rotated -3.75 degrees and partitioned shared edges. "
                                      "Winding labels use explicit slot numbers. Runtime reflects into its clockwise frame."),
              "source_url": "https://github.com/Eomys/pyleecan/blob/cbfe7be3b8a50dbcdecccb655cc7ea74f2443890/pyleecan/Data/Machine/Toyota_Prius.json",
              "source_FEMM_sha256": hashlib.sha256(args.fem.read_bytes()).hexdigest(),
              "coordinate_rotation_deg": -3.75, "units": "mm", "surfaces": surfaces}
    args.out.write_text(json.dumps(output, separators=(",", ":"), allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    print(f"Exported {len(surfaces)} exact analytic surfaces")


if __name__ == "__main__":
    main()
