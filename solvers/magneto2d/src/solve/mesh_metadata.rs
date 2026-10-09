//! Solve-time resolution for optional mesh metadata.

use std::collections::HashMap;
use std::fmt;

use crate::materials::{legacy_element_magnetization_enabled, spm_magnetization_angle_rad};
use crate::mesh::{MeshSource, Region};
use crate::motor::MotorConfig;

use super::types::ImportedPhysicsRegion;
use super::SolveMeshArtifact;

const IMPORTED_PHYSICS_CONTRACT_VERSION: &str = "magneto2d_imported_physics/v0";

#[derive(Debug, Clone, PartialEq)]
pub(super) enum MeshMetadataError {
    InvalidCustomMaterial(String),
    LengthMismatch {
        field: &'static str,
        expected: usize,
        actual: usize,
    },
    MissingMagnetization {
        topology: String,
        element_index: usize,
    },
    MissingCurrentDensity {
        topology: String,
        element_index: usize,
    },
    MissingRegionIds {
        expected: usize,
    },
    UnknownRegionId {
        region_id: String,
        element_index: usize,
    },
    RegionKindMismatch {
        region_id: String,
        element_index: usize,
        contract_kind: String,
        mesh_kind: &'static str,
    },
    UnsupportedContractVersion {
        version: String,
    },
    UnsupportedUnits {
        field: &'static str,
        expected: &'static str,
        actual: String,
    },
    UnsupportedBoundaryPolicy {
        field: &'static str,
        value: String,
    },
    UnknownMaterial {
        region: Region,
        material_key: String,
    },
    MissingMotionState,
    StaleMotionState {
        expected_rotor_angle_deg: f64,
        artifact_rotor_angle_deg: f64,
    },
    MissingAirgapBand,
}

impl fmt::Display for MeshMetadataError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            MeshMetadataError::InvalidCustomMaterial(message) => write!(f, "invalid custom material: {message}"),
            MeshMetadataError::LengthMismatch {
                field,
                expected,
                actual,
            } => write!(
                f,
                "mesh metadata field '{field}' has {actual} entries but mesh has {expected} triangles"
            ),
            MeshMetadataError::MissingMagnetization {
                topology,
                element_index,
            } => write!(
                f,
                "mesh metadata missing magnetization for {topology} magnet element {element_index}"
            ),
            MeshMetadataError::MissingCurrentDensity {
                topology,
                element_index,
            } => write!(
                f,
                "mesh metadata missing current density for {topology} SlotWinding element {element_index}"
            ),
            MeshMetadataError::MissingRegionIds { expected } => write!(
                f,
                "mesh metadata missing element_region_ids for imported physics contract; expected {expected} entries"
            ),
            MeshMetadataError::UnknownRegionId {
                region_id,
                element_index,
            } => write!(
                f,
                "mesh metadata references unknown region id '{region_id}' for element {element_index}"
            ),
            MeshMetadataError::RegionKindMismatch {
                region_id,
                element_index,
                contract_kind,
                mesh_kind,
            } => write!(
                f,
                "mesh metadata region kind mismatch for element {element_index} region '{region_id}': contract={contract_kind}, mesh={mesh_kind}"
            ),
            MeshMetadataError::UnsupportedContractVersion { version } => write!(
                f,
                "unsupported imported physics contract version '{version}'; expected {IMPORTED_PHYSICS_CONTRACT_VERSION}"
            ),
            MeshMetadataError::UnsupportedUnits {
                field,
                expected,
                actual,
            } => write!(
                f,
                "unsupported imported physics contract units.{field}='{actual}'; expected '{expected}'"
            ),
            MeshMetadataError::UnsupportedBoundaryPolicy { field, value } => write!(
                f,
                "unsupported imported physics contract boundary_policy.{field}='{value}'"
            ),
            MeshMetadataError::UnknownMaterial {
                region,
                material_key,
            } => write!(
                f,
                "unsupported material key '{material_key}' for imported {region:?} element"
            ),
            MeshMetadataError::MissingMotionState => write!(
                f,
                "imported physics contract missing baked rotor motion state"
            ),
            MeshMetadataError::StaleMotionState {
                expected_rotor_angle_deg,
                artifact_rotor_angle_deg,
            } => write!(
                f,
                "imported physics contract rotor angle is stale: artifact={artifact_rotor_angle_deg:.6}deg, requested={expected_rotor_angle_deg:.6}deg"
            ),
            MeshMetadataError::MissingAirgapBand => {
                write!(f, "mesh info does not define a valid airgap band")
            }
        }
    }
}

pub(super) fn validate_mesh_metadata(
    artifact: &SolveMeshArtifact,
) -> Result<(), MeshMetadataError> {
    let expected = artifact.mesh.triangles.len();
    if artifact.mesh.regions.len() != expected {
        return Err(MeshMetadataError::LengthMismatch {
            field: "regions",
            expected,
            actual: artifact.mesh.regions.len(),
        });
    }
    if let Some(region_ids) = artifact.element_region_ids.as_ref() {
        if region_ids.len() != expected {
            return Err(MeshMetadataError::LengthMismatch {
                field: "element_region_ids",
                expected,
                actual: region_ids.len(),
            });
        }
    }
    if let Some(magnetization) = artifact.element_magnetization.as_ref() {
        if magnetization.len() != expected {
            return Err(MeshMetadataError::LengthMismatch {
                field: "element_magnetization",
                expected,
                actual: magnetization.len(),
            });
        }
    }
    if let Some(current_density) = artifact.element_current_density_a_per_m2.as_ref() {
        if current_density.len() != expected {
            return Err(MeshMetadataError::LengthMismatch {
                field: "element_current_density_a_per_m2",
                expected,
                actual: current_density.len(),
            });
        }
    }
    validate_physics_contract_metadata(artifact)?;
    Ok(())
}

fn validate_physics_contract_metadata(
    artifact: &SolveMeshArtifact,
) -> Result<(), MeshMetadataError> {
    let Some(contract) = artifact.physics_contract.as_ref() else {
        return Ok(());
    };
    if contract.version != IMPORTED_PHYSICS_CONTRACT_VERSION {
        return Err(MeshMetadataError::UnsupportedContractVersion {
            version: contract.version.clone(),
        });
    }
    validate_units(contract.units.as_ref())?;
    validate_boundary_policy(contract.boundary_policy.as_ref())?;

    let expected = artifact.mesh.triangles.len();
    let Some(element_region_ids) = artifact.element_region_ids.as_ref() else {
        if !contract.regions.is_empty() {
            return Err(MeshMetadataError::MissingRegionIds { expected });
        }
        return Ok(());
    };

    let region_by_id: HashMap<&str, &super::types::ImportedPhysicsRegion> = contract
        .regions
        .iter()
        .map(|region| (region.id.as_str(), region))
        .collect();
    for (idx, region_id) in element_region_ids.iter().enumerate() {
        let Some(contract_region) = region_by_id.get(region_id.as_str()) else {
            return Err(MeshMetadataError::UnknownRegionId {
                region_id: region_id.clone(),
                element_index: idx,
            });
        };
        let mesh_kind = region_kind_label(artifact.mesh.regions[idx]);
        if contract_region.kind != mesh_kind {
            return Err(MeshMetadataError::RegionKindMismatch {
                region_id: region_id.clone(),
                element_index: idx,
                contract_kind: contract_region.kind.clone(),
                mesh_kind,
            });
        }
    }
    Ok(())
}

fn validate_units(units: Option<&serde_json::Value>) -> Result<(), MeshMetadataError> {
    let Some(units) = units.and_then(|value| value.as_object()) else {
        return Ok(());
    };
    for (field, expected) in [
        ("length", "mm"),
        ("angle", "deg"),
        ("current_density", "A_per_m2"),
        ("magnetization_angle", "deg"),
    ] {
        let Some(actual) = units.get(field).and_then(|value| value.as_str()) else {
            continue;
        };
        if actual != expected {
            return Err(MeshMetadataError::UnsupportedUnits {
                field,
                expected,
                actual: actual.to_string(),
            });
        }
    }
    Ok(())
}

fn validate_boundary_policy(
    boundary_policy: Option<&super::types::ImportedBoundaryPolicy>,
) -> Result<(), MeshMetadataError> {
    let Some(policy) = boundary_policy else {
        return Ok(());
    };
    if let Some(outer) = policy.outer_boundary.as_deref() {
        if outer != "dirichlet_az_zero" {
            return Err(MeshMetadataError::UnsupportedBoundaryPolicy {
                field: "outer_boundary",
                value: outer.to_string(),
            });
        }
    }
    if let Some(sector_edges) = policy.sector_edges.as_deref() {
        if sector_edges != "none" {
            return Err(MeshMetadataError::UnsupportedBoundaryPolicy {
                field: "sector_edges",
                value: sector_edges.to_string(),
            });
        }
    }
    Ok(())
}

pub(super) fn validate_imported_step_motion(
    artifact: &SolveMeshArtifact,
    rotor_angle_rad: f64,
) -> Result<(), MeshMetadataError> {
    if !is_imported_artifact(artifact) {
        return Ok(());
    }
    let Some(contract) = artifact.physics_contract.as_ref() else {
        return Ok(());
    };
    let motion = contract
        .motion
        .as_ref()
        .ok_or(MeshMetadataError::MissingMotionState)?;
    match motion.rotor_state.as_deref() {
        Some("baked_in_mesh") => {}
        // Legacy SPM fixed meshes are swept internally: the solver re-tags
        // magnet and source metadata per step, so a step angle away from the
        // as-meshed angle is expected, not stale. The per-step resolvers
        // already ignore imported step metadata at non-matching angles.
        Some("fixed_mesh_retagged") => return Ok(()),
        _ => return Err(MeshMetadataError::MissingMotionState),
    }
    let artifact_angle = motion
        .rotor_angle_mech_deg
        .or(artifact.rotor_angle_mech_deg)
        .filter(|angle| angle.is_finite())
        .ok_or(MeshMetadataError::MissingMotionState)?;
    let requested_angle = rotor_angle_rad.to_degrees();
    if angular_distance_deg(artifact_angle, requested_angle) > 1.0e-6 {
        return Err(MeshMetadataError::StaleMotionState {
            expected_rotor_angle_deg: requested_angle,
            artifact_rotor_angle_deg: artifact_angle,
        });
    }
    Ok(())
}

pub(super) fn validate_imported_sources_for_problem(
    artifact: &SolveMeshArtifact,
    regions: &[Region],
    config: &MotorConfig,
    rotor_angle_rad: f64,
    requested_current_a: f64,
) -> Result<(), MeshMetadataError> {
    validate_mesh_metadata(artifact)?;
    if !is_imported_artifact(artifact)
        || config.topology.eq_ignore_ascii_case("SPM")
        || requested_current_a.abs() <= 1.0e-12
    {
        return Ok(());
    }
    if !explicit_magnetization_matches_step_angle(artifact, rotor_angle_rad) {
        return Err(MeshMetadataError::StaleMotionState {
            expected_rotor_angle_deg: rotor_angle_rad.to_degrees(),
            artifact_rotor_angle_deg: artifact.rotor_angle_mech_deg.unwrap_or(0.0),
        });
    }
    for (idx, region) in regions.iter().enumerate() {
        if *region != Region::SlotWinding {
            continue;
        }
        if current_density_for_element(artifact, idx).is_none() {
            return Err(MeshMetadataError::MissingCurrentDensity {
                topology: config.topology.clone(),
                element_index: idx,
            });
        }
    }
    Ok(())
}

pub(super) fn resolve_step_current_densities_a_per_m2(
    artifact: &SolveMeshArtifact,
    rotor_angle_rad: f64,
) -> Result<Option<Vec<f64>>, MeshMetadataError> {
    validate_mesh_metadata(artifact)?;
    if !has_imported_current_density_metadata(artifact) {
        return Ok(None);
    }
    if !explicit_magnetization_matches_step_angle(artifact, rotor_angle_rad) {
        return Ok(None);
    }
    Ok(Some(
        (0..artifact.mesh.triangles.len())
            .map(|idx| current_density_for_element(artifact, idx).unwrap_or(0.0))
            .collect(),
    ))
}

pub(super) fn resolve_step_current_densities_for_requested_current(
    artifact: &SolveMeshArtifact,
    rotor_angle_rad: f64,
    requested_current_a: f64,
) -> Result<Option<Vec<f64>>, MeshMetadataError> {
    validate_mesh_metadata(artifact)?;
    if requested_current_a.abs() <= 1.0e-12 {
        return Ok(Some(vec![0.0; artifact.mesh.triangles.len()]));
    }
    resolve_step_current_densities_a_per_m2(artifact, rotor_angle_rad)
}

pub(super) fn resolve_step_element_magnetization_rad(
    artifact: &SolveMeshArtifact,
    regions: &[Region],
    centroids: &[[f64; 2]],
    config: &MotorConfig,
    rotor_angle_rad: f64,
) -> Result<Vec<Option<f64>>, MeshMetadataError> {
    let expected = artifact.mesh.triangles.len();
    if regions.len() != expected {
        return Err(MeshMetadataError::LengthMismatch {
            field: "regions",
            expected,
            actual: regions.len(),
        });
    }
    if centroids.len() != expected {
        return Err(MeshMetadataError::LengthMismatch {
            field: "centroids",
            expected,
            actual: centroids.len(),
        });
    }
    validate_mesh_metadata(artifact)?;

    let imported_step_metadata_matches_angle =
        explicit_magnetization_matches_step_angle(artifact, rotor_angle_rad);
    let explicit_magnetization = if imported_step_metadata_matches_angle {
        artifact.element_magnetization.as_ref()
    } else {
        None
    };
    let is_spm = config.topology.eq_ignore_ascii_case("SPM");
    let use_centroid_angle = legacy_element_magnetization_enabled();
    let mut resolved = Vec::with_capacity(expected);

    for (idx, (region, centroid)) in regions.iter().zip(centroids.iter()).enumerate() {
        if *region != Region::Magnet {
            resolved.push(None);
            continue;
        }

        let explicit_angle_deg = explicit_magnetization
            .and_then(|values| values.get(idx).copied().flatten())
            .filter(|angle| angle.is_finite());
        if let Some(angle_deg) = explicit_angle_deg {
            resolved.push(Some(angle_deg.to_radians()));
            continue;
        }
        let contract_angle_deg = imported_step_metadata_matches_angle
            .then(|| region_magnetization_for_element(artifact, idx))
            .flatten();
        if let Some(angle_deg) = contract_angle_deg {
            resolved.push(Some(angle_deg.to_radians()));
            continue;
        }

        if !is_spm {
            return Err(MeshMetadataError::MissingMagnetization {
                topology: config.topology.clone(),
                element_index: idx,
            });
        }

        resolved.push(Some(spm_magnetization_angle_rad(
            *centroid,
            config.rotor.pole_count,
            rotor_angle_rad,
            use_centroid_angle,
        )));
    }

    Ok(resolved)
}

pub(super) fn has_imported_current_density_metadata(artifact: &SolveMeshArtifact) -> bool {
    artifact
        .element_current_density_a_per_m2
        .as_ref()
        .map(|values| values.iter().flatten().any(|density| density.is_finite()))
        .unwrap_or(false)
        || artifact
            .physics_contract
            .as_ref()
            .map(|contract| {
                contract.regions.iter().any(|region| {
                    region.kind == "SlotWinding"
                        && region
                            .current_density_a_per_m2
                            .map(|density| density.is_finite())
                            .unwrap_or(false)
                })
            })
            .unwrap_or(false)
}

fn current_density_for_element(artifact: &SolveMeshArtifact, element_index: usize) -> Option<f64> {
    artifact
        .element_current_density_a_per_m2
        .as_ref()
        .and_then(|values| values.get(element_index).copied().flatten())
        .filter(|density| density.is_finite())
        .or_else(|| {
            contract_region_for_element(artifact, element_index)
                .filter(|region| region.kind == "SlotWinding")
                .and_then(|region| region.current_density_a_per_m2)
                .filter(|density| density.is_finite())
        })
}

fn region_magnetization_for_element(
    artifact: &SolveMeshArtifact,
    element_index: usize,
) -> Option<f64> {
    contract_region_for_element(artifact, element_index)
        .filter(|region| region.kind == "Magnet")
        .and_then(|region| region.magnetization_angle_deg)
        .filter(|angle| angle.is_finite())
}

fn contract_region_for_element<'a>(
    artifact: &'a SolveMeshArtifact,
    element_index: usize,
) -> Option<&'a ImportedPhysicsRegion> {
    let contract = artifact.physics_contract.as_ref()?;
    let region_id = artifact.element_region_ids.as_ref()?.get(element_index)?;
    contract
        .regions
        .iter()
        .find(|region| region.id == *region_id)
}

fn explicit_magnetization_matches_step_angle(
    artifact: &SolveMeshArtifact,
    rotor_angle_rad: f64,
) -> bool {
    let step_deg = rotor_angle_rad.to_degrees();
    let artifact_deg = artifact.rotor_angle_mech_deg.unwrap_or(0.0);
    angular_distance_deg(artifact_deg, step_deg) <= 1.0e-6
}

/// True when the requested step angle matches the artifact's baked angle,
/// i.e. the artifact's per-element/contract step metadata (magnetization,
/// current density, per-element material keys) describes this rotor
/// position. Fixed-mesh re-tagged sweep steps away from the baked angle
/// must not consume that metadata: region kinds have rotated away from the
/// baked layout it was recorded against.
pub(super) fn step_metadata_matches_artifact_angle(
    artifact: &SolveMeshArtifact,
    rotor_angle_rad: f64,
) -> bool {
    explicit_magnetization_matches_step_angle(artifact, rotor_angle_rad)
}

fn angular_distance_deg(left: f64, right: f64) -> f64 {
    if !left.is_finite() || !right.is_finite() {
        return f64::INFINITY;
    }
    ((left - right + 180.0).rem_euclid(360.0) - 180.0).abs()
}

fn is_imported_artifact(artifact: &SolveMeshArtifact) -> bool {
    artifact.physics_contract.is_some()
        || matches!(artifact.mesh.info.mesh_source, Some(MeshSource::Gmsh))
}

fn region_kind_label(region: Region) -> &'static str {
    match region {
        Region::RotorCore => "RotorCore",
        Region::Magnet => "Magnet",
        Region::Airgap => "Airgap",
        Region::StatorTooth => "StatorTooth",
        Region::StatorYoke => "StatorYoke",
        Region::SlotWinding => "SlotWinding",
        Region::FluxBarrier => "FluxBarrier",
        Region::MagnetPocketAir => "MagnetPocketAir",
    }
}
