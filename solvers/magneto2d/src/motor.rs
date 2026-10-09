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

impl MotorConfig {
    /// Reject values that would panic or silently produce a meaningless solve.
    ///
    /// The backend applies tighter engineering ranges; this is the native
    /// boundary's guard against inputs that bypass it.
    pub fn validate(&self) -> Result<(), String> {
        let positive = [
            ("stator.OD_mm", self.stator.od_mm),
            ("stator.ID_mm", self.stator.id_mm),
            ("stator.stack_length_mm", self.stator.stack_length_mm),
            ("stator.tooth_width_mm", self.stator.tooth_width_mm),
            ("stator.yoke_thickness_mm", self.stator.yoke_thickness_mm),
            ("rotor.OD_mm", self.rotor.od_mm),
            ("rotor.magnet_thickness_mm", self.rotor.magnet_thickness_mm),
            ("rotor.magnet_width_mm", self.rotor.magnet_width_mm),
        ];
        for (name, value) in positive {
            if !(value.is_finite() && value > 0.0) {
                return Err(format!(
                    "{name} must be a finite positive number, got {value}"
                ));
            }
        }
        let non_negative = [
            ("stator.slot_opening_mm", Some(self.stator.slot_opening_mm)),
            ("rotor.ID_mm", self.rotor.id_mm),
            ("rotor.bridge_thickness_mm", self.rotor.bridge_thickness_mm),
        ];
        for (name, value) in non_negative {
            if let Some(value) = value {
                if !(value.is_finite() && value >= 0.0) {
                    return Err(format!(
                        "{name} must be a finite non-negative number, got {value}"
                    ));
                }
            }
        }
        if let Some(embrace) = self.rotor.magnet_embrace {
            if !(embrace.is_finite() && (0.0..=1.0).contains(&embrace)) {
                return Err(format!(
                    "rotor.magnet_embrace must be between 0 and 1, got {embrace}"
                ));
            }
        }
        if self.stator.slot_count == 0 {
            return Err("stator.slot_count must be at least 1".to_string());
        }
        if self.rotor.pole_count < 2 {
            return Err(format!(
                "rotor.pole_count must be at least 2, got {}",
                self.rotor.pole_count
            ));
        }
        let counts = [
            ("winding.turns_per_coil", self.winding.turns_per_coil),
            ("winding.layers", self.winding.layers),
            ("winding.parallel_paths", self.winding.parallel_paths),
            ("winding.coil_span", self.winding.coil_span.unwrap_or(1)),
        ];
        for (name, value) in counts {
            if value == 0 {
                return Err(format!("{name} must be at least 1"));
            }
        }
        if let Some(params) = self.solve_params.as_ref() {
            let finite = [
                (
                    "solve_params.current_amplitude_a",
                    params.requested_current_a(),
                ),
                ("solve_params.current_angle_deg", params.current_angle_deg),
                (
                    "solve_params.commutation_advance_deg",
                    params.commutation_advance_deg,
                ),
            ];
            for (name, value) in finite {
                if let Some(value) = value {
                    if !value.is_finite() {
                        return Err(format!("{name} must be finite, got {value}"));
                    }
                }
            }
            if params.max_nonlinear_iterations == Some(0) {
                return Err("solve_params.max_nonlinear_iterations must be at least 1".to_string());
            }
        }
        Ok(())
    }
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
    use super::{MotorConfig, SolveParams};
    use serde_json::json;

    #[test]
    fn solve_params_deserializes_corner_refinement() {
        let params: SolveParams = serde_json::from_str(r#"{"corner_refinement":true}"#).unwrap();

        assert_eq!(params.corner_refinement, Some(true));
    }

    fn valid_config() -> serde_json::Value {
        json!({
            "schema_version": "1.0",
            "topology": "SPM",
            "stator": {
                "OD_mm": 50.0, "ID_mm": 34.0, "slot_count": 12, "stack_length_mm": 40.0,
                "slot_opening_mm": 2.5, "tooth_width_mm": 4.5, "yoke_thickness_mm": 4.5
            },
            "rotor": {
                "OD_mm": 25.0, "magnet_thickness_mm": 3.0, "magnet_width_mm": 16.5,
                "pole_count": 4, "magnet_embrace": 0.85
            },
            "winding": {"type": "concentrated", "turns_per_coil": 10, "layers": 1, "parallel_paths": 1},
            "materials": {
                "stator_steel": "M19", "rotor_steel": "M19", "magnet_grade": "N42", "conductor": "copper"
            },
            "solve_params": {"current_amplitude_a": 0.0, "current_angle_deg": 0.0, "max_nonlinear_iterations": 30}
        })
    }

    fn validate(value: serde_json::Value) -> Result<(), String> {
        serde_json::from_value::<MotorConfig>(value)
            .unwrap()
            .validate()
    }

    #[test]
    fn motor_config_validation_accepts_a_valid_design() {
        assert_eq!(validate(valid_config()), Ok(()));
    }

    #[test]
    fn motor_config_validation_rejects_values_that_would_panic_or_mislead() {
        let cases = [
            ("/rotor/pole_count", json!(0), "rotor.pole_count"),
            ("/rotor/pole_count", json!(1), "rotor.pole_count"),
            ("/stator/slot_count", json!(0), "stator.slot_count"),
            (
                "/stator/stack_length_mm",
                json!(-40.0),
                "stator.stack_length_mm",
            ),
            ("/stator/OD_mm", json!(0.0), "stator.OD_mm"),
            ("/rotor/magnet_embrace", json!(1.5), "rotor.magnet_embrace"),
            (
                "/stator/slot_opening_mm",
                json!(-1.0),
                "stator.slot_opening_mm",
            ),
            (
                "/winding/parallel_paths",
                json!(0),
                "winding.parallel_paths",
            ),
            (
                "/solve_params/max_nonlinear_iterations",
                json!(0),
                "solve_params.max_nonlinear_iterations",
            ),
        ];
        for (pointer, value, field) in cases {
            let mut config = valid_config();
            *config.pointer_mut(pointer).unwrap() = value;
            let err = validate(config).expect_err(pointer);
            assert!(err.starts_with(field), "{pointer}: {err}");
        }
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
