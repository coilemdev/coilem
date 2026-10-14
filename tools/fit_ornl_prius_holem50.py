"""Map the ORNL 2004 Prius rotor pocket onto Pyleecan HoleM50 parameters (#70).

Reads ORNL/TM-2005/33 (S5) from OSTI, checked against its recorded SHA-256, and
extracts the blue rotor vector paths of Fig. 21 (PDF page 32). The rotor OD
circle (6.314 in, dimensioned) sets the drawing's centre and scale. All 8 poles
are then fitted together: one set of HoleM50 parameters, plus the drawing's
centre offset, rotation and anisotropic plot stretch. Residuals are distances
from the drawn pocket outline to the HoleM50 hole outline coilEM meshes,
reported overall, per pole and per pocket feature.

    python tools/fit_ornl_prius_holem50.py osti-885987.pdf docs/hardware-validation/ornl-prius-2004/holem50-mapping.json

Needs pypdf (a development dependency). Takes about a minute.
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from backend.geometry_drawer import _append_circular_arc, _complex_point, _pyleecan_holem50_base_points

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "docs/hardware-validation/ornl-prius-2004/sources.json"
FIGURE_PAGE = 32  # S5 Fig. 21, printed p.25
ROTOR_OD_IN, ROTOR_ID_IN = 6.314, 4.356  # dimensioned on Fig. 21
R_OUT = ROTOR_OD_IN / 2 * 25.4
POLES = 8
HOLE = ("h0", "h1", "h2", "h3", "w0", "w2", "w3", "w4")
DRAWING = ("dx", "dy", "rot", "stretch")
# Pyleecan's Toyota_Prius machine; the existing ornl_prius_2004_ipm fixture uses these.
PYLEECAN_TOYOTA_PRIUS = {"h0": 10.96, "h1": 1.5, "h2": 1.0, "h3": 6.5, "w0": 42.0, "w2": 0.0, "w3": 14.0, "w4": 18.9}
STATED_BRIDGE_MM = (0.056 + 0.060) / 2 * 25.4  # Fig. 21 callouts, 0.056 and 0.060 in
READ_OFF_ERROR_MM = {"positions": 0.5, "widths_and_lengths": 0.1}  # Phase A source audit


def figure_segments(pdf: Path) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """Blue (rotor) line segments of Fig. 21, in PDF points."""

    from pypdf import PdfReader

    expected = next(s["sha256_of_retrieved_pdf"] for s in json.loads(SOURCES.read_text(encoding="utf-8"))["sources"] if s["id"] == "S5")
    if hashlib.sha256(pdf.read_bytes()).hexdigest() != expected:
        raise SystemExit(f"{pdf} is not the ORNL/TM-2005/33 PDF recorded in {SOURCES.relative_to(ROOT)}")
    page = PdfReader(str(pdf)).pages[FIGURE_PAGE - 1]
    segments, blue, start, current, ctm = [], False, None, None, np.eye(3)

    def tx(x, y):
        p = np.array([x, y, 1.0]) @ ctm
        return float(p[0]), float(p[1])

    for operands, op in page.get_contents().operations:
        op = op.decode() if isinstance(op, bytes) else op
        if op == "cm":
            a, b, c, d, e, f = (float(v) for v in operands)
            ctm = np.array([[a, b, 0], [c, d, 0], [e, f, 1]]) @ ctm
        elif op in ("SCN", "SC", "RG"):
            values = [float(v) for v in operands if isinstance(v, (int, float))]
            blue = values[-3:] == [0, 0, 1]
        elif op in ("G", "K"):
            blue = False
        elif op == "m":
            current = start = tx(*map(float, operands))
        elif op == "l":
            point = tx(*map(float, operands))
            if blue:
                segments.append((current, point))
            current = point
        elif op == "h" and current and start:
            if blue:
                segments.append((current, start))
            current = start
    return segments


def fit_circle(points: np.ndarray) -> tuple[float, float, float]:
    x, y = points[:, 0], points[:, 1]
    a = np.c_[2 * x, 2 * y, np.ones(len(x))]
    cx, cy, c = np.linalg.lstsq(a, x**2 + y**2, rcond=None)[0]
    return float(cx), float(cy), float(np.sqrt(c + cx**2 + cy**2))


def calibrate(segments) -> dict[str, float]:
    """Centre and scale from the drawn rotor OD circle (Phase A method)."""

    points = np.array([p for s in segments for p in s])
    radius = np.hypot(*(points - points.mean(axis=0)).T)
    cx, cy, r = fit_circle(points[radius > radius.max() * 0.985])
    return {"centre_x_pt": cx, "centre_y_pt": cy, "pt_per_inch": r / (ROTOR_OD_IN / 2)}


def components(segments) -> list[list[int]]:
    """Group segments that share endpoints (0.05 pt tolerance)."""

    parent: dict = {}

    def find(a):
        while parent.setdefault(a, a) != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def key(p):
        return (round(p[0] / 0.05), round(p[1] / 0.05))

    for a, b in segments:
        ra, rb = find(key(a)), find(key(b))
        if ra != rb:
            parent[ra] = rb
    groups: dict = {}
    for i, (a, _) in enumerate(segments):
        groups.setdefault(find(key(a)), []).append(i)
    return list(groups.values())


def pocket_points(segments, calibration, step_mm: float = 0.1) -> list[np.ndarray]:
    """Densely sampled pocket outline points per pole, in mm about the OD-fit centre.

    The drawn OD dips up to about 1.1 mm inside the nominal circle, overlapping
    the pocket tips in radius, so whole connected pieces are classified: OD
    pieces reach the nominal surface (r > 79.5 mm); shaft and keyway pieces stay
    below 58 mm. Pole k spans 45k..45k+45 deg, with its d-axis at 22.5 + 45k.
    """

    scale = 25.4 / calibration["pt_per_inch"]
    origin = np.array([calibration["centre_x_pt"], calibration["centre_y_pt"]])
    mm = [((np.array(a) - origin) * scale, (np.array(b) - origin) * scale) for a, b in segments]
    keep = []
    for group in components(segments):
        radii = [math.hypot(*p) for i in group for p in mm[i]]
        if min(radii) > 58.0 and max(radii) < 79.5:
            keep.extend(group)
    poles: list[list[np.ndarray]] = [[] for _ in range(POLES)]
    for i in keep:
        a, b = mm[i]
        for t in np.linspace(0.0, 1.0, max(2, math.ceil(np.hypot(*(b - a)) / step_mm) + 1)):
            p = a + t * (b - a)
            poles[int((math.degrees(math.atan2(p[1], p[0])) % 360.0) // 45.0)].append(p)
    return [np.unique(np.round(np.array(p), 6), axis=0) for p in poles]


def holem50_outline(values: dict[str, float], od_mm: float = 2 * R_OUT) -> tuple[np.ndarray, list[str]]:
    """Closed hole outline (air pockets and magnets united) for one pole, d-axis on +x.

    Built from the same points coilEM meshes (backend.geometry_drawer), with
    W1 = 0 and H4 = 0: one connected V, no centre post and no radial bridge.
    Returns the vertices and the pocket feature of each edge.
    """

    rotor = SimpleNamespace(
        OD_mm=od_mm,
        pole_count=POLES,
        magnet_width_mm=values["w4"],
        magnet_thickness_mm=values["h3"],
        holem50_w1_mm=0.0,
        holem50_h4_mm=0.0,
        **{f"holem50_{k}_mm": v for k, v in values.items()},
    )
    z = _pyleecan_holem50_base_points(rotor)
    arc_r = od_mm / 2 - values["h1"]
    points: list[tuple[float, float]] = []
    labels: list[str] = []

    def to(key: str, label: str) -> None:
        points.append(_complex_point(z[key]))
        labels.append(label)

    def arc(start: str, end: str) -> None:
        run = [_complex_point(z[start])]
        _append_circular_arc(run, _complex_point(z[start]), _complex_point(z[end]), arc_r)
        for p in run[1:-1]:
            points.append(p)
            labels.append("tip arc (bridge H1)")

    # Edge i runs from vertex i to vertex i + 1 and carries labels[i].
    to("Z9", "tip arc (bridge H1)")
    arc("Z9", "Z1")
    for key, label in (
        ("Z1", "tip edge facing the q-axis"),
        ("Z2", "barrier inner edge"),
        ("Z3", "stop notch, tip side (H2)"),
        ("Z4", "magnet seat (W4)"),
        ("Z5", "stop notch, apex side (H2)"),
        ("Z6", "apex inner edges"),
        ("Z7", "apex inner edges"),
        ("Z6s", "stop notch, apex side (H2)"),
        ("Z5s", "magnet seat (W4)"),
        ("Z4s", "stop notch, tip side (H2)"),
        ("Z3s", "barrier inner edge"),
        ("Z2s", "tip edge facing the q-axis"),
        ("Z1s", "tip arc (bridge H1)"),
    ):
        to(key, label)
    arc("Z1s", "Z9s")
    for key in ("Z9s", "Z8cs", "Z8", "Z8c"):
        to(key, "outer edge (H0, W0)")
    points.append(_complex_point(z["Z9"]))
    vertices, edge_labels = [points[0]], []
    for p, label in zip(points[1:], labels):
        if math.dist(p, vertices[-1]) > 1e-9:
            vertices.append(p)
            edge_labels.append(label)
    return np.array(vertices), edge_labels


def place(outline: np.ndarray, pole: int, rot_deg: float) -> np.ndarray:
    angle = math.radians(22.5 + 45.0 * pole + rot_deg)
    c, s = math.cos(angle), math.sin(angle)
    return outline @ np.array([[c, s], [-s, c]])


def correct(points: np.ndarray, p: dict[str, float]) -> np.ndarray:
    """Drawing to rotor frame: remove the centre offset and the anisotropic plot stretch."""

    return (points - np.array([p["dx"], p["dy"]])) / np.array([1.0 + p["stretch"], 1.0 - p["stretch"]])


def nearest_edge(points: np.ndarray, poly: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Distance, nearest edge and signed distance (+ = drawn pocket larger than the model)."""

    a, ab = poly[:-1], poly[1:] - poly[:-1]
    t = np.clip(((points[:, None, :] - a[None]) * ab[None]).sum(axis=2) / np.maximum((ab**2).sum(axis=1), 1e-18)[None], 0.0, 1.0)
    dist = np.sqrt(((points[:, None, :] - (a[None] + t[..., None] * ab[None])) ** 2).sum(axis=2))
    edge = dist.argmin(axis=1)
    d = dist[np.arange(len(points)), edge]
    area = 0.5 * np.sum(poly[:-1, 0] * poly[1:, 1] - poly[1:, 0] * poly[:-1, 1])
    cross = ab[edge, 0] * (points[:, 1] - a[edge, 1]) - ab[edge, 1] * (points[:, 0] - a[edge, 0])
    return d, edge, -d * np.sign(cross) * np.sign(area)


def residuals(p: dict[str, float], data: list[np.ndarray]) -> np.ndarray:
    hole = {k: p[k] for k in HOLE}
    invalid = np.full(sum(len(d) for d in data), 10.0)
    if hole["w2"] < 0 or hole["h1"] <= 0 or not 0 < hole["h2"] < hole["h3"]:
        return invalid
    try:
        outline, _ = holem50_outline(hole)
    except (ValueError, ZeroDivisionError):
        return invalid
    return np.concatenate([nearest_edge(correct(pts, p), place(outline, pole, p["rot"]))[0] for pole, pts in enumerate(data)])


def levenberg_marquardt(fun, x0, *, iterations=200, step=1e-5) -> np.ndarray:
    x, lam = np.array(x0, dtype=float), 1e-2
    r = fun(x)
    cost = float(r @ r)
    for _ in range(iterations):
        jac = np.empty((r.size, x.size))
        for i in range(x.size):
            dx = np.zeros_like(x)
            dx[i] = step
            jac[:, i] = (fun(x + dx) - fun(x - dx)) / (2 * step)
        g, h = jac.T @ r, jac.T @ jac
        delta, improved = np.zeros_like(x), False
        for _ in range(12):
            delta = np.linalg.solve(h + lam * np.diag(np.diag(h) + 1e-12), -g)
            r_new = fun(x + delta)
            if float(r_new @ r_new) < cost:
                x, r, cost, lam, improved = x + delta, r_new, float(r_new @ r_new), lam * 0.3, True
                break
            lam *= 10
        if not improved or np.abs(delta).max() < 1e-8:
            break
    return x


def fit(data, free: tuple[str, ...], fixed: dict[str, float], start: dict[str, float]) -> dict[str, float]:
    def unpack(x):
        return {**fixed, **dict(zip(free, (float(v) for v in x)))}

    return unpack(levenberg_marquardt(lambda x: residuals(unpack(x), data), [start[k] for k in free]))


def evaluate(p: dict[str, float], data: list[np.ndarray]) -> dict:
    hole = {k: p[k] for k in HOLE}
    outline, labels = holem50_outline(hole)
    per_pole, features, distances = [], {}, []
    for pole, pts in enumerate(data):
        d, edge, signed = nearest_edge(correct(pts, p), place(outline, pole, p["rot"]))
        distances.append(d)
        per_pole.append({"pole_d_axis_deg": 22.5 + 45 * pole, "rms_mm": round(float(np.sqrt((d**2).mean())), 3), "max_mm": round(float(d.max()), 3)})
        edge_labels = np.array(labels)[edge]
        for label in set(labels):
            if (mask := edge_labels == label).any():
                features.setdefault(label, []).append(signed[mask])
    d = np.concatenate(distances)
    return {
        "holem50_mm": {k: round(v, 3) for k, v in hole.items()},
        "drawing": {
            "centre_offset_mm": [round(p["dx"], 3), round(p["dy"], 3)],
            "rotation_deg": round(p["rot"], 4),
            "stretch_x_over_y": round((1 + p["stretch"]) / (1 - p["stretch"]), 5),
        },
        "rms_mm": round(float(np.sqrt((d**2).mean())), 3),
        "p95_mm": round(float(np.percentile(d, 95)), 3),
        "max_mm": round(float(d.max()), 3),
        "per_pole": per_pole,
        "per_feature": {
            label: {
                "points": int(sum(len(v) for v in values)),
                "mean_signed_mm": round(float(np.concatenate(values).mean()), 3),
                "rms_mm": round(float(np.sqrt((np.concatenate(values) ** 2).mean())), 3),
                "max_abs_mm": round(float(np.abs(np.concatenate(values)).max()), 3),
            }
            for label, values in sorted(features.items())
        },
    }


def main() -> None:
    pdf, out = Path(sys.argv[1]), Path(sys.argv[2])
    segments = figure_segments(pdf)
    calibration = calibrate(segments)
    data = pocket_points(segments, calibration)
    frame = {"dx": 0.0, "dy": 0.0, "rot": 0.0, "stretch": 0.0}
    a = fit(data, DRAWING, dict(PYLEECAN_TOYOTA_PRIUS), {**PYLEECAN_TOYOTA_PRIUS, **frame})
    b = fit(data, HOLE + DRAWING, {}, a)
    c = fit(data, tuple(k for k in HOLE if k != "h1") + DRAWING, {"h1": STATED_BRIDGE_MM}, b)
    # What coilEM meshes: variant C rounded to 0.01 mm, drawing frame refitted.
    rounded = {k: round(c[k], 2) for k in HOLE}
    recommended = fit(data, DRAWING, rounded, c)
    result = {
        "description": (
            "Pyleecan HoleM50 parameters fitted to the ORNL 2004 Prius rotor pocket outline (#70). "
            "Inferred from a figure, not stated by ORNL."
        ),
        "source": {"id": "S5", "report": "ORNL/TM-2005/33", "figure": "Fig. 21, p.25 (PDF 32)", "paths": "blue rotor vector paths"},
        "tool": "tools/fit_ornl_prius_holem50.py",
        "rotor_od_mm": round(2 * R_OUT, 3),
        "drawing_calibration": {k: round(v, 4) for k, v in calibration.items()},
        "points_per_pole": [len(p) for p in data],
        "fixed_mm": {"w1": 0.0, "h4": 0.0},
        "read_off_error_mm": READ_OFF_ERROR_MM,
        "variants": {
            "A_pyleecan_toyota_prius": evaluate(a, data),
            "B_all_parameters_fitted": evaluate(b, data),
            "C_bridge_at_stated_callouts": evaluate(c, data),
        },
        "recommended": {
            "variant": "C_bridge_at_stated_callouts, rounded to 0.01 mm",
            "fit": evaluate(recommended, data),
            "rotor": {
                "OD_mm": round(2 * R_OUT, 2),
                "ID_mm": round(ROTOR_ID_IN * 25.4, 2),
                "ipm_topology": "pyleecan_holem50",
                **{f"holem50_{k}_mm": v for k, v in rounded.items()},
                "holem50_w1_mm": 0.0,
                "holem50_h4_mm": 0.0,
                "magnet_width_mm": rounded["w4"],
                "magnet_thickness_mm": rounded["h3"],
            },
        },
    }
    out.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    for name, v in [*result["variants"].items(), ("recommended", result["recommended"]["fit"])]:
        print(f"{name}: {v['holem50_mm']} rms {v['rms_mm']} p95 {v['p95_mm']} max {v['max_mm']} mm; stretch {v['drawing']['stretch_x_over_y']}")


if __name__ == "__main__":
    main()
