//! Thermal solve report types.

use serde::{Deserialize, Serialize};

use super::energy::ThermalEnergyBalance;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ThermalSolveReport {
    pub openem_convention_tag: String,
    pub nodal_temperature_k: Vec<f64>,
    pub max_temperature_k: f64,
    pub min_temperature_k: f64,
    pub mean_temperature_k: f64,
    pub energy_balance: ThermalEnergyBalance,
    pub nonlinear_iterations: usize,
    pub linear_solver: String,
    pub stack_length_m: f64,
}

impl ThermalSolveReport {
    pub fn from_solution(
        temperature_k: Vec<f64>,
        energy_balance: ThermalEnergyBalance,
        nonlinear_iterations: usize,
        linear_solver: &str,
        stack_length_m: f64,
    ) -> Self {
        let max_temperature_k = temperature_k
            .iter()
            .copied()
            .fold(f64::NEG_INFINITY, f64::max);
        let min_temperature_k = temperature_k.iter().copied().fold(f64::INFINITY, f64::min);
        let mean_temperature_k = if temperature_k.is_empty() {
            0.0
        } else {
            temperature_k.iter().sum::<f64>() / temperature_k.len() as f64
        };
        Self {
            openem_convention_tag: "s48_thermal_steady_state_v1".to_string(),
            nodal_temperature_k: temperature_k,
            max_temperature_k,
            min_temperature_k,
            mean_temperature_k,
            energy_balance,
            nonlinear_iterations,
            linear_solver: linear_solver.to_string(),
            stack_length_m,
        }
    }
}
