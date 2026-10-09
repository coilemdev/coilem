use crate::mesh::{Region, TriMesh};
use crate::motor::MotorConfig;

use super::ConfigSummary;

mod ipm;
mod spm;

use self::ipm::IpmMachineModel;
use self::spm::SpmMachineModel;

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct UnsupportedTopologyError {
    topology: String,
    feature: &'static str,
}

impl UnsupportedTopologyError {
    fn new(topology: impl Into<String>, feature: &'static str) -> Self {
        Self {
            topology: topology.into(),
            feature,
        }
    }
}

impl std::fmt::Display for UnsupportedTopologyError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(
            formatter,
            "magneto2d topology '{}' does not support {} in this solver configuration",
            self.topology, self.feature
        )
    }
}

impl std::error::Error for UnsupportedTopologyError {}

#[derive(Clone, Debug)]
pub(super) struct MachineModel {
    geometry: GeometryModel,
}

#[derive(Clone, Debug)]
enum GeometryModel {
    Spm(SpmMachineModel),
    Ipm(IpmMachineModel),
}

impl MachineModel {
    pub(super) fn from_config(config: &MotorConfig) -> Self {
        let geometry = if config.topology.eq_ignore_ascii_case("SPM") {
            GeometryModel::Spm(SpmMachineModel::from_config(config))
        } else if config.topology.eq_ignore_ascii_case("IPM") {
            GeometryModel::Ipm(IpmMachineModel::from_config(config))
        } else {
            GeometryModel::Ipm(IpmMachineModel::from_config(config))
        };
        Self { geometry }
    }

    pub(super) fn slot_count(&self) -> u32 {
        match &self.geometry {
            GeometryModel::Spm(model) => model.slot_count(),
            GeometryModel::Ipm(model) => model.slot_count(),
        }
    }

    pub(super) fn pole_count(&self) -> u32 {
        match &self.geometry {
            GeometryModel::Spm(model) => model.pole_count(),
            GeometryModel::Ipm(model) => model.pole_count(),
        }
    }

    pub(super) fn stack_length_mm(&self) -> f64 {
        match &self.geometry {
            GeometryModel::Spm(model) => model.stack_length_mm(),
            GeometryModel::Ipm(model) => model.stack_length_mm(),
        }
    }

    pub(super) fn winding_turns_per_coil(&self) -> u32 {
        match &self.geometry {
            GeometryModel::Spm(model) => model.winding_turns_per_coil(),
            GeometryModel::Ipm(model) => model.winding_turns_per_coil(),
        }
    }

    pub(super) fn winding_type(&self) -> &str {
        match &self.geometry {
            GeometryModel::Spm(model) => model.winding_type(),
            GeometryModel::Ipm(model) => model.winding_type(),
        }
    }

    pub(super) fn winding_layers(&self) -> u32 {
        match &self.geometry {
            GeometryModel::Spm(model) => model.winding_layers(),
            GeometryModel::Ipm(model) => model.winding_layers(),
        }
    }

    pub(super) fn winding_parallel_paths(&self) -> u32 {
        match &self.geometry {
            GeometryModel::Spm(model) => model.winding_parallel_paths(),
            GeometryModel::Ipm(model) => model.winding_parallel_paths(),
        }
    }

    pub(super) fn effective_magnet_embrace(&self) -> Result<f64, UnsupportedTopologyError> {
        match &self.geometry {
            GeometryModel::Spm(model) => Ok(model.effective_magnet_embrace()),
            GeometryModel::Ipm(model) => Err(UnsupportedTopologyError::new(
                model.topology_label(),
                "SPM magnet-embrace fallback",
            )),
        }
    }

    pub(super) fn slot_areas(&self) -> Result<Vec<f64>, UnsupportedTopologyError> {
        match &self.geometry {
            GeometryModel::Spm(model) => Ok(model.slot_areas()),
            GeometryModel::Ipm(model) => Err(UnsupportedTopologyError::new(
                model.topology_label(),
                "IPM slot-area inference",
            )),
        }
    }

    pub(super) fn config_summary(
        &self,
        current_amplitude_a: f64,
        current_angle_deg: f64,
        rotor_rotation_model: String,
    ) -> ConfigSummary {
        match &self.geometry {
            GeometryModel::Spm(model) => {
                model.config_summary(current_amplitude_a, current_angle_deg, rotor_rotation_model)
            }
            GeometryModel::Ipm(model) => {
                model.config_summary(current_amplitude_a, current_angle_deg, rotor_rotation_model)
            }
        }
    }

    pub(super) fn rotated_rotor_regions(
        &self,
        mesh: &TriMesh,
        centroids: &[[f64; 2]],
        rotor_angle_rad: f64,
    ) -> Result<Vec<Region>, UnsupportedTopologyError> {
        match &self.geometry {
            GeometryModel::Spm(model) => {
                Ok(model.rotated_rotor_regions(mesh, centroids, rotor_angle_rad))
            }
            GeometryModel::Ipm(model) => Err(UnsupportedTopologyError::new(
                model.topology_label(),
                "fixed-mesh IPM rotor-region rotation",
            )),
        }
    }
}

pub(crate) fn effective_magnet_embrace(
    config: &MotorConfig,
) -> Result<f64, UnsupportedTopologyError> {
    MachineModel::from_config(config).effective_magnet_embrace()
}
