# Halbach arrays

coilEM includes a non-motor magnetic-field workspace for designing and solving
an internal-field cylindrical Halbach array or a finite linear array. Both use the same
generic Magneto2D field core as the lower-level
[`magnetostatic_problem` interface](GENERIC_MAGNETOSTATIC.md).
Both workflows are experimental; the available regression checks do not
establish release-qualified Halbach accuracy.

## Cylindrical V1 support boundary

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
The Halbach report, sample CSV, design images, and PDF carry this permanent limitation:

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
Peak-memory measurement is best-effort and may be unavailable on the host.
Fine quality also solves an enlarged outer boundary and records sensitivity;
quick and standard runs do not perform that extra solve.

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

- `.coilem` project input (legacy `.openem` files also open);
- Halbach solution-report JSON;
- replayable generic problem JSON;
- generic field-solution JSON;
- bore/leakage sample CSV;
- SVG and PNG design diagrams with magnetization arrows; and
- PDF report.

The SVG/PNG diagrams show geometry and magnetization, without solved-field
heatmaps or contours. The problem and generic field JSON exports use their
application-neutral schemas; retain the Halbach report alongside them for the
model notice and application metrics. Downloads are generated from the report
in the current session. Halbach solves do not enter motor saved-run history.

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
| `POST /halbach/export/{export_kind}` | Report/problem/field JSON, CSV, design SVG/PNG, or PDF |

`GET /health` advertises `capabilities.halbach_array_2d`.

## Linear Halbach workflow

In the Halbach Design workspace, select **Linear**. The included N42 example
has four periods, four rectangular magnets per period, 10 mm magnet width and
height, zero gaps, and 100 mm out-of-plane depth. It uses a 5 mm probe offset
and excludes one period at each end from the headline metrics.

The implemented v1 boundary includes:

- 1–16 periods, with four blocks per period;
- positive-y or negative-y strong-side selection and magnetization phase;
- non-negative gaps smaller than the block width;
- catalog or custom linear-recoil magnets;
- centered working-side and weak-side probe lines; and
- quick, standard, fine, and custom mesh/solve settings.

The wavelength is `4 * (block_width + block_gap)`. Edge exclusion must leave
at least one complete period, and probe lines must remain inside the modeled
outer boundary. Fine quality performs an enlarged-boundary sensitivity solve.

The Report stage shows working-line RMS/mean/peak field and ripple, weak-side
RMS field, leakage and suppression ratios, magnet volume, optional mass, and
timing/provenance. The solve resolves finite-array end fringing in the x-y
plane. Out-of-plane depth scales extrusion, volume, mass, and extruded energy;
out-of-plane end effects are not modeled. The 3D view is labeled:

> 2D Magneto2D field extruded for visualization · not a 3D FEM result

Save/reopen a `.coilem` design with `project_kind = linear_halbach_array` and
`halbach_config.kind = linear_halbach_array_config`. The linear UI keeps the
solved report in the browser session and currently offers design-file downloads
only. The cylindrical report/PDF/CSV/image exporter accepts cylindrical reports.

| Route | Purpose |
| --- | --- |
| `POST /halbach/linear/preview` | Geometry, resolved material, and design health |
| `POST /halbach/linear/mesh-preview` | Mesh QA and generic problem hash |
| `POST /halbach/linear/solve/validate` | Validation and warnings |
| `POST /halbach/linear/solve/stream` | Progress SSE followed by the report |
| `POST /halbach/linear/solve` | Synchronous report |

The configuration, report schema, and example are under `schemas/v1/`:
[`linear_halbach_array_config.schema.json`](../schemas/v1/linear_halbach_array_config.schema.json),
[`linear_halbach_solution_report.schema.json`](../schemas/v1/linear_halbach_solution_report.schema.json),
and [`linear_halbach_array_4_period.json`](../schemas/v1/examples/linear_halbach_array_4_period.json).

## Verification scope

The shipped cylindrical regression tests cover:

- strict schema examples and unknown-field rejection;
- area closure, CCW loops, odd/even counts, gaps, physical groups, neutral
  feature tags, and one-to-one triangle ownership;
- analytical 8-, 16-, and 32-segment fixtures;
- rotation covariance, scale invariance, and Br linearity;
- mesh and outer-boundary convergence;
- strict report provenance and retained generic problem hashes.

Linear tests cover configuration, geometry and meshing, an independent
rectangular-magnet analytical oracle, strong-side selection, and report/API
contracts. Solver tests require Gmsh and the built native binary and may skip
when those are unavailable. Public snapshot, boundary, and frontend contract
checks also include these workspaces.

Independent external-solver comparisons and final-candidate Halbach numerical
qualification are not recorded in this checkout. Per-run timings and analytical
estimates are diagnostics, not release-machine performance guarantees. See
[Validation](VALIDATION.md) for the separate motor qualification requirements.
