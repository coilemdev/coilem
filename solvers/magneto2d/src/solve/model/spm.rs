use std::f64::consts::PI;

use crate::mesh::{Region, TriMesh};
use crate::motor::MotorConfig;
use crate::sources::estimate_slot_areas;

use super::super::ConfigSummary;

#[derive(Clone, Debug)]
pub(super) struct SpmMachineModel {
    topology: String,
    stator: StatorGeometry,
    rotor: RotorGeometry,
    winding: WindingGeometry,
}

#[derive(Clone, Debug)]
struct StatorGeometry {
    od_mm: f64,
    id_mm: f64,
    slot_count: u32,
    stack_length_mm: f64,
    slot_opening_mm: f64,
    tooth_width_mm: f64,
    yoke_thickness_mm: f64,
}

#[derive(Clone, Debug)]
struct RotorGeometry {
    od_mm: f64,
    magnet_thickness_mm: f64,
    magnet_width_mm: f64,
    pole_count: u32,
    magnet_embrace: Option<f64>,
}

#[derive(Clone, Debug)]
struct WindingGeometry {
    winding_type: String,
    turns_per_coil: u32,
    layers: u32,
    parallel_paths: u32,
}

impl SpmMachineModel {
    pub(super) fn from_config(config: &MotorConfig) -> Self {
        Self {
            topology: config.topology.clone(),
            stator: StatorGeometry {
                od_mm: config.stator.od_mm,
                id_mm: config.stator.id_mm,
                slot_count: config.stator.slot_count,
                stack_length_mm: config.stator.stack_length_mm,
                slot_opening_mm: config.stator.slot_opening_mm,
                tooth_width_mm: config.stator.tooth_width_mm,
                yoke_thickness_mm: config.stator.yoke_thickness_mm,
            },
            rotor: RotorGeometry {
                od_mm: config.rotor.od_mm,
                magnet_thickness_mm: config.rotor.magnet_thickness_mm,
                magnet_width_mm: config.rotor.magnet_width_mm,
                pole_count: config.rotor.pole_count,
                magnet_embrace: config.rotor.magnet_embrace,
            },
            winding: WindingGeometry {
                winding_type: config.winding.winding_type.clone(),
                turns_per_coil: config.winding.turns_per_coil,
                layers: config.winding.layers,
                parallel_paths: config.winding.parallel_paths,
            },
        }
    }

    pub(super) fn slot_count(&self) -> u32 {
        self.stator.slot_count
    }

    pub(super) fn pole_count(&self) -> u32 {
        self.rotor.pole_count
    }

    pub(super) fn stack_length_mm(&self) -> f64 {
        self.stator.stack_length_mm
    }

    pub(super) fn winding_turns_per_coil(&self) -> u32 {
        self.winding.turns_per_coil
    }

    pub(super) fn winding_type(&self) -> &str {
        &self.winding.winding_type
    }

    pub(super) fn winding_layers(&self) -> u32 {
        self.winding.layers
    }

    pub(super) fn winding_parallel_paths(&self) -> u32 {
        self.winding.parallel_paths
    }

    pub(super) fn effective_magnet_embrace(&self) -> f64 {
        if self.topology.eq_ignore_ascii_case("SPM") {
            let rotor_outer_radius_mm = self.rotor.od_mm / 2.0;
            let magnet_center_radius_mm =
                rotor_outer_radius_mm + 0.5 * self.rotor.magnet_thickness_mm;
            let pole_pitch_rad = 2.0 * PI / self.rotor.pole_count as f64;
            if magnet_center_radius_mm > 1e-12 && pole_pitch_rad > 1e-12 {
                let width_based =
                    self.rotor.magnet_width_mm / (magnet_center_radius_mm * pole_pitch_rad);
                return width_based.clamp(0.0, 1.0);
            }
        }

        self.rotor.magnet_embrace.unwrap_or(0.85)
    }

    pub(super) fn slot_areas(&self) -> Vec<f64> {
        estimate_slot_areas(
            self.stator.id_mm / 2.0,
            self.stator.od_mm / 2.0,
            self.stator.yoke_thickness_mm,
            self.stator.slot_count,
            self.stator.tooth_width_mm,
            self.stator.slot_opening_mm,
        )
    }

    pub(super) fn config_summary(
        &self,
        current_amplitude_a: f64,
        current_angle_deg: f64,
        rotor_rotation_model: String,
    ) -> ConfigSummary {
        ConfigSummary {
            topology: self.topology.clone(),
            slots: self.stator.slot_count,
            poles: self.rotor.pole_count,
            stator_od_mm: self.stator.od_mm,
            rotor_od_mm: self.rotor.od_mm,
            magnet_thickness_mm: self.rotor.magnet_thickness_mm,
            stack_length_mm: self.stator.stack_length_mm,
            current_amplitude_a,
            current_angle_deg,
            rotor_rotation_model,
        }
    }

    pub(super) fn rotated_rotor_regions(
        &self,
        mesh: &TriMesh,
        centroids: &[[f64; 2]],
        rotor_angle_rad: f64,
    ) -> Vec<Region> {
        let rotor_outer_r_m = self.rotor.od_mm * 0.5e-3;
        let magnet_outer_r_m = (self.rotor.od_mm * 0.5 + self.rotor.magnet_thickness_mm) * 1e-3;
        let pole_pitch_rad = 2.0 * PI / self.rotor.pole_count as f64;
        let magnet_embrace = self.effective_magnet_embrace();

        mesh.regions
            .iter()
            .zip(centroids.iter())
            .map(|(region, centroid)| {
                let r_m = (centroid[0] * centroid[0] + centroid[1] * centroid[1]).sqrt();
                let in_magnet_band = r_m >= rotor_outer_r_m && r_m < magnet_outer_r_m;
                if !in_magnet_band {
                    return *region;
                }

                match region {
                    Region::RotorCore
                    | Region::StatorTooth
                    | Region::StatorYoke
                    | Region::SlotWinding
                    | Region::FluxBarrier
                    | Region::MagnetPocketAir => *region,
                    Region::Magnet | Region::Airgap => {
                        let theta = centroid[1].atan2(centroid[0]).rem_euclid(2.0 * PI);
                        let rotor_frame_theta = (theta - rotor_angle_rad).rem_euclid(2.0 * PI);
                        let pole_position = rotor_frame_theta / pole_pitch_rad;
                        let signed_offset = pole_position - pole_position.round();
                        if signed_offset.abs() <= magnet_embrace / 2.0 {
                            Region::Magnet
                        } else {
                            Region::Airgap
                        }
                    }
                }
            })
            .collect()
    }
}
