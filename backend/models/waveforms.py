"""Data contracts for motor waveforms. """

from typing import Optional

from pydantic import BaseModel, Field, field_validator


class TorqueWaveform(BaseModel):
    """Torque as a function of rotor position."""

    electrical_angle_deg: list[float] = Field(
        ..., min_length=2, description="Rotor electrical angles in degrees"
    )
    torque_Nm: list[float] = Field(..., min_length=2, description="Torque values in N·m")
    torque_energy_fd_Nm: Optional[list[float]] = Field(
        default=None,
        description=(
            "Finite-difference torque from magnetic potential energy over the sampled sweep."
        ),
    )
    torque_coenergy_fd_Nm: Optional[list[float]] = Field(
        default=None,
        description="Finite-difference torque from magnetic co-energy over the sampled sweep.",
    )
    energy_potential_J: Optional[list[float]] = Field(
        default=None,
        description="Magnetic potential-energy samples used for finite-difference torque.",
    )
    energy_coenergy_J: Optional[list[float]] = Field(
        default=None,
        description="Magnetic co-energy samples used for finite-difference torque.",
    )

    @field_validator(
        "torque_Nm",
        "torque_energy_fd_Nm",
        "torque_coenergy_fd_Nm",
        "energy_potential_J",
        "energy_coenergy_J",
    )
    @classmethod
    def torque_length_matches_angle(cls, v, info):
        """Torque array must match angle array length."""
        if v is None:
            return v
        if info.data and "electrical_angle_deg" in info.data:
            if len(v) != len(info.data["electrical_angle_deg"]):
                raise ValueError(
                    f"{info.field_name} length must match electrical_angle_deg length"
                )
        return v


class PhaseCurrentWaveform(BaseModel):
    """Exact terminal phase currents aligned to the loaded torque grid."""

    electrical_angle_deg: list[float] = Field(
        ..., min_length=2, description="Rotor electrical angles in degrees"
    )
    phase_a_A: list[float] = Field(..., min_length=2, description="Phase A current in A")
    phase_b_A: list[float] = Field(..., min_length=2, description="Phase B current in A")
    phase_c_A: list[float] = Field(..., min_length=2, description="Phase C current in A")

    @field_validator("phase_a_A", "phase_b_A", "phase_c_A")
    @classmethod
    def phase_length_matches_angle(cls, v, info):
        if info.data and "electrical_angle_deg" in info.data:
            if len(v) != len(info.data["electrical_angle_deg"]):
                raise ValueError(
                    "Phase current length must match electrical_angle_deg length"
                )
        return v


class BackEMFWaveform(BaseModel):
    """Back-EMF waveform for all phases."""

    electrical_angle_deg: list[float] = Field(
        ..., min_length=2, description="Rotor electrical angles in degrees"
    )
    phase_a_V: list[float] = Field(..., min_length=2, description="Phase A back-EMF in V")
    phase_b_V: list[float] = Field(..., min_length=2, description="Phase B back-EMF in V")
    phase_c_V: list[float] = Field(..., min_length=2, description="Phase C back-EMF in V")
    line_ab_V: Optional[list[float]] = Field(
        default=None,
        description="Line-to-line back-EMF Vab = Va - Vb in V",
    )
    line_bc_V: Optional[list[float]] = Field(
        default=None,
        description="Line-to-line back-EMF Vbc = Vb - Vc in V",
    )
    line_ca_V: Optional[list[float]] = Field(
        default=None,
        description="Line-to-line back-EMF Vca = Vc - Va in V",
    )

    @field_validator("phase_b_V", "phase_c_V", "line_ab_V", "line_bc_V", "line_ca_V")
    @classmethod
    def phase_length_matches_angle(cls, v, info):
        """Phase voltage arrays must match angle array length."""
        if v is None:
            return v
        if info.data and "electrical_angle_deg" in info.data:
            if len(v) != len(info.data["electrical_angle_deg"]):
                raise ValueError(
                    "Phase voltage length must match electrical_angle_deg length"
                )
        return v


class BackEMFHarmonicComponent(BaseModel):
    """One electrical Back-EMF harmonic, expressed as RMS voltage."""

    order: int = Field(..., ge=1, description="Electrical harmonic order")
    frequency_Hz: float = Field(..., ge=0, description="Harmonic frequency in Hz")
    phase_a_rms_V: float = Field(..., ge=0)
    phase_b_rms_V: float = Field(..., ge=0)
    phase_c_rms_V: float = Field(..., ge=0)
    line_ab_rms_V: float = Field(..., ge=0)
    line_bc_rms_V: float = Field(..., ge=0)
    line_ca_rms_V: float = Field(..., ge=0)
    phase_a_pct_fundamental: Optional[float] = Field(default=None, ge=0)
    line_ab_pct_fundamental: Optional[float] = Field(default=None, ge=0)


class BackEMFHarmonicAnalysis(BaseModel):
    """Versioned Back-EMF spectrum and THD provenance."""

    schema_version: str = Field(default="openem.back_emf_harmonics/v1")
    method: str = Field(default="periodic_flux_linkage_dft/v1")
    source: str = Field(default="no_load_flux_linkage")
    amplitude_convention: str = Field(default="rms")
    sample_count: int = Field(..., ge=3)
    electrical_fundamental_frequency_Hz: float = Field(..., ge=0)
    headline_harmonic_max: int = Field(default=12, ge=2)
    extended_harmonic_max: int = Field(..., ge=2)
    phase_a_thd_h6_pct: Optional[float] = Field(default=None, ge=0)
    phase_a_thd_h12_pct: Optional[float] = Field(default=None, ge=0)
    phase_a_thd_h24_pct: Optional[float] = Field(default=None, ge=0)
    line_ab_thd_h12_pct: Optional[float] = Field(default=None, ge=0)
    line_ab_thd_h24_pct: Optional[float] = Field(default=None, ge=0)
    harmonics: list[BackEMFHarmonicComponent] = Field(..., min_length=2)
