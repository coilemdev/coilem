# Optional Elmer FEM solver

coilEM contains an adapter for a separately installed Elmer FEM runtime as an
opt-in development and testing alternative to Magneto2D. Elmer is not part of
the coilEM 0.2.0 release claim. It is disabled, hidden, and not probed by
default, and is never downloaded, bundled, linked, or selected automatically.
The public Python environment includes `meshio`, which reads Elmer's VTU
field-result files after the override is deliberately enabled.

## Detection and selection

The adapter accepts Elmer 26.2. Set `COILEM_ENABLE_ELMER=1` before starting
`backend.public_main`; otherwise discovery is skipped, the solver selector
stays hidden, and direct Elmer requests are rejected. When the override is
enabled, discovery selects both executable files as follows:

1. `COILEM_ELMER_HOME`, when set; it searches `bin` and then the supplied
   directory itself for `ElmerSolver` and `ElmerGrid`;
2. the conventional user-local directory
   `~/.local/openem-elmer/26.2/bin`; and
3. `ElmerSolver` and `ElmerGrid` on `PATH`.

An explicit home pins discovery to that directory. If either binary is found
in the conventional directory, that directory is also pinned; a missing
partner is reported rather than combined with a binary from `PATH`.

Both programs must report release 26.2. The local `/health` response exposes
availability, qualification, versions, platform, and an actionable reason.
Dedicated executable-path and hash fields are omitted. Discovery failure
reasons can include the configured installation directory. The Solve screen uses that capability:

- **Magneto2D** remains the default;
- **Elmer FEM** is enabled only when the override is set and discovery succeeds;
  and
- with the override set, a missing or unqualified runtime leaves Elmer visible
  but disabled with an actionable reason.

For development diagnostics, `COILEM_ELMER_ALLOW_UNQUALIFIED=1` bypasses the
version qualification check. The capability's `qualified` flag then reflects
that override, not independently validated accuracy. It does not qualify the
runtime for release.

Changing solver does not reuse or overwrite a previous result. Every solve is
stored as a new immutable run. The launch comparison screen intentionally lists
only completed Magneto2D runs and makes no cross-solver parity claim.

To inspect discovery from the repository environment:

```bash
python -c "from backend.elmer import discover_elmer; print(discover_elmer().health_payload())"
```

## Installing the qualified runtime

Use the official Elmer build instructions for your platform and install the
unmodified 26.2 release. A user-local macOS/Linux build can use the conventional
install prefix above:

```bash
git clone --depth 1 --branch release-26.2 \
  https://github.com/ElmerCSC/elmerfem.git /tmp/coilem-elmer-src
cmake -S /tmp/coilem-elmer-src -B /tmp/coilem-elmer-build \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_INSTALL_PREFIX="$HOME/.local/openem-elmer/26.2" \
  -DWITH_ELMERGUI=OFF -DWITH_MPI=OFF -DWITH_OpenMP=OFF -DWITH_Mumps=OFF
cmake --build /tmp/coilem-elmer-build --parallel
cmake --install /tmp/coilem-elmer-build
```

This is an example build shape, not a replacement for Elmer's platform build
documentation. The adapter's qualified profile uses a serial direct UMFPACK
solve per rotor position. Independent positions may run concurrently.

Successful raw Elmer case directories are deleted by default. Failed cases are
kept under the OS temporary directory and pruned to the ten most recent runs.
For local diagnostics, set `COILEM_ELMER_RETAIN_ARTIFACTS=1` before starting
the backend to retain successful meshes, SIF files, VTUs, and logs as well.
`COILEM_ELMER_RUN_ROOT` selects a different raw-case root; these cases remain
subject to the rolling retention limit. `COILEM_ELMER_ANGLE_WORKERS` sets a
positive worker count capped at 16 and the number of positions. The adaptive
default uses at most half the logical CPUs, capped at four workers.

## Development adapter boundary

The adapter can exercise full-machine 2D radial-flux SPM and native-Gmsh IPM
geometries, M350-50A nonlinear steel, permanent magnets, and supported winding
layouts. It produces loaded torque, no-load phase flux-linkage and Back-EMF,
flux-density maps, field lines, and normal coilEM result provenance. These are
development capabilities, not 0.2.0 launch support or cross-solver accuracy
claims.

Elmer runs use a fixed reproducibility profile:

- native Gmsh generation and ElmerGrid conversion;
- remesh at every rotor position;
- Arkkio torque integration;
- nonlinear relaxation with direct UMFPACK; and
- resultant-field visualization.

The Magneto2D-only stator/PM field decomposition control is disabled for an
Elmer result. Not qualified yet: 3D, sliding mortar, sector periodicity,
circuit coupling, transient or eddy-current analysis, MPI within one position,
and release qualification on any operating-system matrix.

## License and distribution boundary

The Elmer project publishes a mixed license policy: the main library is LGPL,
while ElmerGrid and most solver modules are GPL. This coilEM adapter invokes
unmodified, separately installed executables through files and subprocesses;
the public coilEM source snapshot does not redistribute Elmer binaries or link
Elmer libraries. A user's normal execution of an installed solver does not
change the license of their coilEM input or numerical result.

Anyone who redistributes Elmer binaries, modifies Elmer, or changes this design
to link against Elmer libraries must independently satisfy the applicable
Elmer license, notice, and corresponding-source requirements. See
`THIRD_PARTY_NOTICES.md` and the upstream
[Elmer license policy](https://github.com/ElmerCSC/elmerfem/blob/devel/license_texts/ElmerLicensePolicy.md),
[Elmer 26.2 release](https://github.com/ElmerCSC/elmerfem/releases/tag/release-26.2),
and [build documentation](https://github.com/ElmerCSC/elmerfem/blob/devel/BUILD.md).
