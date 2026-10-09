//! Capture the git SHA at compile time and expose it to the crate as
//! `COILEM_MAGNETO2D_GIT_SHA`. If git is unavailable (release tarball,
//! shallow CI checkout, sandboxed builds) we silently fall back — the
//! schema module will substitute "unknown".
//!
//! We deliberately do *not* re-run on every source change, only on
//! changes to `.git/HEAD` and `.git/index`, so incremental builds stay
//! fast.

use std::process::Command;

fn main() {
    let sha = Command::new("git")
        .args(["rev-parse", "--short=12", "HEAD"])
        .output()
        .ok()
        .and_then(|o| {
            if o.status.success() {
                Some(String::from_utf8_lossy(&o.stdout).trim().to_string())
            } else {
                None
            }
        })
        .filter(|s| !s.is_empty())
        .unwrap_or_else(|| "unknown".to_string());

    println!("cargo:rustc-env=COILEM_MAGNETO2D_GIT_SHA={}", sha);
    // Rebuild only when HEAD or the index changes — not on every source
    // edit.
    println!("cargo:rerun-if-changed=../../.git/HEAD");
    println!("cargo:rerun-if-changed=../../.git/index");
}
