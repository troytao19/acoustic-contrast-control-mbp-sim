"""Recover complex relative transfer from phase-stepped power measurements.

No shared speaker/microphone clock is required. All microphone gain/processing
must remain fixed. Each position has an arbitrary common phase, which cancels
in H^H H. Per-position normalization is deliberately NOT performed.
"""
import numpy as np
from .model import encode, signature, vec


def probes():
    return [np.array([0, 0], complex), np.array([1, 0], complex), np.array([0, 1], complex)] + [np.array([1, np.exp(1j*p)], complex) for p in np.arange(8)*np.pi/4] + [np.array([1, 0], complex)]


def recover(powers, peak, scatter=None):
    p = np.asarray(powers, dtype=float)
    if p.shape != (12,) or not np.all(np.isfinite(p)) or np.any(p < 0):
        raise ValueError("Calibration needs 12 nonnegative finite tone powers.")
    if not 0.001 <= peak <= 0.08:
        raise ValueError("Invalid calibration drive.")
    qs = probes()
    rows = []
    for q in qs:
        cross = q[0]*np.conj(q[1])
        rows.append([1, abs(q[0])**2, abs(q[1])**2, 2*cross.real, -2*cross.imag])
    a = np.array(rows)
    fit, *_ = np.linalg.lstsq(a, p, rcond=None)
    noise, left, right, real, imag = fit
    signal = max(left+right, 1e-30)
    residual = float(np.sqrt(np.mean((a@fit-p)**2))/signal)
    drift = float(abs(p[1]-p[-1])/max(p[1], p[-1], 1e-30))
    cross = real+1j*imag
    coherence = float(abs(cross)/np.sqrt(max(left*right, 1e-30)))
    snr = float(10*np.log10(max(min(left, right), 1e-30)/max(p[0], 1e-30)))
    reasons = []
    if left <= 0 or right <= 0: reasons.append("A channel is below noise.")
    if snr < 15: reasons.append("Channel SNR below 15 dB.")
    if residual > 0.10: reasons.append("Probe-fit residual exceeds 10% (motion, noise, AGC, or nonlinearity).")
    if drift > 0.12: reasons.append("Repeated left-channel level drift exceeds 12%.")
    if not 0.8 <= coherence <= 1.2: reasons.append("Cross-channel consistency is outside 0.8–1.2.")
    if scatter is not None:
        s = np.asarray(scatter, dtype=float)
        if s.shape != (12,) or not np.all(np.isfinite(s)) or np.any(s < 0):
            raise ValueError("Scatter must be 12 finite nonnegative values.")
        if np.max(s[1:]/np.maximum(p[1:], signal*0.01)) > 0.25:
            reasons.append("Tone power varied >25% within a probe.")
    if reasons: raise ValueError("Rejected measurement: " + " ".join(reasons))
    # Projection onto a physical rank-one response, preserving separately measured magnitudes.
    h = np.array([np.sqrt(left), np.sqrt(right)*np.exp(-1j*np.angle(cross))])/peak
    return {"h": encode(h), "quality": {"snr_db": snr, "relative_residual": residual, "repeat_drift": drift, "cross_consistency": coherence, "background_power": float(p[0])}}


def record(c, payload):
    position = vec(payload["position"], "Microphone position")
    if np.any(position < 0) or np.any(position > c["room"]):
        raise ValueError("Microphone position is outside the room.")
    role = payload.get("role", "train")
    if role not in ("train", "holdout"):
        raise ValueError("Choose train or holdout.")
    if not payload.get("fixed_gain_confirmed"):
        raise ValueError("Confirm fixed microphone gain and unchanged system volume before calibration.")
    out = recover(payload["powers"], float(payload["peak"]), payload.get("scatter"))
    out.update({"position": position.tolist(), "role": role, "signature": signature(c), "frequency": c["frequency"], "session": c["session"],
                "powers": payload["powers"], "peak": payload["peak"], "microphone": str(payload.get("microphone", "unknown"))[:250]})
    return out
