"""FEMM utilities and platform detection.

Supports three platforms:
- Windows: native FEMM installation
- Linux (Ubuntu): FEMM via Wine (Tier 2)
- macOS: FEMM via Wine/CrossOver (Tier 3 — best-effort, Apple Silicon requires Rosetta)

The Sprint 1 spike (S0-01) rejected xFEMM (no Python bindings, MATLAB-only).
We use FEMM + pyFEMM via Wine, matching Pyleecan's proven approach.
"""

import os
import platform
import shutil
import subprocess
from typing import Optional

from backend.platform_info import get_platform_info


def check_femm_installation(*, probe_version: bool = True) -> dict:
    """Check if FEMM is installed and get version info.

    Returns:
        Dictionary with keys:
        - available: bool indicating if FEMM is available
        - path: str path to FEMM installation
        - version: str version string (if available)
        - platform: str "Windows", "Darwin", or "Linux"
        - wine_required: bool whether Wine is needed
    """
    system = platform.system()
    result = {
        "available": False,
        "path": None,
        "version": None,
        "platform": system,
        "wine_required": system != "Windows",
    }

    if system == "Windows":
        # Check for FEMM installation on Windows
        common_paths = [
            r"C:\femm42\bin\femm.exe",
            r"C:\Program Files\femm42\bin\femm.exe",
            r"C:\Program Files (x86)\femm42\bin\femm.exe",
            r"C:\Program Files\Femm42\femm.exe",
            r"C:\Program Files (x86)\Femm42\femm.exe",
            r"C:\Program Files\Femm\femm.exe",
            os.path.expandvars(r"%ProgramFiles%\Femm42\femm.exe"),
        ]
        for path in common_paths:
            if os.path.isfile(path):
                result["available"] = True
                result["path"] = path
                if probe_version:
                    try:
                        version_output = subprocess.run(
                            [path, "--version"],
                            capture_output=True, text=True, timeout=5,
                        )
                        if version_output.returncode == 0:
                            result["version"] = version_output.stdout.strip()
                    except Exception:
                        pass
                break
    else:
        # On macOS/Linux, FEMM runs under Wine
        # Check if FEMM is installed in the Wine prefix
        wine_info = check_wine_installation()
        if wine_info["available"]:
            femm_in_wine = _find_femm_in_wine_prefix(wine_info.get("prefix"))
            if femm_in_wine:
                result["available"] = True
                result["path"] = femm_in_wine

    return result


def check_wine_installation() -> dict:
    """Check if Wine is installed (needed for FEMM on macOS/Linux).

    On macOS, checks for:
    - Homebrew Wine (Intel: /usr/local/bin/wine, Apple Silicon: /opt/homebrew/bin/wine)
    - CrossOver Wine (/Applications/CrossOver.app)
    - Game Porting Toolkit (GPTK)
    - MacPorts Wine

    Returns:
        Dictionary with keys:
        - available: bool indicating if Wine is available
        - path: str path to Wine executable
        - version: str version string
        - variant: str "homebrew", "crossover", "gptk", "system", or None
        - prefix: str Wine prefix path (WINEPREFIX)
    """
    result = {
        "available": False,
        "path": None,
        "version": None,
        "variant": None,
        "prefix": os.environ.get("WINEPREFIX", os.path.expanduser("~/.wine")),
    }

    system = platform.system()

    # 1. Check PATH first (works on all platforms)
    for wine_cmd in ["wine64", "wine", "wine32"]:
        wine_path = shutil.which(wine_cmd)
        if wine_path:
            version = _get_wine_version(wine_path)
            if version:
                result["available"] = True
                result["path"] = wine_path
                result["version"] = version
                result["variant"] = _identify_wine_variant(wine_path)
                return result

    # 2. macOS-specific paths
    if system == "Darwin":
        macos_paths = [
            # Homebrew (Apple Silicon)
            "/opt/homebrew/bin/wine64",
            "/opt/homebrew/bin/wine",
            # Homebrew (Intel)
            "/usr/local/bin/wine64",
            "/usr/local/bin/wine",
            # CrossOver
            "/Applications/CrossOver.app/Contents/SharedSupport/CrossOver/bin/wine64",
            "/Applications/CrossOver.app/Contents/SharedSupport/CrossOver/bin/wine",
            # Game Porting Toolkit
            "/usr/local/opt/game-porting-toolkit/bin/wine64",
            # MacPorts
            "/opt/local/bin/wine64",
            "/opt/local/bin/wine",
        ]
        for path in macos_paths:
            if os.path.isfile(path) and os.access(path, os.X_OK):
                version = _get_wine_version(path)
                if version:
                    result["available"] = True
                    result["path"] = path
                    result["version"] = version
                    result["variant"] = _identify_wine_variant(path)
                    return result

    # 3. Linux-specific paths
    elif system == "Linux":
        linux_paths = [
            "/usr/bin/wine64",
            "/usr/bin/wine",
            "/usr/local/bin/wine",
        ]
        for path in linux_paths:
            if os.path.isfile(path) and os.access(path, os.X_OK):
                version = _get_wine_version(path)
                if version:
                    result["available"] = True
                    result["path"] = path
                    result["version"] = version
                    result["variant"] = "system"
                    return result

    return result


def _get_wine_version(wine_path: str) -> Optional[str]:
    """Get Wine version string from executable."""
    try:
        output = subprocess.run(
            [wine_path, "--version"],
            capture_output=True, text=True, timeout=10,
        )
        if output.returncode == 0:
            return output.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, PermissionError):
        pass
    return None


def _identify_wine_variant(wine_path: str) -> str:
    """Identify which Wine variant this is."""
    path_lower = wine_path.lower()
    if "crossover" in path_lower:
        return "crossover"
    elif "game-porting-toolkit" in path_lower or "gptk" in path_lower:
        return "gptk"
    elif "/opt/homebrew/" in path_lower or "/usr/local/" in path_lower:
        return "homebrew"
    elif "/opt/local/" in path_lower:
        return "macports"
    return "system"


def _find_femm_in_wine_prefix(prefix: Optional[str] = None) -> Optional[str]:
    """Look for FEMM installation inside a Wine prefix.

    Args:
        prefix: Wine prefix path. Defaults to ~/.wine.

    Returns:
        Path to femm.exe inside the prefix, or None.
    """
    if prefix is None:
        prefix = os.path.expanduser("~/.wine")

    # Common FEMM install locations inside Wine prefix
    candidates = [
        os.path.join(prefix, "drive_c", "femm42", "bin", "femm.exe"),  # default NSIS installer path
        os.path.join(prefix, "drive_c", "Program Files", "Femm42", "femm.exe"),
        os.path.join(prefix, "drive_c", "Program Files (x86)", "Femm42", "femm.exe"),
        os.path.join(prefix, "drive_c", "femm42", "femm.exe"),
    ]
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    return None


def get_macos_setup_instructions() -> str:
    """Return macOS-specific setup instructions for FEMM + Wine.

    Returns:
        Multi-line string with setup instructions.
    """
    platform_info = get_platform_info()

    if platform_info["is_apple_silicon"]:
        return """
macOS (Apple Silicon) Setup — FEMM via Wine
=============================================

Apple Silicon Macs need Rosetta 2 + Wine to run FEMM (a Windows x86 app).

Option A: Homebrew Wine (recommended)
  1. Install Rosetta 2 (if not already):
     softwareupdate --install-rosetta --agree-to-license

  2. Install Wine via Homebrew:
     brew tap homebrew/cask-versions
     brew install --cask wine-stable

  3. Install FEMM 4.2 in Wine:
     wine64 ~/Downloads/femm42bin_x64.exe
     (Download from https://www.femm.info/wiki/Download)

  4. Install pyFEMM:
     pip install pyfemm

  5. Verify:
     python -c "from backend.femm_utils import check_wine_installation; print(check_wine_installation())"

Option B: CrossOver (easier, commercial)
  1. Install CrossOver from https://www.codeweavers.com/crossover
  2. Create a new bottle → install FEMM 4.2
  3. Set WINEPREFIX to the CrossOver bottle path

Note: Sprint 2's preview endpoint does NOT require FEMM — it uses
pure-math geometry generation. FEMM is only needed for the /solve endpoint.
""".strip()
    else:
        return """
macOS (Intel) Setup — FEMM via Wine
=====================================

  1. Install Wine via Homebrew:
     brew install --cask wine-stable

  2. Install FEMM 4.2 in Wine:
     wine64 ~/Downloads/femm42bin_x64.exe
     (Download from https://www.femm.info/wiki/Download)

  3. Install pyFEMM:
     pip install pyfemm

  4. Verify:
     python -c "from backend.femm_utils import check_wine_installation; print(check_wine_installation())"
""".strip()


# ─── Material Properties ────────────────────────────────────────────────────

# BH curves, magnetic properties, and Steinmetz loss coefficients for steel grades.
# Core loss model (modified Steinmetz): P_core = k_h * f * B^alpha + k_e * f^2 * B^2  [W/kg]
#   k_h: hysteresis loss coefficient [W·s / kg / T^alpha]
#   k_e: eddy current loss coefficient [W·s^2 / kg / T^2]
#   alpha: Steinmetz exponent (typically 1.6–2.2)
# Sources: AK Steel datasheets, Bozorth 1993, Pyrhönen Table 3.2
STEEL_PROPERTIES = {
    "M19": {
        "name": "M19 Silicon Steel",
        "density_kg_m3": 7650,
        "resistivity_ohm_m": 4.6e-7,
        "steinmetz_kh": 0.0275,   # hysteresis coefficient
        "steinmetz_ke": 1.83e-5,  # eddy current coefficient
        "steinmetz_alpha": 1.8,   # Steinmetz exponent
        # 47-point B-H curve lifted verbatim from FEMM 4.2's built-in
        # "M-19 Steel" material (Task #43 probe 2, 2026-04-20). Used as
        # a fallback when OPENEM_FEMM_FORCE_LOCAL_BH=1; kept in lockstep
        # with solvers/magneto2d/materials/M19.csv so magneto2d and
        # local-mode FEMM solve the same iron model.
        "bh_curve": [
            (0.00, 0.0), (0.05, 15.120714), (0.10, 22.718292), (0.15, 27.842733),
            (0.20, 31.871434), (0.25, 35.365044), (0.30, 38.600588), (0.35, 41.736202),
            (0.40, 44.873979), (0.45, 48.087807), (0.50, 51.437236), (0.55, 54.975221),
            (0.60, 58.752993), (0.65, 62.823644), (0.70, 67.245285), (0.75, 72.084406),
            (0.80, 77.420100), (0.85, 83.350021), (0.90, 89.999612), (0.95, 97.537353),
            (1.00, 106.201406), (1.05, 116.348464), (1.10, 128.547329), (1.15, 143.765431),
            (1.20, 163.754169), (1.25, 191.868158), (1.30, 234.833507), (1.35, 306.509769),
            (1.40, 435.255202), (1.45, 674.911968), (1.50, 1108.325569), (1.55, 1813.085468),
            (1.60, 2801.217421), (1.65, 4053.653117), (1.70, 5591.106890), (1.75, 7448.318413),
            (1.80, 9708.815670), (1.85, 12486.931615), (1.90, 16041.483644), (1.95, 21249.420624),
            (2.00, 31313.495878), (2.05, 53589.446877), (2.10, 88477.484601), (2.15, 124329.410540),
            (2.20, 159968.569300), (2.25, 197751.604272), (2.30, 234024.751347),
        ],
    },
    "M27": {
        "name": "M27 Silicon Steel",
        "density_kg_m3": 7700,
        "resistivity_ohm_m": 4.8e-7,
        "steinmetz_kh": 0.0320,
        "steinmetz_ke": 2.10e-5,
        "steinmetz_alpha": 1.8,
        "bh_curve": [
            (0, 0), (0.1, 50), (0.2, 100), (0.3, 150),
            (0.5, 238), (0.7, 300), (1.0, 350), (1.2, 400),
            (1.5, 450), (1.7, 500), (2.0, 550),
        ],
    },
    "M36": {
        "name": "M36 Silicon Steel",
        "density_kg_m3": 7700,
        "resistivity_ohm_m": 5.0e-7,
        "steinmetz_kh": 0.0380,
        "steinmetz_ke": 2.50e-5,
        "steinmetz_alpha": 1.9,
        "bh_curve": [
            (0, 0), (0.1, 60), (0.2, 120), (0.3, 180),
            (0.5, 280), (0.7, 350), (1.0, 420), (1.2, 480),
            (1.5, 550), (1.7, 600), (2.0, 650),
        ],
    },
    "NO20": {
        "name": "NO20 Electrical Steel",
        "density_kg_m3": 7750,
        "resistivity_ohm_m": 4.4e-7,
        "steinmetz_kh": 0.0210,
        "steinmetz_ke": 1.20e-5,
        "steinmetz_alpha": 1.7,
        "bh_curve": [
            (0, 0), (0.1, 35), (0.2, 70), (0.3, 105),
            (0.5, 175), (0.7, 220), (1.0, 260), (1.2, 300),
            (1.5, 350), (1.7, 390), (2.0, 440),
        ],
    },
    "NO27": {
        "name": "NO27 Electrical Steel",
        "density_kg_m3": 7750,
        "resistivity_ohm_m": 4.5e-7,
        "steinmetz_kh": 0.0240,
        "steinmetz_ke": 1.50e-5,
        "steinmetz_alpha": 1.7,
        "bh_curve": [
            (0, 0), (0.1, 40), (0.2, 80), (0.3, 120),
            (0.5, 200), (0.7, 250), (1.0, 300), (1.2, 340),
            (1.5, 390), (1.7, 430), (2.0, 480),
        ],
    },
    "1018_steel": {
        "name": "1018 Carbon Steel",
        "density_kg_m3": 7860,
        "resistivity_ohm_m": 1.04e-7,
        "steinmetz_kh": 0.0500,
        "steinmetz_ke": 5.00e-5,
        "steinmetz_alpha": 2.0,
        "bh_curve": [
            (0, 0), (0.1, 50), (0.2, 100), (0.3, 150),
            (0.5, 250), (0.7, 320), (1.0, 390), (1.2, 450),
            (1.5, 520), (1.7, 570), (2.0, 620),
        ],
    },
}

# FEMM built-in library names for steel materials we can import directly.
# Grades not present here are created locally from the bundled nonlinear B-H data.
FEMM_STEEL_LIBRARY_MAP = {
    "M19": "M-19 Steel",
    "M27": "M-27 Steel",
    "M36": "M-36 Steel",
    "1018_steel": "1018 Steel",
}

# Permanent magnet properties
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

# Conductor properties
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


def get_material_properties(material_name: str) -> Optional[dict]:
    """Get properties for a material.

    Args:
        material_name: Name of material (e.g., 'M19', 'N42', 'copper')

    Returns:
        Dictionary of properties or None if not found
    """
    if material_name in STEEL_PROPERTIES:
        return STEEL_PROPERTIES[material_name]
    if material_name in MAGNET_PROPERTIES:
        return MAGNET_PROPERTIES[material_name]
    if material_name in CONDUCTOR_PROPERTIES:
        return CONDUCTOR_PROPERTIES[material_name]
    return None


def get_femm_steel_material_name(material_name: str) -> Optional[str]:
    """Return the FEMM-side material name for a steel grade."""
    if material_name in FEMM_STEEL_LIBRARY_MAP:
        return FEMM_STEEL_LIBRARY_MAP[material_name]
    props = STEEL_PROPERTIES.get(material_name)
    if props:
        return str(props["name"])
    return None
