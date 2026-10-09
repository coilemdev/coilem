//! Zero-thickness thermal contact / interface conductance.
//!
//! Models a jump condition across duplicated interface nodes:
//!   q_n = H (T_a - T_b)
//! with edge conductance assembled as a 2-node coupling (lumped length share).
//!
//! External Robin/Neumann/Dirichlet BCs remain in [`super::bc`]. This module
//! is the *internal* contact-resistance element that bulk anisotropic k cannot
//! represent without either a thin meshed layer or node duplication.

use serde::{Deserialize, Serialize};

use crate::sparse::CsrMatrix;

/// One interface segment between two duplicated nodes (same physical point,
/// independent DOFs on each side of the contact).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ThermalContactPair {
    /// Node on side A of the interface.
    pub node_a: usize,
    /// Node on side B (duplicated coordinate).
    pub node_b: usize,
    /// Edge length associated with this pair [m] (typically shared half-edge).
    pub length_m: f64,
}

/// Zero-thickness contact with uniform conductance H [W/(m²·K)].
///
/// Heat rate crossing one pair (per unit stack length L):
///   Q' = H * length_m * (T_a - T_b)
/// Assembly contributes ± H * length * L / 2 terms via the length share
/// already stored on each pair (callers pass half-edge lengths for two
/// endpoint pairs of one geometric edge).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ThermalContactInterface {
    pub id: String,
    pub conductance_w_per_m2_k: f64,
    pub pairs: Vec<ThermalContactPair>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct ThermalContactSet {
    pub interfaces: Vec<ThermalContactInterface>,
}

impl ThermalContactSet {
    #[allow(dead_code)] // test-only until backend contact injection wires ThermalContactSet
    pub fn new(interfaces: Vec<ThermalContactInterface>) -> Self {
        Self { interfaces }
    }

    #[allow(dead_code)] // used by upcoming production contact gate checks
    pub fn is_empty(&self) -> bool {
        self.interfaces.is_empty()
    }

    pub fn validate(&self, n_nodes: usize) -> Result<(), String> {
        for interface in &self.interfaces {
            if interface.id.trim().is_empty() {
                return Err("thermal contact interface id must be non-empty".to_string());
            }
            if !interface.conductance_w_per_m2_k.is_finite()
                || interface.conductance_w_per_m2_k <= 0.0
            {
                return Err(format!(
                    "thermal contact '{}': conductance_w_per_m2_k must be \
                     finite and strictly positive (got {})",
                    interface.id, interface.conductance_w_per_m2_k
                ));
            }
            for pair in &interface.pairs {
                if pair.node_a >= n_nodes || pair.node_b >= n_nodes {
                    return Err(format!(
                        "thermal contact '{}': pair ({}, {}) out of range \
                         (mesh has {n_nodes} nodes)",
                        interface.id, pair.node_a, pair.node_b
                    ));
                }
                if pair.node_a == pair.node_b {
                    return Err(format!(
                        "thermal contact '{}': node_a and node_b must differ \
                         (got {})",
                        interface.id, pair.node_a
                    ));
                }
                if !pair.length_m.is_finite() || pair.length_m <= 0.0 {
                    return Err(format!(
                        "thermal contact '{}': length_m must be finite and \
                         positive (got {})",
                        interface.id, pair.length_m
                    ));
                }
            }
        }
        Ok(())
    }

    /// Extra CSR (row, col) entries required for contact couplings.
    pub fn pattern_extras(&self) -> Vec<(usize, usize)> {
        let mut extras = Vec::new();
        for interface in &self.interfaces {
            for pair in &interface.pairs {
                let a = pair.node_a;
                let b = pair.node_b;
                extras.push((a, a));
                extras.push((b, b));
                extras.push((a, b));
                extras.push((b, a));
            }
        }
        extras
    }

    /// Assemble contact coupling into K (already scaled for stack length).
    pub fn apply(
        &self,
        matrix: &mut CsrMatrix,
        stack_length_m: f64,
    ) -> Result<(), String> {
        for interface in &self.interfaces {
            let h = interface.conductance_w_per_m2_k;
            for pair in &interface.pairs {
                let scale = h * pair.length_m * stack_length_m;
                // Lumped 2-node conductor: [+s -s; -s +s]
                add_csr_entry(matrix, pair.node_a, pair.node_a, scale)?;
                add_csr_entry(matrix, pair.node_b, pair.node_b, scale)?;
                add_csr_entry(matrix, pair.node_a, pair.node_b, -scale)?;
                add_csr_entry(matrix, pair.node_b, pair.node_a, -scale)?;
            }
        }
        Ok(())
    }
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
        "CSR pattern missing entry ({row},{col}); rebuild pattern with contact extras"
    ))
}

/// Equivalent conductance for a thin liner of thickness t and conductivity k:
///   H_eq = k / t   [W/(m²·K)]
///
/// Synthetic convenience for analytic tests only — production values must come
/// from cited slots, never from guessed t/k pairs.
#[allow(dead_code)] // analytic-test helper; not referenced from the bin target
pub fn equivalent_conductance_from_thin_layer(k_w_per_m_k: f64, thickness_m: f64) -> f64 {
    k_w_per_m_k / thickness_m
}
