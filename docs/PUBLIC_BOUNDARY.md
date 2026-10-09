# Public Runtime Boundary

The API rejects non-loopback `Host` headers, foreign or opaque (`null`)
browser origins, duplicate provenance headers, and originless cross-site browser
requests before invoking routes. CORS alone is not used as authorization.
The default trusted UI origins are HTTP `localhost` or `127.0.0.1` on ports
5173 and 4173. Command-line clients without browser headers remain supported.

For a separate local development port, set `COILEM_LOCAL_UI_ORIGIN` before
backend startup to one exact HTTP loopback origin, for example
`http://127.0.0.1:54173`. Remote hosts, wildcard origins, paths and missing ports
are rejected. Set `VITE_COILEM_LOCAL_API_BASE` in the matching frontend when
using a different API port. Keep the server bound to loopback.

This is a single-user local application. It does not authenticate other
processes running as the same OS user and is not a network service. Saved-run
paths and replay packages reject pre-existing symbolic links/junctions below
the configured root. Those checks are not isolation from another same-user
process racing filesystem operations. PDF report text is escaped; formula-like
CSV strings are exported as literal text while measured numeric values remain
numeric. Completed historical exports remain immutable.

The coilEM launch service is local-only and exposes exactly these paths:

- `GET /health`
- `GET /materials`
- `POST /materials/import`
- `GET /openapi.json`
- `POST /preview`
- `POST /halbach/preview`
- `POST /halbach/mesh-preview`
- `POST /halbach/solve/validate`
- `POST /halbach/solve`
- `POST /halbach/solve/stream`
- `POST /halbach/export/{export_kind}`
- `POST /halbach/linear/preview`
- `POST /halbach/linear/mesh-preview`
- `POST /halbach/linear/solve/validate`
- `POST /halbach/linear/solve`
- `POST /halbach/linear/solve/stream`
- `GET /runs`
- `GET /runs/{project_slug}/{run_id}`
- `GET /runs/{project_slug}/{run_id}/comparison`
- `DELETE /runs/{project_slug}/{run_id}`
- `POST /runs/{project_slug}/{run_id}/open-folder`
- `GET /runs/{project_slug}/{run_id}/report.pdf`
- `GET /runs/{project_slug}/{run_id}/report.csv`
- `GET /runs/{project_slug}/{run_id}/package.zip`
- `POST /solve`
- `POST /solve/cancel`
- `POST /solve/field-composition/armature`
- `POST /solve/field-composition/armature/stream`
- `GET /solve/field-frame/{artifact_id}`
- `GET /solve/playback-frame/{artifact_id}`
- `POST /solve/stream`
- `POST /solve/validate`
- `POST /solver/mesh-preview`
- `GET /tutorials/follow-the-flux/solve`
- `GET /tutorials/airgap-tax/solve`
- `GET /tutorials/chapter-1-capstone/solve`
- `GET /tutorials/current-field/solve`
- `GET /tutorials/iron-saturation/solve`
- `GET /tutorials/field-force/solve`
- `GET /tutorials/field-force/wire-only/solve`
- `GET /tutorials/field-force/magnet-only/solve`
- `GET /tutorials/field-force/motor/solve`
- `GET /tutorials/iron-saturation/spm-tooth/solve`
- `GET /tutorials/iron-saturation/tooth/solve`
- `GET /tutorials/rotating-field/sweep`
- `GET /tutorials/rotating-field/motor-sweep`
- `GET /tutorials/rotating-field/motor-geometry`
- `GET /tutorials/three-phase-motor/sweep`
- `GET /tutorials/three-phase-motor/geometry`
- `GET /tutorials/rotor-chase/solve`
- `GET /tutorials/lesson-1/field-composition/armature`
- `GET /tutorials/lesson-1/field-composition/pm`
- `GET /tutorials/lesson-1/mesh-preview`
- `GET /tutorials/lesson-1/solve/stream`

The `/tutorials/*` routes serve the ten lessons. They solve small self-contained
teaching fixtures (magnet and steel return path, airgap reluctance, conductor
field, iron saturation, Lorentz force, rotating two- and three-phase fields,
and rotor chase) meshed with Gmsh and solved by the same local Magneto2D core.
The Lesson 1 routes run the 2p/6s SPM teaching motor: a Gmsh mesh preview, a
streamed 0-360 degree loaded torque sweep, and exact source-separated field
sweeps for the armature (stator-only, with magnet remanence disabled) and the
permanent magnets (rotor-only, with phase current disabled). They share the
single-solve claim and the same artifact sanitization as the public solve
surface. `POST /solve/cancel` stops the streamed loaded sweep.

The release request policy accepts Magneto2D with native Gmsh meshes. With
`COILEM_ENABLE_ELMER` unset, it skips Elmer discovery, hides Elmer in the UI,
and rejects direct Elmer requests. Setting `COILEM_ENABLE_ELMER=1` before
startup enables development/testing discovery of a separately installed Elmer
26.2 runtime; it does not expand the 0.2.0 release claim. The policy never
substitutes solvers automatically. It rejects FEMM selection, non-native mesh
sources, thermal requests, and internal debug diagnostics. The service binds to
`127.0.0.1`; the TypeScript client accepts only loopback API hosts. Completed
solves package actual solved positions into
a generic `coilem.field_playback.v2` layered-WebP manifest while retaining one
exact numerical snapshot. The v2 timeline supports angle, time, phase, and
instructional-step sequences; its catalogs use content-defined composition and
layer IDs with semantic roles. Existing v1 manifests remain readable through
the frontend compatibility adapter. See `docs/FIELD_PLAYBACK_V2.md`. The image
route serves only those local WebP layers; the numerical
field-frame route remains the format fallback and inspection path. The
composition route computes an exact Br=0 stator-current sweep for Magneto2D
results; PM-only frames come from the normal Magneto2D solve's exact
zero-current sweep. When the testing override is enabled, Elmer result
visualization remains resultant-field only.

Completed public solves are published to the local solve workspace only after
the project, resolved request, material/build provenance, result, artifacts,
and report exports are durable. The `/runs` routes load immutable run evidence,
serve its existing PDF/CSV/replay exports, retrieve a compact comparison record,
reveal its local folder, or delete one explicitly confirmed run. The run list
reports storage usage and each record's size/status; deletion returns refreshed
storage totals. Loading, comparing, or downloading a run never starts a solver,
and completed runs are never silently pruned.

The visual application is rooted at `frontend/src/public/index.html` and
`frontend/src/public/main.tsx`. Its source/import audit recursively permits
only that directory plus the explicitly allowlisted landing preview and two
shared style sheets. It screens every allowed source and the production bundle
for excluded product surfaces. Development and preview use only
`127.0.0.1:5173` and `127.0.0.1:4173` by default, with their `localhost`
equivalents and the explicit loopback override described above.

The landing preview's compact geometry, mesh, field, and report assets are
self-authored outputs generated from the included 8-pole/12-slot example with
Magneto2D and Gmsh. Their source and solver metadata are embedded in the JSON
files. They are presentation source assets, not external reference data.

Cloud backends/workers, databases/migrations, identity, billing/quota,
administration/support, telemetry, private solver implementations, private
reports, unreviewed material curves, and generated build outputs are excluded
by the snapshot allowlist. The built-in material table is the reproducible
BSD-attributed `materials/electrical-steel/M350-50A.csv` model. The frontend also
includes an explicitly synthetic custom-steel CSV for demonstrating import;
it is not measured supplier data.
Elmer executable binaries and libraries are also excluded; the adapter invokes
only a user-installed runtime through local subprocesses and files.

Internal plans, sprint records, stories, roadmaps, and backlogs are not part of
the public source snapshot. Published material assumptions and limitations are
documented in `MATERIALS.md`.
