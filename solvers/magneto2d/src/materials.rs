//! Material properties for 2D magnetostatic FEM.
//!
//! Provides magnetic permeability (mu) and permanent magnet remanence (Br)
//! for common motor materials, plus nonlinear B-H curve lookup for steels.

use std::collections::{HashMap, HashSet};
use std::env;
use std::f64::consts::PI;
use std::fs;
use std::path::PathBuf;
use std::sync::{Mutex, OnceLock};

use crate::mesh::Region;

/// Permeability of free space [H/m].
pub const MU_0: f64 = 4.0 * PI * 1e-7;

const DEFAULT_LINEAR_STEEL_MU_REL: f64 = 600.0;
const LINEAR_STEEL_MU_ENV: &str = "COILEM_MAGNETO2D_LINEAR_STEEL_MU_REL";
const STEEL_MU_MIN_ENV: &str = "COILEM_MAGNETO2D_STEEL_MU_REL_MIN";
const STEEL_MU_MAX_ENV: &str = "COILEM_MAGNETO2D_STEEL_MU_REL_MAX";
// Allow rights-cleared nonlinear curves to approach air permeability in hard saturation.
const DEFAULT_NONLINEAR_STEEL_MU_MIN: f64 = 1.0;
const DEFAULT_NONLINEAR_STEEL_MU_MAX: f64 = 10_000.0;

static BH_DATABASE: OnceLock<Result<HashMap<String, BHCurve>, String>> = OnceLock::new();
static WARNED_UNKNOWN_STEELS: OnceLock<Mutex<HashSet<String>>> = OnceLock::new();

/// Material properties for a mesh element.
#[derive(Debug, Clone, Copy)]
pub struct MaterialProps {
    /// Relative permeability (mu_r). Steel ~200-2000, magnet ~1.05, air = 1.
    pub mu_rel: f64,
    /// Reluctivity nu = 1/(mu_0 * mu_r) [m/H].
    pub nu: f64,
    /// Remanent flux density Br [T] (nonzero only for permanent magnets).
    pub br: f64,
    /// Magnetization direction angle [rad] (for PM source terms).
    pub mag_angle_rad: f64,
}

impl MaterialProps {
    pub fn new(mu_rel: f64, br: f64, mag_angle_rad: f64) -> Self {
        let mu_rel = mu_rel.max(1.0);
        Self {
            mu_rel,
            nu: 1.0 / (MU_0 * mu_rel),
            br,
            mag_angle_rad,
        }
    }

    pub fn with_mu_rel(&mut self, mu_rel: f64) {
        self.mu_rel = mu_rel.max(1.0);
        self.nu = 1.0 / (MU_0 * self.mu_rel);
    }

    pub fn air() -> Self {
        Self::new(1.0, 0.0, 0.0)
    }

    pub fn steel(name: &str) -> Self {
        // The per-problem resolver supplies the actual initial permeability.
        if is_custom_steel_key(name) {
            return Self::new(1.0, 0.0, 0.0);
        }
        let mu_rel = initial_steel_mu_rel(name);
        Self::new(mu_rel, 0.0, 0.0)
    }

    pub fn magnet(grade: &str, angle_rad: f64) -> Self {
        let (br, mu_rel) = match grade {
            // N35 retains the validated source-catalog value for BLDC parity.
            // Other NdFeB values use Arnold typical values. See MATERIALS.md.
            "N35" => (1.230, 1.05),
            "N38" => (1.260, 1.05),
            "N42" => (1.315, 1.05),
            "Prius_2004_NdFeB" => (1.240, 1.05),
            "N45" => (1.350, 1.05),
            "N48" => (1.400, 1.05),
            "N48SH" => (1.390, 1.05),
            "N52" => (1.450, 1.05),
            "Ferrite" | "Ferrite_Y30" => (0.400, 1.05),
            _ => (1.315, 1.05), // documented nominal N42 default
        };
        Self::new(mu_rel, br * magnet_br_scale(), angle_rad)
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MaterialKeyError {
    pub region: Region,
    pub material_key: String,
}

impl std::fmt::Display for MaterialKeyError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(
            f,
            "unsupported material key '{}' for {:?}",
            self.material_key, self.region
        )
    }
}

impl std::error::Error for MaterialKeyError {}

pub fn steel_grade_from_material_key(key: &str) -> Option<&str> {
    let normalized = key.trim();
    let candidate = normalized
        .strip_prefix("steel:stator:")
        .or_else(|| normalized.strip_prefix("steel:rotor:"))
        .or_else(|| normalized.strip_prefix("steel:"));
    let grade = candidate.unwrap_or(normalized);
    known_steel_grade(grade).then_some(grade)
}

pub fn magnet_grade_from_material_key(key: &str) -> Option<&str> {
    let normalized = key.trim();
    let grade = normalized.strip_prefix("magnet:").unwrap_or(normalized);
    known_magnet_grade(grade).then_some(grade)
}

fn known_steel_grade(grade: &str) -> bool {
    is_custom_steel_key(grade) || matches!(
        grade,
        "M350-50A" | "M19" | "M27" | "M36" | "NO20" | "NO27" | "1018_steel"
    )
}

pub fn is_custom_steel_key(key: &str) -> bool {
    key.strip_prefix("custom:")
        .is_some_and(|digest| digest.len() == 64 && digest.bytes().all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b)))
}

fn known_magnet_grade(grade: &str) -> bool {
    matches!(
        grade,
        "N35"
            | "N38"
            | "N42"
            | "Prius_2004_NdFeB"
            | "N45"
            | "N48"
            | "N48SH"
            | "N52"
            | "Ferrite"
            | "Ferrite_Y30"
    )
}

fn material_from_contract_key(
    region: Region,
    material_key: &str,
    mag_angle_rad: f64,
) -> Result<MaterialProps, MaterialKeyError> {
    let key = material_key.trim();
    match region {
        Region::RotorCore | Region::StatorTooth | Region::StatorYoke => {
            steel_grade_from_material_key(key)
                .map(MaterialProps::steel)
                .ok_or_else(|| MaterialKeyError {
                    region,
                    material_key: key.to_string(),
                })
        }
        Region::Magnet => magnet_grade_from_material_key(key)
            .map(|grade| MaterialProps::magnet(grade, mag_angle_rad))
            .ok_or_else(|| MaterialKeyError {
                region,
                material_key: key.to_string(),
            }),
        Region::Airgap | Region::FluxBarrier | Region::MagnetPocketAir => {
            if key == "air" || key.starts_with("air:") {
                Ok(MaterialProps::air())
            } else {
                Err(MaterialKeyError {
                    region,
                    material_key: key.to_string(),
                })
            }
        }
        Region::SlotWinding => {
            if key == "air" || key.starts_with("conductor:") {
                Ok(MaterialProps::air())
            } else {
                Err(MaterialKeyError {
                    region,
                    material_key: key.to_string(),
                })
            }
        }
    }
}

fn parse_magnet_br_scale(raw: Option<&str>) -> f64 {
    raw.and_then(|value| value.trim().parse::<f64>().ok())
        .filter(|value| value.is_finite() && *value >= 0.0)
        .unwrap_or(1.0)
}

fn magnet_br_scale() -> f64 {
    parse_magnet_br_scale(env::var("COILEM_MAGNET_BR_SCALE").ok().as_deref())
}

#[derive(Debug, Clone)]
pub struct BHCurve {
    #[allow(dead_code)]
    pub name: String,
    pub points: Vec<(f64, f64)>,
}

#[allow(dead_code)]
#[derive(Debug, Clone, Copy)]
pub struct SteinmetzCoefficients {
    pub kh: f64,
    pub ke: f64,
    pub alpha: f64,
    pub density_kg_m3: f64,
}

impl BHCurve {
    fn from_csv(name: &str, raw: &str) -> Result<Self, String> {
        let mut points = Vec::new();

        for (line_index, raw_line) in raw.lines().enumerate() {
            let line = raw_line.trim();
            if line.is_empty() || line.starts_with('#') {
                continue;
            }
            // Skip the CSV header row wherever it lives. Previously gated on
            // line_index == 0, which silently broke M19.csv (header at line
            // 15 after a 14-line comment preamble). That made
            // load_bh_database() return Err, has_bh_curve("M19") false, and
            // the nonlinear solve silently disabled on every fixture using
            // M19 — root cause of the Task #43 / probe 4 cogging parity gap.
            if line.to_ascii_lowercase().contains("b_t") {
                continue;
            }

            let mut cols = line.split(',');
            let b = cols
                .next()
                .ok_or_else(|| format!("missing B field at line {}", line_index + 1))?
                .trim()
                .parse::<f64>()
                .map_err(|_| format!("invalid B value at line {}", line_index + 1))?;
            let h = cols
                .next()
                .ok_or_else(|| format!("missing H field at line {}", line_index + 1))?
                .trim()
                .parse::<f64>()
                .map_err(|_| format!("invalid H value at line {}", line_index + 1))?;
            if cols.next().is_some() {
                return Err(format!("unexpected extra field at line {}", line_index + 1));
            }
            if !b.is_finite() || !h.is_finite() {
                return Err(format!("non-finite B-H point at line {}", line_index + 1));
            }
            if b < 0.0 || h < 0.0 {
                return Err(format!("negative B-H point at line {}", line_index + 1));
            }
            if let Some(&(previous_b, previous_h)) = points.last() {
                if b <= previous_b {
                    return Err(format!(
                        "B values must be strictly increasing at line {}",
                        line_index + 1
                    ));
                }
                if h < previous_h {
                    return Err(format!(
                        "H values must be non-decreasing at line {}",
                        line_index + 1
                    ));
                }
            }
            points.push((b, h));
        }

        if points.len() < 2 {
            return Err(format!(
                "B-H curve '{name}' must contain at least two points"
            ));
        }
        if points[0] != (0.0, 0.0) {
            return Err(format!("B-H curve '{name}' must begin at B=0, H=0"));
        }

        Ok(Self {
            name: name.to_string(),
            points,
        })
    }

    pub fn interpolate_h(&self, b_t: f64) -> f64 {
        let b_t = b_t.abs();
        if b_t <= self.points[0].0 {
            return self.points[0].1;
        }

        for window in self.points.windows(2) {
            let (b0, h0) = window[0];
            let (b1, h1) = window[1];
            if b_t <= b1 {
                let span = (b1 - b0).max(1e-12);
                let t = (b_t - b0) / span;
                return h0 + t * (h1 - h0);
            }
        }

        let (b0, h0) = self.points[self.points.len() - 2];
        let (b1, h1) = self.points[self.points.len() - 1];
        let slope = (h1 - h0) / (b1 - b0).max(1e-12);
        h1 + slope * (b_t - b1)
    }

    pub fn secant_mu_rel(&self, b_t: f64) -> f64 {
        let effective_b = b_t.abs().max(1e-4);
        let h = self.interpolate_h(effective_b).max(1e-9);
        let (min_mu, max_mu) = nonlinear_steel_mu_bounds();
        (effective_b / (MU_0 * h)).clamp(min_mu, max_mu)
    }

    pub fn initial_mu_rel(&self) -> f64 {
        let (min_mu, max_mu) = nonlinear_steel_mu_bounds();
        for &(b_t, h) in self.points.iter().skip(1) {
            if b_t > 0.0 && h > 0.0 {
                return (b_t / (MU_0 * h)).clamp(min_mu, max_mu);
            }
        }
        DEFAULT_LINEAR_STEEL_MU_REL
    }
}

fn env_mu_bound(name: &str, fallback: f64) -> f64 {
    env::var(name)
        .ok()
        .and_then(|value| value.trim().parse::<f64>().ok())
        .filter(|value| value.is_finite() && *value >= 1.0)
        .unwrap_or(fallback)
}

fn nonlinear_steel_mu_bounds() -> (f64, f64) {
    let min_mu = env_mu_bound(STEEL_MU_MIN_ENV, DEFAULT_NONLINEAR_STEEL_MU_MIN);
    let max_mu = env_mu_bound(STEEL_MU_MAX_ENV, DEFAULT_NONLINEAR_STEEL_MU_MAX).max(min_mu);
    (min_mu, max_mu)
}

/// Resolve a named motor material into the neutral field-core curve once at
/// the adapter boundary. Environment-controlled permeability bounds are
/// captured here and become ordinary curve data before iteration starts.
pub fn resolved_field_bh_curve(name: &str) -> Option<crate::field::BhCurve> {
    if env::var(LINEAR_STEEL_MU_ENV)
        .ok()
        .and_then(|value| value.trim().parse::<f64>().ok())
        .filter(|value| value.is_finite() && *value >= 1.0)
        .is_some()
    {
        return None;
    }
    let curve = get_bh_curve(name)?;
    let (mu_r_min, mu_r_max) = nonlinear_steel_mu_bounds();
    Some(crate::field::BhCurve {
        points: curve
            .points
            .iter()
            .map(|&(b_t, h_a_per_m)| crate::field::BhPoint { b_t, h_a_per_m })
            .collect(),
        mu_r_min,
        mu_r_max,
    })
}

fn materials_dirs() -> [PathBuf; 2] {
    let crate_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    [
        crate_dir.join("materials"),
        crate_dir.join("../../materials/electrical-steel"),
    ]
}

fn is_bh_curve_csv(path: &std::path::Path) -> bool {
    let Some(file_name) = path.file_name().and_then(|name| name.to_str()) else {
        return false;
    };
    if file_name.starts_with('.') {
        return false;
    }
    path.extension().and_then(|ext| ext.to_str()) == Some("csv")
}

fn load_bh_database() -> Result<HashMap<String, BHCurve>, String> {
    let mut curves = HashMap::new();
    let m350 = BHCurve::from_csv(
        "M350-50A",
        include_str!("../../../materials/electrical-steel/M350-50A.csv"),
    )?;
    curves.insert("M350-50A".to_string(), m350);
    let mut searched = Vec::new();
    for dir in materials_dirs() {
        searched.push(dir.display().to_string());
        let entries = match fs::read_dir(&dir) {
            Ok(entries) => entries,
            Err(err) if err.kind() == std::io::ErrorKind::NotFound => continue,
            Err(err) => {
                return Err(format!(
                    "failed to read B-H materials dir '{}': {err}",
                    dir.display()
                ));
            }
        };

        for entry in entries {
            let entry = entry.map_err(|err| format!("failed to read B-H material entry: {err}"))?;
            let path = entry.path();
            if !is_bh_curve_csv(&path) {
                continue;
            }

            let name = path
                .file_stem()
                .and_then(|stem| stem.to_str())
                .ok_or_else(|| format!("invalid B-H curve filename '{}'", path.display()))?;
            if name == "M350-50A" {
                // This launch material is compiled from the reviewed shared
                // curve above, so another runtime search path cannot replace it.
                continue;
            }
            let raw = fs::read_to_string(&path)
                .map_err(|err| format!("failed to read B-H curve '{}': {err}", path.display()))?;
            let curve = BHCurve::from_csv(name, &raw)?;
            curves.insert(name.to_string(), curve);
        }
    }

    if curves.is_empty() {
        return Err(format!("no B-H curves found in {}", searched.join(", ")));
    }

    Ok(curves)
}

fn bh_database() -> &'static Result<HashMap<String, BHCurve>, String> {
    BH_DATABASE.get_or_init(load_bh_database)
}

fn warn_unknown_steel_once(name: &str) {
    let warned = WARNED_UNKNOWN_STEELS.get_or_init(|| Mutex::new(HashSet::new()));
    let mut warned = warned.lock().expect("warned steel mutex poisoned");
    if warned.insert(name.to_string()) {
        eprintln!(
            "magneto2d: warning: no bundled B-H curve for steel grade '{name}', using conservative linear mu_r={DEFAULT_LINEAR_STEEL_MU_REL:.0}"
        );
    }
}

fn linear_steel_mu_override() -> Option<f64> {
    env::var(LINEAR_STEEL_MU_ENV)
        .ok()
        .and_then(|value| value.trim().parse::<f64>().ok())
        .filter(|mu_rel| *mu_rel >= 1.0)
}

#[cfg(test)]
pub fn has_bh_curve(name: &str) -> bool {
    if linear_steel_mu_override().is_some() {
        return false;
    }
    match bh_database() {
        Ok(curves) => curves.contains_key(name),
        Err(err) => {
            eprintln!("magneto2d: warning: B-H database unavailable: {err}");
            false
        }
    }
}

pub fn get_bh_curve(name: &str) -> Option<&'static BHCurve> {
    match bh_database() {
        Ok(curves) => curves.get(name),
        Err(err) => {
            eprintln!("magneto2d: warning: B-H database unavailable: {err}");
            None
        }
    }
}

pub fn initial_steel_mu_rel(name: &str) -> f64 {
    if let Some(mu_rel) = linear_steel_mu_override() {
        return mu_rel;
    }
    if let Some(curve) = get_bh_curve(name) {
        curve.initial_mu_rel()
    } else {
        warn_unknown_steel_once(name);
        DEFAULT_LINEAR_STEEL_MU_REL
    }
}

pub fn nonlinear_steel_mu_rel(name: &str, b_t: f64) -> Option<f64> {
    if linear_steel_mu_override().is_some() {
        return None;
    }
    get_bh_curve(name).map(|curve| curve.secant_mu_rel(b_t))
}


/// Assign material properties to each triangle based on its region tag and
/// the angular position of the element centroid (for magnet orientation).
#[allow(dead_code)]
pub fn assign_materials(
    regions: &[Region],
    centroids: &[[f64; 2]],
    stator_steel: &str,
    rotor_steel: &str,
    magnet_grade: &str,
    pole_count: u32,
    rotor_angle_rad: f64,
) -> Vec<MaterialProps> {
    assign_materials_with_mode(
        regions,
        centroids,
        stator_steel,
        rotor_steel,
        magnet_grade,
        pole_count,
        rotor_angle_rad,
        legacy_element_magnetization_enabled(),
    )
}

pub(crate) fn legacy_element_magnetization_enabled() -> bool {
    env::var("COILEM_MAGNETO2D_ELEMENT_MAGNETIZATION")
        .map(|value| matches!(value.as_str(), "1" | "true" | "TRUE" | "yes" | "YES"))
        .unwrap_or(false)
}

pub(crate) fn spm_magnetization_angle_rad(
    centroid: [f64; 2],
    pole_count: u32,
    rotor_angle_rad: f64,
    use_element_magnetization: bool,
) -> f64 {
    // Magnet orientation: radially outward, with alternating polarity.
    // Apply rotor_angle_rad offset to simulate rotor rotation.
    // Pole 0 is centered on +x, matching the backend/FEMM geometry
    // convention rather than occupying the full [0, pole_pitch) span.
    let angle = centroid[1].atan2(centroid[0]);
    let pole_pitch = 2.0 * PI / pole_count as f64;
    let rotor_frame_angle = (angle - rotor_angle_rad).rem_euclid(2.0 * PI);
    let pole_index = (rotor_frame_angle / pole_pitch).round() as i32;
    let pole_index = ((pole_index % pole_count as i32) + pole_count as i32) as u32 % pole_count;
    let pole_center_angle = (rotor_angle_rad + pole_index as f64 * pole_pitch).rem_euclid(2.0 * PI);
    // Default to one constant radial direction per pole so the PM
    // source term matches FEMM's block-label convention and preserves
    // tooth-tip fringing parity more faithfully. A debug override can
    // restore the older per-element radial assignment for comparison.
    // Note: for small rotor steps that don't flip pole_index, the
    // material properties are identical -> same A_z solution. This is
    // a known quantization artifact of the fixed-mesh rotation model.
    let polarity = if pole_index % 2 == 0 { 1.0 } else { -1.0 };
    let base_angle = if use_element_magnetization {
        angle
    } else {
        pole_center_angle
    };
    base_angle + if polarity > 0.0 { 0.0 } else { PI }
}

pub fn assign_materials_with_resolved_magnetization(
    regions: &[Region],
    centroids: &[[f64; 2]],
    element_magnetization_rad: &[Option<f64>],
    stator_steel: &str,
    rotor_steel: &str,
    magnet_grade: &str,
    pole_count: u32,
    rotor_angle_rad: f64,
) -> Vec<MaterialProps> {
    assign_materials_with_mode_and_resolved(
        regions,
        centroids,
        stator_steel,
        rotor_steel,
        magnet_grade,
        pole_count,
        rotor_angle_rad,
        legacy_element_magnetization_enabled(),
        Some(element_magnetization_rad),
    )
}

#[allow(clippy::too_many_arguments)]
pub fn assign_materials_with_contract_materials(
    regions: &[Region],
    centroids: &[[f64; 2]],
    element_magnetization_rad: &[Option<f64>],
    element_material_keys: &[Option<String>],
    stator_steel: &str,
    rotor_steel: &str,
    magnet_grade: &str,
    pole_count: u32,
    rotor_angle_rad: f64,
) -> Result<Vec<MaterialProps>, MaterialKeyError> {
    if element_material_keys.len() != regions.len() {
        return Ok(assign_materials_with_resolved_magnetization(
            regions,
            centroids,
            element_magnetization_rad,
            stator_steel,
            rotor_steel,
            magnet_grade,
            pole_count,
            rotor_angle_rad,
        ));
    }
    regions
        .iter()
        .zip(centroids.iter())
        .enumerate()
        .map(|(idx, (region, centroid))| {
            let mag_angle = element_magnetization_rad
                .get(idx)
                .copied()
                .flatten()
                .unwrap_or_else(|| {
                    spm_magnetization_angle_rad(
                        *centroid,
                        pole_count,
                        rotor_angle_rad,
                        legacy_element_magnetization_enabled(),
                    )
                });
            match element_material_keys
                .get(idx)
                .and_then(|key| key.as_deref())
            {
                Some(key) => material_from_contract_key(*region, key, mag_angle),
                None => Ok(match region {
                    Region::RotorCore => MaterialProps::steel(rotor_steel),
                    Region::StatorTooth | Region::StatorYoke => MaterialProps::steel(stator_steel),
                    Region::Airgap | Region::FluxBarrier | Region::MagnetPocketAir => {
                        MaterialProps::air()
                    }
                    Region::SlotWinding => MaterialProps::air(),
                    Region::Magnet => MaterialProps::magnet(magnet_grade, mag_angle),
                }),
            }
        })
        .collect()
}

#[allow(dead_code)]
fn assign_materials_with_mode(
    regions: &[Region],
    centroids: &[[f64; 2]],
    stator_steel: &str,
    rotor_steel: &str,
    magnet_grade: &str,
    pole_count: u32,
    rotor_angle_rad: f64,
    use_element_magnetization: bool,
) -> Vec<MaterialProps> {
    assign_materials_with_mode_and_resolved(
        regions,
        centroids,
        stator_steel,
        rotor_steel,
        magnet_grade,
        pole_count,
        rotor_angle_rad,
        use_element_magnetization,
        None,
    )
}

fn assign_materials_with_mode_and_resolved(
    regions: &[Region],
    centroids: &[[f64; 2]],
    stator_steel: &str,
    rotor_steel: &str,
    magnet_grade: &str,
    pole_count: u32,
    rotor_angle_rad: f64,
    use_element_magnetization: bool,
    resolved_magnetization_rad: Option<&[Option<f64>]>,
) -> Vec<MaterialProps> {
    regions
        .iter()
        .zip(centroids.iter())
        .enumerate()
        .map(|(idx, (region, centroid))| match region {
            Region::RotorCore => MaterialProps::steel(rotor_steel),
            Region::StatorTooth | Region::StatorYoke => MaterialProps::steel(stator_steel),
            Region::Airgap | Region::FluxBarrier | Region::MagnetPocketAir => MaterialProps::air(),
            Region::SlotWinding => MaterialProps::air(), // copper has mu_r approx 1
            Region::Magnet => {
                let mag_angle = resolved_magnetization_rad
                    .and_then(|values| values.get(idx).copied().flatten())
                    .unwrap_or_else(|| {
                        spm_magnetization_angle_rad(
                            *centroid,
                            pole_count,
                            rotor_angle_rad,
                            use_element_magnetization,
                        )
                    });
                MaterialProps::magnet(magnet_grade, mag_angle)
            }
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use std::f64::consts::PI;

    use super::{
        assign_materials, assign_materials_with_mode, assign_materials_with_resolved_magnetization,
        get_bh_curve, has_bh_curve, initial_steel_mu_rel, is_bh_curve_csv, nonlinear_steel_mu_rel,
        parse_magnet_br_scale, BHCurve, MaterialProps,
    };
    use crate::mesh::Region;


    #[test]
    fn bh_database_ignores_hidden_appledouble_csv_files() {
        assert!(is_bh_curve_csv(std::path::Path::new("M350-50A.csv")));
        assert!(is_bh_curve_csv(std::path::Path::new("M19.csv")));
        assert!(!is_bh_curve_csv(std::path::Path::new("._M19.csv")));
        assert!(!is_bh_curve_csv(std::path::Path::new(".M19.csv")));
    }


    #[test]
    fn from_csv_tolerates_comment_preamble_before_header() {
        // Direct regression test for the header-skip bug. The original gate
        // `line_index == 0 && contains("b_t")` only stripped the header when
        // it sat at line 0; any CSV with leading `#` comments would fall
        // through to parse the header as a data row and blow up with
        // "invalid B value at line N". Catching this at the parser level
        // means we fail with a clear signal regardless of which bundled CSV
        // tripped it.
        let csv = "\
# Source: synthetic
#
# second comment line
B_T,H_A_per_m
0.0,0.0
1.0,100.0
2.0,1000.0
";
        let curve = BHCurve::from_csv("test_preamble", csv)
            .expect("from_csv must skip header after comment preamble");
        assert_eq!(curve.points.len(), 3);
        assert_eq!(curve.points[0], (0.0, 0.0));
        assert_eq!(curve.points[2], (2.0, 1000.0));
    }

    #[test]
    fn from_csv_rejects_non_numeric_data_row() {
        // Paired negative test — we still want from_csv to *reject* bad
        // numeric data so the header-skip loosening above doesn't
        // accidentally swallow garbled files.
        let csv = "\
B_T,H_A_per_m
0.0,0.0
notanumber,100.0
";
        let err = BHCurve::from_csv("test_bad", csv)
            .expect_err("non-numeric data rows must surface as errors");
        assert!(
            err.contains("invalid B"),
            "expected 'invalid B' error, got: {err}"
        );
    }

    #[test]
    fn from_csv_rejects_non_monotonic_and_non_finite_points() {
        let non_monotonic = "\
B_T,H_A_per_m
0.0,0.0
1.0,100.0
0.5,200.0
";
        let err = BHCurve::from_csv("non_monotonic", non_monotonic)
            .expect_err("non-monotonic B values must be rejected");
        assert!(
            err.contains("strictly increasing"),
            "unexpected error: {err}"
        );

        let non_finite = "\
B_T,H_A_per_m
0.0,0.0
1.0,NaN
";
        let err = BHCurve::from_csv("non_finite", non_finite)
            .expect_err("non-finite values must be rejected");
        assert!(err.contains("non-finite"), "unexpected error: {err}");
    }

    #[test]
    fn bundled_m350_50a_curve_has_open_nonlinear_range() {
        assert!(has_bh_curve("M350-50A"));
        let curve = get_bh_curve("M350-50A").expect("M350-50A curve should be bundled");
        assert!(curve.points.len() >= 250);
        assert!(curve.points.last().is_some_and(|(b_t, _)| *b_t >= 2.5));

        let initial = initial_steel_mu_rel("M350-50A");
        let peak_region = nonlinear_steel_mu_rel("M350-50A", 1.0)
            .expect("M350-50A nonlinear curve should be active");
        let saturated = nonlinear_steel_mu_rel("M350-50A", 2.2)
            .expect("M350-50A nonlinear curve should be active");
        assert!(
            (initial - 1210.0).abs() < 1.0,
            "unexpected initial mu_r={initial}"
        );
        assert!(
            peak_region > 5_000.0,
            "unexpected peak-region mu_r={peak_region}"
        );
        assert!(
            saturated < 10.0,
            "hard-saturation mu_r should fall below 10; got {saturated}"
        );
    }




    #[test]
    fn missing_curve_uses_conservative_linear_default() {
        let mu = initial_steel_mu_rel("unknown_steel");
        assert_eq!(mu, 600.0);
    }


    #[test]
    fn magnet_br_scale_parser_accepts_only_finite_nonnegative_values() {
        assert_eq!(parse_magnet_br_scale(None), 1.0);
        assert_eq!(parse_magnet_br_scale(Some("0.75")), 0.75);
        assert_eq!(parse_magnet_br_scale(Some("0")), 0.0);
        assert_eq!(parse_magnet_br_scale(Some("-1")), 1.0);
        assert_eq!(parse_magnet_br_scale(Some("nan")), 1.0);
        assert_eq!(parse_magnet_br_scale(Some("not-a-number")), 1.0);
    }

    #[test]
    fn prius_reference_magnet_has_explicit_br_without_external_scale() {
        let magnet = MaterialProps::magnet("Prius_2004_NdFeB", 0.0);

        assert!((magnet.br - 1.24).abs() < 1e-12);
        assert!((magnet.mu_rel - 1.05).abs() < 1e-12);
    }

    #[test]
    fn n35_matches_shared_product_material_contract() {
        // Python tests check this same contract against both the public
        // catalog and FEMM's actual material source.
        let contract: serde_json::Value =
            serde_json::from_str(include_str!("../tests/fixtures/n35_material_contract.json"))
                .unwrap();
        let grade = contract["grade"].as_str().unwrap();
        let br = contract["remanence_T"].as_f64().unwrap();
        let mu_rel = contract["relative_permeability"].as_f64().unwrap();
        let angle = PI / 7.0;
        let magnet = MaterialProps::magnet(grade, angle);

        assert!((magnet.br - br * super::magnet_br_scale()).abs() < 1e-12);
        assert!((magnet.mu_rel - mu_rel).abs() < 1e-12);
        assert_eq!(magnet.mag_angle_rad, angle);
    }

    #[test]
    fn magnet_polarity_is_centered_on_pole_axes() {
        let regions = vec![Region::Magnet, Region::Magnet, Region::Magnet];
        let centroids = vec![
            [1.0, 0.0],
            [1.0 / 2.0_f64.sqrt(), 1.0 / 2.0_f64.sqrt()],
            [0.0, 1.0],
        ];
        let materials = assign_materials(&regions, &centroids, "M19", "M19", "N42", 8, 0.0);

        assert!((materials[0].mag_angle_rad - 0.0).abs() < 1e-12);
        // 45 mechanical degrees is the center of the second pole and should flip polarity.
        assert!((materials[1].mag_angle_rad - (PI / 4.0 + PI)).abs() < 1e-12);
        // 90 mechanical degrees returns to N polarity for pole 2.
        assert!((materials[2].mag_angle_rad - PI / 2.0).abs() < 1e-12);
    }

    #[test]
    fn default_magnetization_is_constant_within_a_pole() {
        let regions = vec![Region::Magnet];
        let centroids = vec![[0.9238795325, 0.3826834324]]; // 22.5 mech deg
        let materials =
            assign_materials_with_mode(&regions, &centroids, "M19", "M19", "N42", 4, 0.0, false);

        assert!((materials[0].mag_angle_rad - 0.0).abs() < 1e-12);
    }

    #[test]
    fn legacy_element_magnetization_tracks_centroid_angle() {
        let regions = vec![Region::Magnet];
        let centroids = vec![[0.9238795325_f64, 0.3826834324_f64]]; // 22.5 mech deg
        let expected_angle = centroids[0][1].atan2(centroids[0][0]);
        let materials =
            assign_materials_with_mode(&regions, &centroids, "M19", "M19", "N42", 4, 0.0, true);

        assert!((materials[0].mag_angle_rad - expected_angle).abs() < 1e-12);
    }

    #[test]
    fn resolved_magnetization_overrides_spm_fallback_angle() {
        let regions = vec![Region::Magnet];
        let centroids = vec![[1.0, 0.0]];
        let resolved = vec![Some(30.0_f64.to_radians())];

        let materials = assign_materials_with_resolved_magnetization(
            &regions, &centroids, &resolved, "M19", "M19", "N42", 4, 0.0,
        );

        assert!((materials[0].mag_angle_rad - 30.0_f64.to_radians()).abs() < 1e-12);
    }
}
