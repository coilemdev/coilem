use crate::motor::MotorConfig;

use super::super::ConfigSummary;

#[derive(Clone, Debug)]
pub(super) struct IpmMachineModel {
    topology: String,
    stator: StatorGeometry,
    rotor: RotorGeometry,
    winding: WindingGeometry,
}

#[derive(Clone, Debug)]
struct StatorGeometry {
    od_mm: f64,
    slot_count: u32,
    stack_length_mm: f64,
}

#[derive(Clone, Debug)]
struct RotorGeometry {
    od_mm: f64,
    magnet_thickness_mm: f64,
    pole_count: u32,
}

#[derive(Clone, Debug)]
struct WindingGeometry {
    winding_type: String,
    turns_per_coil: u32,
    layers: u32,
    parallel_paths: u32,
}

impl IpmMachineModel {
    pub(super) fn from_config(config: &MotorConfig) -> Self {
        Self {
            topology: config.topology.clone(),
            stator: StatorGeometry {
                od_mm: config.stator.od_mm,
                slot_count: config.stator.slot_count,
                stack_length_mm: config.stator.stack_length_mm,
            },
            rotor: RotorGeometry {
                od_mm: config.rotor.od_mm,
                magnet_thickness_mm: config.rotor.magnet_thickness_mm,
                pole_count: config.rotor.pole_count,
            },
            winding: WindingGeometry {
                winding_type: config.winding.winding_type.clone(),
                turns_per_coil: config.winding.turns_per_coil,
                layers: config.winding.layers,
                parallel_paths: config.winding.parallel_paths,
            },
        }
    }

    pub(super) fn topology_label(&self) -> &str {
        &self.topology
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
}
