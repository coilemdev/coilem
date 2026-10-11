# Release wheels

coilEM ships as one `py3-none-<platform>` wheel per supported platform. Each
wheel carries the Magneto2D executable for that platform and the built UI, so
installing it needs neither Rust nor Node.js. One wheel serves every supported
Python version, because the binary is a standalone executable. Only wheels are
published: building from source needs Rust and Node.js, so there is no sdist.

The `coilEM release wheels` workflow (`.github/workflows/release-wheels.yml`)
builds and tests the wheels for version tags, manual runs and pull requests
that change packaging. Publishing is a separate step.

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
| Linux system libraries | Gmsh needs GLU (`libglu1-mesa` on Debian and Ubuntu). `coilem` checks for it at startup and prints the install command. |
| Python versions | 3.11, 3.12, 3.13 and 3.14, each tested. `Requires-Python` is `>=3.11,<3.15`: every supported version must have wheels for all runtime pins, which the policy tool checks. |
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
`Cargo.lock` for its target, with each crate's license files.

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
python -I acceptance.py --install path/to/coilem-0.2.0-py3-none-macosx_12_0_arm64.whl
```
