//! Validated per-angle solve problem.

use std::collections::HashMap;

use crate::materials::{
    assign_materials_with_contract_materials, assign_materials_with_resolved_magnetization,
    resolved_field_bh_curve, steel_grade_from_material_key, MaterialProps,
};
use crate::mesh::{MeshSource, Region, TriMesh};
use crate::motor::MotorConfig;
use crate::sources::{
    compute_current_densities_from_phase_currents, source_phase_currents_for_excitation,
};

use super::context::SolveContext;
use super::mesh_metadata::{
    resolve_step_current_densities_for_requested_current, resolve_step_element_magnetization_rad,
    step_metadata_matches_artifact_angle, validate_imported_sources_for_problem,
    validate_imported_step_motion, MeshMetadataError,
};

/// Validated data consumed by one field solve.
#[derive(Debug)]
pub(super) struct SolveProblem {
    pub(super) mesh: TriMesh,
    pub(super) materials: Vec<MaterialProps>,
    /// Material assignment before nonlinear warm-start mutation. Kept so a
    /// Newton failure can fall back to Picard from the same problem state.
    pub(super) base_materials: Vec<MaterialProps>,
    pub(super) current_densities_a_per_m2: Vec<f64>,
    pub(super) nonlinear_curve_ids_by_element: Vec<Option<usize>>,
    pub(super) nonlinear_curves: Vec<crate::field::BhCurve>,
    pub(super) nonlinear_material_labels: Vec<String>,
}

impl SolveProblem {
    pub(super) fn from_prepared_mesh(
        ctx: &SolveContext,
        config: &MotorConfig,
        mesh: TriMesh,
        rotor_angle_rad: f64,
        source_current_angle_deg: f64,
        current_a: f64,
    ) -> Result<Self, MeshMetadataError> {
        let custom_curves = config.materials.custom_curves()
            .map_err(MeshMetadataError::InvalidCustomMaterial)?;
        validate_imported_step_motion(&ctx.solve_mesh_artifact, rotor_angle_rad)?;
        validate_imported_sources_for_problem(
            &ctx.solve_mesh_artifact,
            &mesh.regions,
            config,
            rotor_angle_rad,
            current_a,
        )?;

        let resolved_magnetization_rad = resolve_step_element_magnetization_rad(
            &ctx.solve_mesh_artifact,
            &mesh.regions,
            &ctx.centroids,
            config,
            rotor_angle_rad,
        )?;

        // Baked per-element contract materials are only valid at the
        // artifact's own angle. On fixed-mesh re-tagged sweep steps the
        // region kinds rotate away from the baked layout (a baked Magnet
        // element becomes Airgap and vice versa), so pairing them with the
        // static contract keys yields UnknownMaterial; fall back to config
        // materials keyed on the re-tagged regions, matching the
        // magnetization and current-density resolvers.
        let element_material_keys =
            if step_metadata_matches_artifact_angle(&ctx.solve_mesh_artifact, rotor_angle_rad) {
                element_material_keys(&ctx.solve_mesh_artifact)
            } else {
                None
            };
        let mut materials = if let Some(keys) = element_material_keys.as_ref() {
            assign_materials_with_contract_materials(
                &mesh.regions,
                &ctx.centroids,
                &resolved_magnetization_rad,
                keys,
                &config.materials.stator_steel,
                &config.materials.rotor_steel,
                &config.materials.magnet_grade,
                config.rotor.pole_count,
                rotor_angle_rad,
            )
            .map_err(|err| MeshMetadataError::UnknownMaterial {
                region: err.region,
                material_key: err.material_key,
            })?
        } else {
            assign_materials_with_resolved_magnetization(
                &mesh.regions,
                &ctx.centroids,
                &resolved_magnetization_rad,
                &config.materials.stator_steel,
                &config.materials.rotor_steel,
                &config.materials.magnet_grade,
                config.rotor.pole_count,
                rotor_angle_rad,
            )
        };
        let (stator_steel, rotor_steel) =
            resolved_contract_steel_keys(&ctx.solve_mesh_artifact, config);
        for key in [&stator_steel, &rotor_steel] {
            if key.starts_with("custom:") && !custom_curves.contains_key(key) {
                return Err(MeshMetadataError::InvalidCustomMaterial(format!("mesh references missing curve {key}")));
            }
        }
        let (nonlinear_curve_ids_by_element, nonlinear_curves, nonlinear_material_labels) =
            resolved_nonlinear_materials(&mesh.regions, &stator_steel, &rotor_steel, &custom_curves);
        for (index, curve_id) in nonlinear_curve_ids_by_element.iter().enumerate() {
            if let Some(id) = curve_id {
                if custom_curves.contains_key(&nonlinear_material_labels[*id]) {
                    materials[index].with_mu_rel(nonlinear_curves[*id].initial_mu_r());
                }
            }
        }

        let current_densities_a_per_m2 = match resolve_step_current_densities_for_requested_current(
            &ctx.solve_mesh_artifact,
            rotor_angle_rad,
            current_a,
        )? {
            Some(current_densities) => {
                if current_a.abs() <= 1.0e-12 {
                    eprintln!(
                        "  source: zero requested current; ignoring imported element current densities"
                    );
                } else {
                    eprintln!("  source: using imported current densities");
                }
                current_densities
            }
            None => {
                if imported_mesh_input(&ctx.solve_mesh_artifact.mesh.info.mesh_source) {
                    eprintln!("  source: using analytical winding synthesis fallback");
                }
                let phase_currents = source_phase_currents_for_excitation(
                    config,
                    rotor_angle_rad,
                    current_a,
                    source_current_angle_deg,
                );
                compute_current_densities_from_phase_currents(
                    &mesh,
                    &ctx.centroids,
                    &config.winding.winding_type,
                    config.stator.slot_count,
                    config.rotor.pole_count,
                    config.winding.turns_per_coil,
                    config.winding.layers,
                    config.winding.coil_span,
                    phase_currents,
                    &ctx.slot_areas,
                )
            }
        };

        Ok(Self {
            mesh,
            base_materials: materials.clone(),
            materials,
            current_densities_a_per_m2,
            nonlinear_curve_ids_by_element,
            nonlinear_curves,
            nonlinear_material_labels,
        })
    }

    /// Convert the motor adapter's fully resolved per-angle data into the
    /// neutral field contract. Geometry generation, region classification,
    /// winding synthesis, material lookup, and magnet fill remain motor-side;
    /// the returned value contains only solve-ready field data.
    pub(super) fn to_field_problem(
        &self,
        materials: &[MaterialProps],
        boundaries: crate::field::BoundarySet,
        options: crate::field::SolveOptions,
        magnet_fractions: Option<&[f64]>,
        az_warm_start: Option<&[f64]>,
    ) -> crate::field::MagnetostaticProblem {
        let mut field_materials = self
            .nonlinear_curves
            .iter()
            .cloned()
            .map(|bh_curve| crate::field::MaterialModel::Nonlinear { bh_curve })
            .collect::<Vec<_>>();
        let mut linear_material_ids = HashMap::<u64, usize>::new();
        let elements = materials
            .iter()
            .enumerate()
            .map(|(element_index, material)| {
                let material_id = self.nonlinear_curve_ids_by_element[element_index]
                    .unwrap_or_else(|| {
                        *linear_material_ids
                            .entry(material.mu_rel.to_bits())
                            .or_insert_with(|| {
                                let id = field_materials.len();
                                field_materials.push(crate::field::MaterialModel::Linear {
                                    mu_r: material.mu_rel,
                                });
                                id
                            })
                    });
                crate::field::ElementPhysics {
                    material_id,
                    current_density_z_a_per_m2: self.current_densities_a_per_m2[element_index],
                    remanence_t: [
                        material.br * material.mag_angle_rad.cos(),
                        material.br * material.mag_angle_rad.sin(),
                    ],
                    pm_source_scale: magnet_fractions
                        .map(|fractions| fractions[element_index])
                        .unwrap_or(1.0),
                }
            })
            .collect();
        crate::field::MagnetostaticProblem {
            mesh: crate::field::FemMesh {
                nodes_m: self.mesh.nodes.clone(),
                triangles: self.mesh.triangles.clone(),
            },
            materials: field_materials,
            elements,
            boundaries,
            options,
            warm_start: Some(crate::field::FieldWarmStart {
                az_nodal: az_warm_start.unwrap_or_default().to_vec(),
                mu_r_by_element: materials.iter().map(|material| material.mu_rel).collect(),
            }),
        }
    }
}

fn resolved_nonlinear_materials(
    regions: &[Region],
    stator_steel: &str,
    rotor_steel: &str,
    custom_curves: &HashMap<String, crate::field::BhCurve>,
) -> (Vec<Option<usize>>, Vec<crate::field::BhCurve>, Vec<String>) {
    let mut curves = Vec::new();
    let mut labels = Vec::new();
    let mut curve_by_label = HashMap::<String, Option<usize>>::new();
    let curve_ids = regions
        .iter()
        .map(|region| {
            let label = match region {
                Region::RotorCore => Some(rotor_steel),
                Region::StatorTooth | Region::StatorYoke => Some(stator_steel),
                _ => None,
            }?;
            if let Some(curve_id) = curve_by_label.get(label) {
                return *curve_id;
            }
            let curve_id = custom_curves.get(label).cloned().or_else(|| resolved_field_bh_curve(label)).map(|curve| {
                let id = curves.len();
                curves.push(curve);
                labels.push(label.to_string());
                id
            });
            curve_by_label.insert(label.to_string(), curve_id);
            curve_id
        })
        .collect();
    (curve_ids, curves, labels)
}

fn imported_mesh_input(mesh_source: &Option<MeshSource>) -> bool {
    matches!(mesh_source, Some(MeshSource::Gmsh))
}

fn element_material_keys(artifact: &super::SolveMeshArtifact) -> Option<Vec<Option<String>>> {
    let contract = artifact.physics_contract.as_ref()?;
    let region_ids = artifact.element_region_ids.as_ref()?;
    let material_by_region_id: HashMap<&str, &str> = contract
        .regions
        .iter()
        .map(|region| (region.id.as_str(), region.material.as_str()))
        .collect();
    Some(
        region_ids
            .iter()
            .map(|region_id| {
                material_by_region_id
                    .get(region_id.as_str())
                    .map(|value| (*value).to_string())
            })
            .collect(),
    )
}

pub(super) fn resolved_contract_steel_keys(
    artifact: &super::SolveMeshArtifact,
    config: &MotorConfig,
) -> (String, String) {
    let mut stator_steel = config.materials.stator_steel.clone();
    let mut rotor_steel = config.materials.rotor_steel.clone();
    let Some(contract) = artifact.physics_contract.as_ref() else {
        return (stator_steel, rotor_steel);
    };
    for region in &contract.regions {
        match region.kind.as_str() {
            "RotorCore" => {
                if let Some(steel) = steel_grade_from_material_key(&region.material) {
                    rotor_steel = steel.to_string();
                }
            }
            "StatorTooth" | "StatorYoke" => {
                if let Some(steel) = steel_grade_from_material_key(&region.material) {
                    stator_steel = steel.to_string();
                }
            }
            _ => {}
        }
    }
    (stator_steel, rotor_steel)
}
