# Cylindrical Halbach array

coilEM includes a non-motor magnetic-field workspace for designing and solving
an internal-field cylindrical Halbach array. It uses the same production
generic Magneto2D field core as the lower-level
[`magnetostatic_problem` interface](GENERIC_MAGNETOSTATIC.md).

## V1 support boundary

V1 models:

- a full 360-degree x-y cross-section;
- an air-filled bore and surrounding air;
- 4 through 64 annular-wedge permanent-magnet segments, including odd counts;
- optional angular gaps;
- an internal-field dipole (`p = 1`);
- catalog or custom linear-recoil permanent magnets; and
- a zero-vector-potential circular outer boundary.

The field solve is two-dimensional and assumes infinite axial length. The
configured axial length is used only to extrude the 3D design view, calculate
magnet volume and mass, and scale explicitly labeled extruded-2D energy.
Every report and export carries this permanent limitation:

> 2D cross-section extruded over the design length — axial end effects are not included.

V1 does not solve axial end leakage, a finite 3D field, higher multipoles,
yokes, coils, motion, optimization, thermal coupling, eddy currents, or
hysteresis.

## Start a design

On the landing page, open **Magnetic field applications**, then choose
**Cylindrical Halbach array**. This opens its own Design → Solve → Report
workspace without changing the SPM/IPM motor topology flow.

The Design stage has five groups:

1. **Cylinder geometry** — bore and outer diameters, axial length, segment
   count, angular gap, and seam rotation.
2. **Field pattern** — the fixed internal dipole, requested positive-CCW field
   direction, and magnetization-arrow visibility.
3. **Magnet material** — catalog/custom input, temperature, and resolved
   material summary.
4. **Sample region** — bore ROI and external leakage-probe radii.
5. **Advanced geometry** — quality and outer-boundary controls plus the fixed
   v1 boundary.

The 2D view shows every segment, its remanence arrow, the requested bore-field
direction, ROI, and leakage circle. The 3D view extrudes the same wedges and
supports orbit, fit, cutaway, radial explode, and synchronized segment
selection. A solved 3D view always says **2D field extrusion** and does not
invent axial curvature.

## Magnetization convention

Angles are positive counter-clockwise from +x. For segment `i`,

```text
pitch   = 360 / segment_count
theta_i = segment_start_angle + (i + 0.5) * pitch
alpha_i = 2 * theta_i - field_direction
Br_i    = Br(T) * [cos(alpha_i), sin(alpha_i)]
```

The minus sign makes a positive-CCW requested field produce a positive-CCW bore
field while physical seam rotation remains independent. Rotation-covariance
tests cover 0°, 30°, and 90°.

## Configuration example

The schema is `schemas/v1/halbach_array_config.schema.json`; unknown properties
are rejected. A canonical input is:

```json
{
  "kind": "halbach_array_config",
  "version": "1.0",
  "units": {"length": "mm", "angle": "deg"},
  "geometry": {
    "inner_radius": 25.0,
    "outer_radius": 50.0,
    "axial_length": 100.0,
    "segment_count": 16,
    "segment_gap_angle": 0.0,
    "segment_start_angle": 0.0
  },
  "array": {
    "field_mode": "internal",
    "multipole_order": 1,
    "field_direction": 0.0
  },
  "magnet": {
    "source": "catalog",
    "grade": "N42",
    "temperature_c": 20.0
  },
  "sample_region": {
    "radius": 20.0,
    "radial_samples": 31,
    "angular_samples": 96,
    "leakage_probe_radius": 75.0
  },
  "solve": {
    "quality": "standard",
    "mesh": {
      "density": "normal",
      "outer_boundary_radius_factor": 4.0,
      "minimum_elements_across_magnet": 6,
      "corner_refinement": true
    },
    "linear": {
      "solver": "direct",
      "tolerance": 1e-8,
      "max_iterations": 5000
    }
  }
}
```

The complete catalog and custom examples are under `schemas/v1/examples/`.

## Material semantics

Catalog Br and relative permeability values use the documented public magnet
models. Br(T) is independently derated from its reference temperature. The
legacy catalog coercivity field does not identify normal coercivity versus
intrinsic coercivity unambiguously, so every current catalog grade is audited
as `unknown`: its value is retained as metadata but cannot produce a
demagnetization margin.

A custom material may provide `intrinsic_coercivity_a_per_m`; only that
explicit intrinsic quantity is margin-eligible. Optional `alpha_br_per_k` and
`alpha_hcj_per_k` coefficients are applied independently and copied, with
reference temperatures and source notes, into report provenance. Missing
density disables mass but not volume.

Reverse-field output is always labeled **screening diagnostic — not a
demagnetization certification**. The 99th percentile is the headline because
the pointwise maximum is mesh-sensitive.

## Mesh and solve

The Halbach adapter creates a conforming first-order Gmsh mesh with physical
groups for the bore, every magnet, every optional gap, exterior air, and the
outer boundary. Application-neutral feature tags control bore, corner, gap,
interface, and far-field sizing. No segment index controls mesh density.

Every triangle maps to exactly one material/source record. The adapter then
produces a strict, replayable `magnetostatic_problem` v1 document with SI
remanence vectors and its SHA-256. The generic core remains unaware of Halbach
geometry, catalog, metrics, or UX.

The Solve stage can generate a mesh preview and streams these progress stages:

```text
Validating design
Building cross-section
Generating Gmsh mesh
Assigning segment magnetization
Solving Magneto2D field
Sampling bore and leakage fields
Preparing report
```

Quick, standard, and fine presets change mesh resolution without changing the
physics contract. The report retains Gmsh CAD/mesh time, generic preparation,
assembly, linear solution, recovery, application postprocessing, total time,
and peak process memory separately.

## Results and exports

The Report stage leads with:

- mean bore field and direction;
- direction error and ROI uniformity;
- external leakage and leakage-to-bore ratio;
- magnet volume and optional mass;
- analytical continuous and segmented estimates;
- reverse-field screening;
- timing and material/artifact provenance; and
- the model-fidelity notice.

The 2D result viewer provides `|B|`, the requested-direction and transverse
components, `A_z`, contours, field lines, and vectors.

Downloads include:

- `.openem` project input;
- Halbach solution-report JSON;
- replayable generic problem JSON;
- generic field-solution JSON;
- bore/leakage sample CSV;
- SVG and PNG field/design images; and
- PDF report.

Halbach project files use:

```json
{
  "openem_schema_version": 3,
  "project_kind": "halbach_array",
  "halbach_config": {"kind": "halbach_array_config", "version": "1.0"}
}
```

For old project files, an absent `project_kind` still means `motor`.

## Local API

| Route | Purpose |
| --- | --- |
| `POST /halbach/preview` | Geometry, resolved material, and design health |
| `POST /halbach/mesh-preview` | Mesh QA, groups, and problem hash |
| `POST /halbach/solve/validate` | Field-addressable validation and warnings |
| `POST /halbach/solve/stream` | Progress SSE followed by the report |
| `POST /halbach/solve` | Synchronous report |
| `POST /halbach/export/{kind}` | Report/problem/field JSON, CSV, SVG, or PDF |

`GET /health` advertises `capabilities.halbach_array_2d`.

## Validation evidence

The release gates include:

- strict schema examples and unknown-field rejection;
- area closure, CCW loops, odd/even counts, gaps, physical groups, neutral
  feature tags, and one-to-one triangle ownership;
- analytical 8-, 16-, and 32-segment fixtures;
- rotation covariance, scale invariance, and Br linearity;
- mesh and outer-boundary convergence;
- independent reference comparisons when the reference solver is available;
- unchanged motor project compatibility corpus and generic-field tests; and
- public snapshot, boundary, UI-contract, bundle, and runtime smoke gates.

Measured canonical values and release-machine timing are published with each
release rather than presented as universal performance guarantees.
