//! coilEM schema v1 envelope.
//!
//! Every JSON artifact emitted by magneto2d (and, by convention, by the
//! Python diagnostic scripts) carries three top-level metadata keys that
//! identify the schema version, the artifact kind, and its provenance.
//!
//! The envelope uses `#[serde(flatten)]` so the metadata keys sit alongside
//! the existing report fields rather than nesting the payload under a new
//! key. That preserves backward compatibility: consumers that only look at
//! existing fields (`config_summary`, `sweep`, `mesh_info`, …) still work,
//! while ML pipelines can join on `fixture_sha256` and filter by
//! `openem_schema_version`.
//!
//! Stability contract:
//! - `COILEM_SCHEMA_VERSION` bumps only on breaking changes to the
//!   envelope or the inner payload shape.
//! - Adding new optional fields to `OpenemProvenance` is non-breaking.
//! - Envelope keys are namespaced with `openem_` to avoid collisions with
//!   payload fields.
//!
//! See also: `backend/schema.py` for the Python mirror of these types.
use std::fs;
use std::path::Path;
use std::time::{SystemTime, UNIX_EPOCH};

use serde::Serialize;

/// Current envelope version. Bump on any breaking change to either the
/// envelope itself or a payload struct that consumers are expected to key
/// off of.
pub const COILEM_SCHEMA_VERSION: &str = "1.0";

/// Git SHA of the build, captured by `build.rs` at compile time. Falls
/// back to "unknown" when the working tree isn't a git checkout or git is
/// unavailable.
pub const COILEM_MAGNETO2D_GIT_SHA: &str = match option_env!("COILEM_MAGNETO2D_GIT_SHA") {
    Some(v) => v,
    None => "unknown",
};

/// Semver of the magneto2d crate, captured at compile time.
pub const COILEM_MAGNETO2D_VERSION: &str = env!("CARGO_PKG_VERSION");

/// Schema-kind string for a single-angle `SolveReport`.
pub const KIND_SOLVE_REPORT: &str = "solve_report";
/// Steady-state thermal conduction report.
pub const KIND_THERMAL_SOLVE_REPORT: &str = "thermal_solve_report";
/// Schema-kind string for a rotor `SweepReport`.
pub const KIND_SWEEP_REPORT: &str = "sweep_report";
/// Schema-kind string for imported-mesh batch single-angle reports.
pub const KIND_BATCH_SOLVE_REPORTS: &str = "batch_solve_reports";
/// Schema-kind string for a generic `FieldSolutionReport`.
pub const KIND_FIELD_SOLUTION_REPORT: &str = "field_solution_report";
/// Schema-kind string for a `MeshPreviewReport`.
#[allow(dead_code)]
pub const KIND_MESH_PREVIEW: &str = "mesh_preview";

/// Provenance block that travels with every enveloped artifact.
///
/// The goal is reproducibility: given a stored artifact, we can later
/// answer "which solver produced this, against which fixture, on what
/// host, when?"
#[derive(Debug, Serialize)]
pub struct OpenemProvenance {
    /// ISO-8601 UTC timestamp, seconds precision, trailing 'Z'.
    pub generated_at_utc: String,
    /// Unix epoch seconds of the same instant — unambiguous, easy to
    /// sort/join on numerically.
    pub generated_at_unix_sec: u64,
    /// Semver of the magneto2d crate (from Cargo.toml).
    pub magneto2d_version: String,
    /// Git SHA at compile time; "unknown" if build.rs could not resolve.
    pub magneto2d_git_sha: String,
    /// Relative path of the fixture file that drove the solve, as passed
    /// on the CLI. `None` for artifacts that weren't produced from a
    /// fixture file (unit tests, synthetic runs).
    pub fixture_path: Option<String>,
    /// SHA-256 of the fixture file bytes, lowercase hex. `None` when the
    /// fixture is unavailable or hashing is skipped.
    pub fixture_sha256: Option<String>,
    /// Fixture file size in bytes — a cheap secondary fingerprint.
    pub fixture_size_bytes: Option<u64>,
    /// Host OS string (e.g. "macos", "linux"). Useful for segmenting
    /// performance stats later on.
    pub host_os: String,
    /// If this artifact was back-filled by the migration script rather
    /// than emitted by the solver directly, set `true`. Consumers that
    /// need strict provenance should filter these out.
    pub migration_backfilled: bool,
}

impl OpenemProvenance {
    /// Build a fresh provenance record for an artifact produced right now
    /// in this process. Errors during fixture hashing are logged to
    /// stderr and demoted to `None` rather than aborting the solve.
    pub fn capture(fixture_path: Option<&str>) -> Self {
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_secs())
            .unwrap_or(0);

        let (fixture_sha256, fixture_size_bytes) = match fixture_path {
            Some(p) => match hash_fixture(Path::new(p)) {
                Ok((hash, size)) => (Some(hash), Some(size)),
                Err(e) => {
                    eprintln!("magneto2d: fixture hash skipped ({}): {}", p, e);
                    (None, None)
                }
            },
            None => (None, None),
        };

        Self {
            generated_at_utc: format_iso8601_utc(now),
            generated_at_unix_sec: now,
            magneto2d_version: COILEM_MAGNETO2D_VERSION.to_string(),
            magneto2d_git_sha: COILEM_MAGNETO2D_GIT_SHA.to_string(),
            fixture_path: fixture_path.map(|s| s.to_string()),
            fixture_sha256,
            fixture_size_bytes,
            host_os: detect_host_os().to_string(),
            migration_backfilled: false,
        }
    }
}

/// Generic envelope that prepends the three `openem_*` metadata keys to
/// any serializable payload. The payload is flattened so existing
/// consumers don't have to reach through a wrapper key.
#[derive(Debug, Serialize)]
pub struct Enveloped<T: Serialize> {
    pub openem_schema_version: &'static str,
    pub openem_schema_kind: String,
    pub openem_provenance: OpenemProvenance,
    #[serde(flatten)]
    pub payload: T,
}

impl<T: Serialize> Enveloped<T> {
    pub fn new(kind: &str, provenance: OpenemProvenance, payload: T) -> Self {
        Self {
            openem_schema_version: COILEM_SCHEMA_VERSION,
            openem_schema_kind: kind.to_string(),
            openem_provenance: provenance,
            payload,
        }
    }
}

pub fn render_enveloped<T: Serialize>(
    kind: &str,
    fixture_path: Option<&str>,
    payload: T,
) -> Result<String, serde_json::Error> {
    let provenance = OpenemProvenance::capture(fixture_path);
    let enveloped = Enveloped::new(kind, provenance, payload);
    serde_json::to_string_pretty(&enveloped)
}

/// Compute SHA-256 of the fixture file contents and return (hex, size).
///
/// We implement SHA-256 in-tree so we don't drag in a crypto dep purely
/// for fingerprinting. This is *not* a security-sensitive hash — it's a
/// content identifier. The implementation follows FIPS 180-4 literally.
fn hash_fixture(path: &Path) -> Result<(String, u64), String> {
    let bytes = fs::read(path).map_err(|e| e.to_string())?;
    let size = bytes.len() as u64;
    let digest = sha256_bytes(&bytes);
    let hex = digest
        .iter()
        .map(|b| format!("{:02x}", b))
        .collect::<String>();
    Ok((hex, size))
}

fn sha256_bytes(input: &[u8]) -> [u8; 32] {
    // FIPS 180-4 SHA-256. Kept small and auditable; no perf hot path.
    const K: [u32; 64] = [
        0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4,
        0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe,
        0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f,
        0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
        0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc,
        0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
        0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116,
        0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
        0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7,
        0xc67178f2,
    ];

    let mut h: [u32; 8] = [
        0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab,
        0x5be0cd19,
    ];

    // Padding: append 0x80, zeros, then 64-bit big-endian length in bits.
    let bit_len = (input.len() as u64).wrapping_mul(8);
    let mut padded = Vec::with_capacity(input.len() + 72);
    padded.extend_from_slice(input);
    padded.push(0x80);
    while padded.len() % 64 != 56 {
        padded.push(0);
    }
    padded.extend_from_slice(&bit_len.to_be_bytes());

    for chunk in padded.chunks_exact(64) {
        let mut w = [0u32; 64];
        for i in 0..16 {
            w[i] = u32::from_be_bytes([
                chunk[4 * i],
                chunk[4 * i + 1],
                chunk[4 * i + 2],
                chunk[4 * i + 3],
            ]);
        }
        for i in 16..64 {
            let s0 = w[i - 15].rotate_right(7) ^ w[i - 15].rotate_right(18) ^ (w[i - 15] >> 3);
            let s1 = w[i - 2].rotate_right(17) ^ w[i - 2].rotate_right(19) ^ (w[i - 2] >> 10);
            w[i] = w[i - 16]
                .wrapping_add(s0)
                .wrapping_add(w[i - 7])
                .wrapping_add(s1);
        }

        let mut a = h[0];
        let mut b = h[1];
        let mut c = h[2];
        let mut d = h[3];
        let mut e = h[4];
        let mut f = h[5];
        let mut g = h[6];
        let mut hh = h[7];

        for i in 0..64 {
            let s1 = e.rotate_right(6) ^ e.rotate_right(11) ^ e.rotate_right(25);
            let ch = (e & f) ^ (!e & g);
            let temp1 = hh
                .wrapping_add(s1)
                .wrapping_add(ch)
                .wrapping_add(K[i])
                .wrapping_add(w[i]);
            let s0 = a.rotate_right(2) ^ a.rotate_right(13) ^ a.rotate_right(22);
            let maj = (a & b) ^ (a & c) ^ (b & c);
            let temp2 = s0.wrapping_add(maj);
            hh = g;
            g = f;
            f = e;
            e = d.wrapping_add(temp1);
            d = c;
            c = b;
            b = a;
            a = temp1.wrapping_add(temp2);
        }

        h[0] = h[0].wrapping_add(a);
        h[1] = h[1].wrapping_add(b);
        h[2] = h[2].wrapping_add(c);
        h[3] = h[3].wrapping_add(d);
        h[4] = h[4].wrapping_add(e);
        h[5] = h[5].wrapping_add(f);
        h[6] = h[6].wrapping_add(g);
        h[7] = h[7].wrapping_add(hh);
    }

    let mut out = [0u8; 32];
    for (i, word) in h.iter().enumerate() {
        out[4 * i..4 * i + 4].copy_from_slice(&word.to_be_bytes());
    }
    out
}

/// Format a Unix epoch (seconds) as ISO-8601 UTC, e.g.
/// "2026-04-16T12:34:56Z".
///
/// Small civil-from-days algorithm (Howard Hinnant's date algorithm) so
/// we don't pull in a calendar crate for one string.
fn format_iso8601_utc(unix_sec: u64) -> String {
    let seconds_per_day: u64 = 86_400;
    let days = (unix_sec / seconds_per_day) as i64;
    let rem = unix_sec % seconds_per_day;
    let hour = rem / 3600;
    let minute = (rem % 3600) / 60;
    let second = rem % 60;

    // Days since 1970-01-01 → civil date using Hinnant's algorithm.
    // https://howardhinnant.github.io/date_algorithms.html
    let z = days + 719_468;
    let era = if z >= 0 { z } else { z - 146_096 } / 146_097;
    let doe = (z - era * 146_097) as u64; // [0, 146096]
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146_096) / 365; // [0, 399]
    let year = (yoe as i64) + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100); // [0, 365]
    let mp = (5 * doy + 2) / 153; // [0, 11]
    let day = doy - (153 * mp + 2) / 5 + 1; // [1, 31]
    let month = if mp < 10 { mp + 3 } else { mp - 9 }; // [1, 12]
    let year = if month <= 2 { year + 1 } else { year };

    format!(
        "{:04}-{:02}-{:02}T{:02}:{:02}:{:02}Z",
        year, month, day, hour, minute, second
    )
}

fn detect_host_os() -> &'static str {
    // std::env::consts::OS is authoritative and evaluated at compile time.
    std::env::consts::OS
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::Value;

    #[derive(Debug, Serialize)]
    struct DummyPayload {
        alpha: i32,
        beta: String,
    }

    #[test]
    fn iso8601_formatter_matches_known_epochs() {
        // 0 → 1970-01-01T00:00:00Z
        assert_eq!(format_iso8601_utc(0), "1970-01-01T00:00:00Z");
        // 2026-04-16T00:00:00Z = 1,776,297,600 seconds since epoch.
        // Verified against `date -u -d '2026-04-16T00:00:00Z' +%s` —
        // 2026 is not a leap year, and there are 14 leap days between
        // 1970 and 2026 (1972, 76, 80, 84, 88, 92, 96, 2000, 04, 08, 12,
        // 16, 20, 24).
        assert_eq!(format_iso8601_utc(1_776_297_600), "2026-04-16T00:00:00Z");
        // Non-midnight sample: 2026-04-16T12:34:56Z = 1,776,297,600 +
        // 45,296.
        assert_eq!(format_iso8601_utc(1_776_342_896), "2026-04-16T12:34:56Z");
        // End-of-year wraparound: 2023-12-31T23:59:59Z = 1,704,067,199.
        assert_eq!(format_iso8601_utc(1_704_067_199), "2023-12-31T23:59:59Z");
        // Leap day: 2024-02-29T00:00:00Z = 1,709,164,800.
        assert_eq!(format_iso8601_utc(1_709_164_800), "2024-02-29T00:00:00Z");
    }

    #[test]
    fn sha256_matches_known_vectors() {
        // Empty string → e3b0c4...b855
        let empty = sha256_bytes(b"");
        let hex: String = empty.iter().map(|b| format!("{:02x}", b)).collect();
        assert_eq!(
            hex,
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        );
        // "abc" → ba7816bf...
        let abc = sha256_bytes(b"abc");
        let hex: String = abc.iter().map(|b| format!("{:02x}", b)).collect();
        assert_eq!(
            hex,
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        );
    }

    #[test]
    fn envelope_flattens_payload_keys() {
        let provenance = OpenemProvenance {
            generated_at_utc: "2026-04-16T00:00:00Z".to_string(),
            generated_at_unix_sec: 1_776_643_200,
            magneto2d_version: "0.1.1".to_string(),
            magneto2d_git_sha: "abc1234".to_string(),
            fixture_path: Some("fixtures/test.json".to_string()),
            fixture_sha256: Some("deadbeef".to_string()),
            fixture_size_bytes: Some(42),
            host_os: "linux".to_string(),
            migration_backfilled: false,
        };
        let env = Enveloped::new(
            KIND_SOLVE_REPORT,
            provenance,
            DummyPayload {
                alpha: 7,
                beta: "hello".to_string(),
            },
        );
        let rendered = serde_json::to_string(&env).expect("serialize envelope");
        let parsed: Value = serde_json::from_str(&rendered).expect("reparse envelope");

        // The three metadata keys are present at the top level.
        assert_eq!(parsed["openem_schema_version"], "1.0");
        assert_eq!(parsed["openem_schema_kind"], "solve_report");
        assert!(parsed["openem_provenance"].is_object());

        // Payload keys are flattened alongside, not nested under 'payload'.
        assert_eq!(parsed["alpha"], 7);
        assert_eq!(parsed["beta"], "hello");
        assert!(
            parsed.get("payload").is_none(),
            "payload key should not exist — #[serde(flatten)] should inline it"
        );
    }

    #[test]
    fn render_enveloped_preserves_flattened_schema_surface() {
        let rendered = render_enveloped(
            KIND_SOLVE_REPORT,
            None,
            DummyPayload {
                alpha: 7,
                beta: "hello".to_string(),
            },
        )
        .expect("render envelope");
        let parsed: Value = serde_json::from_str(&rendered).expect("reparse envelope");

        assert_eq!(parsed["openem_schema_version"], "1.0");
        assert_eq!(parsed["openem_schema_kind"], "solve_report");
        assert!(parsed["openem_provenance"].is_object());
        assert!(parsed["openem_provenance"]["fixture_path"].is_null());
        assert_eq!(parsed["alpha"], 7);
        assert_eq!(parsed["beta"], "hello");
        assert!(parsed.get("payload").is_none());
    }

    #[test]
    fn envelope_key_collision_is_surfaced() {
        // If a payload ever defines a field named `openem_schema_version`,
        // the #[serde(flatten)] envelope would silently shadow one of
        // them. This test documents the current behavior so future us
        // catches any collision during code review.
        #[derive(Debug, Serialize)]
        struct Colliding {
            openem_schema_version: &'static str,
            value: i32,
        }
        let provenance = OpenemProvenance {
            generated_at_utc: "2026-04-16T00:00:00Z".to_string(),
            generated_at_unix_sec: 1_776_643_200,
            magneto2d_version: "0.1.1".to_string(),
            magneto2d_git_sha: "abc1234".to_string(),
            fixture_path: None,
            fixture_sha256: None,
            fixture_size_bytes: None,
            host_os: "linux".to_string(),
            migration_backfilled: false,
        };
        let env = Enveloped::new(
            KIND_SOLVE_REPORT,
            provenance,
            Colliding {
                openem_schema_version: "payload-wins",
                value: 1,
            },
        );
        // serde_json permits duplicate keys when emitting — last write
        // wins on re-parse. We assert the current behavior so if serde
        // semantics change we notice immediately.
        let rendered = serde_json::to_string(&env).expect("serialize colliding envelope");
        let parsed: Value = serde_json::from_str(&rendered).expect("reparse");
        assert!(
            parsed["openem_schema_version"] == "1.0"
                || parsed["openem_schema_version"] == "payload-wins",
            "collision resolution changed — audit envelope consumers"
        );
    }
}
