//! Imported triangular mesh data model for 2D motor cross-sections.
//!
//! Magneto2D no longer owns a product mesher. The backend generates solve
//! Gmsh mesh artifacts and passes them into this solver.

use serde::{Deserialize, Serialize};

/// A 2D triangular mesh with material region tags.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TriMesh {
    /// Node coordinates (x, y) in mm.
    pub nodes: Vec<[f64; 2]>,
    /// Triangle connectivity: 3 node indices per element.
    pub triangles: Vec<[usize; 3]>,
    /// Material region tag per triangle.
    pub regions: Vec<Region>,
    /// Boundary node indices (outer boundary, for Dirichlet BC).
    pub boundary_nodes: Vec<usize>,
    /// Pairs of nodes on sector edges: (node at θ=0, node at θ=total_span)
    /// at the same radius, for anti-periodic BC.
    pub sector_edge_pairs: Vec<(usize, usize)>,
    /// Mesh metadata.
    pub info: MeshInfo,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MeshInfo {
    pub num_nodes: usize,
    pub num_triangles: usize,
    pub pole_pitch_deg: f64,
    pub n_pole_pitches: u32,
    pub total_span_deg: f64,
    pub angular_divisions: usize,
    pub radial_rings: usize,
    pub mesh_density: String,
    pub radial_layers: Vec<String>,
    /// Actual mesh airgap inner boundary in mm. Optional for backward-compatible
    /// artifact migration; SPM legacy artifacts fall back to magnet_outer_radius_mm.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub airgap_inner_radius_mm: Option<f64>,
    /// Actual mesh airgap outer boundary in mm. Optional for backward-compatible
    /// artifact migration; SPM legacy artifacts fall back to stator_inner_radius_mm.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub airgap_outer_radius_mm: Option<f64>,
    /// Provenance for imported/generated meshes. None means an older artifact
    /// that predates explicit mesh-source metadata.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub mesh_source: Option<MeshSource>,
    /// Radial location of the rotor magnet outer surface in mm
    /// (physical airgap inner boundary).
    pub magnet_outer_radius_mm: f64,
    /// Magnet embrace as a fraction of pole pitch.
    #[serde(default = "default_magnet_embrace")]
    pub magnet_embrace: f64,
    /// Radial location of the stator bore in mm
    /// (physical airgap outer boundary).
    pub stator_inner_radius_mm: f64,
    /// Radial location of the stator slot-block outer boundary in mm
    /// (separates tooth/slot block from the return yoke).
    pub stator_slot_outer_radius_mm: f64,
    /// Radial location of the stator outer diameter in mm.
    pub stator_outer_radius_mm: f64,
    /// Present only for an outer rotor (outrunner), whose radii run the other
    /// way: the stator is inside, so the stator radii above no longer order
    /// bore < slots < yoke, and the mesh carries its exact Dirichlet nodes.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub outer_rotor: Option<OuterRotorMeshInfo>,
    /// Present only when the mesh is one repeating sector of the motor.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub sector: Option<SectorMeshInfo>,
}

/// One repeating sector of the motor, cut separately for stator and rotor.
///
/// The stator wedge starts at `stator_start_deg` and the rotor wedge at
/// `rotor_start_deg`; both span `total_span_deg`. They meet on the circle of
/// radius `mid_gap_radius_mm` in the air gap. `sector_edge_pairs` tie the cut
/// edges, and the non-overlapping arcs of that circle, one sector apart.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SectorMeshInfo {
    /// How many sectors make the full circle.
    pub repeats: u32,
    /// True when the next sector is the negative of this one.
    pub anti_periodic: bool,
    pub stator_start_deg: f64,
    pub rotor_start_deg: f64,
    pub mid_gap_radius_mm: f64,
}

impl MeshInfo {
    /// Angle where angular sampling of the modelled span starts [rad].
    pub fn sector_start_rad(&self) -> f64 {
        self.sector
            .as_ref()
            .map(|sector| sector.stator_start_deg.to_radians())
            .unwrap_or(0.0)
    }

    /// Global index of the first slot inside a sector mesh; 0 for a full circle.
    ///
    /// Slot `k` is centred on `k` slot pitches. The stator cut runs through
    /// the middle of a tooth, so the first slot sits half a pitch past it.
    pub fn first_slot_global(&self, slot_count: usize) -> usize {
        let Some(sector) = &self.sector else {
            return 0;
        };
        if slot_count == 0 {
            return 0;
        }
        let pitch = 2.0 * std::f64::consts::PI / slot_count as f64;
        let first = (sector.stator_start_deg.to_radians() / pitch + 0.5).round() as i64;
        first.rem_euclid(slot_count as i64) as usize
    }

    /// Global slot index of the `slot_local`-th modelled slot.
    pub fn slot_global(&self, slot_local: usize, slot_count: usize) -> usize {
        (self.first_slot_global(slot_count) + slot_local) % slot_count.max(1)
    }

    /// Index, among the modelled slots, of the slot at angle `theta_positive`.
    ///
    /// A full circle counts from the slot at angle zero. A sector counts from
    /// its own first slot, so its slots keep their true global identity, and
    /// with it their winding direction, wherever the sector lies.
    pub fn slot_local_from_theta(
        &self,
        theta_positive: f64,
        slot_pitch_rad: f64,
        total_slots_in_span: usize,
        slot_count: usize,
    ) -> usize {
        if self.sector.is_none() || slot_count == 0 {
            return crate::sources::slot_index_from_theta(
                theta_positive,
                slot_pitch_rad,
                total_slots_in_span,
            );
        }
        let global =
            crate::sources::slot_index_from_theta(theta_positive, slot_pitch_rad, slot_count);
        let local = (global + slot_count - self.first_slot_global(slot_count)) % slot_count;
        local.min(total_slots_in_span.saturating_sub(1))
    }

    /// Shift that starts a sector's contour samples at the first point of
    /// the full circle's sampling grid inside the sector [rad].
    ///
    /// The contour integrates features narrower than its spacing, such as the
    /// field at slot openings, so its value depends on where the samples fall
    /// against the slots. Using the full circle's own grid makes a sector
    /// integrate exactly the samples the full circle would.
    pub fn sector_grid_shift_rad(&self, spacing_rad: f64) -> f64 {
        if self.sector.is_none() || !(spacing_rad > 0.0) {
            return 0.0;
        }
        (self.sector_start_rad() / spacing_rad - 1e-9).ceil() * spacing_rad
    }

    /// Map a point of the full circle (metres) to the equivalent point inside
    /// the modelled sector, and the sign its potential carries there. A
    /// full-circle mesh returns the point unchanged.
    pub fn fold_point(&self, point_m: [f64; 2]) -> ([f64; 2], f64) {
        let Some(sector) = &self.sector else {
            return (point_m, 1.0);
        };
        let span = self.total_span_deg.to_radians();
        if !(span > 0.0) || sector.repeats < 2 {
            return (point_m, 1.0);
        }
        let radius = point_m[0].hypot(point_m[1]);
        let mid_radius = sector.mid_gap_radius_mm * 1e-3;
        // The mesh follows the mid-gap circle with chords, which lie inside
        // it: a point on the circle itself is covered by the outer half only,
        // so it belongs to that half's wedge. The stator is the outer half for
        // an inner rotor.
        let in_outer_half = radius >= mid_radius * (1.0 - 1e-9);
        let on_stator_side = in_outer_half != self.is_outer_rotor();
        let start = if on_stator_side {
            sector.stator_start_deg
        } else {
            sector.rotor_start_deg
        }
        .to_radians();
        let theta = point_m[1].atan2(point_m[0]);
        let offset = (theta - start).rem_euclid(2.0 * std::f64::consts::PI);
        let steps = (offset / span).floor();
        if steps == 0.0 {
            return (point_m, 1.0);
        }
        let (sin_a, cos_a) = (-steps * span).sin_cos();
        let folded = [
            point_m[0] * cos_a - point_m[1] * sin_a,
            point_m[0] * sin_a + point_m[1] * cos_a,
        ];
        let sign = if sector.anti_periodic && (steps as i64) % 2 != 0 {
            -1.0
        } else {
            1.0
        };
        (folded, sign)
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OuterRotorMeshInfo {
    /// Radius inside the stator teeth where tooth flux density is sampled.
    pub tooth_sample_radius_mm: f64,
    /// Radius inside the stator yoke where yoke flux density is sampled.
    pub yoke_sample_radius_mm: f64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AirgapBandSource {
    FromMesh,
    FromMagnetOuterFallback,
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct AirgapBand {
    pub inner_radius_mm: f64,
    pub outer_radius_mm: f64,
    pub source: AirgapBandSource,
}

impl AirgapBand {
    pub fn inner_radius_m(self) -> f64 {
        self.inner_radius_mm * 1.0e-3
    }

    pub fn outer_radius_m(self) -> f64 {
        self.outer_radius_mm * 1.0e-3
    }
}

impl MeshInfo {
    pub fn is_outer_rotor(&self) -> bool {
        self.outer_rotor.is_some()
    }

    pub fn airgap_band(&self) -> Option<AirgapBand> {
        let mesh_inner = self
            .airgap_inner_radius_mm
            .filter(|radius| radius.is_finite() && *radius > 0.0);
        let mesh_outer = self
            .airgap_outer_radius_mm
            .filter(|radius| radius.is_finite() && *radius > 0.0);
        if let (Some(inner_radius_mm), Some(outer_radius_mm)) = (mesh_inner, mesh_outer) {
            if outer_radius_mm > inner_radius_mm {
                return Some(AirgapBand {
                    inner_radius_mm,
                    outer_radius_mm,
                    source: AirgapBandSource::FromMesh,
                });
            }
        }

        let inner_radius_mm = self.magnet_outer_radius_mm;
        let outer_radius_mm = self.stator_inner_radius_mm;
        if inner_radius_mm.is_finite()
            && outer_radius_mm.is_finite()
            && inner_radius_mm > 0.0
            && outer_radius_mm > inner_radius_mm
        {
            Some(AirgapBand {
                inner_radius_mm,
                outer_radius_mm,
                source: AirgapBandSource::FromMagnetOuterFallback,
            })
        } else {
            None
        }
    }
}

fn default_magnet_embrace() -> f64 {
    1.0
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum MeshSource {
    Unknown,
    Native,
    Gmsh,
}

/// Material region for each triangle element.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum Region {
    RotorCore,
    Magnet,
    Airgap,
    StatorTooth,
    StatorYoke,
    SlotWinding,
    FluxBarrier,
    MagnetPocketAir,
}

#[cfg(test)]
mod sector_tests {
    use super::*;

    fn info(sector: Option<SectorMeshInfo>, span_deg: f64, outer_rotor: bool) -> MeshInfo {
        MeshInfo {
            num_nodes: 0,
            num_triangles: 0,
            pole_pitch_deg: 90.0,
            n_pole_pitches: 1,
            total_span_deg: span_deg,
            angular_divisions: 0,
            radial_rings: 0,
            mesh_density: "test".to_string(),
            radial_layers: Vec::new(),
            airgap_inner_radius_mm: None,
            airgap_outer_radius_mm: None,
            mesh_source: None,
            magnet_outer_radius_mm: 29.5,
            magnet_embrace: 0.8,
            stator_inner_radius_mm: 30.0,
            stator_slot_outer_radius_mm: 42.0,
            stator_outer_radius_mm: 50.0,
            outer_rotor: outer_rotor.then_some(OuterRotorMeshInfo {
                tooth_sample_radius_mm: 20.0,
                yoke_sample_radius_mm: 10.0,
            }),
            sector,
        }
    }

    fn quarter(anti_periodic: bool) -> SectorMeshInfo {
        SectorMeshInfo {
            repeats: 4,
            anti_periodic,
            stator_start_deg: -15.0,
            rotor_start_deg: -45.0,
            mid_gap_radius_mm: 29.75,
        }
    }

    fn polar(radius_mm: f64, angle_deg: f64) -> [f64; 2] {
        let angle = angle_deg.to_radians();
        [radius_mm * 1e-3 * angle.cos(), radius_mm * 1e-3 * angle.sin()]
    }

    fn assert_close(a: [f64; 2], b: [f64; 2]) {
        assert!((a[0] - b[0]).abs() < 1e-12 && (a[1] - b[1]).abs() < 1e-12, "{a:?} vs {b:?}");
    }

    #[test]
    fn a_full_circle_mesh_folds_nothing() {
        let full = info(None, 360.0, false);
        assert_eq!(full.fold_point(polar(40.0, 200.0)), (polar(40.0, 200.0), 1.0));
        assert_eq!(full.sector_start_rad(), 0.0);
        assert_eq!(full.sector_grid_shift_rad(0.5_f64.to_radians()), 0.0);
        assert_eq!(full.first_slot_global(12), 0);
        assert_eq!(full.slot_global(7, 12), 7);
    }

    #[test]
    fn stator_and_rotor_points_fold_into_their_own_wedges() {
        let sector = info(Some(quarter(true)), 90.0, false);
        // Stator side (outside the mid-gap circle): the wedge is [-15, 75) deg.
        let (point, sign) = sector.fold_point(polar(40.0, 10.0));
        assert_close(point, polar(40.0, 10.0));
        assert_eq!(sign, 1.0);
        let (point, sign) = sector.fold_point(polar(40.0, 100.0));
        assert_close(point, polar(40.0, 10.0));
        assert_eq!(sign, -1.0);
        let (point, sign) = sector.fold_point(polar(40.0, 190.0));
        assert_close(point, polar(40.0, 10.0));
        assert_eq!(sign, 1.0);
        // Rotor side: the wedge is [-45, 45) deg, so 60 deg is one sector on.
        let (point, sign) = sector.fold_point(polar(20.0, 60.0));
        assert_close(point, polar(20.0, -30.0));
        assert_eq!(sign, -1.0);
        // The same angle on the stator side is inside its wedge.
        assert_eq!(sector.fold_point(polar(40.0, 60.0)).1, 1.0);
        // A point on the mid-gap circle belongs to the outer half: the stator here.
        assert_eq!(sector.fold_point(polar(29.75, 60.0)).1, 1.0);
    }

    #[test]
    fn a_periodic_sector_keeps_the_sign_and_an_outer_rotor_swaps_the_sides() {
        let periodic = info(Some(quarter(false)), 90.0, false);
        assert_eq!(periodic.fold_point(polar(40.0, 100.0)).1, 1.0);

        // Outer rotor: the rotor is outside the mid-gap circle, wedge [-45, 45) deg.
        let outer = info(Some(quarter(true)), 90.0, true);
        let (point, sign) = outer.fold_point(polar(40.0, 60.0));
        assert_close(point, polar(40.0, -30.0));
        assert_eq!(sign, -1.0);
        // And the mid-gap circle itself goes with the rotor, the outer half.
        assert_eq!(outer.fold_point(polar(29.75, 60.0)).1, -1.0);
        assert_eq!(outer.fold_point(polar(20.0, 60.0)).1, 1.0);
    }

    #[test]
    fn sector_slots_keep_their_global_identity_wherever_the_wedge_lies() {
        let pitch = 30.0_f64.to_radians();
        // The wedge starts half a pitch before slot 0 and holds slots 0, 1, 2.
        let base = info(Some(quarter(true)), 90.0, false);
        assert_eq!(base.first_slot_global(12), 0);
        for slot in 0..3 {
            let theta = (slot as f64 * 30.0).to_radians();
            assert_eq!(base.slot_local_from_theta(theta, pitch, 3, 12), slot);
            assert_eq!(base.slot_global(slot, 12), slot);
        }
        // Slot 0 reaches below angle zero; callers pass that as a positive angle.
        assert_eq!(base.slot_local_from_theta(350.0_f64.to_radians(), pitch, 3, 12), 0);

        // Turned by five slot pitches it holds slots 5, 6, 7: slot 6 is not
        // "slot 0 again", which would give it slot 0's winding direction.
        let mut turned = quarter(true);
        turned.stator_start_deg += 150.0;
        turned.rotor_start_deg += 150.0;
        let turned = info(Some(turned), 90.0, false);
        assert_eq!(turned.first_slot_global(12), 5);
        assert_eq!(turned.slot_local_from_theta(180.0_f64.to_radians(), pitch, 3, 12), 1);
        assert_eq!(turned.slot_global(1, 12), 6);
        // A wedge that wraps past the last slot.
        let mut wrapped = quarter(true);
        wrapped.stator_start_deg = 315.0;
        let wrapped = info(Some(wrapped), 90.0, false);
        assert_eq!(wrapped.first_slot_global(12), 11);
        assert_eq!(wrapped.slot_local_from_theta(0.0, pitch, 3, 12), 1);
        assert_eq!(wrapped.slot_global(2, 12), 1);
    }

    #[test]
    fn sector_contour_samples_sit_on_the_full_circle_grid() {
        let spacing = 0.5_f64.to_radians();
        let sector = info(Some(quarter(true)), 90.0, false);
        // -15 deg is a grid line, so sampling starts there.
        assert!((sector.sector_grid_shift_rad(spacing) - (-15.0_f64).to_radians()).abs() < 1e-12);
        let mut odd = quarter(true);
        odd.stator_start_deg = -3.75;
        let odd = info(Some(odd), 45.0, false);
        // -3.75 deg lies between grid lines: start at the next one, -3.5 deg.
        assert!((odd.sector_grid_shift_rad(spacing) - (-3.5_f64).to_radians()).abs() < 1e-12);
    }
}
