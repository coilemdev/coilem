//! Volumetric heat sources for steady-state conduction.

/// Per-element volumetric heat generation [W/m³].
#[derive(Debug, Clone)]
pub struct ThermalSources {
    pub q_w_per_m3: Vec<f64>,
}

impl ThermalSources {
    #[allow(dead_code)] // used by thermal unit tests / future callers
    pub fn uniform(n_elements: usize, q_w_per_m3: f64) -> Self {
        Self {
            q_w_per_m3: vec![q_w_per_m3; n_elements],
        }
    }

    pub fn from_values(q_w_per_m3: Vec<f64>) -> Self {
        Self { q_w_per_m3 }
    }

    #[allow(dead_code)] // used by energy-balance diagnostics / future callers
    pub fn total_power_w(&self, element_areas_m2: &[f64], stack_length_m: f64) -> f64 {
        self.q_w_per_m3
            .iter()
            .zip(element_areas_m2.iter())
            .map(|(q, area)| q * area * stack_length_m)
            .sum()
    }
}
