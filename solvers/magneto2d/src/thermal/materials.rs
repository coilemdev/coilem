//! Thermal material conductivity assignment.

use serde::{Deserialize, Serialize};

/// Per-element thermal conductivity [W/(m·K)].
///
/// Isotropic materials use `k_w_per_m_k`. Anisotropic orthotropic materials
/// set `k_xx` / `k_yy` (principal axes aligned with global x/y for v1).
#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
pub struct ThermalMaterialProps {
    pub k_w_per_m_k: f64,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub k_xx_w_per_m_k: Option<f64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub k_yy_w_per_m_k: Option<f64>,
    /// Optional temperature-dependent conductivity model (isotropic path).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub k_of_t: Option<ThermalConductivityModel>,
}

impl ThermalMaterialProps {
    #[allow(dead_code)] // used by thermal unit tests / future callers
    pub fn constant(k_w_per_m_k: f64) -> Self {
        Self {
            k_w_per_m_k,
            k_xx_w_per_m_k: None,
            k_yy_w_per_m_k: None,
            k_of_t: None,
        }
    }

    #[allow(dead_code)] // used by thermal unit tests / future callers
    pub fn orthotropic(k_xx_w_per_m_k: f64, k_yy_w_per_m_k: f64) -> Self {
        Self {
            k_w_per_m_k: 0.5 * (k_xx_w_per_m_k + k_yy_w_per_m_k),
            k_xx_w_per_m_k: Some(k_xx_w_per_m_k),
            k_yy_w_per_m_k: Some(k_yy_w_per_m_k),
            k_of_t: None,
        }
    }

    pub fn conductivity_at(&self, temperature_k: f64) -> Result<f64, String> {
        match self.k_of_t {
            Some(model) => model.eval(temperature_k),
            None => {
                require_positive_finite(self.k_w_per_m_k, "k_w_per_m_k")?;
                Ok(self.k_w_per_m_k)
            }
        }
    }

    /// Orthotropic tensors and k(T) are mutually exclusive.
    /// Temperature-dependent anisotropic conductivity is unsupported.
    ///
    /// All conductivity parameters must be finite and strictly positive —
    /// negative / zero / NaN k previously produced sub-ambient fields with
    /// a still-closed energy balance.
    pub fn validate(&self) -> Result<(), String> {
        let orthotropic = self.k_xx_w_per_m_k.is_some() || self.k_yy_w_per_m_k.is_some();
        if orthotropic && self.k_of_t.is_some() {
            return Err(
                "thermal material cannot combine orthotropic k_xx/k_yy with k(T); \
                 temperature-dependent anisotropic conductivity is unsupported"
                    .to_string(),
            );
        }
        if self.k_xx_w_per_m_k.is_some() != self.k_yy_w_per_m_k.is_some() {
            return Err(
                "thermal material orthotropic conductivity requires both k_xx and k_yy"
                    .to_string(),
            );
        }
        require_positive_finite(self.k_w_per_m_k, "k_w_per_m_k")?;
        if let Some(kxx) = self.k_xx_w_per_m_k {
            require_positive_finite(kxx, "k_xx_w_per_m_k")?;
        }
        if let Some(kyy) = self.k_yy_w_per_m_k {
            require_positive_finite(kyy, "k_yy_w_per_m_k")?;
        }
        if let Some(model) = self.k_of_t {
            model.validate()?;
        }
        Ok(())
    }

    pub fn tensor(&self) -> [f64; 2] {
        let kxx = self.k_xx_w_per_m_k.unwrap_or(self.k_w_per_m_k);
        let kyy = self.k_yy_w_per_m_k.unwrap_or(self.k_w_per_m_k);
        [kxx, kyy]
    }
}

fn require_positive_finite(value: f64, name: &str) -> Result<(), String> {
    if !value.is_finite() {
        return Err(format!("{name} must be finite (got {value})"));
    }
    if value <= 0.0 {
        return Err(format!("{name} must be strictly positive (got {value})"));
    }
    Ok(())
}

/// Simple linear k(T) model for the nonlinear iteration path.
#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
pub struct ThermalConductivityModel {
    pub k0_w_per_m_k: f64,
    pub t0_k: f64,
    pub dk_dt_w_per_m_k2: f64,
}

impl ThermalConductivityModel {
    pub fn validate(self) -> Result<(), String> {
        require_positive_finite(self.k0_w_per_m_k, "k_of_t.k0_w_per_m_k")?;
        if !self.t0_k.is_finite() {
            return Err(format!("k_of_t.t0_k must be finite (got {})", self.t0_k));
        }
        if !self.dk_dt_w_per_m_k2.is_finite() {
            return Err(format!(
                "k_of_t.dk_dt_w_per_m_k2 must be finite (got {})",
                self.dk_dt_w_per_m_k2
            ));
        }
        Ok(())
    }

    pub fn eval(self, temperature_k: f64) -> Result<f64, String> {
        if !temperature_k.is_finite() {
            return Err(format!(
                "k(T) evaluation temperature must be finite (got {temperature_k})"
            ));
        }
        let k = self.k0_w_per_m_k + self.dk_dt_w_per_m_k2 * (temperature_k - self.t0_k);
        // Never floor invalid physics: non-positive / non-finite k(T) must fail.
        require_positive_finite(k, "k(T)")?;
        Ok(k)
    }

    #[allow(dead_code)] // reserved for Newton Jacobian / nonlinear path
    pub fn derivative(self) -> f64 {
        self.dk_dt_w_per_m_k2
    }
}
