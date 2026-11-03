# Exact-candidate Mac collection

Use a fresh clone, Python 3.12 and Rust 1.94.0. Git, uv, Node.js 24 with npm
and rustup must be installed. The measured candidate stays `88aae101` even
after its release-preparation PRs merge. Use an output folder outside the
checkout and keep the source unchanged during collection.

```sh
git clone https://github.com/coilemdev/coilem.git coilem-v050-benchmark
cd coilem-v050-benchmark
git checkout 88aae101fd487795e7fe5300737679f4133790fd

uv venv --python 3.12
. .venv/bin/activate
uv pip install -r requirements.lock
uv pip install -e ".[dev]"

rustup toolchain install 1.94.0 --profile minimal
cargo +1.94.0 build --release --locked --manifest-path solvers/magneto2d/Cargo.toml

caffeinate -i python -m tools.run_benchmarks \
  --suite benchmarks/abcd-v1.6/benchmark_spec.json \
  --phases A B C D --no-reference --pdf \
  --out-dir "$HOME/coilem-evidence/v050-88aae101-macos"
```

This collects every supported native job, including the complete 17-case
extension. Native-only rows can say NOT_COMPARED until the reviewed reference
join. The legacy ORNL Prius row remains planned unsupported. This command
does not run the separate Pyleecan Prius collection.

If interrupted, resume the same selection and folder with the same clean
checkout and environment:

```sh
caffeinate -i python -m tools.run_benchmarks \
  --suite benchmarks/abcd-v1.6/benchmark_spec.json \
  --phases A B C D --no-reference --pdf --resume \
  --out-dir "$HOME/coilem-evidence/v050-88aae101-macos"
```

Retain the **entire output folder**, including its run manifest, all requests
and results, reports and fixtures. Preserve its original bytes before any
public path redaction. `tools.qualify_benchmark_candidate` in the qualification
follow-up verifies the raw artifacts and source hashes before deriving the
reviewed comparison with zero new field solves. Do not copy the later review
code into the measured checkout while it is collecting.
