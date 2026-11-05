"""Render scientific comparison figures from retained, complete sweep CSVs."""
from __future__ import annotations

import argparse
import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    from pathlib import Path
    parser.add_argument("--analysis", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    summary = json.loads((args.analysis/"summary.json").read_text())
    for key in ("loaded", "noload"):
        if summary["curves"][key]["status"] != "COMPLETE_DIAGNOSTIC":
            raise ValueError("Only complete diagnostic sweeps may be plotted as full curves")
    loaded = np.genfromtxt(args.analysis/"loaded.csv", delimiter=",", names=True)
    noload = np.genfromtxt(args.analysis/"noload.csv", delimiter=",", names=True)
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False, "svg.fonttype": "none"})
    fig, panels = plt.subplots(2, 2, figsize=(13, 8.5), constrained_layout=True)
    colors = ["#b84928", "#218268", "#386ab0"]
    for axis in panels.flat:
        axis.grid(alpha=.2)
        axis.set_xlabel("Electrical angle (deg); mechanical angle = electrical / 7")
        axis.set_xlim(0, 360)
        axis.set_xticks(np.arange(0, 361, 60))
    for prefix, style, label in (("femm", "-", "FEMM sliding band"), ("magneto", "--", "Magneto2D / independent Gmsh")):
        panels[0, 0].plot(loaded["angle_electrical_deg"], loaded[prefix+"_outer_torque_Nm"]*1000, style, label=label)
        panels[1, 0].plot(noload["angle_electrical_deg"], noload[prefix+"_outer_torque_Nm"]*1000, style, label=label)
        for phase, color in zip("ABC", colors):
            panels[0, 1].plot(noload["angle_electrical_deg"][:-1], noload[prefix+"_emf_"+phase+"_V"][:-1],
                              style, color=color, label=f"{label.split(' /')[0]} {phase}")
            panels[1, 1].plot(noload["angle_electrical_deg"], noload[prefix+"_linkage_"+phase+"_Wb"]*1000,
                              style, color=color, label=f"{label.split(' /')[0]} {phase}")
    panels[0, 0].set(title="Loaded torque: fixed currents [0, +4, -4] A", ylabel="Outer-rotor torque (mN m), CCW positive")
    panels[0, 1].set(title="No-load induced phase EMF at 1000 rpm", ylabel="EMF (V), e = -omega d(lambda)/d(theta)")
    panels[1, 0].set(title="No-load torque: provisional cogging samples", ylabel="Outer-rotor torque (mN m)")
    panels[1, 1].set(title="No-load phase flux linkage", ylabel="Flux linkage (mWb)")
    panels[0, 0].legend(fontsize=8)
    panels[0, 1].legend(fontsize=7, ncol=2)
    fig.suptitle("FEMM LRK 12-slot / 14-pole reference: initial 48-angle diagnostic\n"
                 "Unfiltered spectral EMF derivative. Material-law parity and finer-grid qualification remain pending.", fontsize=13)
    args.out.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out/"torque-linkage-bemf.png", dpi=170)
    svg_path = args.out/"torque-linkage-bemf.svg"
    fig.savefig(svg_path)
    svg_path.write_text("\n".join(line.rstrip() for line in svg_path.read_text(encoding="utf-8").splitlines())+"\n", encoding="utf-8")
    plt.close(fig)


if __name__ == "__main__":
    main()
