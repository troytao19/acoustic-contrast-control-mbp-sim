# Measurement protocol and validity

## Two-channel response

At one frequency, position i receives `p_i=h_iL q_L+h_iR q_R`. The two complex responses include the entire speaker groups and Apple processing. They are needed only up to a common phase per position, and remain valid only with fixed physical conditions and operating level.

For a stationary microphone, the probe vectors (before common digital gain) are silence, `(1,0)`, `(0,1)`, eight `(1,exp(iφ))` with φ=0°,45°,…315°, then `(1,0)` again.

Fit twelve powers to `[noise,a,b,Re(c),Im(c)]`, using rows `[1,|qL|²,|qR|²,2Re(qL conj(qR)),-2Im(qL conj(qR))]`. Here `a=|hL|²`, `b=|hR|²`, `c=hL conj(hR)` including squared probe gain. Reconstruction chooses `hL=√a/gain`, `hR=√b exp(-i arg(c))/gain` and projects to a physical rank-one response.

Measured amplitudes are preserved between positions. Normalizing each row would erase the relative levels between zones. A common row phase cancels in `h_iᴴ h_i`; playback and recording clocks need not synchronize. This does not recover absolute propagation phase or broadband impulse responses.

## Microphone capture

An AudioWorklet receives uncompressed Float32 samples and estimates cosine/sine amplitude at the requested frequency using a Hann window for each 4,096-sample block. Power is squared sinusoidal peak amplitude; its common RMS factor cancels in contrast. Blocks are averaged after configurable settling. Worklet output is explicitly silent, preventing microphone monitoring. Only powers, scatter, and metadata reach the local server.

Small clock-rate differences and arbitrary initial phase are tolerated. Motion, significant drift, hardware AGC, changing gain, coherent interference at the test frequency, and nonlinear speaker processing can invalidate the result. Background subtraction approximates incoherent noise; it cannot reliably remove a coherent interfering tone. Pause other audio. Harmonics/broadband loudness are outside this metric.

## Acceptance thresholds

- Reject microphone peaks ≥0.98 full scale.
- Require ≥15 dB tone/background power SNR for both channels.
- Reject fit RMS >10% of combined channel power.
- Reject repeated left-channel drift >12%.
- Require `|c|/√(ab)` between 0.8 and 1.2 before rank-one projection.
- Reject within-probe scatter >25%, with a small floor for phase nulls.
- Bind records to setup, microphone identity, digital gain, device, rate, volume and mute.

These are engineering screening thresholds, not confidence bounds. For example, 10% fitting error does not justify a 40 dB null claim. Independent actual playback is required.

## Independent validation

Training points determine weights. Transfer holdouts do not enter optimization. The interface reports their predictions separately from actual A/B playback.

Actual validation records background, baseline, optimized, optimized repeat, baseline repeat at each fixed position. It rejects <10 dB SNR, >15% repeat drift, or >25% within-step scatter. The two repetitions are averaged and background subtracted. Records include the exact weight/zone/setup fingerprint.

Three distinct positions per zone are required for “sampled verification”; duplicates use the latest value once. Training and holdout points must be at least 1 cm apart. Contrast is the ratio of average **linear powers**, not an average of dB readings. Baseline and optimized playback have equal total squared drive.

This verifies samples only. A spatial scan with wavelength-appropriate spacing and repeated trials is necessary for a volume claim. Include centimetre-scale offsets to test robustness to head motion. After adapting weights based on holdout results, use fresh holdouts.

## Front/back limitation

For two omnidirectional sources in a plane, points mirrored across that plane have identical distances to each source and identical transfer vectors in free space. Every stereo weighting gives equal power at those points. No optimizer can overcome that symmetry under those assumptions.

Chassis diffraction, ports, directivity and reflections may break symmetry, but both speaker groups might share almost the same front/back ratio, leaving little additional control. Reflections can make cancellation more fragile. Measure the actual stand/lid/room setup rather than infer performance from hypothetical directivity.

## Broadband extension

The app now implements model-based music and podcast optimization with frequency-dependent stereo weights, causal FIR filters, shared playback headroom, and evaluation of the rendered audio. See [Broadband audio](broadband.md) for the whole-band objective and its limits. Physical accuracy still requires measured frequency-dependent transfer matrices and independent broadband playback validation. Single-tone microphone calibration cannot validate or calibrate a whole audio band.
