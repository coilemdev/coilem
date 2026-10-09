// Weighted-stress localization accumulator
// helpers, lifted from postprocess/torque.rs. Pure data-flow; no behaviour
// changes. Visibility set to `pub(super)` so the parent torque module
// (mod.rs) can use these types from compute_torque_weighted_stress_debug.

use crate::mesh::Region;

use super::{
    WeightedStressContributionBin, WeightedStressContributionHotspot,
    WeightedStressContributionLocalization,
};

pub(super) struct WeightedStressContributionBinAccumulator {
    label: String,
    element_count: usize,
    torque_nm: f64,
    abs_torque_nm: f64,
    positive_torque_nm: f64,
    negative_torque_nm: f64,
    max_abs_contribution_nm: f64,
}

impl WeightedStressContributionBinAccumulator {
    pub(super) fn new(label: impl Into<String>) -> Self {
        Self {
            label: label.into(),
            element_count: 0,
            torque_nm: 0.0,
            abs_torque_nm: 0.0,
            positive_torque_nm: 0.0,
            negative_torque_nm: 0.0,
            max_abs_contribution_nm: 0.0,
        }
    }

    pub(super) fn add(&mut self, contribution_nm: f64) {
        self.element_count += 1;
        self.torque_nm += contribution_nm;
        let abs_contribution = contribution_nm.abs();
        self.abs_torque_nm += abs_contribution;
        self.max_abs_contribution_nm = self.max_abs_contribution_nm.max(abs_contribution);
        if contribution_nm >= 0.0 {
            self.positive_torque_nm += contribution_nm;
        } else {
            self.negative_torque_nm += contribution_nm;
        }
    }

    pub(super) fn finish(self) -> WeightedStressContributionBin {
        WeightedStressContributionBin {
            label: self.label,
            element_count: self.element_count,
            torque_nm: self.torque_nm,
            abs_torque_nm: self.abs_torque_nm,
            positive_torque_nm: self.positive_torque_nm,
            negative_torque_nm: self.negative_torque_nm,
            max_abs_contribution_nm: self.max_abs_contribution_nm,
        }
    }
}

pub(super) struct WeightedStressContributionAccumulator {
    field_source: String,
    radial_bins: Vec<WeightedStressContributionBinAccumulator>,
    angular_bins: Vec<WeightedStressContributionBinAccumulator>,
    interface_bins: Vec<WeightedStressContributionBinAccumulator>,
    top_abs_contributors: Vec<WeightedStressContributionHotspot>,
    total_abs_torque_nm: f64,
    positive_torque_nm: f64,
    negative_torque_nm: f64,
}

impl WeightedStressContributionAccumulator {
    pub(super) fn new(field_source: &str) -> Self {
        let radial_bins = [
            "radial_0_20_rotor_side",
            "radial_20_40_inner_midgap",
            "radial_40_60_midgap",
            "radial_60_80_outer_midgap",
            "radial_80_100_stator_side",
        ]
        .into_iter()
        .map(WeightedStressContributionBinAccumulator::new)
        .collect();
        let angular_bins = (0..24)
            .map(|idx| WeightedStressContributionBinAccumulator::new(format!("angular_{idx:02}")))
            .collect();
        let interface_bins = [
            "rotor_boundary",
            "slot_mouth_boundary",
            "tooth_tip_boundary",
            "slot_mouth_tooth_tip_boundary",
            "yoke_boundary",
            "slot_domain",
            "inner_airgap_bulk",
            "mid_airgap_bulk",
            "outer_airgap_bulk",
            "other",
        ]
        .into_iter()
        .map(WeightedStressContributionBinAccumulator::new)
        .collect();
        Self {
            field_source: field_source.to_string(),
            radial_bins,
            angular_bins,
            interface_bins,
            top_abs_contributors: Vec::new(),
            total_abs_torque_nm: 0.0,
            positive_torque_nm: 0.0,
            negative_torque_nm: 0.0,
        }
    }

    #[allow(clippy::too_many_arguments)]
    pub(super) fn add(
        &mut self,
        triangle_index: usize,
        region: Region,
        interface_class: &str,
        centroid_x_m: f64,
        centroid_y_m: f64,
        radius_m: f64,
        theta_mech_rad: f64,
        total_span_rad: f64,
        radial_fraction: f64,
        contribution_nm: f64,
        b_r_t: f64,
        b_t_t: f64,
        weight_centroid: f64,
        grad_w_mag_per_m: f64,
    ) {
        let abs_contribution = contribution_nm.abs();
        self.total_abs_torque_nm += abs_contribution;
        if contribution_nm >= 0.0 {
            self.positive_torque_nm += contribution_nm;
        } else {
            self.negative_torque_nm += contribution_nm;
        }

        let radial_idx = ((radial_fraction.clamp(0.0, 0.999_999) * self.radial_bins.len() as f64)
            as usize)
            .min(self.radial_bins.len() - 1);
        self.radial_bins[radial_idx].add(contribution_nm);

        let theta_in_span = theta_mech_rad.rem_euclid(total_span_rad.max(1.0e-12));
        let angular_idx = ((theta_in_span / total_span_rad.max(1.0e-12))
            * self.angular_bins.len() as f64) as usize;
        let angular_idx = angular_idx.min(self.angular_bins.len() - 1);
        self.angular_bins[angular_idx].add(contribution_nm);

        let interface_idx = self
            .interface_bins
            .iter()
            .position(|bin| bin.label == interface_class)
            .unwrap_or(self.interface_bins.len() - 1);
        self.interface_bins[interface_idx].add(contribution_nm);

        self.top_abs_contributors
            .push(WeightedStressContributionHotspot {
                triangle_index,
                region: format!("{region:?}"),
                interface_class: interface_class.to_string(),
                centroid_x_mm: centroid_x_m * 1e3,
                centroid_y_mm: centroid_y_m * 1e3,
                radius_mm: radius_m * 1e3,
                theta_mech_deg: theta_mech_rad.to_degrees(),
                radial_fraction,
                contribution_nm,
                abs_contribution_nm: abs_contribution,
                b_r_t,
                b_t_t,
                weight_centroid,
                grad_w_mag_per_m,
            });
    }

    pub(super) fn finish(mut self) -> WeightedStressContributionLocalization {
        self.top_abs_contributors.sort_by(|a, b| {
            b.abs_contribution_nm
                .partial_cmp(&a.abs_contribution_nm)
                .unwrap_or(std::cmp::Ordering::Equal)
        });
        self.top_abs_contributors.truncate(16);
        WeightedStressContributionLocalization {
            field_source: self.field_source,
            total_abs_torque_nm: self.total_abs_torque_nm,
            positive_torque_nm: self.positive_torque_nm,
            negative_torque_nm: self.negative_torque_nm,
            radial_bins: self
                .radial_bins
                .into_iter()
                .map(WeightedStressContributionBinAccumulator::finish)
                .collect(),
            angular_bins: self
                .angular_bins
                .into_iter()
                .map(WeightedStressContributionBinAccumulator::finish)
                .collect(),
            interface_bins: self
                .interface_bins
                .into_iter()
                .map(WeightedStressContributionBinAccumulator::finish)
                .collect(),
            top_abs_contributors: self.top_abs_contributors,
        }
    }
}

pub(super) fn weighted_stress_interface_class(
    region: Region,
    radial_fraction: f64,
    touches_inner: bool,
    touches_outer_slot: bool,
    touches_outer_tooth: bool,
    touches_outer_yoke: bool,
) -> &'static str {
    if region == Region::SlotWinding {
        return "slot_domain";
    }
    if touches_outer_slot && touches_outer_tooth {
        return "slot_mouth_tooth_tip_boundary";
    }
    if touches_outer_slot {
        return "slot_mouth_boundary";
    }
    if touches_outer_tooth {
        return "tooth_tip_boundary";
    }
    if touches_outer_yoke {
        return "yoke_boundary";
    }
    if touches_inner {
        return "rotor_boundary";
    }
    if radial_fraction < 0.25 {
        "inner_airgap_bulk"
    } else if radial_fraction > 0.75 {
        "outer_airgap_bulk"
    } else {
        "mid_airgap_bulk"
    }
}
