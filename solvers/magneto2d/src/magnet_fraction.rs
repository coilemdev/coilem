//! Sub-element magnet area fraction for smooth rotor sweeps.
//!
//! With `fixed_mesh` rotation, the mesh is built once at rotor_angle = 0 and
//! reused across all rotor positions. Per-step the magnet/airgap region tag
//! for each triangle is recomputed by centroid (`rotated_rotor_regions`).
//! This is fast but discrete: as the rotor rotates, individual triangles
//! near the magnet embrace edges flip Magnet ↔ Airgap as a unit, and each
//! flip causes a small step change in the PM source term ∫ν(B_r × ∇φ)·dΩ.
//! The differentiated flux linkage dλ/dθ then has spikes locked to the
//! sample rate — visible as jagged dashed back-EMF curves in the compare UI.
//!
//! This module computes a smooth per-triangle "magnet fill fraction"
//! ∈ [0, 1] by clipping each magnet-band triangle against the rotated pole
//! wedges. The fraction is then used in `assemble_source` to scale the PM
//! contribution:
//!
//! ```text
//! f[a] += fraction · mat.nu · mat.br · rotated · area
//! ```
//!
//! As the rotor rotates by Δθ, the fraction transitions continuously from
//! 1.0 → 0.0 (or vice versa) for each border triangle, eliminating the step
//! changes in λ. dλ/dθ becomes smooth without any post-processing filter.
//!
//! Geometry notes:
//! - Inner/outer radial boundaries of the magnet band coincide with mesh
//!   ring edges in both the structured and spade meshers, so triangles do
//!   not straddle them. The only "soft" boundaries are the angular embrace
//!   cuts at pole_center ± half_embrace_rad.
//! - For each triangle in the magnet band, we identify the closest pole
//!   center and clip against that pole's two embrace edges using
//!   Sutherland-Hodgman against two half-planes (rays from origin).
//! - For triangles in the magnet band but far from any pole's wedge
//!   (i.e., entirely between two adjacent magnets), the closest-pole's
//!   wedge clip yields zero area → fraction = 0 → no PM source. Correct.
//! - For triangles entirely inside one pole's wedge, both clips pass all
//!   vertices → clipped area = triangle area → fraction = 1. Identical to
//!   the discrete classification.
//! - The closest-pole choice handles the wrap at θ = 0 / 2π naturally
//!   because we measure pole index in the rotor frame.
//!
//! Complexity: O(n_triangles_in_magnet_band) per rotor angle. Each clip is
//! ~10 floating point ops on a triangle → cheap relative to the FEM solve.

use std::f64::consts::PI;

use crate::mesh::{Region, TriMesh};
use crate::motor::MotorConfig;
use crate::solve::effective_magnet_embrace;

/// Compute the per-triangle magnet area fraction in [0, 1] for the given
/// rotor angle. Returns a vector of length `mesh.triangles.len()`.
///
/// Triangles outside the magnet radial band always get 0.0. Triangles fully
/// inside a pole wedge get 1.0. Border triangles get a fractional value
/// that varies smoothly with rotor angle.
///
/// The returned fractions are intended to multiply the PM source term
/// contribution in `assemble_source`. They do NOT modify region tags or
/// the stiffness matrix — μ_rel for the magnet (≈ 1.05 for NdFeB) is close
/// enough to airgap (1.0) that source-only blending captures ~95% of the
/// smoothing benefit at a fraction of the implementation complexity.
pub fn magnet_fill_fractions(
    mesh: &TriMesh,
    centroids: &[[f64; 2]],
    config: &MotorConfig,
    rotor_angle_rad: f64,
) -> Option<Vec<f64>> {
    let n_tri = mesh.triangles.len();
    let mut fractions = vec![0.0_f64; n_tri];

    let rotor_outer_r_m = config.rotor.od_mm * 0.5e-3;
    let magnet_outer_r_m = (config.rotor.od_mm * 0.5 + config.rotor.magnet_thickness_mm) * 1e-3;
    let pole_count = config.rotor.pole_count.max(1) as i64;
    let pole_pitch_rad = 2.0 * PI / pole_count as f64;
    let magnet_embrace = match effective_magnet_embrace(config) {
        Ok(value) => value.clamp(0.0, 1.0),
        Err(err) => {
            eprintln!("magneto2d: skipping SPM magnet-fill fractions: {err}");
            return None;
        }
    };
    let half_embrace_rad = 0.5 * magnet_embrace * pole_pitch_rad;

    if half_embrace_rad <= 0.0 {
        return None; // no magnets
    }

    for (idx, tri) in mesh.triangles.iter().enumerate() {
        // Quick reject: only blend triangles that are in the magnet
        // radial band. Other triangles keep their existing region tag and
        // the assembler skips them naturally (br = 0 for non-magnet
        // materials).
        let cx = centroids[idx][0];
        let cy = centroids[idx][1];
        let r_m = (cx * cx + cy * cy).sqrt();
        let in_band = r_m >= rotor_outer_r_m && r_m < magnet_outer_r_m;
        if !in_band {
            continue;
        }

        // Only triangles tagged Magnet or Airgap by the band classifier
        // can be candidates. (Some meshers — e.g. spade — may have a
        // RotorCore triangle whose centroid drifts into the magnet band
        // by floating-point noise; preserve its existing classification.)
        let region = mesh.regions[idx];
        if !matches!(region, Region::Magnet | Region::Airgap) {
            continue;
        }

        let [i, j, m] = *tri;
        let tri_verts = [mesh.nodes[i], mesh.nodes[j], mesh.nodes[m]];
        let tri_area = triangle_area(&tri_verts);
        if tri_area <= 0.0 {
            continue;
        }

        // Find nearest pole center in the rotated frame. The centroid
        // angle minus rotor_angle gives the rotor-frame angle; dividing
        // by pole_pitch and rounding yields the pole index.
        let theta = cy.atan2(cx);
        let rotor_frame_theta = (theta - rotor_angle_rad).rem_euclid(2.0 * PI);
        let pole_position = rotor_frame_theta / pole_pitch_rad;
        let nearest_pole = pole_position.round() as i64;

        // Pole center in world frame.
        let pole_center_world =
            (nearest_pole as f64 * pole_pitch_rad + rotor_angle_rad).rem_euclid(2.0 * PI);
        let theta_lo = pole_center_world - half_embrace_rad;
        let theta_hi = pole_center_world + half_embrace_rad;

        // Clip the triangle against the wedge {θ_lo ≤ arg(x, y) ≤ θ_hi}.
        // Each edge of the wedge is a ray from origin; the wedge is the
        // intersection of two half-planes:
        //   keep_lo: -x·sin(θ_lo) + y·cos(θ_lo) ≥ 0   (above lower ray)
        //   keep_hi: -x·sin(θ_hi) + y·cos(θ_hi) ≤ 0   (below upper ray)
        // For wedges that wrap across the 0/2π seam this still works
        // because we evaluate the two half-planes independently with
        // the world-frame angles directly.
        let mut polygon: Vec<[f64; 2]> = tri_verts.to_vec();
        polygon = clip_against_ray_above(&polygon, theta_lo);
        if polygon.is_empty() {
            continue;
        }
        polygon = clip_against_ray_below(&polygon, theta_hi);
        if polygon.is_empty() {
            continue;
        }

        let clipped_area = polygon_area(&polygon);
        let fraction = (clipped_area / tri_area).clamp(0.0, 1.0);
        fractions[idx] = fraction;
    }

    Some(fractions)
}

fn triangle_area(verts: &[[f64; 2]; 3]) -> f64 {
    let [x1, y1] = verts[0];
    let [x2, y2] = verts[1];
    let [x3, y3] = verts[2];
    ((x2 - x1) * (y3 - y1) - (x3 - x1) * (y2 - y1)).abs() * 0.5
}

fn polygon_area(polygon: &[[f64; 2]]) -> f64 {
    if polygon.len() < 3 {
        return 0.0;
    }
    let mut sum = 0.0;
    let n = polygon.len();
    for i in 0..n {
        let [x1, y1] = polygon[i];
        let [x2, y2] = polygon[(i + 1) % n];
        sum += x1 * y2 - x2 * y1;
    }
    sum.abs() * 0.5
}

/// Sutherland-Hodgman clip against the half-plane "above" the ray from
/// origin at angle θ. The ray's left normal is (-sin θ, cos θ); the
/// half-plane keeps points with -x·sin θ + y·cos θ ≥ 0.
fn clip_against_ray_above(polygon: &[[f64; 2]], theta: f64) -> Vec<[f64; 2]> {
    clip_half_plane(polygon, -theta.sin(), theta.cos(), 0.0, true)
}

/// Sutherland-Hodgman clip against the half-plane "below" the ray from
/// origin at angle θ. Same line as `clip_against_ray_above` but with the
/// inequality reversed.
fn clip_against_ray_below(polygon: &[[f64; 2]], theta: f64) -> Vec<[f64; 2]> {
    clip_half_plane(polygon, -theta.sin(), theta.cos(), 0.0, false)
}

/// Generic Sutherland-Hodgman against a single half-plane defined by
/// a·x + b·y ≥ c (when keep_above is true) or ≤ c (when false).
///
/// Returns the clipped polygon. Empty if all vertices fall outside.
fn clip_half_plane(
    polygon: &[[f64; 2]],
    a: f64,
    b: f64,
    c: f64,
    keep_above: bool,
) -> Vec<[f64; 2]> {
    if polygon.is_empty() {
        return Vec::new();
    }
    let inside = |p: &[f64; 2]| -> bool {
        let v = a * p[0] + b * p[1];
        if keep_above {
            v >= c - 1e-15
        } else {
            v <= c + 1e-15
        }
    };
    // Intersect segment p1->p2 with the half-plane boundary a·x + b·y = c.
    let intersect = |p1: &[f64; 2], p2: &[f64; 2]| -> [f64; 2] {
        let v1 = a * p1[0] + b * p1[1] - c;
        let v2 = a * p2[0] + b * p2[1] - c;
        let denom = v1 - v2;
        if denom.abs() < 1e-18 {
            // Parallel; bias to p2 (downstream vertex).
            return *p2;
        }
        let t = v1 / denom;
        [p1[0] + t * (p2[0] - p1[0]), p1[1] + t * (p2[1] - p1[1])]
    };

    let mut out = Vec::with_capacity(polygon.len() + 2);
    let n = polygon.len();
    for i in 0..n {
        let curr = &polygon[i];
        let next = &polygon[(i + 1) % n];
        let curr_in = inside(curr);
        let next_in = inside(next);
        match (curr_in, next_in) {
            (true, true) => out.push(*next),
            (true, false) => out.push(intersect(curr, next)),
            (false, true) => {
                out.push(intersect(curr, next));
                out.push(*next);
            }
            (false, false) => {}
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_tri(verts: [[f64; 2]; 3]) -> Vec<[f64; 2]> {
        verts.to_vec()
    }

    #[test]
    fn polygon_area_unit_triangle() {
        let tri = make_tri([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]]);
        assert!((polygon_area(&tri) - 0.5).abs() < 1e-12);
    }

    #[test]
    fn polygon_area_unit_square() {
        let sq = vec![[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]];
        assert!((polygon_area(&sq) - 1.0).abs() < 1e-12);
    }

    #[test]
    fn clip_keeps_polygon_when_entirely_inside() {
        // Triangle in upper half-plane y > 0; clip against y ≥ 0.
        let tri = make_tri([[0.0, 1.0], [1.0, 1.0], [0.5, 2.0]]);
        let clipped = clip_half_plane(&tri, 0.0, 1.0, 0.0, true);
        let area_in = polygon_area(&tri);
        let area_out = polygon_area(&clipped);
        assert!((area_in - area_out).abs() < 1e-12);
    }

    #[test]
    fn clip_drops_polygon_when_entirely_outside() {
        // Triangle in lower half-plane y < 0; clip against y ≥ 0.
        let tri = make_tri([[0.0, -1.0], [1.0, -1.0], [0.5, -2.0]]);
        let clipped = clip_half_plane(&tri, 0.0, 1.0, 0.0, true);
        assert!(clipped.is_empty() || polygon_area(&clipped) < 1e-12);
    }

    #[test]
    fn clip_straddling_triangle_returns_partial_area() {
        // Triangle (0,-1), (2,-1), (1,2). Clip against y ≥ 0.
        // Original area = 0.5 * 2 * 3 = 3.
        // Clipped to y ≥ 0 is a triangle with apex (1,2) and base segment
        // on y = 0 from x = 1/3 (left edge: y = (-1) + 3·t from (0,-1)
        // to (1,2) → y=0 at t=1/3, x=1/3) to x = 5/3 (right edge from
        // (2,-1) to (1,2) → t=1/3, x = 2 - 1/3 = 5/3). Base length 4/3,
        // height 2. Area = 4/3.
        let tri = make_tri([[0.0, -1.0], [2.0, -1.0], [1.0, 2.0]]);
        let clipped = clip_half_plane(&tri, 0.0, 1.0, 0.0, true);
        let expected = 4.0 / 3.0;
        let actual = polygon_area(&clipped);
        assert!(
            (actual - expected).abs() < 1e-10,
            "expected {expected}, got {actual}"
        );
    }

    #[test]
    fn wedge_clip_inside_pole() {
        // Triangle entirely inside a wedge centered on θ=0 with half-
        // angle π/4 (i.e., -45° to 45°). Triangle near +x axis.
        let tri = make_tri([[1.0, 0.0], [2.0, 0.1], [1.5, -0.1]]);
        let area_in = polygon_area(&tri);

        let lo = -PI / 4.0;
        let hi = PI / 4.0;
        let clipped1 = clip_against_ray_above(&tri, lo);
        let clipped2 = clip_against_ray_below(&clipped1, hi);
        let area_out = polygon_area(&clipped2);
        assert!((area_in - area_out).abs() < 1e-10);
    }

    #[test]
    fn wedge_clip_outside_pole() {
        // Triangle on -x axis, wedge centered on +x axis (θ=0).
        let tri = make_tri([[-1.0, 0.0], [-2.0, 0.1], [-1.5, -0.1]]);
        let lo = -PI / 4.0;
        let hi = PI / 4.0;
        let clipped1 = clip_against_ray_above(&tri, lo);
        let clipped2 = clip_against_ray_below(&clipped1, hi);
        assert!(polygon_area(&clipped2) < 1e-10);
    }
}
