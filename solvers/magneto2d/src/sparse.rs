//! Sparse matrix storage and Conjugate Gradient solver.
//!
//! COO (triplet) format for assembly → CSR for fast SpMV → CG solve.
//! The stiffness matrix is symmetric positive definite after Dirichlet BC,
//! so CG converges reliably.

use rayon::prelude::*;
use serde::Serialize;
use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::OnceLock;
use std::time::Instant;

#[derive(Debug, Clone, Default, Serialize, PartialEq)]
pub struct PcgProfile {
    pub solve_calls: u64,
    pub converged_calls: u64,
    pub max_iter_calls: u64,
    pub zero_rhs_calls: u64,
    pub iterations: u64,
    pub preconditioner_build_us: u64,
    pub preconditioner_apply_us: u64,
    pub spmv_us: u64,
    pub dot_us: u64,
    pub vector_update_us: u64,
    pub residual_check_us: u64,
    pub final_residual_us: u64,
}

impl PcgProfile {
    pub fn add_assign(&mut self, other: &Self) {
        self.solve_calls += other.solve_calls;
        self.converged_calls += other.converged_calls;
        self.max_iter_calls += other.max_iter_calls;
        self.zero_rhs_calls += other.zero_rhs_calls;
        self.iterations += other.iterations;
        self.preconditioner_build_us += other.preconditioner_build_us;
        self.preconditioner_apply_us += other.preconditioner_apply_us;
        self.spmv_us += other.spmv_us;
        self.dot_us += other.dot_us;
        self.vector_update_us += other.vector_update_us;
        self.residual_check_us += other.residual_check_us;
        self.final_residual_us += other.final_residual_us;
    }
}

/// Sparse matrix in COO (coordinate/triplet) format for assembly.
pub struct CooMatrix {
    pub nrows: usize,
    pub ncols: usize,
    rows: Vec<usize>,
    cols: Vec<usize>,
    vals: Vec<f64>,
}

/// Sparse matrix in CSR (compressed sparse row) format for fast SpMV.
pub struct CsrMatrix {
    pub nrows: usize,
    pub ncols: usize,
    /// Row pointer: row i has entries in indices[row_ptr[i]..row_ptr[i+1]].
    pub row_ptr: Vec<usize>,
    /// Column indices.
    pub col_idx: Vec<usize>,
    /// Values.
    pub values: Vec<f64>,
}

#[derive(Clone)]
pub struct ElementCsrAssemblyPattern {
    nrows: usize,
    ncols: usize,
    row_ptr: Vec<usize>,
    col_idx: Vec<usize>,
    element_slots: Vec<[[usize; 3]; 3]>,
    slot_by_row_col: HashMap<(usize, usize), usize>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum PcgExecution {
    Serial,
    Parallel,
}

impl PcgExecution {
    fn from_env() -> Self {
        if truthy_env("MAGNETO2D_PCG_PARALLEL") || truthy_env("COILEM_MAGNETO2D_PCG_PARALLEL") {
            Self::Parallel
        } else {
            Self::Serial
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum PcgPreconditionerKind {
    IncompleteCholesky,
    Jacobi,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) struct PcgOptions {
    pub execution: PcgExecution,
    pub preconditioner: PcgPreconditionerKind,
    pub residual_check_interval: usize,
}

impl PcgOptions {
    fn from_env() -> Self {
        let preconditioner = if pcg_preconditioner_name().eq_ignore_ascii_case("jacobi") {
            PcgPreconditionerKind::Jacobi
        } else {
            PcgPreconditionerKind::IncompleteCholesky
        };
        Self {
            execution: PcgExecution::from_env(),
            preconditioner,
            residual_check_interval: pcg_residual_check_interval(),
        }
    }
}

impl CooMatrix {
    pub fn new(n: usize) -> Self {
        Self {
            nrows: n,
            ncols: n,
            rows: Vec::with_capacity(n * 7), // ~7 nonzeros per row for triangles
            cols: Vec::with_capacity(n * 7),
            vals: Vec::with_capacity(n * 7),
        }
    }

    /// Add a value to position (i, j). Duplicates are summed during CSR conversion.
    #[inline]
    pub fn add(&mut self, row: usize, col: usize, val: f64) {
        self.rows.push(row);
        self.cols.push(col);
        self.vals.push(val);
    }

    /// Convert to CSR format, summing duplicate entries.
    pub fn to_csr(self) -> CsrMatrix {
        let nnz = self.rows.len();
        // Sort by (row, col).
        let mut indices: Vec<usize> = (0..nnz).collect();
        indices.sort_unstable_by(|&a, &b| {
            self.rows[a]
                .cmp(&self.rows[b])
                .then(self.cols[a].cmp(&self.cols[b]))
        });

        let mut row_ptr = vec![0usize; self.nrows + 1];
        let mut col_idx = Vec::with_capacity(nnz);
        let mut values = Vec::with_capacity(nnz);

        let mut prev_row = usize::MAX;
        let mut prev_col = usize::MAX;

        for &idx in &indices {
            let r = self.rows[idx];
            let c = self.cols[idx];
            let v = self.vals[idx];

            if r == prev_row && c == prev_col {
                // Sum duplicate.
                *values.last_mut().unwrap() += v;
            } else {
                col_idx.push(c);
                values.push(v);
                // Fill row_ptr for any skipped rows.
                for rp in (prev_row.wrapping_add(1))..=r {
                    if rp < self.nrows + 1 {
                        row_ptr[rp] = col_idx.len() - 1;
                    }
                }
                prev_row = r;
                prev_col = c;
            }
        }

        // Fill remaining row_ptr entries.
        let final_nnz = col_idx.len();
        for rp in (prev_row.wrapping_add(1))..=self.nrows {
            row_ptr[rp] = final_nnz;
        }

        CsrMatrix {
            nrows: self.nrows,
            ncols: self.ncols,
            row_ptr,
            col_idx,
            values,
        }
    }
}

impl ElementCsrAssemblyPattern {
    pub fn from_triangles(
        nrows: usize,
        triangles: &[[usize; 3]],
        extra_entries: &[(usize, usize)],
    ) -> Self {
        let mut entries = Vec::with_capacity(triangles.len() * 9 + extra_entries.len());
        for &[i, j, m] in triangles {
            let local_nodes = [i, j, m];
            for &row in &local_nodes {
                for &col in &local_nodes {
                    entries.push((row, col));
                }
            }
        }
        entries.extend_from_slice(extra_entries);
        entries.retain(|&(row, col)| row < nrows && col < nrows);
        entries.sort_unstable();
        entries.dedup();

        let mut row_ptr = vec![0usize; nrows + 1];
        for &(row, _) in &entries {
            if row < nrows {
                row_ptr[row + 1] += 1;
            }
        }
        for row in 0..nrows {
            row_ptr[row + 1] += row_ptr[row];
        }

        let mut next = row_ptr[..nrows].to_vec();
        let mut col_idx = vec![0usize; entries.len()];
        for &(row, col) in &entries {
            if row < nrows {
                let idx = next[row];
                col_idx[idx] = col;
                next[row] += 1;
            }
        }

        let mut slot_by_row_col = HashMap::with_capacity(col_idx.len());
        for row in 0..nrows {
            for idx in row_ptr[row]..row_ptr[row + 1] {
                slot_by_row_col.insert((row, col_idx[idx]), idx);
            }
        }

        let element_slots = triangles
            .iter()
            .map(|&[i, j, m]| {
                let local_nodes = [i, j, m];
                let mut slots = [[0usize; 3]; 3];
                for a in 0..3 {
                    for b in 0..3 {
                        slots[a][b] = *slot_by_row_col
                            .get(&(local_nodes[a], local_nodes[b]))
                            .expect("triangle entry must exist in CSR assembly pattern");
                    }
                }
                slots
            })
            .collect();

        Self {
            nrows,
            ncols: nrows,
            row_ptr,
            col_idx,
            element_slots,
            slot_by_row_col,
        }
    }

    pub fn zero_matrix(&self) -> CsrMatrix {
        CsrMatrix {
            nrows: self.nrows,
            ncols: self.ncols,
            row_ptr: self.row_ptr.clone(),
            col_idx: self.col_idx.clone(),
            values: vec![0.0; self.col_idx.len()],
        }
    }

    /// Compare the exact prepared CSR structure without allocating another
    /// copy of the row pointers or column indices.
    pub(crate) fn matches_structure(&self, matrix: &CsrMatrix) -> bool {
        self.nrows == matrix.nrows
            && self.ncols == matrix.ncols
            && self.row_ptr == matrix.row_ptr
            && self.col_idx == matrix.col_idx
    }

    #[inline]
    pub fn element_slots(&self, element_index: usize) -> &[[usize; 3]; 3] {
        &self.element_slots[element_index]
    }

    #[inline]
    pub fn slot(&self, row: usize, col: usize) -> Option<usize> {
        self.slot_by_row_col.get(&(row, col)).copied()
    }
}

impl CsrMatrix {
    /// Sparse matrix-vector product: y = A * x.
    pub fn mul_vec(&self, x: &[f64], y: &mut [f64]) {
        self.mul_vec_serial(x, y);
    }

    fn mul_vec_with_execution(&self, x: &[f64], y: &mut [f64], execution: PcgExecution) {
        match execution {
            PcgExecution::Serial => self.mul_vec_serial(x, y),
            PcgExecution::Parallel => self.mul_vec_parallel(x, y),
        }
    }

    fn mul_vec_serial(&self, x: &[f64], y: &mut [f64]) {
        debug_assert_eq!(x.len(), self.ncols);
        debug_assert_eq!(y.len(), self.nrows);
        for i in 0..self.nrows {
            let mut sum = 0.0;
            for idx in self.row_ptr[i]..self.row_ptr[i + 1] {
                sum += self.values[idx] * x[self.col_idx[idx]];
            }
            y[i] = sum;
        }
    }

    fn mul_vec_parallel(&self, x: &[f64], y: &mut [f64]) {
        debug_assert_eq!(x.len(), self.ncols);
        debug_assert_eq!(y.len(), self.nrows);
        y.par_iter_mut().enumerate().for_each(|(i, yi)| {
            let mut sum = 0.0;
            for idx in self.row_ptr[i]..self.row_ptr[i + 1] {
                sum += self.values[idx] * x[self.col_idx[idx]];
            }
            *yi = sum;
        });
    }

    /// Apply Dirichlet BC: zero row and column, set diagonal to 1, zero RHS.
    /// Symmetric zeroing ensures CG convergence on SPD systems.
    pub fn apply_dirichlet(&mut self, rhs: &mut [f64], boundary_nodes: &[usize]) {
        let mut is_bc = vec![false; self.nrows];
        for &node in boundary_nodes {
            if node < self.nrows {
                is_bc[node] = true;
            }
        }

        // For each row, zero out any column entries that point to a BC node
        // (symmetric column zeroing) and zero out BC rows entirely.
        for i in 0..self.nrows {
            if is_bc[i] {
                // Zero out entire BC row, set diagonal to 1.
                for idx in self.row_ptr[i]..self.row_ptr[i + 1] {
                    if self.col_idx[idx] == i {
                        self.values[idx] = 1.0;
                    } else {
                        self.values[idx] = 0.0;
                    }
                }
                rhs[i] = 0.0;
            } else {
                // For non-BC rows, zero out entries in BC columns.
                for idx in self.row_ptr[i]..self.row_ptr[i + 1] {
                    if is_bc[self.col_idx[idx]] {
                        self.values[idx] = 0.0;
                    }
                }
            }
        }
    }

    /// Apply inhomogeneous Dirichlet values: u[i] = value for each set entry.
    ///
    /// Used by thermal fixed-temperature BCs and the weighted-stress auxiliary
    /// Laplace solve. Symmetric column elimination keeps the system SPD for PCG.
    pub fn apply_dirichlet_values(
        &mut self,
        rhs: &mut [f64],
        boundary_values: &[Option<f64>],
    ) -> Result<(), String> {
        if self.nrows != boundary_values.len() || rhs.len() != boundary_values.len() {
            return Err("Dirichlet value dimensions do not match matrix".to_string());
        }

        for row in 0..self.nrows {
            if let Some(value) = boundary_values[row] {
                let mut found_diag = false;
                for idx in self.row_ptr[row]..self.row_ptr[row + 1] {
                    if self.col_idx[idx] == row {
                        self.values[idx] = 1.0;
                        found_diag = true;
                    } else {
                        self.values[idx] = 0.0;
                    }
                }
                if !found_diag {
                    return Err(format!("Dirichlet row {row} has no diagonal entry"));
                }
                rhs[row] = value;
            } else {
                for idx in self.row_ptr[row]..self.row_ptr[row + 1] {
                    if let Some(value) = boundary_values[self.col_idx[idx]] {
                        rhs[row] -= self.values[idx] * value;
                        self.values[idx] = 0.0;
                    }
                }
            }
        }
        Ok(())
    }

    /// Diagonal preconditioner (Jacobi): returns 1/diag(A).
    pub fn diagonal_preconditioner(&self) -> Vec<f64> {
        let mut diag = vec![1.0; self.nrows];
        for i in 0..self.nrows {
            if let Some(d) = self.diagonal_value(i) {
                diag[i] = if d.abs() > 1e-30 { 1.0 / d } else { 1.0 };
            }
        }
        diag
    }

    fn diagonal_value(&self, row: usize) -> Option<f64> {
        if row >= self.nrows {
            return None;
        }
        for idx in self.row_ptr[row]..self.row_ptr[row + 1] {
            if self.col_idx[idx] == row {
                return Some(self.values[idx]);
            }
        }
        None
    }
}

enum PcgPreconditioner {
    Jacobi(Vec<f64>),
    IncompleteCholesky(IncompleteCholesky),
}

impl PcgPreconditioner {
    fn build(a: &CsrMatrix, kind: PcgPreconditionerKind) -> Self {
        if kind == PcgPreconditionerKind::Jacobi {
            return Self::Jacobi(a.diagonal_preconditioner());
        }

        // IC(0) with local pivot repair. Plain IC(0) breaks down on the
        // anti-periodic penalty pair rows (diag ≈ off-diag ≈ 1e10, so the
        // pivot update cancels to ~0 depending on node ordering — structured
        // meshes happen to survive, spade/gmsh orderings do not). Repairing
        // the failing pivot locally (reset to the original matrix diagonal)
        // keeps L·Lᵀ symmetric positive definite — any lower-triangular
        // factor with positive diagonals is — while preserving full
        // preconditioner quality on every healthy row. A global Manteuffel
        // shift was tried first and rejected: unstructured orderings needed
        // shifts up to 1e-1, which tripled PCG iteration counts.
        match IncompleteCholesky::factor(a) {
            Some(factor) => Self::IncompleteCholesky(factor),
            None => {
                eprintln!("  pcg: IC(0) factorization failed; falling back to Jacobi");
                Self::Jacobi(a.diagonal_preconditioner())
            }
        }
    }

    fn apply_with_execution(
        &self,
        r: &[f64],
        z: &mut [f64],
        scratch: &mut [f64],
        execution: PcgExecution,
    ) {
        match self {
            Self::Jacobi(inv_diag) => {
                if execution == PcgExecution::Parallel {
                    z.par_iter_mut()
                        .enumerate()
                        .for_each(|(i, zi)| *zi = inv_diag[i] * r[i]);
                } else {
                    for i in 0..r.len() {
                        z[i] = inv_diag[i] * r[i];
                    }
                }
            }
            Self::IncompleteCholesky(factor) => factor.apply(r, z, scratch),
        }
    }
}

fn pcg_preconditioner_name() -> String {
    // Default since the solver-speedup pass: shifted IC(0). It cuts PCG
    // iterations ~20x vs Jacobi on the lesson 2p6s sweep (1300-1900 iters
    // -> 60-120) for a few percent extra build cost per linear solve.
    // Set MAGNETO2D_PCG_PRECONDITIONER=jacobi to restore the old behavior.
    std::env::var("MAGNETO2D_PCG_PRECONDITIONER").unwrap_or_else(|_| "ic".to_string())
}

/// Lower-triangular IC(0) factor in flat CSR-style storage. The factor is
/// applied twice per PCG iteration, so layout matters: contiguous arrays
/// (instead of a Vec of per-row Vecs) roughly halve apply time at FEM mesh
/// sizes by eliminating per-row pointer chasing.
struct IncompleteCholesky {
    row_ptr: Vec<usize>,
    col_idx: Vec<usize>,
    values: Vec<f64>,
    diag: Vec<f64>,
    inv_diag: Vec<f64>,
}

impl IncompleteCholesky {
    /// Incomplete Cholesky factorization restricted to A's strictly-lower
    /// sparsity pattern, with local pivot repair: whenever a pivot update
    /// cancels below the floor (the anti-periodic penalty pair rows do this
    /// on unstructured node orderings), the pivot is reset to the original
    /// matrix diagonal instead of abandoning the factorization. The repaired
    /// factor stays SPD (positive diagonals ⇒ L·Lᵀ ≻ 0) and acts like
    /// Jacobi on the repaired rows only. Returns None only on structural
    /// problems (non-square, missing/non-positive/non-finite diagonal).
    fn factor(a: &CsrMatrix) -> Option<Self> {
        if a.nrows != a.ncols {
            return None;
        }
        let n = a.nrows;

        let mut row_ptr = Vec::with_capacity(n + 1);
        row_ptr.push(0_usize);
        let mut col_idx: Vec<usize> = Vec::new();
        let mut values: Vec<f64> = Vec::new();
        let mut a_values_row: Vec<f64> = Vec::new();
        let mut diag: Vec<f64> = Vec::with_capacity(n);
        let mut inv_diag: Vec<f64> = Vec::with_capacity(n);

        for i in 0..n {
            let row_start = col_idx.len();
            a_values_row.clear();
            let mut diag_a = None;

            for idx in a.row_ptr[i]..a.row_ptr[i + 1] {
                let col = a.col_idx[idx];
                let value = a.values[idx];
                if col < i {
                    if value.abs() > 0.0 {
                        col_idx.push(col);
                        a_values_row.push(value);
                    }
                } else if col == i {
                    diag_a = Some(value);
                }
            }
            values.resize(row_start + a_values_row.len(), 0.0);

            let diag_a = diag_a?;
            if !diag_a.is_finite() || diag_a <= 0.0 {
                return None;
            }

            for pos in 0..a_values_row.len() {
                let col = col_idx[row_start + pos];
                let pivot = diag[col];
                let correction = lower_row_dot(
                    &col_idx[row_start..row_start + pos],
                    &values[row_start..row_start + pos],
                    &col_idx[row_ptr[col]..row_ptr[col + 1]],
                    &values[row_ptr[col]..row_ptr[col + 1]],
                );
                let entry = (a_values_row[pos] - correction) / pivot;
                if !entry.is_finite() {
                    return None;
                }
                values[row_start + pos] = entry;
            }

            let diag_correction: f64 = values[row_start..].iter().map(|v| v * v).sum();
            let mut diag_candidate = diag_a - diag_correction;
            let diag_floor = 1e-24_f64.max(diag_a.abs() * 1e-14);
            if !diag_candidate.is_finite() || diag_candidate <= diag_floor {
                // Local repair: keep this row's coupling for the rows below
                // it, but restore the full original diagonal so the pivot is
                // safely positive and well-scaled.
                diag_candidate = diag_a;
            }

            let pivot = diag_candidate.sqrt();
            diag.push(pivot);
            inv_diag.push(1.0 / pivot);
            row_ptr.push(col_idx.len());
        }

        Some(Self {
            row_ptr,
            col_idx,
            values,
            diag,
            inv_diag,
        })
    }

    fn apply(&self, r: &[f64], z: &mut [f64], scratch: &mut [f64]) {
        let n = self.diag.len();
        debug_assert_eq!(r.len(), n);
        debug_assert_eq!(z.len(), n);
        debug_assert_eq!(scratch.len(), n);

        // Forward solve L·y = r.
        for i in 0..n {
            let mut sum = r[i];
            for idx in self.row_ptr[i]..self.row_ptr[i + 1] {
                sum -= self.values[idx] * scratch[self.col_idx[idx]];
            }
            scratch[i] = sum * self.inv_diag[i];
        }

        // Backward solve Lᵀ·z = y.
        z.copy_from_slice(scratch);
        for i in (0..n).rev() {
            let solved = z[i] * self.inv_diag[i];
            z[i] = solved;
            for idx in self.row_ptr[i]..self.row_ptr[i + 1] {
                z[self.col_idx[idx]] -= self.values[idx] * solved;
            }
        }
    }
}

fn lower_row_dot(
    cols: &[usize],
    values: &[f64],
    other_cols: &[usize],
    other_values: &[f64],
) -> f64 {
    let mut lhs = 0;
    let mut rhs = 0;
    let mut sum = 0.0;
    while lhs < cols.len() && rhs < other_cols.len() {
        let lhs_col = cols[lhs];
        let rhs_col = other_cols[rhs];
        if lhs_col == rhs_col {
            sum += values[lhs] * other_values[rhs];
            lhs += 1;
            rhs += 1;
        } else if lhs_col < rhs_col {
            lhs += 1;
        } else {
            rhs += 1;
        }
    }
    sum
}

/// Preconditioned Conjugate Gradient solver for Ax = b.
///
/// Returns the best iterate at `max_iter`. Profiled callers (the generic field
/// API and tight motor solves) inspect `PcgProfile::max_iter_calls` and reject
/// an iteration-capped result at their contract boundary.
pub fn pcg_solve(a: &CsrMatrix, b: &[f64], max_iter: usize, tol: f64) -> Result<Vec<f64>, String> {
    pcg_solve_with_guess(a, b, max_iter, tol, None)
}

fn pcg_residual_check_interval() -> usize {
    std::env::var("MAGNETO2D_PCG_RESIDUAL_CHECK_INTERVAL")
        .ok()
        .and_then(|value| value.parse::<usize>().ok())
        .filter(|&value| value > 0)
        .unwrap_or(8)
}

/// Preconditioned Conjugate Gradient solver for Ax = b with an optional initial guess.
///
/// A good initial guess is especially valuable during nonlinear Picard iteration:
/// consecutive material updates perturb the stiffness matrix, but the vector
/// potential field usually changes smoothly. Reusing the previous A_z solution
/// avoids restarting every linear solve from zero.
pub fn pcg_solve_with_guess(
    a: &CsrMatrix,
    b: &[f64],
    max_iter: usize,
    tol: f64,
    initial_guess: Option<&[f64]>,
) -> Result<Vec<f64>, String> {
    pcg_solve_with_guess_inner(
        a,
        b,
        max_iter,
        tol,
        initial_guess,
        PcgOptions::from_env(),
        None,
    )
}

pub(crate) fn pcg_solve_with_guess_options_profiled(
    a: &CsrMatrix,
    b: &[f64],
    max_iter: usize,
    tol: f64,
    initial_guess: Option<&[f64]>,
    options: PcgOptions,
) -> Result<(Vec<f64>, PcgProfile), String> {
    let mut profile = PcgProfile {
        solve_calls: 1,
        ..PcgProfile::default()
    };
    let solution = pcg_solve_with_guess_inner(
        a,
        b,
        max_iter,
        tol,
        initial_guess,
        options,
        Some(&mut profile),
    )?;
    Ok((solution, profile))
}

pub(crate) fn pcg_solve_with_guess_options(
    a: &CsrMatrix,
    b: &[f64],
    max_iter: usize,
    tol: f64,
    initial_guess: Option<&[f64]>,
    options: PcgOptions,
) -> Result<Vec<f64>, String> {
    pcg_solve_with_guess_inner(a, b, max_iter, tol, initial_guess, options, None)
}

fn pcg_solve_with_guess_inner(
    a: &CsrMatrix,
    b: &[f64],
    max_iter: usize,
    tol: f64,
    initial_guess: Option<&[f64]>,
    options: PcgOptions,
    mut profile: Option<&mut PcgProfile>,
) -> Result<Vec<f64>, String> {
    let n = a.nrows;
    let execution = options.execution;
    let precond = record_pcg_timed(
        &mut profile,
        |profile, elapsed| profile.preconditioner_build_us += elapsed,
        || PcgPreconditioner::build(a, options.preconditioner),
    );

    let has_initial_guess = matches!(initial_guess, Some(guess) if guess.len() == n);
    let mut x = initial_guess
        .filter(|guess| guess.len() == n)
        .map(|guess| guess.to_vec())
        .unwrap_or_else(|| vec![0.0; n]);
    let mut r = b.to_vec();
    if has_initial_guess {
        let mut ax = vec![0.0; n];
        record_pcg_timed(
            &mut profile,
            |profile, elapsed| profile.spmv_us += elapsed,
            || a.mul_vec_with_execution(&x, &mut ax, execution),
        );
        for i in 0..n {
            r[i] = b[i] - ax[i];
        }
    }
    let mut z = vec![0.0; n]; // z = M^{-1} r
    let mut precond_scratch = vec![0.0; n];
    record_pcg_timed(
        &mut profile,
        |profile, elapsed| profile.preconditioner_apply_us += elapsed,
        || precond.apply_with_execution(&r, &mut z, &mut precond_scratch, execution),
    );
    let mut p = z.clone();
    let mut rz = record_pcg_timed(
        &mut profile,
        |profile, elapsed| profile.dot_us += elapsed,
        || dot_with_execution(&r, &z, execution),
    );

    let b_norm = record_pcg_timed(
        &mut profile,
        |profile, elapsed| profile.dot_us += elapsed,
        || dot_with_execution(b, b, execution).sqrt(),
    );
    if b_norm < 1e-30 {
        if let Some(profile) = profile.as_deref_mut() {
            profile.zero_rhs_calls += 1;
            profile.converged_calls += 1;
        }
        return Ok(x); // zero RHS → zero solution
    }

    let initial_r_norm = record_pcg_timed(
        &mut profile,
        |profile, elapsed| profile.residual_check_us += elapsed,
        || dot_with_execution(&r, &r, execution).sqrt(),
    );
    if initial_r_norm / b_norm < tol {
        if let Some(profile) = profile.as_deref_mut() {
            profile.converged_calls += 1;
        }
        eprintln!(
            "  pcg: converged in 0 iterations (rel_residual={:.2e})",
            initial_r_norm / b_norm
        );
        return Ok(x);
    }

    let mut ap = vec![0.0; n];
    let residual_check_interval = options.residual_check_interval.max(1);

    for iter in 0..max_iter {
        if let Some(profile) = profile.as_deref_mut() {
            profile.iterations += 1;
        }
        record_pcg_timed(
            &mut profile,
            |profile, elapsed| profile.spmv_us += elapsed,
            || a.mul_vec_with_execution(&p, &mut ap, execution),
        );
        let pap = record_pcg_timed(
            &mut profile,
            |profile, elapsed| profile.dot_us += elapsed,
            || dot_with_execution(&p, &ap, execution),
        );
        if pap.abs() < 1e-30 {
            break;
        }
        let alpha = rz / pap;

        record_pcg_timed(
            &mut profile,
            |profile, elapsed| profile.vector_update_us += elapsed,
            || update_solution_and_residual(&mut x, &p, &mut r, &ap, alpha, execution),
        );

        record_pcg_timed(
            &mut profile,
            |profile, elapsed| profile.preconditioner_apply_us += elapsed,
            || precond.apply_with_execution(&r, &mut z, &mut precond_scratch, execution),
        );
        let rz_new = record_pcg_timed(
            &mut profile,
            |profile, elapsed| profile.dot_us += elapsed,
            || dot_with_execution(&r, &z, execution),
        );
        if rz_new.abs() < 1e-60 {
            let r_norm = record_pcg_timed(
                &mut profile,
                |profile, elapsed| profile.residual_check_us += elapsed,
                || dot_with_execution(&r, &r, execution).sqrt(),
            );
            if let Some(profile) = profile.as_deref_mut() {
                profile.converged_calls += 1;
            }
            eprintln!(
                "  pcg: converged in {} iterations (rel_residual={:.2e})",
                iter + 1,
                r_norm / b_norm
            );
            return Ok(x);
        }

        if (iter + 1) % residual_check_interval == 0 || iter + 1 == max_iter {
            let r_norm = record_pcg_timed(
                &mut profile,
                |profile, elapsed| profile.residual_check_us += elapsed,
                || dot_with_execution(&r, &r, execution).sqrt(),
            );
            if r_norm / b_norm < tol {
                if let Some(profile) = profile.as_deref_mut() {
                    profile.converged_calls += 1;
                }
                eprintln!(
                    "  pcg: converged in {} iterations (rel_residual={:.2e})",
                    iter + 1,
                    r_norm / b_norm
                );
                return Ok(x);
            }
        }

        let beta = rz_new / rz;
        rz = rz_new;

        record_pcg_timed(
            &mut profile,
            |profile, elapsed| profile.vector_update_us += elapsed,
            || update_direction(&mut p, &z, beta, execution),
        );
    }

    let mut final_res = vec![0.0; n];
    record_pcg_timed(
        &mut profile,
        |profile, elapsed| profile.final_residual_us += elapsed,
        || a.mul_vec_with_execution(&x, &mut final_res, execution),
    );
    let res_norm = record_pcg_timed(
        &mut profile,
        |profile, elapsed| profile.final_residual_us += elapsed,
        || residual_norm_with_execution(&final_res, b, execution),
    );
    // The p·Ap breakdown exit lands here too; only an iterate that misses the
    // tolerance counts as capped.
    let converged = res_norm / b_norm < tol;
    if let Some(profile) = profile {
        if converged {
            profile.converged_calls += 1;
        } else {
            profile.max_iter_calls += 1;
        }
    }
    if converged {
        eprintln!(
            "  pcg: converged at breakdown (rel_residual={:.2e})",
            res_norm / b_norm
        );
    } else {
        eprintln!(
            "  pcg: max iterations reached (rel_residual={:.2e})",
            res_norm / b_norm
        );
    }
    Ok(x) // return best approximation
}

fn record_pcg_timed<T, F, R>(profile: &mut Option<&mut PcgProfile>, record: R, op: F) -> T
where
    F: FnOnce() -> T,
    R: FnOnce(&mut PcgProfile, u64),
{
    if profile.is_some() {
        let started = Instant::now();
        let result = op();
        if let Some(profile) = profile.as_deref_mut() {
            record(profile, started.elapsed().as_micros() as u64);
        }
        result
    } else {
        op()
    }
}

#[inline]
fn dot(a: &[f64], b: &[f64]) -> f64 {
    a.iter().zip(b.iter()).map(|(x, y)| x * y).sum()
}

#[inline]
fn dot_with_execution(a: &[f64], b: &[f64], execution: PcgExecution) -> f64 {
    debug_assert_eq!(a.len(), b.len());
    match execution {
        PcgExecution::Serial => dot(a, b),
        PcgExecution::Parallel => a.par_iter().zip(b.par_iter()).map(|(x, y)| x * y).sum(),
    }
}

fn update_solution_and_residual(
    x: &mut [f64],
    p: &[f64],
    r: &mut [f64],
    ap: &[f64],
    alpha: f64,
    execution: PcgExecution,
) {
    debug_assert_eq!(x.len(), p.len());
    debug_assert_eq!(r.len(), ap.len());
    debug_assert_eq!(x.len(), r.len());
    match execution {
        PcgExecution::Serial => {
            for i in 0..x.len() {
                x[i] += alpha * p[i];
                r[i] -= alpha * ap[i];
            }
        }
        PcgExecution::Parallel => x
            .par_iter_mut()
            .zip(r.par_iter_mut())
            .zip(p.par_iter().zip(ap.par_iter()))
            .for_each(|((xi, ri), (pi, api))| {
                *xi += alpha * *pi;
                *ri -= alpha * *api;
            }),
    }
}

fn update_direction(p: &mut [f64], z: &[f64], beta: f64, execution: PcgExecution) {
    debug_assert_eq!(p.len(), z.len());
    match execution {
        PcgExecution::Serial => {
            for i in 0..p.len() {
                p[i] = z[i] + beta * p[i];
            }
        }
        PcgExecution::Parallel => p.par_iter_mut().zip(z.par_iter()).for_each(|(pi, zi)| {
            *pi = *zi + beta * *pi;
        }),
    }
}

fn residual_norm_with_execution(lhs: &[f64], rhs: &[f64], execution: PcgExecution) -> f64 {
    debug_assert_eq!(lhs.len(), rhs.len());
    match execution {
        PcgExecution::Serial => lhs
            .iter()
            .zip(rhs.iter())
            .map(|(a, b)| (a - b).powi(2))
            .sum::<f64>()
            .sqrt(),
        PcgExecution::Parallel => lhs
            .par_iter()
            .zip(rhs.par_iter())
            .map(|(a, b)| (a - b).powi(2))
            .sum::<f64>()
            .sqrt(),
    }
}

fn truthy_env(name: &str) -> bool {
    std::env::var(name)
        .ok()
        .map(|value| {
            let normalized = value.trim().to_ascii_lowercase();
            !normalized.is_empty()
                && normalized != "0"
                && normalized != "false"
                && normalized != "no"
                && normalized != "off"
        })
        .unwrap_or(false)
}

// ─── Sparse direct Cholesky (faer LLT) ──────────────────────────────────────
//
// Alternative to PCG for the repeated solves inside a Picard/Newton loop:
// the stiffness pattern is fixed per mesh, so the symbolic factorization
// (elimination ordering + fill analysis) is computed once and every linear
// solve is a numeric refactor + two triangular solves, with no iteration
// count at all. Enabled via MAGNETO2D_LINEAR_SOLVER=direct; any failure
// (non-SPD numerics, unexpected pattern) falls back to PCG transparently.

/// Lazily-initialized per-pattern state for the faer direct solver. One of
/// these lives in `SolveMatrixPattern`, i.e. one per mesh per solve context,
/// shared across all Picard/Newton iterations at that rotor angle.
pub struct DirectCholeskyCache {
    state: OnceLock<Option<DirectCholeskySymbolic>>,
    symbolic_builds: AtomicU64,
    numeric_factorizations: AtomicU64,
    cache_hits: AtomicU64,
    pattern_mismatches: AtomicU64,
    pcg_fallbacks: AtomicU64,
}

impl Default for DirectCholeskyCache {
    fn default() -> Self {
        Self::new()
    }
}

#[derive(Debug, Clone, Copy, Default, Serialize, PartialEq, Eq)]
pub struct DirectCholeskyStats {
    pub symbolic_builds: u64,
    pub numeric_factorizations: u64,
    pub cache_hits: u64,
    pub pattern_mismatches: u64,
    pub pcg_fallbacks: u64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DirectCholeskyError {
    PatternMismatch,
}

struct DirectCholeskySymbolic {
    nrows: usize,
    ncols: usize,
    /// CSC pattern with row indices sorted within each column. Because the
    /// stiffness matrix is symmetric, the CSR arrays double as CSC arrays of
    /// the same matrix; faer additionally requires sorted indices, so this
    /// is a sorted copy of the assembly pattern.
    pattern: faer::sparse::SymbolicSparseColMat<usize>,
    /// Maps each slot of the sorted pattern back to the assembly CSR slot,
    /// so per-solve values can be gathered with one O(nnz) pass.
    value_gather: Vec<usize>,
    /// The cached symbolic factorization (ordering + fill structure).
    symbolic_llt: faer::sparse::linalg::solvers::SymbolicLlt<usize>,
}

impl DirectCholeskyCache {
    pub fn new() -> Self {
        Self {
            state: OnceLock::new(),
            symbolic_builds: AtomicU64::new(0),
            numeric_factorizations: AtomicU64::new(0),
            cache_hits: AtomicU64::new(0),
            pattern_mismatches: AtomicU64::new(0),
            pcg_fallbacks: AtomicU64::new(0),
        }
    }

    /// Attempt the checked direct solve used by prepared field systems.
    /// Returns `Ok(None)` when symbolic or numeric factorization is
    /// unavailable so the caller can fall back to PCG. A same-size or
    /// same-nnz matrix with different CSR structure is a typed mismatch,
    /// never a silent reuse of the cached value-gather map.
    pub fn solve_checked(
        &self,
        a: &CsrMatrix,
        b: &[f64],
    ) -> Result<Option<Vec<f64>>, DirectCholeskyError> {
        let state_was_initialized = self.state.get().is_some();
        let symbolic = self
            .state
            .get_or_init(|| {
                self.symbolic_builds.fetch_add(1, Ordering::Relaxed);
                let built = DirectCholeskySymbolic::build(a);
                if built.is_none() {
                    eprintln!(
                        "  direct_solver: symbolic Cholesky unavailable for this \
                         pattern; falling back to PCG"
                    );
                }
                built
            })
            .as_ref();
        let Some(symbolic) = symbolic else {
            self.pcg_fallbacks.fetch_add(1, Ordering::Relaxed);
            return Ok(None);
        };
        if state_was_initialized {
            self.cache_hits.fetch_add(1, Ordering::Relaxed);
        }
        if !symbolic.matches_pattern(a) {
            self.pattern_mismatches.fetch_add(1, Ordering::Relaxed);
            return Err(DirectCholeskyError::PatternMismatch);
        }
        self.numeric_factorizations.fetch_add(1, Ordering::Relaxed);
        let solution = symbolic.solve(a, b);
        if solution.is_none() {
            self.pcg_fallbacks.fetch_add(1, Ordering::Relaxed);
        }
        Ok(solution)
    }

    pub fn stats(&self) -> DirectCholeskyStats {
        DirectCholeskyStats {
            symbolic_builds: self.symbolic_builds.load(Ordering::Relaxed),
            numeric_factorizations: self.numeric_factorizations.load(Ordering::Relaxed),
            cache_hits: self.cache_hits.load(Ordering::Relaxed),
            pattern_mismatches: self.pattern_mismatches.load(Ordering::Relaxed),
            pcg_fallbacks: self.pcg_fallbacks.load(Ordering::Relaxed),
        }
    }
}

impl DirectCholeskySymbolic {
    fn build(a: &CsrMatrix) -> Option<Self> {
        if a.nrows != a.ncols || a.row_ptr.len() != a.nrows + 1 {
            return None;
        }
        let nnz = a.col_idx.len();

        // Sort indices within each row (== column of the symmetric CSC view)
        // and remember where each sorted slot came from.
        let mut sorted_idx: Vec<usize> = Vec::with_capacity(nnz);
        let mut value_gather: Vec<usize> = Vec::with_capacity(nnz);
        for row in 0..a.nrows {
            let start = a.row_ptr[row];
            let end = a.row_ptr[row + 1];
            let mut slots: Vec<usize> = (start..end).collect();
            slots.sort_unstable_by_key(|&slot| a.col_idx[slot]);
            // Duplicate indices within a row would break the CSC invariants.
            for pair in slots.windows(2) {
                if a.col_idx[pair[0]] == a.col_idx[pair[1]] {
                    return None;
                }
            }
            for slot in slots {
                sorted_idx.push(a.col_idx[slot]);
                value_gather.push(slot);
            }
        }

        let pattern = faer::sparse::SymbolicSparseColMat::new_checked(
            a.nrows,
            a.ncols,
            a.row_ptr.clone(),
            None,
            sorted_idx,
        );
        let symbolic_llt = faer::sparse::linalg::solvers::SymbolicLlt::try_new(
            pattern.as_ref(),
            faer::Side::Lower,
        )
        .ok()?;

        Some(Self {
            nrows: a.nrows,
            ncols: a.ncols,
            pattern,
            value_gather,
            symbolic_llt,
        })
    }

    fn matches_pattern(&self, a: &CsrMatrix) -> bool {
        let pattern = self.pattern.as_ref();
        self.nrows == a.nrows
            && self.ncols == a.ncols
            && pattern.col_ptr() == a.row_ptr
            && pattern.row_idx().len() == self.value_gather.len()
            && pattern.row_idx().iter().zip(self.value_gather.iter()).all(
                |(&expected_col, &original_slot)| {
                    a.col_idx.get(original_slot).copied() == Some(expected_col)
                },
            )
    }

    fn solve(&self, a: &CsrMatrix, b: &[f64]) -> Option<Vec<f64>> {
        use faer::linalg::solvers::Solve;

        if a.values.len() != self.value_gather.len() || b.len() != a.nrows {
            return None;
        }
        let values: Vec<f64> = self
            .value_gather
            .iter()
            .map(|&slot| a.values[slot])
            .collect();
        let mat = faer::sparse::SparseColMatRef::new(self.pattern.as_ref(), &values);
        let llt = faer::sparse::linalg::solvers::Llt::try_new_with_symbolic(
            self.symbolic_llt.clone(),
            mat,
            faer::Side::Lower,
        )
        .ok()?;

        let mut rhs = faer::Mat::<f64>::from_fn(b.len(), 1, |i, _| b[i]);
        llt.solve_in_place(rhs.as_mut());
        Some((0..b.len()).map(|i| rhs[(i, 0)]).collect())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_coo_to_csr_simple() {
        let mut coo = CooMatrix::new(3);
        // 2x2 identity + (0,0)=3 duplicate
        coo.add(0, 0, 2.0);
        coo.add(0, 0, 1.0); // duplicate → sum to 3
        coo.add(1, 1, 4.0);
        coo.add(2, 2, 5.0);
        coo.add(0, 1, 1.0);
        coo.add(1, 0, 1.0);

        let csr = coo.to_csr();
        let mut y = vec![0.0; 3];
        csr.mul_vec(&[1.0, 1.0, 1.0], &mut y);
        assert!((y[0] - 4.0).abs() < 1e-10); // 3*1 + 1*1
        assert!((y[1] - 5.0).abs() < 1e-10); // 1*1 + 4*1
        assert!((y[2] - 5.0).abs() < 1e-10); // 5*1
    }

    #[test]
    fn test_parallel_mul_vec_matches_serial() {
        let mut coo = CooMatrix::new(4);
        coo.add(0, 0, 4.0);
        coo.add(0, 1, 1.0);
        coo.add(1, 0, 1.0);
        coo.add(1, 1, 3.0);
        coo.add(1, 2, -1.0);
        coo.add(2, 1, -1.0);
        coo.add(2, 2, 2.0);
        coo.add(3, 3, 5.0);
        let csr = coo.to_csr();
        let x = [1.0, -2.0, 0.5, 3.0];
        let mut serial = vec![0.0; 4];
        let mut parallel = vec![0.0; 4];

        csr.mul_vec_serial(&x, &mut serial);
        csr.mul_vec_parallel(&x, &mut parallel);

        assert_eq!(serial, parallel);
    }

    #[test]
    fn test_parallel_dot_and_updates_match_serial() {
        let a = [1.0, -2.0, 3.5, 4.25];
        let b = [0.5, 6.0, -1.0, 2.0];
        assert_eq!(
            dot_with_execution(&a, &b, PcgExecution::Serial),
            dot_with_execution(&a, &b, PcgExecution::Parallel)
        );

        let mut x_serial = vec![1.0, 2.0, 3.0, 4.0];
        let mut x_parallel = x_serial.clone();
        let mut r_serial = vec![4.0, 3.0, 2.0, 1.0];
        let mut r_parallel = r_serial.clone();
        let p = [0.25, 0.5, 0.75, 1.0];
        let ap = [1.0, 1.25, 1.5, 1.75];

        update_solution_and_residual(
            &mut x_serial,
            &p,
            &mut r_serial,
            &ap,
            0.125,
            PcgExecution::Serial,
        );
        update_solution_and_residual(
            &mut x_parallel,
            &p,
            &mut r_parallel,
            &ap,
            0.125,
            PcgExecution::Parallel,
        );

        assert_eq!(x_serial, x_parallel);
        assert_eq!(r_serial, r_parallel);
    }

    #[test]
    fn test_pcg_solve_identity() {
        let mut coo = CooMatrix::new(3);
        coo.add(0, 0, 2.0);
        coo.add(1, 1, 3.0);
        coo.add(2, 2, 4.0);
        let csr = coo.to_csr();

        let b = vec![4.0, 9.0, 16.0];
        let x = pcg_solve(&csr, &b, 100, 1e-10).unwrap();
        assert!((x[0] - 2.0).abs() < 1e-8);
        assert!((x[1] - 3.0).abs() < 1e-8);
        assert!((x[2] - 4.0).abs() < 1e-8);
    }

    #[test]
    fn test_pcg_solve_with_initial_guess() {
        let mut coo = CooMatrix::new(3);
        coo.add(0, 0, 2.0);
        coo.add(1, 1, 3.0);
        coo.add(2, 2, 4.0);
        let csr = coo.to_csr();

        let b = vec![4.0, 9.0, 16.0];
        let exact = vec![2.0, 3.0, 4.0];
        let x = pcg_solve_with_guess(&csr, &b, 100, 1e-10, Some(&exact)).unwrap();
        assert!((x[0] - 2.0).abs() < 1e-8);
        assert!((x[1] - 3.0).abs() < 1e-8);
        assert!((x[2] - 4.0).abs() < 1e-8);
    }

    #[test]
    fn test_pcg_solve_coupled() {
        // [[4, 1], [1, 3]] * [x1, x2] = [1, 2]
        // Solution: x1 = 1/11, x2 = 7/11
        let mut coo = CooMatrix::new(2);
        coo.add(0, 0, 4.0);
        coo.add(0, 1, 1.0);
        coo.add(1, 0, 1.0);
        coo.add(1, 1, 3.0);
        let csr = coo.to_csr();

        let b = vec![1.0, 2.0];
        let x = pcg_solve(&csr, &b, 100, 1e-10).unwrap();
        assert!((x[0] - 1.0 / 11.0).abs() < 1e-8);
        assert!((x[1] - 7.0 / 11.0).abs() < 1e-8);
    }

    #[test]
    fn test_incomplete_cholesky_matches_coupled_spd_solve() {
        let mut coo = CooMatrix::new(2);
        coo.add(0, 0, 4.0);
        coo.add(0, 1, 1.0);
        coo.add(1, 0, 1.0);
        coo.add(1, 1, 3.0);
        let csr = coo.to_csr();
        let factor = IncompleteCholesky::factor(&csr).expect("2x2 SPD should factor");

        let r = vec![1.0, 2.0];
        let mut z = vec![0.0; 2];
        let mut scratch = vec![0.0; 2];
        factor.apply(&r, &mut z, &mut scratch);

        assert!((z[0] - 1.0 / 11.0).abs() < 1e-8);
        assert!((z[1] - 7.0 / 11.0).abs() < 1e-8);
    }

    #[test]
    fn test_direct_cholesky_matches_pcg_on_spd_system() {
        // 3x3 SPD with deliberately unsorted column order in one row to
        // exercise the sort+gather path.
        let mut coo = CooMatrix::new(3);
        coo.add(0, 0, 4.0);
        coo.add(0, 1, 1.0);
        coo.add(1, 1, 3.0);
        coo.add(1, 0, 1.0);
        coo.add(1, 2, 0.5);
        coo.add(2, 1, 0.5);
        coo.add(2, 2, 2.0);
        let csr = coo.to_csr();
        let b = vec![1.0, 2.0, 3.0];

        let cache = DirectCholeskyCache::new();
        let x_direct = cache
            .solve_checked(&csr, &b)
            .expect("SPD pattern must match")
            .expect("SPD system must factor");
        let x_pcg = pcg_solve(&csr, &b, 100, 1e-12).unwrap();
        for (d, p) in x_direct.iter().zip(x_pcg.iter()) {
            assert!((d - p).abs() < 1e-9, "direct={d} pcg={p}");
        }

        // Second solve with different values, same pattern: exercises the
        // cached-symbolic refactor path.
        let mut coo2 = CooMatrix::new(3);
        coo2.add(0, 0, 8.0);
        coo2.add(0, 1, 2.0);
        coo2.add(1, 1, 6.0);
        coo2.add(1, 0, 2.0);
        coo2.add(1, 2, 1.0);
        coo2.add(2, 1, 1.0);
        coo2.add(2, 2, 4.0);
        let csr2 = coo2.to_csr();
        let x2_direct = cache
            .solve_checked(&csr2, &b)
            .expect("refactor pattern must match")
            .expect("refactor must succeed");
        let x2_pcg = pcg_solve(&csr2, &b, 100, 1e-12).unwrap();
        for (d, p) in x2_direct.iter().zip(x2_pcg.iter()) {
            assert!((d - p).abs() < 1e-9, "refactor direct={d} pcg={p}");
        }
    }

    #[test]
    fn direct_cholesky_rejects_same_nnz_different_csr_pattern() {
        let first = CsrMatrix {
            nrows: 3,
            ncols: 3,
            row_ptr: vec![0, 2, 5, 7],
            col_idx: vec![0, 1, 0, 1, 2, 1, 2],
            values: vec![4.0, -1.0, -1.0, 4.0, -1.0, -1.0, 3.0],
        };
        let different = CsrMatrix {
            nrows: 3,
            ncols: 3,
            row_ptr: vec![0, 3, 5, 7],
            col_idx: vec![0, 1, 2, 0, 1, 0, 2],
            values: vec![4.0, -1.0, -0.5, -1.0, 4.0, -0.5, 3.0],
        };
        assert_eq!(first.values.len(), different.values.len());
        let cache = DirectCholeskyCache::new();
        assert!(cache
            .solve_checked(&first, &[1.0, 2.0, 3.0])
            .unwrap()
            .is_some());
        assert_eq!(
            cache.solve_checked(&different, &[1.0, 2.0, 3.0]),
            Err(DirectCholeskyError::PatternMismatch)
        );
        assert_eq!(
            cache.stats(),
            DirectCholeskyStats {
                symbolic_builds: 1,
                numeric_factorizations: 1,
                cache_hits: 1,
                pattern_mismatches: 1,
                pcg_fallbacks: 0,
            }
        );
    }

    #[test]
    fn test_incomplete_cholesky_rejects_missing_or_bad_diagonal() {
        // Non-positive diagonal is a structural failure: refuse to factor.
        let mut coo = CooMatrix::new(2);
        coo.add(0, 0, 1.0);
        coo.add(0, 1, 0.5);
        coo.add(1, 0, 0.5);
        coo.add(1, 1, -1.0);
        let csr = coo.to_csr();

        assert!(IncompleteCholesky::factor(&csr).is_none());
    }

    #[test]
    fn test_incomplete_cholesky_repairs_cancelled_pivot() {
        // Mimics an anti-periodic penalty pair on an unfavourable node
        // ordering: diag ≈ |off-diag| so the plain IC(0) pivot update
        // cancels to ~0. Local repair must keep the factorization alive
        // and produce a finite, SPD apply (positive diagonals ⇒ L·Lᵀ ≻ 0).
        let penalty = 1.0e10;
        let mut coo = CooMatrix::new(2);
        coo.add(0, 0, penalty);
        coo.add(0, 1, -penalty);
        coo.add(1, 0, -penalty);
        coo.add(1, 1, penalty);
        let csr = coo.to_csr();

        let factor = IncompleteCholesky::factor(&csr).expect("pivot repair must succeed");
        let r = vec![penalty, penalty];
        let mut z = vec![0.0; 2];
        let mut scratch = vec![0.0; 2];
        factor.apply(&r, &mut z, &mut scratch);
        assert!(z.iter().all(|v| v.is_finite()));
        // M⁻¹ must be SPD: rᵀ·M⁻¹·r > 0 for r ≠ 0.
        assert!(r.iter().zip(z.iter()).map(|(a, b)| a * b).sum::<f64>() > 0.0);
    }
}
