"""Solver-neutral scalar material properties used by analysis code.

This module intentionally excludes solver-library identifiers and B-H sample
tables.  In particular, the FEMM-derived M19 B-H samples remain quarantined in
the private FEMM integration until their redistribution rights are resolved.
"""

from __future__ import annotations

# Modified Steinmetz model:
# P_core = k_h * f * B**alpha + k_e * f**2 * B**2  [W/kg]
STEEL_ANALYSIS_PROPERTIES = {
    "M19": {
        "name": "M19 Silicon Steel",
        "density_kg_m3": 7650,
        "resistivity_ohm_m": 4.6e-7,
        "steinmetz_kh": 0.0275,
        "steinmetz_ke": 1.83e-5,
        "steinmetz_alpha": 1.8,
    },
    "M27": {
        "name": "M27 Silicon Steel",
        "density_kg_m3": 7700,
        "resistivity_ohm_m": 4.8e-7,
        "steinmetz_kh": 0.0320,
        "steinmetz_ke": 2.10e-5,
        "steinmetz_alpha": 1.8,
    },
    "M36": {
        "name": "M36 Silicon Steel",
        "density_kg_m3": 7700,
        "resistivity_ohm_m": 5.0e-7,
        "steinmetz_kh": 0.0380,
        "steinmetz_ke": 2.50e-5,
        "steinmetz_alpha": 1.9,
    },
    "NO20": {
        "name": "NO20 Electrical Steel",
        "density_kg_m3": 7750,
        "resistivity_ohm_m": 4.4e-7,
        "steinmetz_kh": 0.0210,
        "steinmetz_ke": 1.20e-5,
        "steinmetz_alpha": 1.7,
    },
    "NO27": {
        "name": "NO27 Electrical Steel",
        "density_kg_m3": 7750,
        "resistivity_ohm_m": 4.5e-7,
        "steinmetz_kh": 0.0240,
        "steinmetz_ke": 1.50e-5,
        "steinmetz_alpha": 1.7,
    },
    "1018_steel": {
        "name": "1018 Carbon Steel",
        "density_kg_m3": 7860,
        "resistivity_ohm_m": 1.04e-7,
        "steinmetz_kh": 0.0500,
        "steinmetz_ke": 5.00e-5,
        "steinmetz_alpha": 2.0,
    },
}


MAGNET_PROPERTIES = {
    "N35": {
        "name": "NdFeB N35",
        "remanence_T": 1.23,
        "coercivity_bH_kA_m": -955,
        "coercivity_bM_kA_m": -79.6,
        "max_energy_kJ_m3": 287,
        "density_kg_m3": 7450,
        "relative_permeability": 1.05,
    },
    "N42": {
        "name": "NdFeB N42",
        "remanence_T": 1.30,
        "coercivity_bH_kA_m": -955,
        "coercivity_bM_kA_m": -79.6,
        "max_energy_kJ_m3": 330,
        "density_kg_m3": 7450,
        "relative_permeability": 1.05,
    },
    "Prius_2004_NdFeB": {
        "name": "Prius 2004 / Pyleecan NdFeB",
        "remanence_T": 1.24,
        "coercivity_bH_kA_m": -955,
        "coercivity_bM_kA_m": -79.6,
        "max_energy_kJ_m3": 330,
        "density_kg_m3": 7450,
        "relative_permeability": 1.05,
    },
    "N48": {
        "name": "NdFeB N48",
        "remanence_T": 1.40,
        "coercivity_bH_kA_m": -955,
        "coercivity_bM_kA_m": -79.6,
        "max_energy_kJ_m3": 390,
        "density_kg_m3": 7450,
        "relative_permeability": 1.05,
    },
    "N52": {
        "name": "NdFeB N52",
        "remanence_T": 1.47,
        "coercivity_bH_kA_m": -955,
        "coercivity_bM_kA_m": -79.6,
        "max_energy_kJ_m3": 440,
        "density_kg_m3": 7450,
        "relative_permeability": 1.05,
    },
    "N48SH": {
        "name": "NdFeB N48SH (High Temperature)",
        "remanence_T": 1.38,
        "coercivity_bH_kA_m": -1194,
        "coercivity_bM_kA_m": -100,
        "max_energy_kJ_m3": 375,
        "density_kg_m3": 7450,
        "relative_permeability": 1.05,
    },
    "Ferrite_Y30": {
        "name": "Ferrite Y30",
        "remanence_T": 0.39,
        "coercivity_bH_kA_m": -240,
        "coercivity_bM_kA_m": -24,
        "max_energy_kJ_m3": 26,
        "density_kg_m3": 4800,
        "relative_permeability": 1.1,
    },
}


CONDUCTOR_PROPERTIES = {
    "copper": {
        "name": "Copper",
        "conductivity_S_m": 5.96e7,
        "density_kg_m3": 8960,
        "thermal_conductivity_W_m_K": 400,
    },
    "aluminum": {
        "name": "Aluminum",
        "conductivity_S_m": 3.77e7,
        "density_kg_m3": 2700,
        "thermal_conductivity_W_m_K": 237,
    },
}
