//! Geometry-backed mesh and solve-context setup for Magneto2D.

use crate::mesh::{AirgapBand, MeshSource, TriMesh};
use crate::motor::MotorConfig;
use crate::sources::mesh_slot_areas_mm2;

use super::mesh_metadata::{
    has_imported_current_density_metadata, validate_mesh_metadata, MeshMetadataError,
};
use super::model::MachineModel;
use super::{
    resolve_operating_point, uses_remesh_per_step, ConfigSummary, OperatingPointSummary,
    SolveMeshArtifact,
};

/// Common geometry/mesh setup shared between single and sweep solves.
#[derive(Clone)]
pub(super) struct SolveContext {
    pub(super) solve_mesh_artifact: SolveMeshArtifact,
    pub(super) mesh: TriMesh,
    pub(super) airgap_band: AirgapBand,
    pub(super) centroids: Vec<[f64; 2]>,
    pub(super) config_summary: ConfigSummary,
    pub(super) operating_point: OperatingPointSummary,
    pub(super) current_a: f64,
    pub(super) current_angle: f64,
    pub(super) slot_areas: Vec<f64>,
    pub(super) rated_speed_rpm: u32,
    pub(super) n_pole_pitches: u32,
}

/// Legacy native mesh-generation entry point retained only to return a typed
/// migration error for old direct Magneto2D callers.
pub(super) fn generate_solve_mesh_at_angle(
    config: &MotorConfig,
    rotor_angle_rad: f64,
) -> Result<TriMesh, String> {
    let _ = (config, rotor_angle_rad);
    Err(native_mesh_generation_removed_message())
}

pub(super) fn native_mesh_generation_removed_message() -> String {
    "Magneto2D Rust native mesh generation was removed; generate a solve mesh artifact with the backend Gmsh mesh preview and pass it with --mesh-input or --batch-input".to_string()
}

pub(super) fn config_summary_for(
    config: &MotorConfig,
    current_amplitude_a: f64,
    current_angle_deg: f64,
) -> ConfigSummary {
    let machine = MachineModel::from_config(config);
    // Resolve the rotor rotation model via the same helper the sweep
    // dispatcher uses, so the echo can't drift from the actually-taken
    // code path. Absent / None -> "fixed_mesh" (back-compat default).
    let rotor_rotation_model = config
        .solve_params
        .as_ref()
        .map(|sp| sp.rotor_rotation_model_label())
        .unwrap_or("fixed_mesh")
        .to_string();
    machine.config_summary(current_amplitude_a, current_angle_deg, rotor_rotation_model)
}

pub(super) fn setup_context(
    config: &MotorConfig,
    solve_mesh_artifact: Option<SolveMeshArtifact>,
) -> Result<SolveContext, String> {
    if config
        .solve_params
        .as_ref()
        .map(|sp| sp.excitation_mode_label() == "ideal_six_step_120")
        .unwrap_or(false)
        && !config.topology.eq_ignore_ascii_case("SPM")
    {
        return Err(
            "ideal_six_step_120 is supported only for inner-rotor SPM in the BLDC MVP".to_string(),
        );
    }
    let machine = MachineModel::from_config(config);
    let mut solve_mesh_artifact =
        solve_mesh_artifact.ok_or_else(native_mesh_generation_removed_message)?;
    validate_mesh_metadata(&solve_mesh_artifact).map_err(|err| err.to_string())?;
    let n_pole_pitches = solve_mesh_artifact.mesh.info.n_pole_pitches;

    convert_mesh_to_si(&mut solve_mesh_artifact.mesh);
    let mesh = solve_mesh_artifact.mesh.clone();
    let airgap_band = mesh
        .info
        .airgap_band()
        .ok_or_else(|| MeshMetadataError::MissingAirgapBand.to_string())?;
    let centroids = mesh_centroids(&mesh);

    let sp = config.solve_params.as_ref();
    let operating_point = resolve_operating_point(sp)?;
    let current_a = operating_point.resolved_phase_current_peak_a;
    let current_angle = operating_point.resolved_current_angle_deg;
    let rated_speed_rpm = sp.and_then(|s| s.rated_speed_rpm).unwrap_or(3000);

    eprintln!(
        "magneto2d: operating point current_angle_deg={:.1} (requested={:?})",
        current_angle, operating_point.requested_current_angle_deg
    );
    eprintln!(
        "magneto2d: current_amplitude_A={:.3} {} -> phase_peak={:.3}A",
        operating_point.resolved_current_amplitude_a,
        operating_point.current_amplitude_convention,
        operating_point.resolved_phase_current_peak_a,
    );
    eprintln!("magneto2d: {}", operating_point.current_amplitude_rule);
    eprintln!(
        "magneto2d: current angle reference='{}'",
        operating_point.current_angle_reference
    );
    eprintln!("magneto2d: {}", operating_point.resolution_rule);

    let has_imported_current_density = has_imported_current_density_metadata(&solve_mesh_artifact);
    let imported_mesh_input = is_imported_mesh_input(&mesh.info);
    let slot_areas = if imported_mesh_input {
        let imported_slot_areas = mesh_slot_areas_mm2(
            &mesh,
            &centroids,
            config.stator.slot_count,
            config.rotor.pole_count,
        );
        let populated_slots = imported_slot_areas
            .iter()
            .filter(|area_mm2| **area_mm2 > 1.0e-9)
            .count();
        if populated_slots == imported_slot_areas.len() && !imported_slot_areas.is_empty() {
            eprintln!(
                "magneto2d: imported mesh current normalization uses mesh slot areas ({} slots)",
                imported_slot_areas.len(),
            );
            imported_slot_areas
        } else {
            if has_imported_current_density {
                eprintln!(
                    "magneto2d: imported mesh slot areas incomplete ({}/{} populated); imported current densities bypass analytical slot areas",
                    populated_slots,
                    imported_slot_areas.len(),
                );
                imported_slot_areas
            } else {
                eprintln!(
                    "magneto2d: imported mesh slot areas incomplete ({}/{} populated); using analytical slot areas",
                    populated_slots,
                    imported_slot_areas.len(),
                );
                machine.slot_areas().map_err(|err| err.to_string())?
            }
        }
    } else {
        machine.slot_areas().map_err(|err| err.to_string())?
    };

    let config_summary = config_summary_for(
        config,
        operating_point.resolved_current_amplitude_a,
        current_angle,
    );

    Ok(SolveContext {
        solve_mesh_artifact,
        mesh,
        airgap_band,
        centroids,
        config_summary,
        operating_point,
        current_a,
        current_angle,
        slot_areas,
        rated_speed_rpm,
        n_pole_pitches,
    })
}

/// Build a `SolveContext` whose mesh has the rotor baked at `rotor_angle_rad`.
/// Reuses the scalar operating-point / slot-area / speed fields from the base
/// context (those are mesh-independent) and only rebuilds the per-mesh data
/// (nodes, triangles, regions, centroids). Called once per rotor position
/// when `rotor_rotation_model == "remesh_per_step"`.
pub(super) fn remesh_ctx_for_angle(
    base: &SolveContext,
    config: &MotorConfig,
    rotor_angle_rad: f64,
) -> Result<SolveContext, String> {
    let _ = (base, config, rotor_angle_rad);
    Err(native_mesh_generation_removed_message())
}

pub(super) fn single_angle_context_artifact(
    config: &MotorConfig,
    rotor_angle_rad: f64,
    solve_mesh_artifact: Option<SolveMeshArtifact>,
) -> Result<(Option<SolveMeshArtifact>, bool), String> {
    if let Some(artifact) = solve_mesh_artifact {
        let rotor_baked_in_mesh = config.topology.eq_ignore_ascii_case("IPM")
            && is_imported_mesh_input(&artifact.mesh.info);
        return Ok((Some(artifact), rotor_baked_in_mesh));
    }
    if !uses_remesh_per_step(config) {
        return Ok((None, false));
    }
    let _ = rotor_angle_rad;
    Err(native_mesh_generation_removed_message())
}

fn is_imported_mesh_input(info: &crate::mesh::MeshInfo) -> bool {
    matches!(info.mesh_source, Some(MeshSource::Gmsh))
}

fn convert_mesh_to_si(mesh: &mut TriMesh) {
    for node in &mut mesh.nodes {
        node[0] *= 1e-3;
        node[1] *= 1e-3;
    }
}

fn mesh_centroids(mesh: &TriMesh) -> Vec<[f64; 2]> {
    mesh.triangles
        .iter()
        .map(|tri| {
            let [i, j, m] = *tri;
            [
                (mesh.nodes[i][0] + mesh.nodes[j][0] + mesh.nodes[m][0]) / 3.0,
                (mesh.nodes[i][1] + mesh.nodes[j][1] + mesh.nodes[m][1]) / 3.0,
            ]
        })
        .collect()
}
