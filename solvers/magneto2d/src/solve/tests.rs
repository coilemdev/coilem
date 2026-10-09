use super::mesh_metadata::{
    resolve_step_current_densities_a_per_m2, resolve_step_current_densities_for_requested_current,
    resolve_step_element_magnetization_rad, validate_imported_sources_for_problem,
    validate_imported_step_motion, validate_mesh_metadata, MeshMetadataError,
};
use super::problem::{resolved_contract_steel_keys, SolveProblem};
use super::{
    applied_current_angle_deg, back_emf_from_flux_linkage, back_emf_thd_pct,
    backtracked_relaxation, balanced_three_phase_winding, build_airgap_brbt_profile,
    cap_mu_rel_step, centered_endpoint_period_waveform, centered_no_load_cogging_waveform,
    cogging_period_electrical_deg, cogging_torque_method, compute_energy_functional_summary,
    covers_integer_cogging_period, default_nonlinear_tol_for_quality, effective_magnet_embrace,
    finite_difference_waveform, first_harmonic_peak, harmonic_peak, motor_boundary_set,
    outer_dirichlet_boundary_nodes, parse_pm_source_work_scale,
    pm_sidewall_quadrature_diagnostic_config, resolve_operating_point, rotated_rotor_regions,
    rotor_electrical_angle_deg, setup_context, sextant_phase_map, single_angle_context_artifact,
    synced_current_angle_deg, torque_ripple_pct, uses_cogging_remesh_per_step, CoggingTorqueMethod,
    NonlinearSolveConfig, NonlinearSolverKind, PicardRelaxationState, SolveMeshArtifact,
};
use crate::materials::MaterialProps;
use crate::mesh::{AirgapBandSource, MeshInfo, MeshSource, Region, TriMesh};
use crate::motor::MotorConfig;
use crate::postprocess::ElementField;
use std::ffi::OsString;
use std::sync::{Mutex, OnceLock};

struct EnvVarGuard {
    key: &'static str,
    previous: Option<OsString>,
}

impl EnvVarGuard {
    fn set(key: &'static str, value: &str) -> Self {
        let previous = std::env::var_os(key);
        std::env::set_var(key, value);
        Self { key, previous }
    }
}

impl Drop for EnvVarGuard {
    fn drop(&mut self) {
        match &self.previous {
            Some(value) => std::env::set_var(self.key, value),
            None => std::env::remove_var(self.key),
        }
    }
}

fn parse_motor_config(json: &str) -> MotorConfig {
    serde_json::from_str(json).expect("test config should deserialize")
}

fn compact_4p12s_config(topology: &str) -> MotorConfig {
    parse_motor_config(&format!(
        r#"{{
          "schema_version": "1.0",
          "topology": "{topology}",
          "stator": {{
            "OD_mm": 50.0,
            "ID_mm": 34.0,
            "slot_count": 12,
            "stack_length_mm": 40.0,
            "slot_opening_mm": 2.5,
            "tooth_width_mm": 4.5,
            "yoke_thickness_mm": 4.5
          }},
          "rotor": {{
            "OD_mm": 25.0,
            "magnet_thickness_mm": 3.0,
            "magnet_width_mm": 16.5,
            "pole_count": 4,
            "magnet_embrace": 0.85
          }},
          "winding": {{
            "type": "concentrated",
            "turns_per_coil": 10,
            "layers": 1,
            "parallel_paths": 1
          }},
          "materials": {{
            "stator_steel": "M19",
            "rotor_steel": "M19",
            "magnet_grade": "N42",
            "conductor": "copper"
          }}
        }}"#,
    ))
}

fn metadata_test_artifact(
    regions: Vec<Region>,
    element_magnetization: Option<Vec<Option<f64>>>,
) -> SolveMeshArtifact {
    let num_triangles = regions.len();
    let triangles = match num_triangles {
        0 => Vec::new(),
        1 => vec![[0, 1, 2]],
        _ => (0..num_triangles)
            .map(|idx| [0, idx + 1, idx + 2])
            .collect(),
    };
    let nodes = (0..num_triangles + 2)
        .map(|idx| {
            let theta = idx as f64 * 0.5;
            [theta.cos(), theta.sin()]
        })
        .collect();

    SolveMeshArtifact {
        physics_contract: None,
        mesh: TriMesh {
            nodes,
            triangles,
            regions,
            boundary_nodes: Vec::new(),
            sector_edge_pairs: Vec::new(),
            info: MeshInfo {
                num_nodes: num_triangles + 2,
                num_triangles,
                pole_pitch_deg: 90.0,
                n_pole_pitches: 4,
                total_span_deg: 360.0,
                angular_divisions: 0,
                radial_rings: 0,
                mesh_density: "test".to_string(),
                radial_layers: vec!["test".to_string()],
                airgap_inner_radius_mm: None,
                airgap_outer_radius_mm: None,
                mesh_source: None,
                magnet_outer_radius_mm: 64.0,
                magnet_embrace: 1.0,
                stator_inner_radius_mm: 65.0,
                stator_slot_outer_radius_mm: 89.0,
                stator_outer_radius_mm: 100.0,
            },
        },
        rotor_angle_mech_deg: None,
        element_region_ids: None,
        element_magnetization,
        element_current_density_a_per_m2: None,
    }
}

fn full_slot_winding_import_artifact(slot_count: u32, pole_count: u32) -> SolveMeshArtifact {
    let slot_count_usize = slot_count as usize;
    let slot_pitch_rad = 2.0 * std::f64::consts::PI / slot_count as f64;
    let mut nodes = Vec::with_capacity(slot_count_usize * 3);
    let mut triangles = Vec::with_capacity(slot_count_usize);
    let mut regions = Vec::with_capacity(slot_count_usize);

    for slot in 0..slot_count_usize {
        let theta = slot as f64 * slot_pitch_rad;
        let half_width = slot_pitch_rad * 0.15;
        let base = nodes.len();
        for (radius_mm, angle_rad) in [
            (70.0, theta - half_width),
            (82.0, theta),
            (70.0, theta + half_width),
        ] {
            nodes.push([radius_mm * angle_rad.cos(), radius_mm * angle_rad.sin()]);
        }
        triangles.push([base, base + 1, base + 2]);
        regions.push(Region::SlotWinding);
    }

    SolveMeshArtifact {
        physics_contract: None,
        mesh: TriMesh {
            nodes,
            triangles,
            regions,
            boundary_nodes: Vec::new(),
            sector_edge_pairs: Vec::new(),
            info: MeshInfo {
                num_nodes: slot_count_usize * 3,
                num_triangles: slot_count_usize,
                pole_pitch_deg: 360.0 / pole_count as f64,
                n_pole_pitches: pole_count,
                total_span_deg: 360.0,
                angular_divisions: slot_count_usize,
                radial_rings: 1,
                mesh_density: "gmsh_import".to_string(),
                radial_layers: vec!["slot_winding".to_string()],
                airgap_inner_radius_mm: None,
                airgap_outer_radius_mm: None,
                mesh_source: Some(MeshSource::Gmsh),
                magnet_outer_radius_mm: 64.0,
                magnet_embrace: 1.0,
                stator_inner_radius_mm: 65.0,
                stator_slot_outer_radius_mm: 89.0,
                stator_outer_radius_mm: 100.0,
            },
        },
        rotor_angle_mech_deg: None,
        element_region_ids: None,
        element_magnetization: None,
        element_current_density_a_per_m2: None,
    }
}

fn imported_contract_artifact(
    regions: Vec<Region>,
    region_ids: Vec<&str>,
    contract_regions: serde_json::Value,
) -> SolveMeshArtifact {
    let mut artifact = metadata_test_artifact(regions, None);
    let n = artifact.mesh.triangles.len();
    artifact.mesh.info.mesh_source = Some(MeshSource::Gmsh);
    artifact.mesh.info.mesh_density = "gmsh_test".to_string();
    artifact.rotor_angle_mech_deg = Some(0.0);
    artifact.element_region_ids = Some(region_ids.into_iter().map(str::to_string).collect());
    artifact.element_magnetization = Some(vec![None; n]);
    artifact.element_current_density_a_per_m2 = Some(vec![None; n]);
    artifact.physics_contract = Some(
        serde_json::from_value(serde_json::json!({
            "version": "magneto2d_imported_physics/v0",
            "topology_hint": "IPM",
            "units": {
                "length": "mm",
                "angle": "deg",
                "current_density": "A_per_m2",
                "magnetization_angle": "deg"
            },
            "motion": {
                "rotor_angle_mech_deg": 0.0,
                "rotor_state": "baked_in_mesh"
            },
            "boundary_policy": {
                "outer_boundary": "dirichlet_az_zero",
                "sector_edges": "none"
            },
            "regions": contract_regions,
            "provenance": {
                "mesh_source": "gmsh"
            }
        }))
        .expect("contract should deserialize"),
    );
    artifact
}

#[test]
fn legacy_solve_mesh_artifact_deserializes_without_contract_metadata() {
    let artifact: SolveMeshArtifact = serde_json::from_str(
        r#"{
          "mesh": {
            "nodes": [[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]],
            "triangles": [[0, 1, 2]],
            "regions": ["Airgap"],
            "boundary_nodes": [],
            "sector_edge_pairs": [],
            "info": {
              "num_nodes": 3,
              "num_triangles": 1,
              "pole_pitch_deg": 90.0,
              "n_pole_pitches": 4,
              "total_span_deg": 360.0,
              "angular_divisions": 0,
              "radial_rings": 0,
              "mesh_density": "legacy",
              "radial_layers": ["legacy"],
              "magnet_outer_radius_mm": 64.0,
              "stator_inner_radius_mm": 65.0,
              "stator_slot_outer_radius_mm": 89.0,
              "stator_outer_radius_mm": 100.0
            }
          }
        }"#,
    )
    .expect("legacy artifact should remain readable");

    assert_eq!(artifact.mesh.info.magnet_embrace, 1.0);
    assert_eq!(artifact.mesh.info.airgap_inner_radius_mm, None);
    assert_eq!(artifact.mesh.info.airgap_outer_radius_mm, None);
    assert_eq!(artifact.mesh.info.mesh_source, None);
    assert!(artifact.physics_contract.is_none());
    assert_eq!(artifact.element_region_ids, None);
    assert_eq!(artifact.element_magnetization, None);
    assert_eq!(artifact.element_current_density_a_per_m2, None);
}

#[test]
fn solve_mesh_artifact_deserializes_contract_metadata() {
    let artifact: SolveMeshArtifact = serde_json::from_str(
        r#"{
          "physics_contract": {
            "version": "magneto2d_imported_physics/v0",
            "topology_hint": "IPM",
            "units": {
              "length": "mm",
              "angle": "deg",
              "current_density": "A_per_m2",
              "magnetization_angle": "deg"
            },
            "motion": {
              "rotor_angle_mech_deg": 0.0,
              "rotor_state": "baked_in_mesh"
            },
            "boundary_policy": {
              "outer_boundary": "dirichlet_az_zero",
              "sector_edges": "none"
            },
            "regions": [
              {
                "id": "MagnetPoleN",
                "kind": "Magnet",
                "material": "N42",
                "magnetization_angle_deg": 30.0
              },
              {
                "id": "MagnetPocketAir",
                "kind": "MagnetPocketAir",
                "material": "air"
              }
            ],
            "provenance": {
              "mesh_source": "gmsh",
              "current_density_source": "gmsh_region",
              "magnetization_source": "gmsh_region",
              "material_assignment_source": "motor_config_compatibility_default"
            }
          },
          "mesh": {
            "nodes": [[0.0, 0.0], [1.0, 0.0], [0.0, 1.0], [-1.0, 0.0]],
            "triangles": [[0, 1, 2], [0, 2, 3]],
            "regions": ["Magnet", "MagnetPocketAir"],
            "boundary_nodes": [],
            "sector_edge_pairs": [],
            "info": {
              "num_nodes": 4,
              "num_triangles": 2,
              "pole_pitch_deg": 90.0,
              "n_pole_pitches": 4,
              "total_span_deg": 360.0,
              "angular_divisions": 0,
              "radial_rings": 0,
              "mesh_density": "gmsh_import",
              "radial_layers": ["gmsh_import"],
              "airgap_inner_radius_mm": 64.0,
              "airgap_outer_radius_mm": 65.0,
              "mesh_source": "gmsh",
              "magnet_outer_radius_mm": 64.0,
              "stator_inner_radius_mm": 65.0,
              "stator_slot_outer_radius_mm": 89.0,
              "stator_outer_radius_mm": 100.0
            }
          },
          "element_region_ids": ["MagnetPoleN", "MagnetPocketAir"],
          "element_magnetization": [30.0, null],
          "element_current_density_a_per_m2": [null, 1200000.0]
        }"#,
    )
    .expect("artifact metadata should deserialize");

    let contract = artifact
        .physics_contract
        .as_ref()
        .expect("contract should deserialize");
    assert_eq!(contract.version, "magneto2d_imported_physics/v0");
    assert_eq!(contract.topology_hint.as_deref(), Some("IPM"));
    assert_eq!(contract.regions.len(), 2);
    assert_eq!(contract.regions[0].kind, "Magnet");
    assert_eq!(contract.regions[1].kind, "MagnetPocketAir");
    assert_eq!(
        contract
            .boundary_policy
            .as_ref()
            .and_then(|policy| policy.outer_boundary.as_deref()),
        Some("dirichlet_az_zero")
    );
    assert_eq!(artifact.mesh.info.airgap_inner_radius_mm, Some(64.0));
    assert_eq!(artifact.mesh.info.airgap_outer_radius_mm, Some(65.0));
    assert_eq!(artifact.mesh.info.mesh_source, Some(MeshSource::Gmsh));
    assert_eq!(
        artifact.element_region_ids.as_ref().unwrap(),
        &vec!["MagnetPoleN".to_string(), "MagnetPocketAir".to_string()]
    );
    assert_eq!(
        artifact.element_magnetization.as_ref().unwrap(),
        &vec![Some(30.0), None]
    );
    assert_eq!(
        artifact.element_current_density_a_per_m2.as_ref().unwrap(),
        &vec![None, Some(1200000.0)]
    );
}

#[test]
fn solve_mesh_artifact_deserializes_generic_region_kinds() {
    let artifact: SolveMeshArtifact = serde_json::from_str(
        r#"{
          "mesh": {
            "nodes": [[0.0, 0.0], [1.0, 0.0], [0.0, 1.0], [-1.0, 0.0], [0.0, -1.0], [2.0, 0.0], [0.0, 2.0], [-2.0, 0.0]],
            "triangles": [[0, 1, 2], [0, 2, 3], [0, 3, 4], [0, 4, 1], [0, 5, 6], [0, 6, 7]],
            "regions": ["RotorCore", "Magnet", "Airgap", "SlotWinding", "FluxBarrier", "MagnetPocketAir"],
            "boundary_nodes": [],
            "sector_edge_pairs": [],
            "info": {
              "num_nodes": 8,
              "num_triangles": 6,
              "pole_pitch_deg": 90.0,
              "n_pole_pitches": 4,
              "total_span_deg": 360.0,
              "angular_divisions": 0,
              "radial_rings": 0,
              "mesh_density": "gmsh_import",
              "radial_layers": ["gmsh_import"],
              "airgap_inner_radius_mm": 64.0,
              "airgap_outer_radius_mm": 65.0,
              "mesh_source": "gmsh",
              "magnet_outer_radius_mm": 64.0,
              "stator_inner_radius_mm": 65.0,
              "stator_slot_outer_radius_mm": 89.0,
              "stator_outer_radius_mm": 100.0
            }
          },
          "element_magnetization": [null, 0.0, null, null, null, null],
          "element_current_density_a_per_m2": [null, null, null, 2000000.0, null, null]
        }"#,
    )
    .expect("generic imported region kinds should deserialize");

    assert_eq!(
        artifact.mesh.regions,
        vec![
            Region::RotorCore,
            Region::Magnet,
            Region::Airgap,
            Region::SlotWinding,
            Region::FluxBarrier,
            Region::MagnetPocketAir,
        ]
    );
}

#[test]
fn mesh_metadata_resolver_preserves_imported_magnetization_angles() {
    let config = cogging_policy_config(100.0, "fixed_mesh");
    let artifact = metadata_test_artifact(
        vec![Region::Magnet, Region::Airgap],
        Some(vec![Some(30.0), None]),
    );
    let centroids = vec![[1.0, 0.0], [0.0, 1.0]];

    let resolved = resolve_step_element_magnetization_rad(
        &artifact,
        &artifact.mesh.regions,
        &centroids,
        &config,
        0.0,
    )
    .expect("imported SPM magnetization should resolve");

    assert!((resolved[0].unwrap() - 30.0_f64.to_radians()).abs() < 1.0e-12);
    assert_eq!(resolved[1], None);
}

#[test]
fn mesh_metadata_resolver_ignores_stale_imported_magnetization_after_rotation() {
    let config = cogging_policy_config(100.0, "fixed_mesh");
    let mut artifact = metadata_test_artifact(vec![Region::Magnet], Some(vec![Some(30.0)]));
    artifact.rotor_angle_mech_deg = Some(0.0);
    let centroids = vec![[1.0, 0.0]];

    let resolved = resolve_step_element_magnetization_rad(
        &artifact,
        &artifact.mesh.regions,
        &centroids,
        &config,
        10.0_f64.to_radians(),
    )
    .expect("SPM fallback magnetization should replace stale imported metadata");

    assert!((resolved[0].unwrap() - 10.0_f64.to_radians()).abs() < 1.0e-12);
}

#[test]
fn mesh_metadata_resolver_fills_spm_missing_magnetization_from_legacy_logic() {
    let config = cogging_policy_config(100.0, "fixed_mesh");
    let artifact = metadata_test_artifact(vec![Region::Magnet], None);
    let theta = 22.5_f64.to_radians();
    let centroids = vec![[theta.cos(), theta.sin()]];

    let resolved = resolve_step_element_magnetization_rad(
        &artifact,
        &artifact.mesh.regions,
        &centroids,
        &config,
        0.0,
    )
    .expect("SPM fallback magnetization should resolve");

    assert!((resolved[0].unwrap() - 0.0).abs() < 1.0e-12);
}

#[test]
fn mesh_metadata_resolver_rejects_non_spm_missing_magnetization() {
    let mut config = cogging_policy_config(100.0, "fixed_mesh");
    config.topology = "IPM".to_string();
    let artifact = metadata_test_artifact(vec![Region::Magnet], None);
    let centroids = vec![[1.0, 0.0]];

    let err = resolve_step_element_magnetization_rad(
        &artifact,
        &artifact.mesh.regions,
        &centroids,
        &config,
        0.0,
    )
    .expect_err("IPM magnet elements must provide explicit magnetization");

    assert_eq!(
        err,
        MeshMetadataError::MissingMagnetization {
            topology: "IPM".to_string(),
            element_index: 0,
        }
    );
}

#[test]
fn mesh_metadata_resolver_uses_region_magnetization_when_element_value_absent() {
    let mut config = cogging_policy_config(100.0, "fixed_mesh");
    config.topology = "IPM".to_string();
    let mut artifact = imported_contract_artifact(
        vec![Region::Magnet, Region::Airgap],
        vec!["magnet_1", "airgap"],
        serde_json::json!([
            {
                "id": "magnet_1",
                "kind": "Magnet",
                "material": "magnet:N42",
                "magnetization_angle_deg": 42.0
            },
            {"id": "airgap", "kind": "Airgap", "material": "air"}
        ]),
    );
    artifact.element_magnetization = None;
    let centroids = vec![[1.0, 0.0], [0.0, 1.0]];

    let resolved = resolve_step_element_magnetization_rad(
        &artifact,
        &artifact.mesh.regions,
        &centroids,
        &config,
        0.0,
    )
    .expect("IPM magnetization should fall back to the region contract");

    assert!((resolved[0].unwrap() - 42.0_f64.to_radians()).abs() < 1.0e-12);
    assert_eq!(resolved[1], None);
}

#[test]
fn mesh_metadata_resolver_prefers_element_magnetization_over_region_value() {
    let mut config = cogging_policy_config(100.0, "fixed_mesh");
    config.topology = "IPM".to_string();
    let mut artifact = imported_contract_artifact(
        vec![Region::Magnet],
        vec!["magnet_1"],
        serde_json::json!([
            {
                "id": "magnet_1",
                "kind": "Magnet",
                "material": "magnet:N42",
                "magnetization_angle_deg": 42.0
            }
        ]),
    );
    artifact.element_magnetization = Some(vec![Some(15.0)]);
    let centroids = vec![[1.0, 0.0]];

    let resolved = resolve_step_element_magnetization_rad(
        &artifact,
        &artifact.mesh.regions,
        &centroids,
        &config,
        0.0,
    )
    .expect("element magnetization should override the region contract");

    assert!((resolved[0].unwrap() - 15.0_f64.to_radians()).abs() < 1.0e-12);
}

#[test]
fn mesh_metadata_validation_rejects_wrong_length_vectors() {
    let artifact = metadata_test_artifact(vec![Region::Magnet], Some(vec![Some(0.0), None]));

    let err = validate_mesh_metadata(&artifact)
        .expect_err("metadata vector length should match triangle count");

    assert_eq!(
        err,
        MeshMetadataError::LengthMismatch {
            field: "element_magnetization",
            expected: 1,
            actual: 2,
        }
    );
}

#[test]
fn mesh_metadata_resolver_preserves_imported_current_densities() {
    let mut artifact = metadata_test_artifact(vec![Region::SlotWinding, Region::Airgap], None);
    artifact.rotor_angle_mech_deg = Some(0.0);
    artifact.element_current_density_a_per_m2 = Some(vec![Some(1.25e6), None]);

    let resolved = resolve_step_current_densities_a_per_m2(&artifact, 0.0)
        .expect("imported current metadata should validate")
        .expect("current metadata should resolve for matching angle");

    assert_eq!(resolved, vec![1.25e6, 0.0]);
}

#[test]
fn mesh_metadata_resolver_uses_region_current_when_element_value_absent() {
    let artifact = imported_contract_artifact(
        vec![Region::SlotWinding, Region::Airgap],
        vec!["slot_1", "airgap"],
        serde_json::json!([
            {
                "id": "slot_1",
                "kind": "SlotWinding",
                "material": "conductor:copper",
                "current_density_a_per_m2": 1.25e6
            },
            {"id": "airgap", "kind": "Airgap", "material": "air"}
        ]),
    );

    let resolved = resolve_step_current_densities_a_per_m2(&artifact, 0.0)
        .expect("region current metadata should validate")
        .expect("region current metadata should resolve for matching angle");

    assert_eq!(resolved, vec![1.25e6, 0.0]);
}

#[test]
fn mesh_metadata_resolver_uses_region_current_when_element_vector_absent() {
    let mut artifact = imported_contract_artifact(
        vec![Region::SlotWinding],
        vec!["slot_1"],
        serde_json::json!([
            {
                "id": "slot_1",
                "kind": "SlotWinding",
                "material": "conductor:copper",
                "current_density_a_per_m2": 1.25e6
            }
        ]),
    );
    artifact.element_current_density_a_per_m2 = None;

    let resolved = resolve_step_current_densities_a_per_m2(&artifact, 0.0)
        .expect("region current metadata should validate without an element vector")
        .expect("region current metadata should resolve without an element vector");

    assert_eq!(resolved, vec![1.25e6]);
}

#[test]
fn mesh_metadata_resolver_prefers_element_current_over_region_value() {
    let mut artifact = imported_contract_artifact(
        vec![Region::SlotWinding],
        vec!["slot_1"],
        serde_json::json!([
            {
                "id": "slot_1",
                "kind": "SlotWinding",
                "material": "conductor:copper",
                "current_density_a_per_m2": 1.25e6
            }
        ]),
    );
    artifact.element_current_density_a_per_m2 = Some(vec![Some(2.5e6)]);

    let resolved = resolve_step_current_densities_a_per_m2(&artifact, 0.0)
        .expect("element current metadata should validate")
        .expect("element current metadata should resolve for matching angle");

    assert_eq!(resolved, vec![2.5e6]);
}

#[test]
fn mesh_metadata_resolver_ignores_stale_imported_current_densities() {
    let mut artifact = metadata_test_artifact(vec![Region::SlotWinding], None);
    artifact.rotor_angle_mech_deg = Some(0.0);
    artifact.element_current_density_a_per_m2 = Some(vec![Some(1.25e6)]);

    let resolved = resolve_step_current_densities_a_per_m2(&artifact, 5.0_f64.to_radians())
        .expect("stale imported current metadata should validate but not resolve");

    assert_eq!(resolved, None);
}

#[test]
fn zero_requested_current_overrides_imported_current_density_metadata() {
    let mut artifact = metadata_test_artifact(vec![Region::SlotWinding, Region::Airgap], None);
    artifact.rotor_angle_mech_deg = Some(0.0);
    artifact.element_current_density_a_per_m2 = Some(vec![Some(1.25e6), None]);

    let resolved = resolve_step_current_densities_for_requested_current(&artifact, 0.0, 0.0)
        .expect("zero-current imported metadata should validate")
        .expect("zero-current solve should resolve to an explicit zero vector");

    assert_eq!(resolved, vec![0.0, 0.0]);
}

#[test]
fn ipm_imported_mesh_with_explicit_current_density_avoids_slot_area_fallback() {
    let ipm_config = compact_4p12s_config("IPM");
    let mut imported_mesh = metadata_test_artifact(vec![Region::RotorCore], None);
    imported_mesh.mesh.info.mesh_density = "gmsh_import".to_string();
    imported_mesh.mesh.info.mesh_source = Some(MeshSource::Gmsh);
    imported_mesh.element_current_density_a_per_m2 = Some(vec![Some(0.0)]);

    let ctx = setup_context(&ipm_config, Some(imported_mesh))
        .expect("explicit imported source metadata should avoid IPM slot-area inference");

    assert!(!ctx.slot_areas.is_empty());
    assert!(ctx.slot_areas.iter().all(|area| *area == 0.0));
}

#[test]
fn ipm_gmsh_mesh_with_explicit_current_density_avoids_slot_area_fallback() {
    let ipm_config = compact_4p12s_config("IPM");
    let mut imported_mesh = metadata_test_artifact(vec![Region::RotorCore], None);
    imported_mesh.mesh.info.mesh_density = "gmsh_coarse".to_string();
    imported_mesh.mesh.info.mesh_source = Some(MeshSource::Gmsh);
    imported_mesh.element_current_density_a_per_m2 = Some(vec![Some(0.0)]);

    let ctx = setup_context(&ipm_config, Some(imported_mesh))
        .expect("explicit Gmsh source metadata should avoid IPM slot-area inference");

    assert!(!ctx.slot_areas.is_empty());
    assert!(ctx.slot_areas.iter().all(|area| *area == 0.0));
}

// --- Phase 0 guardrails for the imported-artifact contract ---
//
// These tests pin the current behavior of the mesh-metadata layer so the
// Phase 1 SolveProblem refactor (which will promote some of these cases into
// typed errors) has a tripwire when behavior changes.

#[test]
fn mesh_metadata_validation_rejects_wrong_length_current_density() {
    let mut artifact = metadata_test_artifact(vec![Region::SlotWinding], None);
    artifact.element_current_density_a_per_m2 = Some(vec![Some(1.0e6), Some(2.0e6)]);

    let err = validate_mesh_metadata(&artifact)
        .expect_err("current-density vector length must match triangle count");

    assert_eq!(
        err,
        MeshMetadataError::LengthMismatch {
            field: "element_current_density_a_per_m2",
            expected: 1,
            actual: 2,
        }
    );
}

#[test]
fn mesh_metadata_validation_rejects_wrong_length_region_ids() {
    let mut artifact = metadata_test_artifact(vec![Region::Magnet], None);
    artifact.element_region_ids = Some(vec!["a".to_string(), "b".to_string()]);

    let err = validate_mesh_metadata(&artifact)
        .expect_err("element_region_ids length must match triangle count");

    assert_eq!(
        err,
        MeshMetadataError::LengthMismatch {
            field: "element_region_ids",
            expected: 1,
            actual: 2,
        }
    );
}

#[test]
fn mesh_metadata_validation_rejects_unknown_contract_region_id() {
    let artifact = imported_contract_artifact(
        vec![Region::SlotWinding],
        vec!["slot_1"],
        serde_json::json!([
            {"id": "slot_2", "kind": "SlotWinding", "material": "conductor:copper"}
        ]),
    );

    let err = validate_mesh_metadata(&artifact)
        .expect_err("contract region ids must cover element_region_ids");

    assert_eq!(
        err,
        MeshMetadataError::UnknownRegionId {
            region_id: "slot_1".to_string(),
            element_index: 0,
        }
    );
}

#[test]
fn mesh_metadata_validation_rejects_contract_region_kind_mismatch() {
    let artifact = imported_contract_artifact(
        vec![Region::SlotWinding],
        vec!["slot_1"],
        serde_json::json!([
            {"id": "slot_1", "kind": "Airgap", "material": "air"}
        ]),
    );

    let err =
        validate_mesh_metadata(&artifact).expect_err("contract kind must match mesh region kind");

    assert_eq!(
        err,
        MeshMetadataError::RegionKindMismatch {
            region_id: "slot_1".to_string(),
            element_index: 0,
            contract_kind: "Airgap".to_string(),
            mesh_kind: "SlotWinding",
        }
    );
}

#[test]
fn mesh_metadata_validation_rejects_unsupported_boundary_policy() {
    let mut artifact = imported_contract_artifact(
        vec![Region::Airgap],
        vec!["airgap"],
        serde_json::json!([
            {"id": "airgap", "kind": "Airgap", "material": "air"}
        ]),
    );
    artifact
        .physics_contract
        .as_mut()
        .unwrap()
        .boundary_policy
        .as_mut()
        .unwrap()
        .outer_boundary = Some("neumann".to_string());

    let err = validate_mesh_metadata(&artifact)
        .expect_err("unsupported imported boundary policy should fail");

    assert_eq!(
        err,
        MeshMetadataError::UnsupportedBoundaryPolicy {
            field: "outer_boundary",
            value: "neumann".to_string(),
        }
    );
}

#[test]
fn mesh_metadata_resolver_rejects_non_spm_magnet_with_explicit_none_magnetization() {
    // A non-SPM artifact that supplies the element_magnetization vector but
    // leaves the magnet element's entry as None should still trip
    // MissingMagnetization — presence of the vector is not a substitute for
    // an actual angle on a magnet element.
    let mut config = cogging_policy_config(100.0, "fixed_mesh");
    config.topology = "IPM".to_string();
    let artifact = metadata_test_artifact(vec![Region::Magnet], Some(vec![None]));
    let centroids = vec![[1.0, 0.0]];

    let err = resolve_step_element_magnetization_rad(
        &artifact,
        &artifact.mesh.regions,
        &centroids,
        &config,
        0.0,
    )
    .expect_err("IPM magnet element with explicit-None magnetization must error");

    assert_eq!(
        err,
        MeshMetadataError::MissingMagnetization {
            topology: "IPM".to_string(),
            element_index: 0,
        }
    );
}

#[test]
fn mesh_metadata_resolver_returns_none_when_current_density_absent() {
    // Phase 1 gap tripwire: today, an imported artifact with no
    // element_current_density_a_per_m2 returns Ok(None) here, which causes
    // solve_at_angle to fall back to compute_current_densities (the analytical
    // SPM-style path) regardless of topology. For non-SPM imported lanes that
    // is wrong physics with mislabeled provenance. Phase 1 will gate this at
    // a higher layer (SolveProblem build) so non-SPM artifacts without
    // imported currents fail with a typed MissingCurrentDensity error before
    // assembly. This test pins the current resolver behavior; when Phase 1
    // lands and the higher-level gate changes the observed behavior, the
    // adapter test that asserts "setup succeeds for IPM-missing-currents"
    // should flip to expect_err. The resolver itself can keep its current
    // shape — it's not the gate.
    let artifact = metadata_test_artifact(vec![Region::SlotWinding], None);

    let resolved = resolve_step_current_densities_a_per_m2(&artifact, 0.0)
        .expect("absent current-density metadata validates trivially");

    assert_eq!(resolved, None);
}

#[test]
fn imported_step_motion_rejects_stale_baked_mesh_angle() {
    let mut artifact = imported_contract_artifact(
        vec![Region::Airgap],
        vec!["airgap"],
        serde_json::json!([
            {"id": "airgap", "kind": "Airgap", "material": "air"}
        ]),
    );
    artifact.rotor_angle_mech_deg = Some(0.0);
    artifact
        .physics_contract
        .as_mut()
        .unwrap()
        .motion
        .as_mut()
        .unwrap()
        .rotor_angle_mech_deg = Some(0.0);

    let err = validate_imported_step_motion(&artifact, 5.0_f64.to_radians())
        .expect_err("stale baked rotor angle should fail");

    assert_eq!(
        err,
        MeshMetadataError::StaleMotionState {
            expected_rotor_angle_deg: 5.0,
            artifact_rotor_angle_deg: 0.0,
        }
    );
}

#[test]
fn imported_step_motion_allows_fixed_mesh_retagged_at_any_angle() {
    let mut artifact = imported_contract_artifact(
        vec![Region::Airgap],
        vec!["airgap"],
        serde_json::json!([
            {"id": "airgap", "kind": "Airgap", "material": "air"}
        ]),
    );
    artifact.rotor_angle_mech_deg = Some(0.0);
    let motion = artifact
        .physics_contract
        .as_mut()
        .unwrap()
        .motion
        .as_mut()
        .unwrap();
    motion.rotor_angle_mech_deg = Some(0.0);
    motion.rotor_state = Some("fixed_mesh_retagged".to_string());

    validate_imported_step_motion(&artifact, 5.0_f64.to_radians())
        .expect("fixed_mesh_retagged artifacts are re-tagged per step, not stale");
}

#[test]
fn mesh_metadata_rejects_region_count_mismatch_with_typed_error() {
    let mut artifact = imported_contract_artifact(
        vec![Region::Airgap],
        vec!["airgap"],
        serde_json::json!([
            {"id": "airgap", "kind": "Airgap", "material": "air"}
        ]),
    );
    artifact.mesh.regions.clear();

    let err = validate_mesh_metadata(&artifact)
        .expect_err("regions shorter than triangles must fail, not panic");

    assert_eq!(
        err,
        MeshMetadataError::LengthMismatch {
            field: "regions",
            expected: artifact.mesh.triangles.len(),
            actual: 0,
        }
    );
}

#[test]
fn imported_problem_validation_rejects_loaded_ipm_missing_slot_current_density() {
    let mut config = compact_4p12s_config("IPM");
    config.solve_params = Some(
        serde_json::from_value(serde_json::json!({
            "current_amplitude_A": 8.0,
            "current_angle_deg": 45.0,
            "rotor_rotation_model": "remesh_per_step"
        }))
        .expect("solve params should deserialize"),
    );
    let artifact = imported_contract_artifact(
        vec![Region::SlotWinding],
        vec!["slot_1"],
        serde_json::json!([
            {"id": "slot_1", "kind": "SlotWinding", "material": "conductor:copper"}
        ]),
    );

    let err =
        validate_imported_sources_for_problem(&artifact, &artifact.mesh.regions, &config, 0.0, 8.0)
            .expect_err("loaded IPM imported slot current density should be mandatory");

    assert_eq!(
        err,
        MeshMetadataError::MissingCurrentDensity {
            topology: "IPM".to_string(),
            element_index: 0,
        }
    );
}

#[test]
fn imported_problem_validation_accepts_loaded_ipm_region_current_density() {
    let mut config = compact_4p12s_config("IPM");
    config.solve_params = Some(
        serde_json::from_value(serde_json::json!({
            "current_amplitude_A": 8.0,
            "current_angle_deg": 45.0,
            "rotor_rotation_model": "remesh_per_step"
        }))
        .expect("solve params should deserialize"),
    );
    let mut artifact = imported_contract_artifact(
        vec![Region::SlotWinding],
        vec!["slot_1"],
        serde_json::json!([
            {
                "id": "slot_1",
                "kind": "SlotWinding",
                "material": "conductor:copper",
                "current_density_a_per_m2": 1.25e6
            }
        ]),
    );
    artifact.element_current_density_a_per_m2 = None;

    validate_imported_sources_for_problem(&artifact, &artifact.mesh.regions, &config, 0.0, 8.0)
        .expect("loaded IPM imported slot current density can come from the region contract");
}

#[test]
fn solve_problem_consumes_imported_current_density_before_fallback() {
    let mut config = compact_4p12s_config("IPM");
    config.solve_params = Some(
        serde_json::from_value(serde_json::json!({
            "current_amplitude_A": 8.0,
            "current_angle_deg": 45.0,
            "rotor_rotation_model": "remesh_per_step"
        }))
        .expect("solve params should deserialize"),
    );
    let mut artifact = imported_contract_artifact(
        vec![Region::SlotWinding],
        vec!["slot_1"],
        serde_json::json!([
            {
                "id": "slot_1",
                "kind": "SlotWinding",
                "material": "conductor:copper",
                "current_density_a_per_m2": 1.25e6,
                "winding": {
                    "slot_index": 1,
                    "phase": "A",
                    "direction": "in",
                    "layer": 1,
                    "current_density_source": "geometry_ir_winding_table",
                    "current_density_a_per_m2": 1.25e6
                }
            }
        ]),
    );
    artifact.element_current_density_a_per_m2 = Some(vec![Some(1.25e6)]);
    let winding = artifact
        .physics_contract
        .as_ref()
        .and_then(|contract| contract.regions.first())
        .and_then(|region| region.winding.as_ref())
        .expect("winding metadata should deserialize");
    assert_eq!(winding["phase"], "A");

    let ctx = setup_context(&config, Some(artifact.clone())).expect("context should build");
    let problem = SolveProblem::from_prepared_mesh(&ctx, &config, ctx.mesh.clone(), 0.0, 45.0, 8.0)
        .expect("explicit imported current density should build a solve problem");

    assert_eq!(problem.current_densities_a_per_m2, vec![1.25e6]);
}

#[test]
fn solve_problem_consumes_imported_region_current_density_before_fallback() {
    let mut config = compact_4p12s_config("IPM");
    config.solve_params = Some(
        serde_json::from_value(serde_json::json!({
            "current_amplitude_A": 8.0,
            "current_angle_deg": 45.0,
            "rotor_rotation_model": "remesh_per_step"
        }))
        .expect("solve params should deserialize"),
    );
    let mut artifact = imported_contract_artifact(
        vec![Region::SlotWinding],
        vec!["slot_1"],
        serde_json::json!([
            {
                "id": "slot_1",
                "kind": "SlotWinding",
                "material": "conductor:copper",
                "current_density_a_per_m2": 1.25e6,
                "winding": {
                    "slot_index": 1,
                    "phase": "A",
                    "direction": "in",
                    "layer": 1,
                    "current_density_source": "geometry_ir_winding_table",
                    "current_density_a_per_m2": 1.25e6
                }
            }
        ]),
    );
    artifact.element_current_density_a_per_m2 = None;

    let ctx = setup_context(&config, Some(artifact)).expect("context should build");
    let problem = SolveProblem::from_prepared_mesh(&ctx, &config, ctx.mesh.clone(), 0.0, 45.0, 8.0)
        .expect("region imported current density should build a solve problem");

    assert_eq!(problem.current_densities_a_per_m2, vec![1.25e6]);
}

#[test]
fn solve_problem_resolves_materials_from_imported_contract_keys() {
    let mut config = compact_4p12s_config("IPM");
    config.solve_params = Some(
        serde_json::from_value(serde_json::json!({
            "current_amplitude_A": 0.0,
            "current_angle_deg": 45.0,
            "rotor_rotation_model": "remesh_per_step"
        }))
        .expect("solve params should deserialize"),
    );
    let mut artifact = imported_contract_artifact(
        vec![Region::StatorTooth, Region::RotorCore, Region::Magnet],
        vec!["tooth_1", "rotor_core", "magnet_1"],
        serde_json::json!([
            {"id": "tooth_1", "kind": "StatorTooth", "material": "steel:stator:NO20"},
            {"id": "rotor_core", "kind": "RotorCore", "material": "steel:rotor:M36"},
            {
                "id": "magnet_1",
                "kind": "Magnet",
                "material": "magnet:N48SH",
                "magnetization_angle_deg": 0.0
            }
        ]),
    );
    artifact.element_magnetization = Some(vec![None, None, Some(0.0)]);
    artifact.element_current_density_a_per_m2 = Some(vec![Some(0.0), Some(0.0), Some(0.0)]);
    let (stator_steel, rotor_steel) = resolved_contract_steel_keys(&artifact, &config);

    let ctx = setup_context(&config, Some(artifact)).expect("context should build");
    let problem = SolveProblem::from_prepared_mesh(&ctx, &config, ctx.mesh.clone(), 0.0, 45.0, 0.0)
        .expect("contract material keys should resolve");

    assert_eq!(stator_steel, "NO20");
    assert_eq!(rotor_steel, "M36");
    assert!(problem.materials[0].mu_rel > 1.0);
    assert!(problem.materials[1].mu_rel > 1.0);
    assert!(problem.materials[2].br > 1.35);
}

#[test]
fn solve_problem_rejects_unknown_contract_material_key() {
    let config = compact_4p12s_config("IPM");
    let mut artifact = imported_contract_artifact(
        vec![Region::StatorTooth],
        vec!["tooth_1"],
        serde_json::json!([
            {"id": "tooth_1", "kind": "StatorTooth", "material": "steel:stator:unknownium"}
        ]),
    );
    artifact.element_magnetization = Some(vec![None]);
    artifact.element_current_density_a_per_m2 = Some(vec![Some(0.0)]);

    let ctx = setup_context(&config, Some(artifact)).expect("context should build");
    let err = SolveProblem::from_prepared_mesh(&ctx, &config, ctx.mesh.clone(), 0.0, 45.0, 0.0)
        .expect_err("unknown contract material should fail");

    assert_eq!(
        err,
        MeshMetadataError::UnknownMaterial {
            region: Region::StatorTooth,
            material_key: "steel:stator:unknownium".to_string(),
        }
    );
}

#[test]
fn nonlinear_tolerance_tracks_solve_quality() {
    assert_eq!(default_nonlinear_tol_for_quality(Some("quick")), 0.075);
    assert_eq!(default_nonlinear_tol_for_quality(Some("standard")), 0.075);
    assert_eq!(default_nonlinear_tol_for_quality(Some("fine")), 0.05);
    assert_eq!(default_nonlinear_tol_for_quality(Some("custom")), 0.05);
    assert_eq!(default_nonlinear_tol_for_quality(None), 0.05);
}

#[test]
fn picard_relaxation_state_matches_legacy_update_policy() {
    let config = NonlinearSolveConfig {
        max_iterations: 10,
        convergence_threshold: 0.05,
        initial_relaxation: 0.1,
        adaptive_picard: true,
        min_relaxation: 0.05,
        max_relaxation: 0.2,
        mu_rel_step_cap: 1.5,
        backtracking_enabled: true,
        backtracking_growth_limit: 1.05,
        backtracking_shrink: 0.5,
        solver_kind: NonlinearSolverKind::Picard,
        newton_initial_damping: 1.0,
        newton_min_damping: 0.0625,
        newton_line_search_shrink: 0.5,
        newton_line_search_accept_ratio: 0.999,
        newton_convergence_threshold: 0.04,
    };
    let mut state = PicardRelaxationState::new(config);

    assert!((state.relaxation - 0.1).abs() < 1e-15);
    assert!((config.convergence_residual(0.8) - 0.08).abs() < 1e-15);

    state.update_after_residual(1.0, config);
    assert!((state.relaxation - 0.1).abs() < 1e-15);

    state.update_after_residual(1.06, config);
    assert!((state.relaxation - 0.055).abs() < 1e-15);

    state.update_after_residual(0.04, config);
    assert!((state.relaxation - 0.055).abs() < 1e-15);

    state.update_after_residual(0.02, config);
    assert!((state.relaxation - 0.06875).abs() < 1e-15);
}

#[test]
fn nonlinear_backtracking_shrinks_to_relaxation_floor_on_raw_growth() {
    let config = NonlinearSolveConfig {
        max_iterations: 10,
        convergence_threshold: 0.05,
        initial_relaxation: 0.1,
        adaptive_picard: true,
        min_relaxation: 0.0125,
        max_relaxation: 0.2,
        mu_rel_step_cap: 1.5,
        backtracking_enabled: true,
        backtracking_growth_limit: 1.05,
        backtracking_shrink: 0.5,
        solver_kind: NonlinearSolverKind::Picard,
        newton_initial_damping: 1.0,
        newton_min_damping: 0.0625,
        newton_line_search_shrink: 0.5,
        newton_line_search_accept_ratio: 0.999,
        newton_convergence_threshold: 0.04,
    };

    let (relaxation, attempts) = backtracked_relaxation(Some(1.0), 1.2, 0.1, config);
    assert_eq!(attempts, 3);
    assert!((relaxation - 0.0125).abs() < 1e-15);

    let (relaxation, attempts) = backtracked_relaxation(Some(1.0), 1.01, 0.1, config);
    assert_eq!(attempts, 0);
    assert!((relaxation - 0.1).abs() < 1e-15);
}

#[test]
fn nonlinear_mu_rel_step_cap_bounds_relaxed_update() {
    assert!((cap_mu_rel_step(100.0, 1000.0, 1.5) - 150.0).abs() < 1e-12);
    assert!((cap_mu_rel_step(100.0, 10.0, 1.5) - (100.0 / 1.5)).abs() < 1e-12);
    assert!((cap_mu_rel_step(100.0, 120.0, 1.5) - 120.0).abs() < 1e-12);
    assert!((cap_mu_rel_step(100.0, 40.0, 1.0) - 100.0).abs() < 1e-12);
}

#[test]
fn outer_dirichlet_boundary_nodes_excludes_rotor_inner_bore() {
    let mesh = TriMesh {
        nodes: vec![
            [0.0116, 0.0],
            [0.0, 0.0116],
            [0.108, 0.0],
            [0.0, 0.108],
            [0.058, 0.0],
        ],
        triangles: vec![[0, 1, 4], [2, 3, 4]],
        regions: vec![Region::RotorCore, Region::StatorYoke],
        boundary_nodes: vec![0, 1, 2, 3],
        sector_edge_pairs: Vec::new(),
        info: MeshInfo {
            num_nodes: 5,
            num_triangles: 2,
            pole_pitch_deg: 90.0,
            n_pole_pitches: 4,
            total_span_deg: 360.0,
            angular_divisions: 4,
            radial_rings: 2,
            mesh_density: "test".to_string(),
            radial_layers: vec!["rotor_core".to_string(), "stator_yoke".to_string()],
            airgap_inner_radius_mm: None,
            airgap_outer_radius_mm: None,
            mesh_source: None,
            magnet_outer_radius_mm: 63.0,
            magnet_embrace: 0.85,
            stator_inner_radius_mm: 64.0,
            stator_slot_outer_radius_mm: 96.0,
            stator_outer_radius_mm: 108.0,
        },
    };

    assert_eq!(outer_dirichlet_boundary_nodes(&mesh), vec![2, 3]);
}

#[test]
fn motor_boundary_set_deduplicates_legacy_multi_pitch_nodes_in_input_order() {
    let mesh = TriMesh {
        nodes: vec![
            [0.0116, 0.0],
            [0.0, 0.0116],
            [0.108, 0.0],
            [0.0, 0.108],
            [0.058, 0.0],
        ],
        triangles: vec![[0, 1, 4], [2, 3, 4]],
        regions: vec![Region::RotorCore, Region::StatorYoke],
        boundary_nodes: vec![3, 2, 3, 2],
        sector_edge_pairs: vec![(0, 1)],
        info: MeshInfo {
            num_nodes: 5,
            num_triangles: 2,
            pole_pitch_deg: 90.0,
            n_pole_pitches: 4,
            total_span_deg: 360.0,
            angular_divisions: 4,
            radial_rings: 2,
            mesh_density: "test".to_string(),
            radial_layers: vec!["rotor_core".to_string(), "stator_yoke".to_string()],
            airgap_inner_radius_mm: None,
            airgap_outer_radius_mm: None,
            mesh_source: None,
            magnet_outer_radius_mm: 63.0,
            magnet_embrace: 0.85,
            stator_inner_radius_mm: 64.0,
            stator_slot_outer_radius_mm: 96.0,
            stator_outer_radius_mm: 108.0,
        },
    };

    let boundaries = motor_boundary_set(&mesh, 4);

    assert_eq!(boundaries.dirichlet_az_zero_nodes, vec![3, 2]);
    assert_eq!(boundaries.paired_nodes.len(), 1);
    assert_eq!(boundaries.paired_nodes[0].nodes, [0, 1]);
}

fn cogging_policy_env_lock() -> &'static Mutex<()> {
    static LOCK: OnceLock<Mutex<()>> = OnceLock::new();
    LOCK.get_or_init(|| Mutex::new(()))
}

fn cogging_policy_config(stator_od_mm: f64, rotor_rotation_model: &str) -> MotorConfig {
    parse_motor_config(&format!(
        r#"{{
          "schema_version": "1.0",
          "topology": "SPM",
          "stator": {{
            "OD_mm": {stator_od_mm},
            "ID_mm": {stator_id_mm},
            "slot_count": 12,
            "stack_length_mm": 40.0,
            "slot_opening_mm": 2.5,
            "tooth_width_mm": 4.5,
            "yoke_thickness_mm": 4.5
          }},
          "rotor": {{
            "OD_mm": {rotor_od_mm},
            "magnet_thickness_mm": 3.0,
            "magnet_width_mm": 16.5,
            "pole_count": 4,
            "magnet_embrace": 0.85
          }},
          "winding": {{
            "type": "concentrated",
            "turns_per_coil": 10,
            "layers": 1,
            "parallel_paths": 1
          }},
          "materials": {{
            "stator_steel": "M19",
            "rotor_steel": "M19",
            "magnet_grade": "N42",
            "conductor": "copper"
          }},
          "solve_params": {{
            "current_amplitude_A": 0.01,
            "current_angle_deg": 0.0,
            "rated_speed_rpm": 3000,
            "rotor_rotation_model": "{rotor_rotation_model}"
          }}
        }}"#,
        stator_id_mm = stator_od_mm * 0.68,
        rotor_od_mm = stator_od_mm * 0.5,
    ))
}

fn spm_8p12s_remesh_config() -> MotorConfig {
    parse_motor_config(
        r#"{
          "schema_version": "1.0",
          "topology": "SPM",
          "stator": {
            "OD_mm": 100.0,
            "ID_mm": 60.0,
            "slot_count": 12,
            "stack_length_mm": 50.0,
            "slot_opening_mm": 2.0,
            "tooth_width_mm": 9.0,
            "yoke_thickness_mm": 8.0
          },
          "rotor": {
            "OD_mm": 54.0,
            "magnet_thickness_mm": 2.5,
            "magnet_width_mm": 16.5,
            "pole_count": 8,
            "magnet_embrace": 0.833,
            "bridge_thickness_mm": 0.8
          },
          "winding": {
            "type": "concentrated",
            "turns_per_coil": 12,
            "layers": 1,
            "parallel_paths": 1
          },
          "materials": {
            "stator_steel": "M19",
            "rotor_steel": "M19",
            "magnet_grade": "N42",
            "conductor": "copper"
          },
          "solve_params": {
            "current_amplitude_A": 0.0,
            "current_amplitude_convention": "peak",
            "current_angle_deg": 0.0,
            "rated_speed_rpm": 3000,
            "mesh_density": "fine",
            "rotor_rotation_model": "remesh_per_step"
          },
          "solve_options": {
            "torque_sweep": false,
            "back_emf": false,
            "cogging_torque": false,
            "thd_analysis": false
          }
        }"#,
    )
}

#[test]
fn single_angle_remesh_without_imported_mesh_reports_removed_native_generation() {
    let config = spm_8p12s_remesh_config();
    let err = single_angle_context_artifact(&config, 0.0, None)
        .expect_err("direct remesh should require an imported mesh artifact");

    assert!(
        err.contains("Rust native mesh generation was removed"),
        "{err}"
    );
    assert!(err.contains("Gmsh"), "{err}");
}

#[test]
fn single_angle_imported_mesh_bypasses_removed_remesh_generation() {
    let config = spm_8p12s_remesh_config();
    let pole_pairs = (config.rotor.pole_count / 2).max(1) as f64;
    let mut imported_mesh = metadata_test_artifact(vec![Region::Airgap], None);
    imported_mesh.mesh.info.mesh_source = Some(MeshSource::Gmsh);
    let (_mesh, rotor_baked_in_mesh) = single_angle_context_artifact(
        &config,
        (10.0_f64 / pole_pairs).to_radians(),
        Some(imported_mesh),
    )
    .expect("imported mesh artifact should bypass remesh generation");
    assert!(
        !rotor_baked_in_mesh,
        "imported meshes remain fixed inputs and are not regenerated"
    );
}

#[test]
fn setup_context_keeps_imported_solve_mesh_artifact() {
    let config = spm_8p12s_remesh_config();
    let mut artifact = metadata_test_artifact(vec![Region::Airgap], None);
    artifact.mesh.info.mesh_source = Some(MeshSource::Gmsh);
    let expected_nodes = artifact.mesh.info.num_nodes;
    let expected_triangles = artifact.mesh.info.num_triangles;
    let ctx = setup_context(&config, Some(artifact))
        .expect("imported solve mesh artifact should build context");

    assert_eq!(ctx.mesh.info.num_nodes, expected_nodes);
    assert_eq!(ctx.mesh.info.num_triangles, expected_triangles);
    assert_eq!(ctx.solve_mesh_artifact.mesh.info.num_nodes, expected_nodes);
    assert_eq!(
        ctx.solve_mesh_artifact.mesh.info.num_triangles,
        expected_triangles
    );
    assert_eq!(ctx.solve_mesh_artifact.mesh.nodes[0], ctx.mesh.nodes[0]);
}

#[test]
fn native_mesh_preview_returns_removed_generation_error() {
    let config = compact_4p12s_config("IPM");

    let err = super::generate_mesh_preview_at_angle(&config, 0.0)
        .expect_err("native Rust mesh preview should be removed");

    assert!(
        err.contains("Rust native mesh generation was removed"),
        "{err}"
    );
    assert!(err.contains("Gmsh"), "{err}");
}

#[test]
fn ipm_gmsh_imported_mesh_context_uses_imported_slot_areas() {
    let ipm_config = compact_4p12s_config("IPM");
    let imported_mesh = full_slot_winding_import_artifact(
        ipm_config.stator.slot_count,
        ipm_config.rotor.pole_count,
    );

    let ctx = setup_context(&ipm_config, Some(imported_mesh)).expect(
        "complete reference solver-import slot regions should avoid IPM analytical slot-area inference",
    );

    assert!(!ctx.slot_areas.is_empty());
    assert!(ctx.slot_areas.iter().all(|area| *area > 0.0));
    assert_eq!(
        ctx.solve_mesh_artifact.mesh.info.mesh_density,
        "gmsh_import"
    );
}

#[test]
fn ipm_imported_mesh_context_still_rejects_incomplete_slot_areas() {
    let ipm_config = compact_4p12s_config("IPM");
    let mut imported_mesh = metadata_test_artifact(vec![Region::RotorCore], None);
    imported_mesh.mesh.info.mesh_density = "gmsh_import".to_string();
    imported_mesh.mesh.info.mesh_source = Some(MeshSource::Gmsh);

    let err = match setup_context(&ipm_config, Some(imported_mesh)) {
        Ok(_) => panic!("incomplete IPM imported slot areas should remain unsupported"),
        Err(err) => err,
    };

    assert!(err.contains("topology 'IPM'"), "{err}");
    assert!(err.contains("IPM slot-area inference"), "{err}");
    assert!(err.contains("IPM slot-area inference"), "{err}");
}


#[test]
fn ipm_gmsh_imported_single_angle_treats_mesh_as_rotor_baked() {
    let ipm_config = compact_4p12s_config("IPM");
    let mut imported_mesh = metadata_test_artifact(vec![Region::Airgap], None);
    imported_mesh.mesh.info.mesh_density = "gmsh_coarse".to_string();
    imported_mesh.mesh.info.mesh_source = Some(MeshSource::Gmsh);
    imported_mesh.rotor_angle_mech_deg = Some(0.0);

    let (_artifact, rotor_baked_in_mesh) =
        single_angle_context_artifact(&ipm_config, 0.0, Some(imported_mesh))
            .expect("IPM Gmsh artifact should be accepted as a baked single-angle mesh");

    assert!(rotor_baked_in_mesh);
}

#[test]
fn ipm_machine_model_keeps_topology_specific_geometry_rules_only() {
    let config = compact_4p12s_config("IPM");
    let machine = super::model::MachineModel::from_config(&config);

    let err = machine
        .effective_magnet_embrace()
        .expect_err("IPM must not use the SPM magnet-embrace fallback");
    assert_eq!(
        err.to_string(),
        "magneto2d topology 'IPM' does not support SPM magnet-embrace fallback in this solver configuration"
    );
}

#[test]
fn airgap_brbt_profile_bins_radial_and_tangential_fields() {
    let mesh = TriMesh {
        nodes: vec![
            [15.5e-3, 0.0],
            [17.0e-3, 0.0],
            [15.5e-3, 1.5e-3],
            [0.0, 15.5e-3],
            [0.0, 17.0e-3],
            [-1.5e-3, 15.5e-3],
        ],
        triangles: vec![[0, 1, 2], [3, 4, 5]],
        regions: vec![Region::Airgap, Region::Airgap],
        boundary_nodes: Vec::new(),
        sector_edge_pairs: Vec::new(),
        info: MeshInfo {
            num_nodes: 6,
            num_triangles: 2,
            pole_pitch_deg: 180.0,
            n_pole_pitches: 2,
            total_span_deg: 360.0,
            angular_divisions: 2,
            radial_rings: 2,
            mesh_density: "test".to_string(),
            radial_layers: vec!["airgap".to_string()],
            airgap_inner_radius_mm: None,
            airgap_outer_radius_mm: None,
            mesh_source: None,
            magnet_outer_radius_mm: 15.5,
            magnet_embrace: 1.0,
            stator_inner_radius_mm: 17.0,
            stator_slot_outer_radius_mm: 21.0,
            stator_outer_radius_mm: 25.0,
        },
    };
    let fields = vec![
        ElementField {
            bx: 1.0,
            by: 0.0,
            b_mag: 1.0,
        },
        ElementField {
            bx: -1.0,
            by: 0.0,
            b_mag: 1.0,
        },
    ];
    let profile = build_airgap_brbt_profile(
        &mesh,
        &fields,
        &mesh.regions,
        mesh.info
            .airgap_band()
            .expect("test mesh should define an airgap band"),
    )
    .expect("airgap profile should be built");

    assert_eq!(profile.sample_count, 2);
    assert_eq!(profile.bin_count, 144);
    assert_eq!(profile.bins.len(), 2);
    assert!((profile.bins[0].br_t - 0.999).abs() < 0.01);
    assert!(profile.bins.iter().any(|bin| bin.bt_t > 0.99));
}

#[test]
fn setup_context_resolves_airgap_band_from_mesh_metadata() {
    let config = cogging_policy_config(50.0, "fixed_mesh");
    let mut artifact = metadata_test_artifact(vec![Region::Airgap], None);
    artifact.mesh.info.airgap_inner_radius_mm = Some(63.0);
    artifact.mesh.info.airgap_outer_radius_mm = Some(65.0);
    artifact.mesh.info.magnet_outer_radius_mm = 61.0;
    artifact.mesh.info.stator_inner_radius_mm = 66.0;

    let ctx = setup_context(&config, Some(artifact)).expect("context should build");

    assert_eq!(ctx.airgap_band.source, AirgapBandSource::FromMesh);
    assert_eq!(ctx.airgap_band.inner_radius_mm, 63.0);
    assert_eq!(ctx.airgap_band.outer_radius_mm, 65.0);
}

#[test]
fn setup_context_resolves_airgap_band_from_legacy_fallback() {
    let config = cogging_policy_config(50.0, "fixed_mesh");
    let artifact = metadata_test_artifact(vec![Region::Airgap], None);

    let ctx = setup_context(&config, Some(artifact)).expect("context should build");

    assert_eq!(
        ctx.airgap_band.source,
        AirgapBandSource::FromMagnetOuterFallback
    );
    assert_eq!(ctx.airgap_band.inner_radius_mm, 64.0);
    assert_eq!(ctx.airgap_band.outer_radius_mm, 65.0);
}

#[test]
fn finite_difference_waveform_handles_open_endpoints() {
    let values = vec![0.0, 1.0, 4.0];
    let derivative = finite_difference_waveform(&values, 1.0, false);
    assert!((derivative[0] - 1.0).abs() < 1e-12);
    assert!((derivative[1] - 2.0).abs() < 1e-12);
    assert!((derivative[2] - 3.0).abs() < 1e-12);
}

#[test]
fn energy_and_coenergy_fd_torque_signs_match() {
    let potential_energy = vec![0.0, 1.0, 4.0];
    let coenergy = vec![0.0, -1.0, -4.0];
    let torque_from_energy: Vec<f64> = finite_difference_waveform(&potential_energy, 1.0, false)
        .into_iter()
        .map(|d_energy_dtheta| -d_energy_dtheta)
        .collect();
    let torque_from_coenergy = finite_difference_waveform(&coenergy, 1.0, false);

    for (left, right) in torque_from_energy.iter().zip(torque_from_coenergy.iter()) {
        assert!((left - right).abs() < 1e-12);
    }
}

#[test]
fn pm_source_work_scale_parser_accepts_only_finite_nonnegative_values() {
    assert_eq!(parse_pm_source_work_scale(None), 1.0);
    assert_eq!(parse_pm_source_work_scale(Some("0.885")), 0.885);
    assert_eq!(parse_pm_source_work_scale(Some("0")), 0.0);
    assert_eq!(parse_pm_source_work_scale(Some("-1")), 1.0);
    assert_eq!(parse_pm_source_work_scale(Some("nan")), 1.0);
    assert_eq!(parse_pm_source_work_scale(Some("not-a-number")), 1.0);
}

#[test]
fn pm_source_work_scale_adjusts_exported_energy_components() {
    let _lock = cogging_policy_env_lock().lock().unwrap();
    let _env = EnvVarGuard::set("COILEM_MAGNETO2D_PM_SOURCE_WORK_SCALE", "1");
    let mesh = TriMesh {
        nodes: vec![[0.0, 0.0], [1.0e-3, 0.0], [0.0, 1.0e-3]],
        triangles: vec![[0, 1, 2]],
        regions: vec![Region::Magnet],
        boundary_nodes: Vec::new(),
        sector_edge_pairs: Vec::new(),
        info: MeshInfo {
            num_nodes: 3,
            num_triangles: 1,
            pole_pitch_deg: 360.0,
            n_pole_pitches: 1,
            total_span_deg: 360.0,
            angular_divisions: 1,
            radial_rings: 1,
            mesh_density: "test".to_string(),
            radial_layers: vec!["magnet".to_string()],
            airgap_inner_radius_mm: None,
            airgap_outer_radius_mm: None,
            mesh_source: None,
            magnet_outer_radius_mm: 1.0,
            magnet_embrace: 1.0,
            stator_inner_radius_mm: 2.0,
            stator_slot_outer_radius_mm: 3.0,
            stator_outer_radius_mm: 4.0,
        },
    };
    let materials = vec![MaterialProps {
        mu_rel: 1.0,
        nu: 2.0,
        br: 1.0,
        mag_angle_rad: 0.0,
    }];
    let currents = vec![0.0];
    let az = vec![0.0, 0.0, 1.0];

    let baseline = compute_energy_functional_summary(&mesh, &materials, &currents, &az, 1000.0, 1);
    std::env::set_var("COILEM_MAGNETO2D_PM_SOURCE_WORK_SCALE", "0.25");
    let scaled = compute_energy_functional_summary(&mesh, &materials, &currents, &az, 1000.0, 1);

    assert!((baseline.field_energy_j - scaled.field_energy_j).abs() < 1e-12);
    assert!((scaled.pm_source_work_j - 0.25 * baseline.pm_source_work_j).abs() < 1e-12);
    assert!(
        (scaled.pm_source_work_magnet_detail_j.radial_middle_j
            - 0.25 * baseline.pm_source_work_magnet_detail_j.radial_middle_j)
            .abs()
            < 1e-12
    );
    assert!(
        (scaled.coenergy_j
            - (scaled.pm_source_work_j + scaled.current_source_work_j - scaled.field_energy_j))
            .abs()
            < 1e-12
    );
    assert!((scaled.coenergy_by_region_j.magnet_j - scaled.coenergy_j).abs() < 1e-12);
    assert!((scaled.coenergy_magnet_detail_j.radial_middle_j - scaled.coenergy_j).abs() < 1e-12);
}

#[test]
fn pm_sidewall_quadrature_diagnostic_scales_pm_corner_terms_only_when_enabled() {
    let _lock = cogging_policy_env_lock().lock().unwrap();
    let _enabled = EnvVarGuard::set("COILEM_MAGNETO2D_PM_SIDEWALL_QUADRATURE_DIAGNOSTIC", "1");
    let _pm_scale = EnvVarGuard::set(
        "COILEM_MAGNETO2D_PM_SIDEWALL_QUADRATURE_PM_SOURCE_SCALE",
        "2.0",
    );
    let _field_scale =
        EnvVarGuard::set("COILEM_MAGNETO2D_PM_SIDEWALL_QUADRATURE_FIELD_SCALE", "3.0");
    let _side_window = EnvVarGuard::set(
        "COILEM_MAGNETO2D_PM_SIDEWALL_QUADRATURE_SIDE_WINDOW_MM",
        "1000",
    );
    let _corner_window = EnvVarGuard::set(
        "COILEM_MAGNETO2D_PM_SIDEWALL_QUADRATURE_CORNER_WINDOW_MM",
        "1000",
    );

    let config = pm_sidewall_quadrature_diagnostic_config();
    assert!(config.enabled);
    assert!((config.pm_source_scale - 2.0).abs() < 1e-12);
    assert!((config.field_scale - 3.0).abs() < 1e-12);
    assert!((config.coenergy_scale - 1.0).abs() < 1e-12);

    let mesh = TriMesh {
        nodes: vec![[0.0, 0.0], [1.0e-3, 0.0], [0.0, 1.0e-3]],
        triangles: vec![[0, 1, 2]],
        regions: vec![Region::Magnet],
        boundary_nodes: Vec::new(),
        sector_edge_pairs: Vec::new(),
        info: MeshInfo {
            num_nodes: 3,
            num_triangles: 1,
            pole_pitch_deg: 360.0,
            n_pole_pitches: 1,
            total_span_deg: 360.0,
            angular_divisions: 1,
            radial_rings: 1,
            mesh_density: "test".to_string(),
            radial_layers: vec!["magnet".to_string()],
            airgap_inner_radius_mm: None,
            airgap_outer_radius_mm: None,
            mesh_source: None,
            magnet_outer_radius_mm: 1.0,
            magnet_embrace: 1.0,
            stator_inner_radius_mm: 2.0,
            stator_slot_outer_radius_mm: 3.0,
            stator_outer_radius_mm: 4.0,
        },
    };
    let materials = vec![MaterialProps {
        mu_rel: 1.0,
        nu: 2.0,
        br: 1.0,
        mag_angle_rad: 0.0,
    }];
    let currents = vec![0.0];
    let az = vec![0.0, 0.0, 1.0];

    std::env::remove_var("COILEM_MAGNETO2D_PM_SIDEWALL_QUADRATURE_DIAGNOSTIC");
    let baseline = compute_energy_functional_summary(&mesh, &materials, &currents, &az, 1000.0, 1);
    std::env::set_var("COILEM_MAGNETO2D_PM_SIDEWALL_QUADRATURE_DIAGNOSTIC", "1");
    let scaled = compute_energy_functional_summary(&mesh, &materials, &currents, &az, 1000.0, 1);

    assert!((scaled.field_energy_j - 3.0 * baseline.field_energy_j).abs() < 1e-12);
    assert!((scaled.pm_source_work_j - 2.0 * baseline.pm_source_work_j).abs() < 1e-12);
    assert!(
        (scaled.coenergy_j
            - (scaled.pm_source_work_j + scaled.current_source_work_j - scaled.field_energy_j))
            .abs()
            < 1e-12
    );
    assert!((scaled.coenergy_by_region_j.magnet_j - scaled.coenergy_j).abs() < 1e-12);
    assert!(
        (scaled.coenergy_magnet_detail_j.angular_edge_j - scaled.coenergy_j).abs() < 1e-12
            || (scaled.coenergy_magnet_detail_j.angular_interior_j - scaled.coenergy_j).abs()
                < 1e-12
    );
}

#[test]
fn pm_sidewall_quadrature_diagnostic_can_scale_local_coenergy() {
    let _lock = cogging_policy_env_lock().lock().unwrap();
    let _enabled = EnvVarGuard::set("COILEM_MAGNETO2D_PM_SIDEWALL_QUADRATURE_DIAGNOSTIC", "1");
    let _coenergy_scale = EnvVarGuard::set(
        "COILEM_MAGNETO2D_PM_SIDEWALL_QUADRATURE_COENERGY_SCALE",
        "0.5",
    );
    let _side_window = EnvVarGuard::set(
        "COILEM_MAGNETO2D_PM_SIDEWALL_QUADRATURE_SIDE_WINDOW_MM",
        "1000",
    );
    let _radial_depth = EnvVarGuard::set(
        "COILEM_MAGNETO2D_PM_SIDEWALL_QUADRATURE_RADIAL_DEPTH_MM",
        "1000",
    );

    let config = pm_sidewall_quadrature_diagnostic_config();
    assert!(config.enabled);
    assert!((config.pm_source_scale - 1.0).abs() < 1e-12);
    assert!((config.field_scale - 1.0).abs() < 1e-12);
    assert!((config.coenergy_scale - 0.5).abs() < 1e-12);

    let mesh = TriMesh {
        nodes: vec![[0.0, 0.0], [1.0e-3, 0.0], [0.0, 1.0e-3]],
        triangles: vec![[0, 1, 2]],
        regions: vec![Region::Magnet],
        boundary_nodes: Vec::new(),
        sector_edge_pairs: Vec::new(),
        info: MeshInfo {
            num_nodes: 3,
            num_triangles: 1,
            pole_pitch_deg: 360.0,
            n_pole_pitches: 1,
            total_span_deg: 360.0,
            angular_divisions: 1,
            radial_rings: 1,
            mesh_density: "test".to_string(),
            radial_layers: vec!["magnet".to_string()],
            airgap_inner_radius_mm: None,
            airgap_outer_radius_mm: None,
            mesh_source: None,
            magnet_outer_radius_mm: 1.0,
            magnet_embrace: 1.0,
            stator_inner_radius_mm: 2.0,
            stator_slot_outer_radius_mm: 3.0,
            stator_outer_radius_mm: 4.0,
        },
    };
    let materials = vec![MaterialProps {
        mu_rel: 1.0,
        nu: 2.0,
        br: 1.0,
        mag_angle_rad: 0.0,
    }];
    let currents = vec![0.0];
    let az = vec![0.0, 0.0, 1.0];

    std::env::remove_var("COILEM_MAGNETO2D_PM_SIDEWALL_QUADRATURE_DIAGNOSTIC");
    let baseline = compute_energy_functional_summary(&mesh, &materials, &currents, &az, 1000.0, 1);
    std::env::set_var("COILEM_MAGNETO2D_PM_SIDEWALL_QUADRATURE_DIAGNOSTIC", "1");
    let scaled = compute_energy_functional_summary(&mesh, &materials, &currents, &az, 1000.0, 1);

    assert!((scaled.field_energy_j - baseline.field_energy_j).abs() < 1e-12);
    assert!((scaled.coenergy_j - 0.5 * baseline.coenergy_j).abs() < 1e-12);
    assert!(
        (scaled.coenergy_j
            - (scaled.pm_source_work_j + scaled.current_source_work_j - scaled.field_energy_j))
            .abs()
            < 1e-12
    );
    assert!((scaled.coenergy_by_region_j.magnet_j - scaled.coenergy_j).abs() < 1e-12);
}

#[test]
fn explicit_zero_angle_is_not_rewritten_to_negative_q_axis() {
    let config = parse_motor_config(
        r#"{
          "schema_version": "1.0",
          "topology": "SPM",
          "stator": {
            "OD_mm": 200.0,
            "ID_mm": 130.0,
            "slot_count": 12,
            "stack_length_mm": 100.0,
            "slot_opening_mm": 10.2,
            "tooth_width_mm": 15.3,
            "yoke_thickness_mm": 24.0
          },
          "rotor": {
            "OD_mm": 120.0,
            "magnet_thickness_mm": 4.0,
            "magnet_width_mm": 33.0,
            "pole_count": 8,
            "magnet_embrace": 0.8
          },
          "winding": {
            "type": "concentrated",
            "turns_per_coil": 8,
            "layers": 1,
            "parallel_paths": 1
          },
          "materials": {
            "stator_steel": "M19",
            "rotor_steel": "M19",
            "magnet_grade": "N42",
            "conductor": "copper"
          },
          "solve_params": {
            "current_amplitude_A": 50.0,
            "current_angle_deg": 0.0,
            "rated_speed_rpm": 3000
          }
        }"#,
    );

    let operating_point = resolve_operating_point(config.solve_params.as_ref())
        .expect("operating point should resolve");

    assert_eq!(operating_point.requested_current_angle_deg, Some(0.0));
    assert_eq!(operating_point.resolved_current_angle_deg, 0.0);
}

#[test]
fn missing_angle_defaults_to_zero_for_spm_q_axis() {
    let config = parse_motor_config(
        r#"{
          "schema_version": "1.0",
          "topology": "SPM",
          "stator": {
            "OD_mm": 200.0,
            "ID_mm": 130.0,
            "slot_count": 12,
            "stack_length_mm": 100.0,
            "slot_opening_mm": 10.2,
            "tooth_width_mm": 15.3,
            "yoke_thickness_mm": 24.0
          },
          "rotor": {
            "OD_mm": 120.0,
            "magnet_thickness_mm": 4.0,
            "magnet_width_mm": 33.0,
            "pole_count": 8,
            "magnet_embrace": 0.8
          },
          "winding": {
            "type": "concentrated",
            "turns_per_coil": 8,
            "layers": 1,
            "parallel_paths": 1
          },
          "materials": {
            "stator_steel": "M19",
            "rotor_steel": "M19",
            "magnet_grade": "N42",
            "conductor": "copper"
          },
          "solve_params": {
            "current_amplitude_A": 50.0,
            "rated_speed_rpm": 3000
          }
        }"#,
    );

    let operating_point = resolve_operating_point(config.solve_params.as_ref())
        .expect("operating point should resolve");

    assert_eq!(operating_point.requested_current_angle_deg, None);
    assert_eq!(operating_point.resolved_current_angle_deg, 0.0);
    assert!(operating_point
        .resolution_rule
        .contains("defaulting to gamma=0"));
}

#[test]
fn rms_current_amplitude_is_converted_to_peak_current() {
    let config = parse_motor_config(
        r#"{
          "schema_version": "1.0",
          "topology": "SPM",
          "stator": {
            "OD_mm": 200.0,
            "ID_mm": 130.0,
            "slot_count": 12,
            "stack_length_mm": 100.0,
            "slot_opening_mm": 10.2,
            "tooth_width_mm": 15.3,
            "yoke_thickness_mm": 24.0
          },
          "rotor": {
            "OD_mm": 120.0,
            "magnet_thickness_mm": 4.0,
            "magnet_width_mm": 33.0,
            "pole_count": 8,
            "magnet_embrace": 0.8
          },
          "winding": {
            "type": "concentrated",
            "turns_per_coil": 8,
            "layers": 1,
            "parallel_paths": 1
          },
          "materials": {
            "stator_steel": "M19",
            "rotor_steel": "M19",
            "magnet_grade": "N42",
            "conductor": "copper"
          },
          "solve_params": {
            "current_amplitude_A": 50.0,
            "current_amplitude_convention": "rms",
            "current_angle_deg": 30.0,
            "rated_speed_rpm": 3000
          }
        }"#,
    );

    let operating_point = resolve_operating_point(config.solve_params.as_ref())
        .expect("operating point should resolve");

    assert_eq!(operating_point.current_amplitude_convention, "rms");
    assert_eq!(operating_point.resolved_current_amplitude_a, 50.0);
    assert!((operating_point.resolved_phase_current_peak_a - 50.0 * 2.0_f64.sqrt()).abs() < 1e-9);
    assert!(operating_point.current_amplitude_rule.contains("sqrt(2)"));
}

#[test]
fn applied_current_angle_uses_unified_q_axis_gamma_convention() {
    // Positive gamma ADVANCES the source phasor. gamma=0
    // rows stay bit-identical to the legacy rotor_elec - 90 source angle.
    assert_eq!(applied_current_angle_deg(30.0, 0.0), -60.0);
    assert_eq!(applied_current_angle_deg(0.0, 0.0), -90.0);
    assert_eq!(applied_current_angle_deg(30.0, 30.0), -30.0);
}

#[test]
fn rotor_electrical_angle_scales_with_pole_pairs() {
    let mech_rad = 15.0_f64.to_radians();
    assert!((rotor_electrical_angle_deg(mech_rad, 2) - 30.0).abs() < 1e-9);
}

#[test]
fn single_angle_sync_matches_full_sweep_rule() {
    let mech_rad = 15.0_f64.to_radians();
    let pole_pairs = 2;
    let advance_deg = 0.0;
    assert!((synced_current_angle_deg(mech_rad, pole_pairs, advance_deg) - (-60.0)).abs() < 1e-9);
    assert!((synced_current_angle_deg(mech_rad, pole_pairs, 30.0) - (-30.0)).abs() < 1e-9);
}

#[test]
fn spm_effective_magnet_embrace_follows_width_at_magnet_midline() {
    let config = parse_motor_config(
        r#"{
          "schema_version": "1.0",
          "topology": "SPM",
          "stator": {
            "OD_mm": 50.0,
            "ID_mm": 34.0,
            "slot_count": 12,
            "stack_length_mm": 40.0,
            "slot_opening_mm": 2.5,
            "tooth_width_mm": 4.5,
            "yoke_thickness_mm": 4.5
          },
          "rotor": {
            "OD_mm": 25.0,
            "magnet_thickness_mm": 3.0,
            "magnet_width_mm": 16.5,
            "pole_count": 4,
            "magnet_embrace": 0.85
          },
          "winding": {
            "type": "concentrated",
            "turns_per_coil": 10,
            "layers": 1,
            "parallel_paths": 1
          },
          "materials": {
            "stator_steel": "M19",
            "rotor_steel": "M19",
            "magnet_grade": "N42",
            "conductor": "copper"
          }
        }"#,
    );

    let embrace = effective_magnet_embrace(&config).expect("SPM magnet embrace should be defined");
    assert!((embrace - 0.75).abs() < 1e-3);
}

#[test]
fn rotor_region_labels_rotate_with_requested_angle() {
    let config = parse_motor_config(
        r#"{
          "schema_version": "1.0",
          "topology": "SPM",
          "stator": {
            "OD_mm": 50.0,
            "ID_mm": 34.0,
            "slot_count": 12,
            "stack_length_mm": 40.0,
            "slot_opening_mm": 2.5,
            "tooth_width_mm": 4.5,
            "yoke_thickness_mm": 4.5
          },
          "rotor": {
            "OD_mm": 25.0,
            "magnet_thickness_mm": 3.0,
            "magnet_width_mm": 16.5,
            "pole_count": 4,
            "magnet_embrace": 0.85
          },
          "winding": {
            "type": "concentrated",
            "turns_per_coil": 10,
            "layers": 1,
            "parallel_paths": 1
          },
          "materials": {
            "stator_steel": "M19",
            "rotor_steel": "M19",
            "magnet_grade": "N42",
            "conductor": "copper"
          }
        }"#,
    );

    let mesh = TriMesh {
        nodes: vec![],
        triangles: vec![],
        regions: vec![
            Region::Magnet,
            Region::Magnet,
            Region::Airgap,
            Region::Airgap,
        ],
        boundary_nodes: vec![],
        sector_edge_pairs: vec![],
        info: MeshInfo {
            num_nodes: 0,
            num_triangles: 0,
            pole_pitch_deg: 90.0,
            n_pole_pitches: 4,
            total_span_deg: 360.0,
            angular_divisions: 360,
            radial_rings: 1,
            mesh_density: "synthetic".to_string(),
            radial_layers: vec!["magnet".to_string()],
            airgap_inner_radius_mm: None,
            airgap_outer_radius_mm: None,
            mesh_source: None,
            magnet_outer_radius_mm: 15.5,
            magnet_embrace: 1.0,
            stator_inner_radius_mm: 17.0,
            stator_slot_outer_radius_mm: 20.0,
            stator_outer_radius_mm: 25.0,
        },
    };
    let centroids = vec![
        [0.014, 0.0],
        [
            0.014 * (45.0_f64).to_radians().cos(),
            0.014 * (45.0_f64).to_radians().sin(),
        ],
        [
            0.014 * (75.0_f64).to_radians().cos(),
            0.014 * (75.0_f64).to_radians().sin(),
        ],
        [
            0.014 * (120.0_f64).to_radians().cos(),
            0.014 * (120.0_f64).to_radians().sin(),
        ],
    ];

    let regions_zero = rotated_rotor_regions(&mesh, &centroids, &config, 0.0)
        .expect("SPM rotor labels should rotate");
    let regions_thirty = rotated_rotor_regions(&mesh, &centroids, &config, 30.0_f64.to_radians())
        .expect("SPM rotor labels should rotate");

    assert_eq!(regions_zero[0], Region::Magnet);
    assert_eq!(regions_zero[1], Region::Airgap);
    assert_eq!(regions_zero[2], Region::Magnet);
    assert_eq!(regions_zero[3], Region::Magnet);

    assert_eq!(regions_thirty[0], Region::Magnet);
    assert_eq!(regions_thirty[1], Region::Magnet);
    assert_eq!(regions_thirty[2], Region::Airgap);
    assert_eq!(regions_thirty[3], Region::Magnet);
}

#[test]
fn first_harmonic_peak_matches_sine_amplitude() {
    let n = 48;
    let amplitude = 37.5;
    let waveform: Vec<f64> = (0..n)
        .map(|k| {
            let theta = 2.0 * std::f64::consts::PI * k as f64 / n as f64;
            amplitude * theta.sin()
        })
        .collect();

    assert!((first_harmonic_peak(&waveform) - amplitude).abs() < 1e-9);
}

#[test]
fn back_emf_from_flux_linkage_matches_reference_derivative_sign() {
    let n = 48;
    let omega = 123.0;
    let d_theta = 2.0 * std::f64::consts::PI / n as f64;
    let psi: Vec<f64> = (0..n)
        .map(|k| {
            let theta = d_theta * k as f64;
            theta.cos()
        })
        .collect();

    let emf = back_emf_from_flux_linkage(&psi, d_theta, omega, true);
    assert!(emf[0].abs() < 1e-9);
    assert!(emf[n / 4] < 0.0);
    assert!((emf[n / 4] + omega).abs() / omega < 0.01);
}

#[test]
fn back_emf_from_flux_linkage_uses_open_endpoints_for_partial_sweeps() {
    let psi = vec![0.0, 1.0, 4.0];
    let emf = back_emf_from_flux_linkage(&psi, 1.0, 10.0, false);

    assert!((emf[0] - 10.0).abs() < 1e-12);
    assert!((emf[1] - 20.0).abs() < 1e-12);
    assert!((emf[2] - 30.0).abs() < 1e-12);
}

#[test]
fn harmonic_peak_tracks_requested_harmonic() {
    let n = 60;
    let amplitude = 9.25;
    let harmonic = 5;
    let waveform: Vec<f64> = (0..n)
        .map(|k| {
            let theta = 2.0 * std::f64::consts::PI * harmonic as f64 * k as f64 / n as f64;
            amplitude * theta.sin()
        })
        .collect();

    assert!((harmonic_peak(&waveform, harmonic) - amplitude).abs() < 1e-9);
    assert!(harmonic_peak(&waveform, 1) < 1e-9);
}

#[test]
fn back_emf_thd_matches_known_harmonic_mix() {
    let n = 60;
    let fundamental = 10.0;
    let fifth = 3.0;
    let seventh = 4.0;
    let waveform: Vec<f64> = (0..n)
        .map(|k| {
            let theta = 2.0 * std::f64::consts::PI * k as f64 / n as f64;
            fundamental * theta.sin() + fifth * (5.0 * theta).sin() + seventh * (7.0 * theta).sin()
        })
        .collect();

    let expected = (fifth * fifth + seventh * seventh).sqrt() / fundamental * 100.0;
    assert!((back_emf_thd_pct(&waveform, 25) - expected).abs() < 1e-9);
}

#[test]
fn torque_ripple_uses_absolute_average_torque() {
    let waveform = [-5.0, -3.0, -7.0, -1.0];
    let expected = (-1.0 - (-7.0)) / 4.0 * 100.0;
    assert!((torque_ripple_pct(&waveform) - expected).abs() < 1e-9);
}

#[test]
fn cogging_period_matches_slot_pole_repeat_unit() {
    assert!((cogging_period_electrical_deg(12, 8) - 60.0).abs() < 1e-9);
    assert!((cogging_period_electrical_deg(24, 16) - 60.0).abs() < 1e-9);
}

#[test]
fn centered_no_load_cogging_waveform_removes_only_dc_bias() {
    let raw = [-0.027, 0.023, 0.073, -0.077];
    let centered = centered_no_load_cogging_waveform(&raw, 0.0, 360.0, 12, 4)
        .expect("full no-load 4p12s sweep should be centerable");
    let mean = centered.iter().sum::<f64>() / centered.len() as f64;
    let raw_span = raw.iter().copied().fold(f64::NEG_INFINITY, f64::max)
        - raw.iter().copied().fold(f64::INFINITY, f64::min);
    let centered_span = centered.iter().copied().fold(f64::NEG_INFINITY, f64::max)
        - centered.iter().copied().fold(f64::INFINITY, f64::min);

    assert!(mean.abs() < 1e-12);
    assert!((centered_span - raw_span).abs() < 1e-12);
}

#[test]
fn centered_no_load_cogging_waveform_is_not_loaded_or_partial_span() {
    let raw = [1.0, 2.0, 3.0, 4.0];

    assert!(covers_integer_cogging_period(360.0, 12, 4));
    assert!(covers_integer_cogging_period(60.0, 12, 8));
    assert!(!covers_integer_cogging_period(45.0, 12, 8));
    assert!(centered_no_load_cogging_waveform(&raw, 1.0, 360.0, 12, 4).is_none());
    assert!(centered_no_load_cogging_waveform(&raw, 0.0, 45.0, 12, 8).is_none());
}

#[test]
fn centered_endpoint_period_waveform_ignores_duplicate_endpoint() {
    let raw = [1.0, 3.0, 5.0, 1.0];
    let centered =
        centered_endpoint_period_waveform(&raw).expect("endpointed period should be centerable");
    let unique_mean =
        centered[..centered.len() - 1].iter().sum::<f64>() / (centered.len() - 1) as f64;

    assert!(unique_mean.abs() < 1e-12);
    assert!((centered[0] - centered[centered.len() - 1]).abs() < 1e-12);
    assert!(centered_endpoint_period_waveform(&[1.0]).is_none());
}

#[test]
fn cogging_torque_method_defaults_to_arkkio_with_contour_override() {
    let _guard = cogging_policy_env_lock()
        .lock()
        .expect("cogging policy env lock poisoned");
    let config = cogging_policy_config(100.0, "fixed_mesh");

    std::env::remove_var("MAGNETO2D_COGGING_TORQUE_METHOD");
    assert_eq!(cogging_torque_method(&config), CoggingTorqueMethod::Arkkio);

    std::env::set_var("MAGNETO2D_COGGING_TORQUE_METHOD", "contour");
    assert_eq!(cogging_torque_method(&config), CoggingTorqueMethod::Contour);

    std::env::set_var("MAGNETO2D_COGGING_TORQUE_METHOD", "mst");
    assert_eq!(cogging_torque_method(&config), CoggingTorqueMethod::AreaMst);

    std::env::set_var("MAGNETO2D_COGGING_TORQUE_METHOD", "wst_centered");
    assert_eq!(
        cogging_torque_method(&config),
        CoggingTorqueMethod::WeightedStressCentered
    );

    std::env::set_var("MAGNETO2D_COGGING_TORQUE_METHOD", "product");
    assert_eq!(cogging_torque_method(&config), CoggingTorqueMethod::Arkkio);

    std::env::remove_var("MAGNETO2D_COGGING_TORQUE_METHOD");
}

#[test]
fn cogging_product_policy_remeshes_small_od_only() {
    let _guard = cogging_policy_env_lock()
        .lock()
        .expect("cogging policy env lock poisoned");
    std::env::remove_var("MAGNETO2D_COGGING_ROTATION_POLICY");

    let small = cogging_policy_config(50.0, "fixed_mesh");
    let cutoff = cogging_policy_config(75.0, "fixed_mesh");
    let large = cogging_policy_config(76.0, "fixed_mesh");
    let explicit_remesh = cogging_policy_config(100.0, "remesh_per_step");

    assert!(uses_cogging_remesh_per_step(&small));
    assert!(uses_cogging_remesh_per_step(&cutoff));
    assert!(!uses_cogging_remesh_per_step(&large));
    assert!(uses_cogging_remesh_per_step(&explicit_remesh));
}

#[test]
fn cogging_policy_env_can_force_modes_for_od_band_diagnostics() {
    let _guard = cogging_policy_env_lock()
        .lock()
        .expect("cogging policy env lock poisoned");
    let small = cogging_policy_config(50.0, "fixed_mesh");
    let large = cogging_policy_config(100.0, "fixed_mesh");

    std::env::set_var("MAGNETO2D_COGGING_ROTATION_POLICY", "fixed_mesh");
    assert!(!uses_cogging_remesh_per_step(&small));
    assert!(!uses_cogging_remesh_per_step(&large));

    std::env::set_var("MAGNETO2D_COGGING_ROTATION_POLICY", "remesh_per_step");
    assert!(uses_cogging_remesh_per_step(&small));
    assert!(uses_cogging_remesh_per_step(&large));

    std::env::set_var("MAGNETO2D_COGGING_ROTATION_POLICY", "product");
    assert!(uses_cogging_remesh_per_step(&small));
    assert!(!uses_cogging_remesh_per_step(&large));

    std::env::remove_var("MAGNETO2D_COGGING_ROTATION_POLICY");
}

/// Invariant: parallel and serial rotor sweeps must produce
/// numerically-identical waveforms.
///
/// Each position in the rayon par_iter is an independent magnetostatic
/// solve over `&SolveContext` (auto-Sync plain data) and `&MotorConfig`
/// with no shared mutable state. If a future change accidentally adds
/// shared mutation — or reorders a reduction that is not associative in
/// floating-point — this test catches it by comparing the per-position
/// torque/flux-linkage vectors and the scalar aggregates. Tolerances are
/// deliberately tight because any drift here means nondeterminism crept
/// into the hot path.
#[test]
fn parallel_sweep_matches_serial_sweep() {
    use super::run_rotor_sweep_with_mesh;

    // Tiny 4p/12s SPM config — small enough to solve quickly, large
    // enough to exercise the full setup/assemble/solve/extract pipeline.
    // 4 positions = one electrical period at 90° steps; short runtime
    // but enough rayon work for parallel dispatch to happen.
    let config = parse_motor_config(
        r#"{
          "schema_version": "1.0",
          "topology": "SPM",
          "stator": {
            "OD_mm": 50.0,
            "ID_mm": 34.0,
            "slot_count": 12,
            "stack_length_mm": 40.0,
            "slot_opening_mm": 2.5,
            "tooth_width_mm": 4.5,
            "yoke_thickness_mm": 4.5
          },
          "rotor": {
            "OD_mm": 25.0,
            "magnet_thickness_mm": 3.0,
            "magnet_width_mm": 16.5,
            "pole_count": 4,
            "magnet_embrace": 0.85
          },
          "winding": {
            "type": "concentrated",
            "turns_per_coil": 10,
            "layers": 1,
            "parallel_paths": 1
          },
          "materials": {
            "stator_steel": "M19",
            "rotor_steel": "M19",
            "magnet_grade": "N42",
            "conductor": "copper"
          },
          "solve_params": {
            "solve_quality": "quick",
            "mesh_density": "normal",
            "current_amplitude_A": 10.0,
            "current_angle_deg": 0.0,
            "rated_speed_rpm": 3000
          }
        }"#,
    );

    let n_positions = 4;
    let mut artifact = metadata_test_artifact(vec![Region::Airgap], None);
    artifact.mesh.info.mesh_source = Some(MeshSource::Gmsh);
    artifact.mesh.info.mesh_density = "gmsh_test".to_string();
    artifact.mesh.boundary_nodes = vec![0, 1, 2];

    let parallel =
        run_rotor_sweep_with_mesh(&config, n_positions, None, false, Some(artifact.clone()))
            .expect("parallel sweep should succeed");
    let serial = run_rotor_sweep_with_mesh(&config, n_positions, None, true, Some(artifact))
        .expect("serial sweep should succeed");

    assert_vec_close(
        &parallel.sweep.rotor_positions_elec_deg,
        &serial.sweep.rotor_positions_elec_deg,
        "rotor_positions_elec_deg",
    );
    assert_vec_close(
        &parallel.sweep.torque_nm,
        &serial.sweep.torque_nm,
        "torque_nm",
    );
    assert_vec_close(
        &parallel.sweep.torque_mst_nm,
        &serial.sweep.torque_mst_nm,
        "torque_mst_nm",
    );
    assert_vec_close(
        &parallel.sweep.torque_arkkio_nm,
        &serial.sweep.torque_arkkio_nm,
        "torque_arkkio_nm",
    );
    assert_vec_close(
        &parallel.sweep.loaded_flux_linkage_a_wb,
        &serial.sweep.loaded_flux_linkage_a_wb,
        "loaded_flux_linkage_a_wb",
    );
    assert_vec_close(
        &parallel.sweep.loaded_flux_linkage_b_wb,
        &serial.sweep.loaded_flux_linkage_b_wb,
        "loaded_flux_linkage_b_wb",
    );
    assert_vec_close(
        &parallel.sweep.loaded_flux_linkage_c_wb,
        &serial.sweep.loaded_flux_linkage_c_wb,
        "loaded_flux_linkage_c_wb",
    );
    assert_vec_close(
        &parallel.sweep.no_load_flux_linkage_a_wb,
        &serial.sweep.no_load_flux_linkage_a_wb,
        "no_load_flux_linkage_a_wb",
    );
    assert_vec_close(
        &parallel.sweep.no_load_flux_linkage_b_wb,
        &serial.sweep.no_load_flux_linkage_b_wb,
        "no_load_flux_linkage_b_wb",
    );
    assert_vec_close(
        &parallel.sweep.no_load_flux_linkage_c_wb,
        &serial.sweep.no_load_flux_linkage_c_wb,
        "no_load_flux_linkage_c_wb",
    );

    assert_scalar_close(
        parallel.sweep.avg_torque_nm,
        serial.sweep.avg_torque_nm,
        "avg_torque_nm",
    );
    assert_scalar_close(
        parallel.sweep.avg_torque_arkkio_nm,
        serial.sweep.avg_torque_arkkio_nm,
        "avg_torque_arkkio_nm",
    );
    assert_scalar_close(
        parallel.sweep.torque_ripple_pct,
        serial.sweep.torque_ripple_pct,
        "torque_ripple_pct",
    );
    // back_emf_fundamental_v is now Option<f64> (None when sub-360° elec
    // sweep can't support DFT). Both passes should produce the same
    // Some(_) on full-cycle sweeps; if they disagree, that's a bug.
    match (
        parallel.sweep.back_emf_fundamental_v,
        serial.sweep.back_emf_fundamental_v,
    ) {
        (Some(p), Some(s)) => assert_scalar_close(p, s, "back_emf_fundamental_v"),
        (None, None) => (),
        (p, s) => {
            panic!("back_emf_fundamental_v parallel/serial mismatch: parallel={p:?} serial={s:?}")
        }
    }
    assert_scalar_close(
        parallel.sweep.back_emf_peak_v,
        serial.sweep.back_emf_peak_v,
        "back_emf_peak_v",
    );

    assert_eq!(
        parallel.sweep.loaded_nonlinear_iterations, serial.sweep.loaded_nonlinear_iterations,
        "loaded_nonlinear_iterations diverged between parallel and serial"
    );
    assert_eq!(
        parallel.sweep.no_load_nonlinear_iterations, serial.sweep.no_load_nonlinear_iterations,
        "no_load_nonlinear_iterations diverged between parallel and serial"
    );
}

fn assert_vec_close(parallel: &[f64], serial: &[f64], label: &str) {
    assert_eq!(
        parallel.len(),
        serial.len(),
        "{label} length mismatch: parallel={}, serial={}",
        parallel.len(),
        serial.len(),
    );
    for (i, (p, s)) in parallel.iter().zip(serial.iter()).enumerate() {
        assert_scalar_close_inner(*p, *s, &format!("{label}[{i}]"));
    }
}

fn assert_scalar_close(parallel: f64, serial: f64, label: &str) {
    assert_scalar_close_inner(parallel, serial, label);
}

fn assert_scalar_close_inner(parallel: f64, serial: f64, label: &str) {
    let abs_tol = 1e-12;
    let rel_tol = 1e-10;
    let diff = (parallel - serial).abs();
    let magnitude = parallel.abs().max(serial.abs());
    let ok = diff <= abs_tol || diff <= rel_tol * magnitude;
    assert!(
        ok,
        "{label}: parallel={parallel:.15e} vs serial={serial:.15e} differ by {diff:.3e} \
         (abs_tol={abs_tol:.1e}, rel_tol={rel_tol:.1e})",
    );
}

// ── Sextant sweep symmetry helpers ───────────────────────────────────────────

#[test]
fn sextant_phase_map_matches_three_phase_synthesis() {
    // The defining property: advancing the source angle by k·60° elec must
    // equal applying the phase map k times to the original current triple.
    use crate::sources::phase_currents_from_angle;
    let amplitude = 70.71;
    for &gamma in &[0.0, 13.7, 90.0, 211.4, 359.0] {
        let base = phase_currents_from_angle(amplitude, gamma);
        for sextant in 0..=6 {
            let advanced = phase_currents_from_angle(amplitude, gamma + 60.0 * sextant as f64);
            let mapped = sextant_phase_map(base, sextant);
            for phase in 0..3 {
                assert!(
                    (advanced[phase] - mapped[phase]).abs() <= 1e-9 * amplitude,
                    "γ={gamma}° sextant={sextant} phase={phase}: \
                     synthesis={} vs map={}",
                    advanced[phase],
                    mapped[phase],
                );
            }
        }
    }
}

#[test]
fn sextant_phase_map_half_wave_and_identity() {
    let triple = [1.5, -0.25, 2.75];
    assert_eq!(sextant_phase_map(triple, 3), [-1.5, 0.25, -2.75]);
    assert_eq!(sextant_phase_map(triple, 6), triple);
    assert_eq!(sextant_phase_map(triple, 0), triple);
}

#[test]
fn balanced_winding_detection() {
    // 12s8p (hobbyist preset) and 12s4p are symmetric 3-phase windings.
    assert!(balanced_three_phase_winding(12, 8));
    assert!(balanced_three_phase_winding(12, 4));
    assert!(balanced_three_phase_winding(9, 8));
    // 4-slot lesson motor: no balanced 3-phase winding exists.
    assert!(!balanced_three_phase_winding(4, 2));
    // Slot counts not divisible by 3 can never carry a symmetric winding.
    assert!(!balanced_three_phase_winding(10, 8));
    assert!(!balanced_three_phase_winding(0, 8));
}
