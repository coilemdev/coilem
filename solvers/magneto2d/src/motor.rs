//! coilEM MotorConfig deserialization (minimal subset for SPM).

use serde::Deserialize;
use std::collections::HashMap;

#[derive(Debug, Deserialize)]
pub struct MotorConfig {
    #[allow(dead_code)]
    pub schema_version: String,
    pub topology: String,
    pub stator: Stator,
    pub rotor: Rotor,
    pub winding: Winding,
    pub materials: Materials,
    pub solve_params: Option<SolveParams>,
    pub solve_options: Option<SolveOptions>,
}

#[derive(Debug, Deserialize)]
pub struct Stator {
    #[serde(rename = "OD_mm")]
    pub od_mm: f64,
    #[serde(rename = "ID_mm")]
    pub id_mm: f64,
    pub slot_count: u32,
    pub stack_length_mm: f64,
    pub slot_opening_mm: f64,
    pub tooth_width_mm: f64,
    pub yoke_thickness_mm: f64,
}

#[derive(Debug, Deserialize)]
pub struct Rotor {
    #[serde(rename = "OD_mm")]
    pub od_mm: f64,
    #[serde(rename = "ID_mm")]
    #[allow(dead_code)]
    pub id_mm: Option<f64>,
    pub magnet_thickness_mm: f64,
    pub magnet_width_mm: f64,
    pub pole_count: u32,
    pub magnet_embrace: Option<f64>,
    #[allow(dead_code)]
    pub bridge_thickness_mm: Option<f64>,
}

#[derive(Debug, Deserialize)]
pub struct Winding {
    #[serde(rename = "type")]
    pub winding_type: String,
    pub turns_per_coil: u32,
    pub layers: u32,
    pub parallel_paths: u32,
    pub coil_span: Option<u32>,
}

#[derive(Debug, Deserialize)]
pub struct Materials {
    pub stator_steel: String,
    pub rotor_steel: String,
    pub magnet_grade: String,
    #[allow(dead_code)]
    pub conductor: String,
    #[serde(default)]
    pub custom_steels: HashMap<String, CustomSteel>,
}

#[derive(Debug, Deserialize)]
pub struct CustomSteel {
    pub id: String,
    pub bh_curve: Vec<(f64, f64)>,
}

impl Materials {
    /// Curves are scoped to one motor input, never installed in the global catalog.
    pub fn custom_curves(&self) -> Result<HashMap<String, crate::field::BhCurve>, String> {
        let mut curves = HashMap::new();
        if self.custom_steels.len() > 16 {
            return Err("a project can contain at most 16 custom steels".into());
        }
        for (key, material) in &self.custom_steels {
            if !crate::materials::is_custom_steel_key(key) || material.id != *key {
                return Err("custom steel identity must match its project key".into());
            }
            let points = &material.bh_curve;
            if !(3..=4096).contains(&points.len()) || points[0] != (0.0, 0.0) {
                return Err("custom B-H curve needs 3–4096 points beginning at (0,0)".into());
            }
            for (index, &(b, h)) in points.iter().enumerate() {
                if !b.is_finite() || !h.is_finite() || !(0.0..=5.0).contains(&b) || !(0.0..=1e7).contains(&h) {
                    return Err("custom B-H curve has nonfinite or out-of-range points".into());
                }
                if index > 0 {
                    if b <= points[index - 1].0 || h <= points[index - 1].1 {
                        return Err("custom B and H must both strictly increase".into());
                    }
                    let mu_r = b / (crate::materials::MU_0 * h);
                    if !(1.0..=1e6).contains(&mu_r) {
                        return Err("custom steel relative permeability is out of range; check B/H units".into());
                    }
                }
            }
            curves.insert(key.clone(), crate::field::BhCurve {
                points: points.iter().map(|&(b_t, h_a_per_m)| crate::field::BhPoint { b_t, h_a_per_m }).collect(),
                mu_r_min: 1.0,
                mu_r_max: 1e6,
            });
        }
        for key in [&self.stator_steel, &self.rotor_steel] {
            if key.starts_with("custom:") && !curves.contains_key(key) {
                return Err(format!("missing embedded custom steel curve: {key}"));
            }
        }
        Ok(curves)
    }
}

#[derive(Debug, Deserialize)]
pub struct SolveParams {
    pub solve_quality: Option<String>,
    #[allow(dead_code)]
    pub mesh_density: Option<String>,
    pub current_amplitude_a: Option<f64>,
    #[serde(rename = "current_amplitude_A")]
    pub current_amplitude_a_alt: Option<f64>,
    pub current_amplitude_convention: Option<String>,
    pub current_angle_deg: Option<f64>,
    pub excitation_mode: Option<String>,
    pub commutation_advance_deg: Option<f64>,
    pub phase_connection: Option<String>,
    pub excitation_rotation_convention: Option<String>,
    pub rated_speed_rpm: Option<u32>,
    pub max_nonlinear_iterations: Option<usize>,
    pub nonlinear_solver: Option<String>,
    pub linear_solver_preconditioner: Option<String>,
    /// How the rotor "rotates" between sweep positions.
    ///   "fixed_mesh"      — (default) single mesh, magnet regions re-tagged per
    ///                       step via rotated_rotor_regions. Element boundaries
    ///                       quantize the rotor angle → staircase artefacts on
    ///                       8p+ topologies.
    ///   "remesh_per_step" — regenerate the mesh at each rotor angle so magnet
    ///                       edges land on actual mesh edges. Slower (mesh +
    ///                       assembly rebuilt per step) but continuous in θ.
    pub rotor_rotation_model: Option<String>,
    /// Optional slot-mouth/slot-sidewall refinement policy consumed by the
    /// upstream Gmsh/FEMM mesh artifact builders.
    #[allow(dead_code)]
    pub slot_sidewall_refinement: Option<bool>,
    /// Optional PM magnet-corner/tooth-tip refinement policy consumed by the
    /// upstream Gmsh/FEMM mesh artifact builders.
    #[allow(dead_code)]
    pub corner_refinement: Option<bool>,
}

#[derive(Debug, Deserialize)]
pub struct SolveOptions {
    #[allow(dead_code)]
    pub torque_sweep: Option<bool>,
    pub back_emf: Option<bool>,
    #[allow(dead_code)]
    pub flux_density: Option<bool>,
    pub cogging_torque: Option<bool>,
    pub thd_analysis: Option<bool>,
}

impl SolveParams {
    pub fn current_a(&self) -> f64 {
        self.current_amplitude_a
            .or(self.current_amplitude_a_alt)
            .unwrap_or(50.0)
    }

    pub fn requested_current_a(&self) -> Option<f64> {
        self.current_amplitude_a.or(self.current_amplitude_a_alt)
    }

    pub fn excitation_mode_label(&self) -> &str {
        self.excitation_mode.as_deref().unwrap_or("sinusoidal")
    }

    pub fn commutation_advance_deg(&self) -> f64 {
        self.commutation_advance_deg.unwrap_or(0.0)
    }

    pub fn phase_connection_label(&self) -> &str {
        self.phase_connection.as_deref().unwrap_or("wye")
    }

    pub fn excitation_rotation_convention_label(&self) -> &str {
        self.excitation_rotation_convention
            .as_deref()
            .unwrap_or("counterclockwise_positive_solver")
    }

    /// Rotor rotation model. "fixed_mesh" (default, back-compat) | "remesh_per_step".
    pub fn rotor_rotation_model_label(&self) -> &str {
        self.rotor_rotation_model.as_deref().unwrap_or("fixed_mesh")
    }
}

#[cfg(test)]
mod tests {
    use super::SolveParams;

    #[test]
    fn solve_params_deserializes_corner_refinement() {
        let params: SolveParams = serde_json::from_str(r#"{"corner_refinement":true}"#).unwrap();

        assert_eq!(params.corner_refinement, Some(true));
    }
}

#[cfg(test)]
mod custom_steel_tests {
    use super::Materials;
    use serde_json::json;

    fn material_input() -> serde_json::Value {
        let key = format!("custom:{}", "a".repeat(64));
        json!({
            "stator_steel": key, "rotor_steel": "M350-50A", "magnet_grade": "N35", "conductor": "copper",
            "custom_steels": {key.clone(): {"id": key, "bh_curve": [[0,0], [1,100], [2,10000]]}}
        })
    }

    #[test]
    fn custom_steel_is_scoped_to_the_input_and_interpolates_imported_points() {
        let key = format!("custom:{}", "a".repeat(64));
        let first: Materials = serde_json::from_value(material_input()).unwrap();
        let mut other = material_input();
        other["custom_steels"][&key]["bh_curve"][2][1] = json!(20000);
        let second: Materials = serde_json::from_value(other).unwrap();
        assert_eq!(first.custom_curves().unwrap()[&key].interpolate_h(1.5), 5050.0);
        assert_eq!(second.custom_curves().unwrap()[&key].interpolate_h(1.5), 10050.0);
        assert_eq!(first.custom_curves().unwrap()[&key].interpolate_h(1.5), 5050.0);
    }

    #[test]
    fn custom_steel_rejects_missing_decreasing_or_aliased_data() {
        let key = format!("custom:{}", "a".repeat(64));
        for invalid in [json!([[0,0],[1,100],[2,50]]), json!([[0,0],[1,100],[1,1000]]), json!([[1,0],[2,100],[3,10000]])] {
            let mut value = material_input();
            value["custom_steels"][&key]["bh_curve"] = invalid;
            assert!(serde_json::from_value::<Materials>(value).unwrap().custom_curves().is_err());
        }
        let mut missing = material_input();
        missing["custom_steels"] = json!({});
        assert!(serde_json::from_value::<Materials>(missing).unwrap().custom_curves().is_err());
        let mut aliased = material_input();
        aliased["custom_steels"][&key]["id"] = json!("M350-50A");
        assert!(serde_json::from_value::<Materials>(aliased).unwrap().custom_curves().is_err());
    }
}
