//! Thermal boundary conditions: Dirichlet, Neumann flux, convection, radiation.

use serde::{Deserialize, Serialize};

use crate::sparse::CsrMatrix;

pub const STEFAN_BOLTZMANN: f64 = 5.670374419e-8;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum ThermalBoundaryCondition {
    /// Fixed temperature on listed nodes [K].
    Dirichlet {
        node_indices: Vec<usize>,
        temperature_k: f64,
    },
    /// Prescribed outward heat flux on boundary edges [W/m²].
    /// Edge is (node_a, node_b); positive flux leaves the domain.
    NeumannFlux {
        edges: Vec<[usize; 2]>,
        flux_w_per_m2: f64,
    },
    /// Convection: q = h (T - T_amb) leaving the domain on boundary edges.
    Convection {
        edges: Vec<[usize; 2]>,
        h_w_per_m2_k: f64,
        ambient_k: f64,
    },
    /// Nonlinear radiation: q = ε σ (T⁴ - T_amb⁴) leaving the domain.
    Radiation {
        edges: Vec<[usize; 2]>,
        emissivity: f64,
        ambient_k: f64,
    },
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct ThermalBoundarySet {
    pub conditions: Vec<ThermalBoundaryCondition>,
}

impl ThermalBoundarySet {
    #[allow(dead_code)] // used by thermal unit tests / future callers
    pub fn new(conditions: Vec<ThermalBoundaryCondition>) -> Self {
        Self { conditions }
    }

    /// Require at least one absolute-temperature anchor.
    ///
    /// Empty and pure-Neumann systems are underconstrained: absolute T is
    /// arbitrary (or all-zero) while energy balance can still report closed.
    ///
    /// Indices are validated against `n_nodes`: out-of-range Dirichlet nodes
    /// or convection/radiation edge endpoints are rejected (they previously
    /// passed this gate while `dirichlet_values` silently ignored them).
    pub fn validate_temperature_anchor(&self, n_nodes: usize) -> Result<(), String> {
        if self.conditions.is_empty() {
            return Err(
                "thermal boundaries empty: require at least one Dirichlet, \
                 positive-h convection, or radiation temperature anchor"
                    .to_string(),
            );
        }
        self.validate_boundary_indices(n_nodes)?;
        for condition in &self.conditions {
            match condition {
                ThermalBoundaryCondition::Dirichlet {
                    node_indices,
                    temperature_k,
                } => {
                    let in_range = node_indices.iter().any(|&n| n < n_nodes);
                    if in_range && temperature_k.is_finite() {
                        return Ok(());
                    }
                }
                ThermalBoundaryCondition::Convection {
                    edges,
                    h_w_per_m2_k,
                    ambient_k,
                } => {
                    let in_range = edges
                        .iter()
                        .any(|[a, b]| *a < n_nodes && *b < n_nodes);
                    if in_range
                        && h_w_per_m2_k.is_finite()
                        && *h_w_per_m2_k > 0.0
                        && ambient_k.is_finite()
                    {
                        return Ok(());
                    }
                }
                ThermalBoundaryCondition::Radiation {
                    edges,
                    emissivity,
                    ambient_k,
                } => {
                    let in_range = edges
                        .iter()
                        .any(|[a, b]| *a < n_nodes && *b < n_nodes);
                    if in_range
                        && emissivity.is_finite()
                        && *emissivity > 0.0
                        && ambient_k.is_finite()
                    {
                        return Ok(());
                    }
                }
                ThermalBoundaryCondition::NeumannFlux { .. } => {}
            }
        }
        Err(
            "thermal boundaries lack a temperature anchor: pure Neumann \
             (or zero-h / empty-edge convection/radiation) leaves absolute \
             temperature underconstrained"
                .to_string(),
        )
    }

    /// Reject any Dirichlet node or edge endpoint outside `[0, n_nodes)`.
    pub fn validate_boundary_indices(&self, n_nodes: usize) -> Result<(), String> {
        for condition in &self.conditions {
            match condition {
                ThermalBoundaryCondition::Dirichlet { node_indices, .. } => {
                    for &node in node_indices {
                        if node >= n_nodes {
                            return Err(format!(
                                "Dirichlet node_indices contains out-of-range \
                                 index {node} (mesh has {n_nodes} nodes)"
                            ));
                        }
                    }
                }
                ThermalBoundaryCondition::NeumannFlux { edges, .. }
                | ThermalBoundaryCondition::Convection { edges, .. }
                | ThermalBoundaryCondition::Radiation { edges, .. } => {
                    for edge in edges {
                        let [a, b] = *edge;
                        if a >= n_nodes || b >= n_nodes {
                            return Err(format!(
                                "boundary edge [{a}, {b}] has out-of-range \
                                 endpoint (mesh has {n_nodes} nodes)"
                            ));
                        }
                    }
                }
            }
        }
        Ok(())
    }

    pub fn dirichlet_values(&self, n_nodes: usize) -> Vec<Option<f64>> {
        let mut values = vec![None; n_nodes];
        for condition in &self.conditions {
            if let ThermalBoundaryCondition::Dirichlet {
                node_indices,
                temperature_k,
            } = condition
            {
                for &node in node_indices {
                    // Indices must already pass validate_boundary_indices;
                    // keep a defensive skip so assembly never panics.
                    if node < n_nodes {
                        values[node] = Some(*temperature_k);
                    }
                }
            }
        }
        values
    }

    /// Assemble linear (Dirichlet / Neumann / convection) contributions.
    /// Radiation is applied separately in the nonlinear loop.
    pub fn apply_linear(
        &self,
        matrix: &mut CsrMatrix,
        rhs: &mut [f64],
        nodes_m: &[[f64; 2]],
        stack_length_m: f64,
    ) -> Result<(), String> {
        self.apply_linear_without_dirichlet(matrix, rhs, nodes_m, stack_length_m)?;
        let dirichlet = self.dirichlet_values(rhs.len());
        if dirichlet.iter().any(Option::is_some) {
            matrix.apply_dirichlet_values(rhs, &dirichlet)?;
        }
        Ok(())
    }

    /// Neumann + convection only (no Dirichlet row replacement).
    pub fn apply_linear_without_dirichlet(
        &self,
        matrix: &mut CsrMatrix,
        rhs: &mut [f64],
        nodes_m: &[[f64; 2]],
        stack_length_m: f64,
    ) -> Result<(), String> {
        for condition in &self.conditions {
            match condition {
                ThermalBoundaryCondition::NeumannFlux {
                    edges,
                    flux_w_per_m2,
                } => {
                    apply_neumann_flux(rhs, nodes_m, edges, *flux_w_per_m2, stack_length_m);
                }
                ThermalBoundaryCondition::Convection {
                    edges,
                    h_w_per_m2_k,
                    ambient_k,
                } => {
                    apply_convection(
                        matrix,
                        rhs,
                        nodes_m,
                        edges,
                        *h_w_per_m2_k,
                        *ambient_k,
                        stack_length_m,
                    )?;
                }
                ThermalBoundaryCondition::Dirichlet { .. }
                | ThermalBoundaryCondition::Radiation { .. } => {}
            }
        }
        Ok(())
    }

    pub fn has_radiation(&self) -> bool {
        self.conditions
            .iter()
            .any(|c| matches!(c, ThermalBoundaryCondition::Radiation { .. }))
    }

    /// Apply linearized radiation about the current temperature iterate.
    ///
    /// q(T) ≈ q(T*) + h_rad (T - T*) with h_rad = 4 ε σ T*³,
    /// which yields the Robin form used by the small-ΔT property gate.
    pub fn apply_radiation_linearized(
        &self,
        matrix: &mut CsrMatrix,
        rhs: &mut [f64],
        nodes_m: &[[f64; 2]],
        temperature_k: &[f64],
        stack_length_m: f64,
    ) -> Result<(), String> {
        for condition in &self.conditions {
            if let ThermalBoundaryCondition::Radiation {
                edges,
                emissivity,
                ambient_k,
            } = condition
            {
                apply_radiation_linearized(
                    matrix,
                    rhs,
                    nodes_m,
                    edges,
                    temperature_k,
                    *emissivity,
                    *ambient_k,
                    stack_length_m,
                )?;
            }
        }
        Ok(())
    }
}

fn edge_length_m(nodes_m: &[[f64; 2]], a: usize, b: usize) -> f64 {
    let dx = nodes_m[b][0] - nodes_m[a][0];
    let dy = nodes_m[b][1] - nodes_m[a][1];
    (dx * dx + dy * dy).sqrt()
}

fn apply_neumann_flux(
    rhs: &mut [f64],
    nodes_m: &[[f64; 2]],
    edges: &[[usize; 2]],
    flux_w_per_m2: f64,
    stack_length_m: f64,
) {
    // Weak form for -div(k grad T) = q with outward flux q_n:
    // boundary term contributes -∫ q_n φ_i dS to the residual of K T = f,
    // so f_i -= q_n * length * stack / 2 per endpoint when q_n is outward.
    for edge in edges {
        let [a, b] = *edge;
        let length = edge_length_m(nodes_m, a, b);
        let contrib = -flux_w_per_m2 * length * stack_length_m / 2.0;
        if a < rhs.len() {
            rhs[a] += contrib;
        }
        if b < rhs.len() {
            rhs[b] += contrib;
        }
    }
}

fn apply_convection(
    matrix: &mut CsrMatrix,
    rhs: &mut [f64],
    nodes_m: &[[f64; 2]],
    edges: &[[usize; 2]],
    h_w_per_m2_k: f64,
    ambient_k: f64,
    stack_length_m: f64,
) -> Result<(), String> {
    // q_out = h (T - T_amb) → add h * mass-lumped edge terms to K and
    // h * T_amb * length * stack / 2 to f.
    for edge in edges {
        let [a, b] = *edge;
        let length = edge_length_m(nodes_m, a, b);
        let scale = h_w_per_m2_k * length * stack_length_m;
        // Consistent 2-node edge mass: (1/6)[2 1; 1 2] * scale, but lumped
        // (1/2) on diagonal is stable and matches the analytic 1D gates.
        add_csr_entry(matrix, a, a, 0.5 * scale)?;
        add_csr_entry(matrix, b, b, 0.5 * scale)?;
        let load = h_w_per_m2_k * ambient_k * length * stack_length_m / 2.0;
        if a < rhs.len() {
            rhs[a] += load;
        }
        if b < rhs.len() {
            rhs[b] += load;
        }
    }
    Ok(())
}

fn apply_radiation_linearized(
    matrix: &mut CsrMatrix,
    rhs: &mut [f64],
    nodes_m: &[[f64; 2]],
    edges: &[[usize; 2]],
    temperature_k: &[f64],
    emissivity: f64,
    ambient_k: f64,
    stack_length_m: f64,
) -> Result<(), String> {
    let eps = emissivity.max(0.0).min(1.0);
    let tamb4 = ambient_k.powi(4);
    for edge in edges {
        let [a, b] = *edge;
        let length = edge_length_m(nodes_m, a, b);
        let t_edge = 0.5 * (temperature_k[a] + temperature_k[b]);
        let t_edge = t_edge.max(1.0);
        let h_rad = 4.0 * eps * STEFAN_BOLTZMANN * t_edge.powi(3);
        let q_star = eps * STEFAN_BOLTZMANN * (t_edge.powi(4) - tamb4);
        // Linearize: q ≈ q* + h_rad (T - T*) = h_rad T + (q* - h_rad T*)
        let scale = h_rad * length * stack_length_m;
        add_csr_entry(matrix, a, a, 0.5 * scale)?;
        add_csr_entry(matrix, b, b, 0.5 * scale)?;
        let load = (h_rad * t_edge - q_star) * length * stack_length_m / 2.0;
        if a < rhs.len() {
            rhs[a] += load;
        }
        if b < rhs.len() {
            rhs[b] += load;
        }
    }
    Ok(())
}

fn add_csr_entry(matrix: &mut CsrMatrix, row: usize, col: usize, value: f64) -> Result<(), String> {
    if row >= matrix.nrows || col >= matrix.nrows {
        return Err(format!("CSR entry ({row},{col}) out of range"));
    }
    for idx in matrix.row_ptr[row]..matrix.row_ptr[row + 1] {
        if matrix.col_idx[idx] == col {
            matrix.values[idx] += value;
            return Ok(());
        }
    }
    Err(format!(
        "CSR pattern missing entry ({row},{col}); rebuild pattern with boundary extras"
    ))
}

/// Equivalent linearized radiation film coefficient h_rad = 4 ε σ T³.
#[allow(dead_code)] // used by thermal unit tests / radiation↔convection equivalence
pub fn linearized_radiation_h(emissivity: f64, temperature_k: f64) -> f64 {
    4.0 * emissivity.max(0.0).min(1.0) * STEFAN_BOLTZMANN * temperature_k.max(1.0).powi(3)
}
