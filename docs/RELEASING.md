# Release wheels

coilEM ships as one `py3-none-<platform>` wheel per supported platform. Each
wheel carries the Magneto2D executable for that platform and the built UI, so
installing it needs neither Rust nor Node.js. One wheel serves every supported
Python version, because the binary is a standalone executable. Only wheels are
published: building from source needs Rust and Node.js, so there is no sdist.

The `coilEM release wheels` workflow (`.github/workflows/release-wheels.yml`)
builds and tests the wheels for version tags, manual runs and pull requests
that change packaging. A manual run can also rehearse publishing on TestPyPI,
and a pushed version tag publishes to PyPI once a reviewer approves; see
[Publishing a release](#publishing-a-release).

## Compatibility policy

| Area | Policy |
| --- | --- |
| Platforms | macOS arm64, macOS x86_64, Linux x86_64 (glibc), Windows x64. Linux and Windows on ARM wait for Gmsh wheels. |
| Minimum OS and glibc | The highest minimum among the binary wheels of every runtime pin in `requirements.lock`, and never below what the Rust standard library needs. `python -m tools.release.policy` computes it from PyPI on each run. |
| macOS build | `MACOSX_DEPLOYMENT_TARGET` for the Rust build equals the declared minimum. |
| Linux build | The binary is built in the newest manylinux image whose glibc does not exceed the floor. |
| Windows build | The C runtime is linked statically (`-C target-feature=+crt-static`), so no Visual C++ redistributable is needed. |
| CPU baseline | Generic x86-64 and arm64 code generation. Release builds refuse `RUSTFLAGS`, `CARGO_BUILD_RUSTFLAGS` and `COILEM_MAGNETO2D_BUILD_RUSTFLAGS`. |
| Native libraries | `auditwheel show` (Linux), `delocate-listdeps` (macOS) and `dumpbin /dependents` (Windows), plus `tools/release/native_deps.py`, which fails on any library outside the operating system or a minimum OS above the wheel tag. |
| Linux system libraries | Gmsh needs GLU, OpenGL and X11 client libraries (`libglu1-mesa libgl1 libx11-6 libxcursor1 libxext6 libxfixes3 libxft2 libxinerama1 libxrender1 libfontconfig1 libgomp1` on Debian and Ubuntu). The hosted runner images already have the OpenGL and X11 libraries, so CI does not test a minimal system (#77). `coilem` checks at startup that Gmsh loads: it prints the install command when GLU is missing and names any other missing library. |
| Python versions | 3.11, 3.12, 3.13, 3.14 and 3.15, each tested. `Requires-Python` is `>=3.11,<3.16`: every supported version must have wheels for all runtime pins, which the policy tool checks. A pin may be split by `python_version` marker when no single version has wheels for every supported Python; the policy tool requires exactly one pin per package for each supported platform and Python version. |
| Runners | Pinned images: builds on ubuntu-24.04, macos-15, macos-15-intel and windows-2022; acceptance on the oldest supported image with a hosted runner (ubuntu-22.04, macos-15, macos-15-intel, windows-2022). |

On 2026-10-11 the policy gave these platform tags:

| Target | Wheel platform tag | Set by |
| --- | --- | --- |
| macOS arm64 | `macosx_12_0_arm64` | gmsh |
| macOS x86_64 | `macosx_10_15_x86_64` | gmsh, numpy, pillow |
| Linux x86_64 | `manylinux_2_27_x86_64` | numpy, pillow |
| Windows x64 | `win_amd64` | |

The Linux binary is built in `manylinux2014` (glibc 2.17), because the next
image, `manylinux_2_28`, exceeds the 2.27 floor.

## Reproducible builds and provenance

- Wheels require exactly the versions in `requirements.lock`; `pyproject.toml`
  reads its dependency list from that file. `verify_wheel.py` compares the
  wheel metadata with the lock.
- CI audits each supported Python's pins with pip-audit. `python -m
  tools.release.policy --audit-pins DIR` writes them without markers,
  because pip-audit skips pins whose markers do not match its interpreter.
- Release builds use the pinned Rust toolchain with `cargo build --release
  --locked` and the frontend's `npm ci`. The UI is built once and shared by
  every wheel.
- Each wheel stamps `backend/_build_info.json` with the application version and
  commit, the Magneto2D version, target and binary SHA-256, the UI bundle hash,
  and the rustc, Cargo, Node and npm versions. `/health` reports it as `build`,
  and new motor runs record it in their provenance and PDF report.
- Packaged schemas and the M350-50A curve must match `snapshot-manifest.json`,
  or the build fails. The binary and UI are generated, so their hashes live in
  the build information and the wheel `RECORD`.

## Licenses in the wheel

The wheel's `.dist-info/licenses/` holds `LICENSE` and
`THIRD_PARTY_NOTICES.md`; the latter carries the frontend runtime notices for
the bundled UI. `backend/_licenses/magneto2d-rust-crates.txt` lists the Rust
crates linked into that wheel's Magneto2D executable, resolved from
`Cargo.lock` for its target, with each crate's license files. Crates
published without their own license file get their upstream LICENSE from
`tools/release/crate_notices/`; a linked crate with neither stops the build,
and `verify_wheel.py` checks that every listed crate has a license text.

## Building and checking locally

From a checkout with Rust, Node.js and Python:

```sh
python -m tools.release.policy
python -m tools.release.artifacts ui --out dist/release
python -m tools.release.artifacts magneto2d --target aarch64-apple-darwin \
  --out dist/release/magneto2d --macos-deployment-target 12.0
COILEM_BUILD_UI_DIST=dist/release/ui \
COILEM_BUILD_MAGNETO2D_BINARY=dist/release/magneto2d/magneto2d \
COILEM_WHEEL_PLATFORM_TAG=macosx_12_0_arm64 \
  python -m pip wheel . --no-deps --wheel-dir dist/wheels
python -m tools.release.verify_wheel dist/wheels/*.whl --platform-tag macosx_12_0_arm64
python -m tools.release.native_deps dist/wheels/*.whl
```

`tools/release/acceptance.py` uses only the standard library and carries its own
inputs. Copy it outside the checkout and run it with the Python version under
test. It installs the wheel into a fresh environment where Cargo and Node.js
cannot be found, then exercises the installed `coilem` through HTTP:

```sh
python -I acceptance.py --install path/to/coilem-0.3.1-py3-none-macosx_12_0_arm64.whl
```

## TestPyPI rehearsal

A rehearsal publishes the wheels to [TestPyPI](https://test.pypi.org), a
separate index for trying out releases, and tests the installed result. It
uses trusted publishing, so no token is stored in the repository.

One-time setup, done by the project owner:

1. Create a TestPyPI account (separate from PyPI) and enable two-factor
   authentication.
2. Under *Your account → Publishing*, add a pending trusted publisher for the
   project `coilem`: owner `coilemdev`, repository `coilem`, workflow
   `release-wheels.yml`, environment `testpypi`. A pending publisher does not
   reserve the name; the first upload creates the project.
3. In the GitHub repository settings, create the environment `testpypi`.
   Optionally require a reviewer, so each upload waits for approval.

To rehearse, open *Actions → coilEM release wheels → Run workflow* and choose
`publish: testpypi`. The workflow must exist on the default branch for that
button to appear; the run can target another branch. The run:

1. sets a unique development version, `<version>.dev<run id><attempt>`,
   because TestPyPI never accepts the same version twice;
2. builds, checks and accepts the wheels exactly as for any other run;
3. uploads the four wheels to TestPyPI only if every acceptance job passed;
4. on each platform, downloads the wheel from TestPyPI, checks it is
   byte-identical to the wheel CI built, installs it with its dependencies
   from PyPI, and repeats the acceptance test.

To try a rehearsal build by hand, download the wheel from TestPyPI and run
that file. Its dependencies then come from PyPI:

```sh
python -m pip download --no-deps --index-url https://test.pypi.org/simple/ coilem==0.3.1.devN -d coilem-wheel
uvx --from coilem-wheel/coilem-0.3.1.devN-*.whl coilem
```

Do not install with `--extra-index-url https://test.pypi.org/simple/`: anyone
can upload to TestPyPI, so its copies of coilEM's dependencies are untrusted.

## Publishing a release

One-time setup, done by the project owner:

1. Create a PyPI account and enable two-factor authentication.
2. Under *Your account → Publishing*, add a pending trusted publisher for the
   project `coilem`: owner `coilemdev`, repository `coilem`, workflow
   `release-wheels.yml`, environment `pypi`. Until the first upload, anyone
   can still register the name.
3. In the GitHub repository settings, create the environment `pypi`. Add a
   required reviewer and, under *Deployment branches and tags*, allow only
   tags matching `v*`. Restrict `testpypi` to `main` the same way.

Each release:

1. On a branch, set the version in `backend/__init__.py`,
   `frontend/package.json` (and its lock file) and `COILEM_APP_VERSION` in
   `frontend/src/public/designFile.ts`; `tests/test_public_candidate.py`
   checks that they agree. Give `RELEASE_NOTES.md` the new heading.
2. Merge, then run a TestPyPI rehearsal on that `main` commit and try the
   build by hand on each platform.
3. Tag that commit and push the tag. The tag must name the version exactly,
   such as `v0.3.1` for 0.3.1, or the policy job stops the run;
   `python -m tools.release.version --tag v0.3.1` runs the same check.

   ```sh
   git tag -a v0.3.1 -m "coilEM 0.3.1" <commit>
   git push origin v0.3.1
   ```

4. The workflow builds and accepts the wheels as for any run, then waits for
   approval of the `pypi` environment. Approving it uploads the four wheels
   with trusted publishing.
5. On each platform, the workflow downloads the wheel from PyPI, checks it is
   byte-identical to the wheel CI built, and repeats the acceptance test.
6. Finally it attaches the wheels to a draft GitHub release for the tag, with
   `RELEASE_NOTES.md` as its notes. Review the draft and publish it.

PyPI never accepts the same version twice, even after a file is deleted. A
broken release can be yanked, which hides it from new installs, but a fix
needs a new version such as 0.3.1.

