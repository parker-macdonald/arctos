//! Simple Bayesian filter for client–server time offset estimation.
//! Gaussian prior and likelihood; conjugate update with optional outlier rejection.

/// Bayesian filter for a single scalar (time offset) with Gaussian prior and measurement noise.
#[derive(Clone, Debug)]
pub struct BayesianOffsetFilter {
    /// Posterior mean (estimated offset in seconds): server_time = client_time + mean
    pub mean: f64,
    /// Posterior variance (uncertainty in seconds²)
    pub variance: f64,
    /// Process noise per step (variance added each update to allow drift)
    pub process_noise: f64,
    /// Measurement noise variance (R)
    pub measurement_variance: f64,
    /// Reject measurement if |z - mean| > outlier_sigma * sqrt(variance + measurement_variance)
    pub outlier_sigma: f64,
    /// Don't reject until variance drops below this (avoid rejecting during initial convergence)
    pub min_variance_for_rejection: f64,
    pub rejected_count: u32,
}

impl Default for BayesianOffsetFilter {
    fn default() -> Self {
        Self {
            mean: 0.0,
            variance: 1e10, // high initial uncertainty
            process_noise: 1e-8,
            measurement_variance: 0.0015, // measurement noise variance (s²)
            outlier_sigma: 2.0,
            min_variance_for_rejection: 1.0,
            rejected_count: 0,
        }
    }
}

impl BayesianOffsetFilter {
    /// Update with a new measurement (offset in seconds). Returns current posterior mean.
    pub fn update(&mut self, measurement: f64) -> f64 {
        // Predict: add process noise (random walk)
        self.variance += self.process_noise;

        // Outlier rejection
        if self.variance < self.min_variance_for_rejection {
            let innovation = measurement - self.mean;
            let innovation_var = self.variance + self.measurement_variance;
            let std_dev = innovation_var.sqrt();
            if std_dev > 1e-20 {
                let z_score = innovation.abs() / std_dev;
                if z_score > self.outlier_sigma {
                    self.rejected_count += 1;
                    return self.mean;
                }
            }
        }

        // Update: Gaussian conjugate prior × likelihood → posterior
        // posterior precision = prior_precision + likelihood_precision
        // posterior_mean = (prior_mean * prior_precision + measurement * likelihood_precision) / posterior_precision
        let prior_precision = 1.0 / self.variance;
        let likelihood_precision = 1.0 / self.measurement_variance;
        let posterior_precision = prior_precision + likelihood_precision;
        self.variance = 1.0 / posterior_precision;
        self.mean = (self.mean * prior_precision + measurement * likelihood_precision)
            / posterior_precision;

        self.mean
    }

    pub fn get_mean(&self) -> f64 {
        self.mean
    }

    pub fn get_variance(&self) -> f64 {
        self.variance
    }

    pub fn reset(&mut self) {
        self.mean = 0.0;
        self.variance = 1e10;
        self.rejected_count = 0;
    }
}
