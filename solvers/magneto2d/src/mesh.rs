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
