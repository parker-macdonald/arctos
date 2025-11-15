// Kalman Filter for time offset estimation
// Shared implementation used across multiple pages
class KalmanFilter {
    constructor() {
        this.x = 0;  // prior state
        this.P = 1e10;  // prior cov
        this.Q = 0.00000001; // dynamics are xdot=f(x)=0 lmao. clock drift is very very small.
        this.R = 0.0015; 
        this.outlierThreshold = 2.0;  // unit is stdevs
        this.minConfidenceForRejection = 1.0;  // reject outliers if P < this (outlier measurement is better than nothing)
        this.rejectedCount = 0;
    }
    
    update(measurement) {
        // Predict
        this.P = this.P + this.Q;
        // Outlier rejection: only reject if we have some confidence in our estimate
        // Skip rejection during initial convergence (when P is very large)
        if (this.P < this.minConfidenceForRejection) {
            const innovation = measurement - this.x;
            const innovationCovariance = this.P + this.R;  // Total uncertainty
            const stdDev = Math.sqrt(innovationCovariance);
            const zScore = Math.abs(innovation) / stdDev;
            
            if (zScore > this.outlierThreshold) {
                // Reject outlier - don't update the filter
                this.rejectedCount++;
                console.log(`Rejected outlier measurement: ${measurement.toFixed(6)}s, z-score: ${zScore.toFixed(2)}, current estimate: ${this.x.toFixed(6)}s`);
                // Still return current state
                return this.x;
            }
        }
        
        // Update
        const K = this.P / (this.P + this.R);  // Kalman gain
        this.x = this.x + K * (measurement - this.x);
        this.P = (1 - K) * this.P;
        
        return this.x;
    }
    
    getState() {
        return this.x;
    }
    
    getCovariance() {
        return this.P;
    }
    
    reset() {
        this.x = 0;
        this.P = 1e10;
        this.rejectedCount = 0;
    }
    
    // Save state to object for persistence
    toJSON() {
        return {
            x: this.x,
            P: this.P
        };
    }
    
    // Load state from object
    fromJSON(data) {
        if (data && typeof data.x === 'number' && typeof data.P === 'number') {
            this.x = data.x;
            this.P = data.P;
        }
    }
}

// Load Kalman filter state from localStorage
function loadKFState() {
    try {
        const saved = localStorage.getItem("kf state");
        if (saved) {
            const state = JSON.parse(saved);
            kalmanFilter.fromJSON(state);
            console.log('Loaded KF state from localStorage:', state);
        }
    } catch (error) {
        console.error('Error loading KF state:', error);
    }
}

// Save Kalman filter state to localStorage
function saveKFState() {
    try {
        const state = kalmanFilter.toJSON();
        localStorage.setItem("kf state", JSON.stringify(state));
    } catch (error) {
        console.error('Error saving KF state:', error);
    }
}