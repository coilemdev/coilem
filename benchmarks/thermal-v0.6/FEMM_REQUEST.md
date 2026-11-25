# Thermal conduction protocol 0.6.0-1: owner Windows FEMM request

> **Status:** the comparison has been run with FEMM 5.0 on macOS by
> `tools/check_thermal_conduction_femm.py`. Its results page and the bundles in
> `femm/` are kept in the private repository. The protocol now accepts FEMM 5
> as well as FEMM 4.2. The request below is kept as written for a FEMM 4.2 run
> on Windows.

This is a separate heat-flow protocol, not a change to ABCD 1.6.0. Registration
is `conduction-gates.json`; freeze its hash and exported request **before** the
Windows run. All six registered cases remain NOT_COMPARED until real reference
bundles arrive. Synthetic tests demonstrate the harness, not FEMM agreement.
Publish failures and mesh failures alongside passes. Do not tune bands to data.

The default candidate is now `surface_mean_v2`, following the
[analytical root-cause correction](ANALYTICAL_REDUCTION_FIX.md). It separates
tooth/yoke means from their surface temperatures and exports a new request
identity with thermal source hashes. Use `--candidate-model legacy_mean_paths_v1`
to reproduce an already-exported original request or judge its matching bundle.
An old-model bundle cannot be presented as a corrected-model comparison. The
registered geometry, sources, conductivities and acceptance bands are unchanged.

## Registered problems

Concentrated SPM 8p12s and distributed SPM 12p36s, each with copper-only,
iron-only, and combined heat. Fixture paths and SHA256 are pinned. Conductivities
are deliberately prescribed constants (slot 1, tooth/yoke 20 W/(m K)), engineering
assumptions shared by both codes. This does not validate homogenization or actual
material conductivity. Uniform generation is specified separately for each region
as Q/(total group area * stack length), in W/m3. Group watts are divided by area,
not by element count. Zero source in an iron-only winding is intentional.

Only winding and stator cross-section domains are solved. Use their exact IR
line/arc loops, including slot openings. The outer stator surface is fixed at
20 C (293.15 K in FEMM); every other exterior surface, including bore and slot
mouths, is adiabatic. Touching winding/steel and tooth/yoke interfaces are perfect
contacts. No liner, housing shell, contact resistance, axial loss, end turn,
convection, air domain, rotor or rotation. The boundary is an ideal fixed housing
interface. This isolates cross-section paths from M1's other assumptions.

## Export and collect

From the checkout (PYTHONPATH must name that checkout):

```
python -m tools.check_thermal_conduction --case spm_concentrated_combined --request-out thermal-request.json
```

Repeat for all IDs in the registration. The JSON includes exact region loops,
area, conductivity, source density, source heat, boundary, reduced-network
prediction, and a request hash. Import the loops into FEMM's **heat flow** problem;
use millimetres, planar depth equal to stack_length_mm, and constant isotropic
conductivity. Deduplicate shared edges and preserve arcs. Record the FEMM build,
mesh settings and SHA256 of the saved input, solution and raw output package.
Export the native region IDs too, so areas and temperatures can be audited.
A ready request is provided here; the Windows geometry adapter/run is owner work.
Choose a new request filename when changing the candidate; the exporter refuses
to overwrite a frozen request. Archive both the JSON and its source identity.

The [FEMM manual, heat-flow postprocessor section 3.8](https://www.femm.info/Archives/doc/manual.pdf)
defines `ho_blockintegral(0)` as the block mean temperature and
`ho_blockintegral(1)` as cross-section area. Select each winding/tooth/yoke region,
record both quantities, clear selection, repeat. Convert FEMM Kelvin to Celsius
and area to m2. Do not substitute label temperatures or unweighted node means.
Both sides of the harness use sum(area * mean temperature) / sum(area); the
lumped node is constant over its group area. Region areas must agree with the
request within 0.5%. The tolerance covers meshing; it does not permit a different
geometry. Use `regions` and `coarse_regions` arrays with the same group coverage.

Run a coarse mesh, then halve its characteristic size everywhere, with further
refinement at slot mouths and narrow teeth. Fine/coarse group means must differ
by at most max(1% of fine temperature rise, 0.2 K). Continue refinement if needed;
retain all results. A mesh failure is a FAIL, not missing evidence or a pass.

Bundle JSON:

```
{
  "case_id": "spm_concentrated_combined",
  "request_sha256": "hash from exported request",
  "solver": "FEMM 4.2 heat flow",
  "solver_build": "actual Windows build",
  "raw_artifact_sha256": "SHA256 of archived inputs/solutions/raw exports",
  "boundary_C": 20,
  "regions": [{"node": "winding", "area_m2": 0.001, "mean_temperature_C": 30}],
  "coarse_regions": [{"node": "winding", "area_m2": 0.001, "mean_temperature_C": 30.1}]
}
```

Numbers above illustrate the format only; include all real winding, tooth and
yoke regions (or audited area-weighted groups), never these example values.

```
python -m tools.check_thermal_conduction --case spm_concentrated_combined --bundle measured.json
```

## Frozen bands and interpretation

For each of winding, teeth and yoke compare the **temperature rise above the
fixed boundary**, with PASS error <= max(10% of reference rise, 2 K), YELLOW up
to twice that band, FAIL beyond. A reference near room temperature cannot gain
an artificially loose relative band from absolute Kelvin or Celsius values.
These are candidate engineering bands, not a published standard. A case takes
the worst node/mesh status. Missing bundle is NOT_COMPARED. No output becomes
physically qualified from this code-to-code comparison.

The corrected predicted paths use exact planar three-terminal tooth/yoke slabs
and IR aggregate areas, with an insulated bore and fixed outer surface. The
winding link retains the equal-wall-temperature mean reduction and distributes
its side heat at the tooth mean. Source-free transport between steel layers is
now represented explicitly; actual two-dimensional tooth/slot gradients and
the planar aggregate remain approximations. Iron-only/copper-only cases probe
those limits. The legacy model remains selectable for old requests. A failed
case requires correcting the reduction or narrowing support before claiming
conduction agreement. Do not quietly qualify M1 based on just the combined case.
FEMM agreement says nothing about convection, end windings, contacts, uncertain
conductivity/homogenization, hotspots, magnet heat or speed-dependent cooling.
