//! Steady-state thermal FEA.
//!
//! The binary CLI only needs [`run_steady_state_thermal`]. Constructors and
//! helpers below are part of the thermal API used by unit tests and upcoming
//! Phase D / UI paths; they are intentionally kept even when the bin does not
//! call them yet.

pub mod assembly;
pub mod bc;
pub mod contacts;
pub mod energy;
pub mod materials;
pub mod solve;
pub mod sources;
pub mod types;

#[cfg(test)]
mod tests;

pub use solve::run_steady_state_thermal;
