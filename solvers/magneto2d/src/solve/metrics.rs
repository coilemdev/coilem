use std::f64::consts::PI;

use super::lcm;

pub(super) struct TorqueSweepMetrics {
    pub(super) avg_torque_nm: f64,
    pub(super) ripple_pct: f64,
    pub(super) contour_centered_nm: Option<Vec<f64>>,
    pub(super) avg_contour_centered_nm: Option<f64>,
    pub(super) avg_area_mst_nm: f64,
    pub(super) avg_arkkio_nm: f64,
    pub(super) weighted_stress_nm: Option<Vec<f64>>,
    pub(super) avg_weighted_stress_nm: Option<f64>,
    pub(super) weighted_stress_centered_nm: Option<Vec<f64>>,
    pub(super) avg_weighted_stress_centered_nm: Option<f64>,
    pub(super) crosscheck_delta_nm: f64,
    pub(super) crosscheck_delta_pct: Option<f64>,
}

pub(super) struct BackEmfSweepMetrics {
    pub(super) loaded_power_balance_a_v: Vec<f64>,
    pub(super) loaded_power_balance_b_v: Vec<f64>,
    pub(super) loaded_power_balance_c_v: Vec<f64>,
    pub(super) loaded_a_v: Vec<f64>,
    pub(super) loaded_b_v: Vec<f64>,
    pub(super) loaded_c_v: Vec<f64>,
    pub(super) no_load_a_v: Vec<f64>,
    pub(super) no_load_b_v: Vec<f64>,
    pub(super) no_load_c_v: Vec<f64>,
    pub(super) no_load_a_physical_v: Vec<f64>,
    pub(super) no_load_b_physical_v: Vec<f64>,
    pub(super) no_load_c_physical_v: Vec<f64>,
    pub(super) peak_v: f64,
    /// Per-rev-mech fundamental peak. `None` when the sweep is shorter
    /// than one full electrical cycle — DFT support is missing and a
    /// silent 0.0 would produce phantom -100% deltas vs FEMM in the
    /// Phase A Test Results table. The Python reader (`backend/solver.py`,
    /// `scripts/phase_a_report/extraction.py`) treats `None`/`null`
    /// here as "fundamental unavailable" and skips the BEMF gate.
    pub(super) fundamental_v: Option<f64>,
    pub(super) peak_physical_v: f64,
    pub(super) fundamental_peak_physical_v: Option<f64>,
    pub(super) fundamental_rms_v: Option<f64>,
    pub(super) thd_pct: Option<f64>,
}

pub(super) fn first_harmonic_peak(waveform: &[f64]) -> f64 {
    harmonic_peak(waveform, 1)
}

pub(super) fn harmonic_peak(waveform: &[f64], harmonic: usize) -> f64 {
    let n = waveform.len();
    if n < 2 || harmonic == 0 || harmonic >= n {
        return 0.0;
    }

    let mut re = 0.0;
    let mut im = 0.0;
    for (k, sample) in waveform.iter().enumerate() {
        let theta = 2.0 * PI * harmonic as f64 * k as f64 / n as f64;
        re += sample * theta.cos();
        im -= sample * theta.sin();
    }

    (2.0 / n as f64) * (re * re + im * im).sqrt()
}

pub(super) fn back_emf_from_flux_linkage(
    psi: &[f64],
    d_theta_elec_rad: f64,
    omega_scale: f64,
    periodic: bool,
) -> Vec<f64> {
    if psi.is_empty() || d_theta_elec_rad.abs() <= 1e-18 {
        return Vec::new();
    }

    finite_difference_waveform(psi, d_theta_elec_rad, periodic)
        .into_iter()
        .map(|dpsi_dtheta| {
            // Match the existing FEMM/coilEM waveform convention. The
            // displayed solver-alignment BEMF is +dPsi/dtheta scaled by the
            // requested angular speed, not the opposite generator sign.
            dpsi_dtheta * omega_scale
        })
        .collect()
}

pub(super) fn back_emf_thd_pct(waveform: &[f64], max_harmonic: usize) -> f64 {
    let n = waveform.len();
    if n < 4 {
        return 0.0;
    }

    let available_harmonic = n / 2;
    if available_harmonic < 2 {
        return 0.0;
    }

    let fundamental = harmonic_peak(waveform, 1);
    if fundamental <= 1e-12 {
        return 0.0;
    }

    let limit = max_harmonic.min(available_harmonic);
    let harmonics_power = (2..=limit)
        .map(|harmonic| {
            let amplitude = harmonic_peak(waveform, harmonic);
            amplitude * amplitude
        })
        .sum::<f64>();

    harmonics_power.sqrt() / fundamental * 100.0
}

pub(super) fn torque_ripple_pct(waveform: &[f64]) -> f64 {
    if waveform.is_empty() {
        return 0.0;
    }

    let avg_torque = waveform.iter().sum::<f64>() / waveform.len() as f64;
    if avg_torque.abs() <= 1e-12 {
        return 0.0;
    }

    let max_torque = waveform.iter().copied().fold(f64::NEG_INFINITY, f64::max);
    let min_torque = waveform.iter().copied().fold(f64::INFINITY, f64::min);
    (max_torque - min_torque) / avg_torque.abs() * 100.0
}

pub(super) fn waveform_mean(waveform: &[f64]) -> f64 {
    if waveform.is_empty() {
        return 0.0;
    }
    waveform.iter().sum::<f64>() / waveform.len() as f64
}

fn optional_waveform_mean(waveform: Option<&Vec<f64>>) -> Option<f64> {
    waveform.map(|values| values.iter().sum::<f64>() / values.len().max(1) as f64)
}

fn three_phase_abs_peak(a: &[f64], b: &[f64], c: &[f64]) -> f64 {
    a.iter()
        .chain(b.iter())
        .chain(c.iter())
        .map(|v| v.abs())
        .fold(0.0_f64, f64::max)
}

pub(super) fn finite_difference_waveform(values: &[f64], dx: f64, periodic: bool) -> Vec<f64> {
    if values.is_empty() {
        return Vec::new();
    }
    if !dx.is_finite() || dx.abs() <= 1e-12 {
        return vec![0.0; values.len()];
    }

    match values.len() {
        1 => vec![0.0],
        2 => {
            let slope = (values[1] - values[0]) / dx;
            vec![slope, slope]
        }
        n => (0..n)
            .map(|i| {
                if periodic {
                    let prev = values[(i + n - 1) % n];
                    let next = values[(i + 1) % n];
                    (next - prev) / (2.0 * dx)
                } else if i == 0 {
                    (values[1] - values[0]) / dx
                } else if i + 1 == n {
                    (values[n - 1] - values[n - 2]) / dx
                } else {
                    (values[i + 1] - values[i - 1]) / (2.0 * dx)
                }
            })
            .collect(),
    }
}

pub(super) fn cogging_period_electrical_deg(slot_count: u32, pole_count: u32) -> f64 {
    let pole_pairs = pole_count as f64 / 2.0;
    let mechanical_period_deg = 360.0 / lcm(slot_count, pole_count) as f64;
    mechanical_period_deg * pole_pairs
}

pub(super) fn covers_integer_cogging_period(
    sweep_span_deg: f64,
    slot_count: u32,
    pole_count: u32,
) -> bool {
    let period = cogging_period_electrical_deg(slot_count, pole_count);
    if !period.is_finite() || period <= 0.0 || !sweep_span_deg.is_finite() {
        return false;
    }
    let periods = sweep_span_deg / period;
    (periods - periods.round()).abs() <= 1.0e-9
}

pub(super) fn centered_no_load_cogging_waveform(
    values: &[f64],
    current_a: f64,
    sweep_span_deg: f64,
    slot_count: u32,
    pole_count: u32,
) -> Option<Vec<f64>> {
    if values.is_empty()
        || current_a.abs() > 1.0e-12
        || !covers_integer_cogging_period(sweep_span_deg, slot_count, pole_count)
    {
        return None;
    }
    let mean = values.iter().sum::<f64>() / values.len() as f64;
    Some(values.iter().map(|value| value - mean).collect())
}

pub(super) fn centered_endpoint_period_waveform(values: &[f64]) -> Option<Vec<f64>> {
    if values.len() < 2 {
        return None;
    }
    let unique_len = values.len() - 1;
    let mean = values[..unique_len].iter().sum::<f64>() / unique_len as f64;
    Some(values.iter().map(|value| value - mean).collect())
}

pub(super) fn torque_metric_centering_span_deg(
    sampled_angles_elec_deg: &[f64],
    cli_sweep_span_deg: f64,
) -> f64 {
    if cli_sweep_span_deg >= 360.0 - 1.0e-9 || sampled_angles_elec_deg.len() < 2 {
        return cli_sweep_span_deg;
    }
    let first = sampled_angles_elec_deg[0];
    let last = sampled_angles_elec_deg[sampled_angles_elec_deg.len() - 1];
    let sampled_span = last - first;
    if sampled_span.is_finite() && sampled_span > 0.0 {
        sampled_span
    } else {
        cli_sweep_span_deg
    }
}

pub(super) fn assemble_torque_sweep_metrics(
    torques_contour: &[f64],
    torques_area_mst: &[f64],
    torques_arkkio: &[f64],
    torques_weighted_stress: Vec<f64>,
    saw_weighted_stress: bool,
    missing_weighted_stress: bool,
    n_positions: usize,
    current_a: f64,
    sweep_span_deg: f64,
    slot_count: u32,
    pole_count: u32,
) -> TorqueSweepMetrics {
    let avg_torque_nm = torques_contour.iter().sum::<f64>() / torques_contour.len() as f64;
    let ripple_pct = torque_ripple_pct(torques_contour);
    let contour_centered_nm = centered_no_load_cogging_waveform(
        torques_contour,
        current_a,
        sweep_span_deg,
        slot_count,
        pole_count,
    );
    let avg_contour_centered_nm = optional_waveform_mean(contour_centered_nm.as_ref());
    let avg_area_mst_nm = torques_area_mst.iter().sum::<f64>() / torques_area_mst.len() as f64;
    let avg_arkkio_nm = torques_arkkio.iter().sum::<f64>() / torques_arkkio.len().max(1) as f64;
    let weighted_stress_nm = if saw_weighted_stress
        && !missing_weighted_stress
        && torques_weighted_stress.len() == n_positions
    {
        Some(torques_weighted_stress)
    } else {
        None
    };
    let avg_weighted_stress_nm = optional_waveform_mean(weighted_stress_nm.as_ref());
    let weighted_stress_centered_nm = weighted_stress_nm.as_ref().and_then(|values| {
        centered_no_load_cogging_waveform(values, current_a, sweep_span_deg, slot_count, pole_count)
    });
    let avg_weighted_stress_centered_nm =
        optional_waveform_mean(weighted_stress_centered_nm.as_ref());
    let crosscheck_delta_nm = avg_area_mst_nm - avg_torque_nm;
    let crosscheck_delta_pct = if avg_torque_nm.abs() > 1e-12 {
        Some((crosscheck_delta_nm / avg_torque_nm) * 100.0)
    } else {
        None
    };

    TorqueSweepMetrics {
        avg_torque_nm,
        ripple_pct,
        contour_centered_nm,
        avg_contour_centered_nm,
        avg_area_mst_nm,
        avg_arkkio_nm,
        weighted_stress_nm,
        avg_weighted_stress_nm,
        weighted_stress_centered_nm,
        avg_weighted_stress_centered_nm,
        crosscheck_delta_nm,
        crosscheck_delta_pct,
    }
}

pub(super) fn assemble_back_emf_sweep_metrics(
    loaded_psi_a: &[f64],
    loaded_psi_b: &[f64],
    loaded_psi_c: &[f64],
    noload_psi_a: &[f64],
    noload_psi_b: &[f64],
    noload_psi_c: &[f64],
    d_theta_elec: f64,
    omega_mech: f64,
    omega_elec: f64,
    full_cycle_waveform: bool,
    run_thd: bool,
) -> BackEmfSweepMetrics {
    let loaded_power_balance_a_v =
        back_emf_from_flux_linkage(loaded_psi_a, d_theta_elec, omega_elec, full_cycle_waveform);
    let loaded_power_balance_b_v =
        back_emf_from_flux_linkage(loaded_psi_b, d_theta_elec, omega_elec, full_cycle_waveform);
    let loaded_power_balance_c_v =
        back_emf_from_flux_linkage(loaded_psi_c, d_theta_elec, omega_elec, full_cycle_waveform);
    let loaded_a_v =
        back_emf_from_flux_linkage(loaded_psi_a, d_theta_elec, omega_mech, full_cycle_waveform);
    let loaded_b_v =
        back_emf_from_flux_linkage(loaded_psi_b, d_theta_elec, omega_mech, full_cycle_waveform);
    let loaded_c_v =
        back_emf_from_flux_linkage(loaded_psi_c, d_theta_elec, omega_mech, full_cycle_waveform);
    let no_load_a_v =
        back_emf_from_flux_linkage(noload_psi_a, d_theta_elec, omega_mech, full_cycle_waveform);
    let no_load_b_v =
        back_emf_from_flux_linkage(noload_psi_b, d_theta_elec, omega_mech, full_cycle_waveform);
    let no_load_c_v =
        back_emf_from_flux_linkage(noload_psi_c, d_theta_elec, omega_mech, full_cycle_waveform);
    let no_load_a_physical_v =
        back_emf_from_flux_linkage(noload_psi_a, d_theta_elec, omega_elec, full_cycle_waveform);
    let no_load_b_physical_v =
        back_emf_from_flux_linkage(noload_psi_b, d_theta_elec, omega_elec, full_cycle_waveform);
    let no_load_c_physical_v =
        back_emf_from_flux_linkage(noload_psi_c, d_theta_elec, omega_elec, full_cycle_waveform);
    let peak_v = three_phase_abs_peak(&no_load_a_v, &no_load_b_v, &no_load_c_v);
    // Emit None when the sweep is sub-360° elec: the harmonic_peak() DFT
    // assumes the samples cover one full electrical period, and on a
    // partial span the sin/cos basis isn't orthogonal so the formula
    // produces a biased value (often near zero by phase cancellation).
    // Returning None here lets downstream consumers distinguish
    // "fundamental unavailable" from a real zero-volt reading.
    let fundamental_v = if full_cycle_waveform {
        Some(first_harmonic_peak(&no_load_a_v))
    } else {
        None
    };
    let peak_physical_v = three_phase_abs_peak(
        &no_load_a_physical_v,
        &no_load_b_physical_v,
        &no_load_c_physical_v,
    );
    let fundamental_peak_physical_v = if full_cycle_waveform {
        Some(first_harmonic_peak(&no_load_a_physical_v))
    } else {
        None
    };
    let fundamental_rms_v = fundamental_peak_physical_v.map(|v| v / 2.0_f64.sqrt());
    let thd_pct = if run_thd && full_cycle_waveform {
        Some(back_emf_thd_pct(&no_load_a_physical_v, 25))
    } else {
        None
    };

    BackEmfSweepMetrics {
        loaded_power_balance_a_v,
        loaded_power_balance_b_v,
        loaded_power_balance_c_v,
        loaded_a_v,
        loaded_b_v,
        loaded_c_v,
        no_load_a_v,
        no_load_b_v,
        no_load_c_v,
        no_load_a_physical_v,
        no_load_b_physical_v,
        no_load_c_physical_v,
        peak_v,
        fundamental_v,
        peak_physical_v,
        fundamental_peak_physical_v,
        fundamental_rms_v,
        thd_pct,
    }
}
