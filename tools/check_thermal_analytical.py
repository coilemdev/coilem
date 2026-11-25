"""Run the independent analytical thermal suite; FAIL returns exit status 1."""

from backend.benchmark_suite.thermal_analytical import main

if __name__ == "__main__":
    raise SystemExit(main())
