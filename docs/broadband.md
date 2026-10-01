# Broadband music and podcast control

The Program Audio panel renders a selected clip through **two frequency-dependent FIR filters** and sends the resulting stereo samples to the built-in speaker device via native Core Audio AUHAL. This is audio playback, not a succession of sine-tone demonstrations.

## Use

1. Set the MacBook pose and bright/dark volumes. **Try offset front / rear zones** supplies a more promising starting geometry than symmetric above/below points.
2. In **Program Audio**, choose the bundled music or podcast excerpt, or upload a mono/stereo WAV of 0.5–30 seconds (≤24 MB). Uploaded files remain local.
3. Choose a band (20–20,000 Hz limits, subject to the device sample rate; default **150–4,000 Hz**) and phase-only or amplitude-plus-phase control. Use the approximate room model; single-tone calibration cannot support broadband inference.
4. Click **Optimize audio band**. The app computes the clip's spectrum, optimizes its total band-energy contrast, realizes causal filters, renders both A/B versions and checks their output spectra on independent spatial integration samples.
5. Click **Play optimized audio** and **Play equal-drive audio** while keeping playback gain and system volume fixed. Stop interrupts either. The system speaker rate and device settings are checked before playback; rerender if they change.
6. View the integrated 3D audio field and XY/XZ/YZ sections, per-frequency contrast, and realized R−L phase. Switch back to the single-tone field when inspecting a particular tone.
7. Export the report, both WAVs, and `filters.npz`. Exported WAVs include shared normalization but **do not include the native playback gain**. NPZ contains the exact FIR taps, sample rate, ideal weights and common normalization; use taps with the normalization to reproduce the render.

Changing the source, band or scene marks the previous render stale and disables its playback. An export remains a snapshot of the prior settings. Cancel stops the numerical job; it is separate from Stop audio. Saved render directories remain under `data/broadband/`; export URLs are available for up to eight recent jobs in the current server session.

## Samples and provenance

- **Music:** 12-second flute/drum ensemble test sample from [Samplelib](https://samplelib.com/sample-mp3.html). Its [license page](https://samplelib.com/license.html) states no restrictions on the supplied samples. Downloaded MP3, decoded to 44.1 kHz mono PCM.
- **Podcast:** 20-second excerpt starting at 01:00 of **LibriVox Community Podcast #66**, in the [2007 archive](https://archive.org/details/librivox_community_2007). The freely downloadable episode was used for this local test; the archive metadata did not provide an item-specific license, so no additional redistribution permission is asserted. The source 64 kbps MP3 was decoded to 44.1 kHz mono PCM.

Exact source URLs and attribution are retained in `media/sources.json`. The renderer needs only the bundled WAVs, NumPy and SciPy; it does not download audio at runtime. FFmpeg was used to prepare the excerpts. WAV upload does not require FFmpeg. Stereo uploads are downmixed `(L+R)/2` to one coherent program so both speaker groups can cooperate on spatial control; original stereo imaging is not preserved.

## Whole-band objective

For frequencies f, let `R_B(f)=H_B(f)ᴴ H_B(f)/N_B`, similarly `R_D`. Let `w(f)` be the selected clip's spectral energy times the common band-edge taper squared. The ideal discrete optimization is

```
maximize  Σ_f w(f) q(f)ᴴ R_B(f) q(f)
          ────────────────────────────────────────
          Σ_f w(f) [q(f)ᴴ R_D(f) q(f) + β s(f)]

s(f) = trace((R_B(f)+R_D(f))/2)/2
```

Phase-only control constrains both channel magnitudes to `1/√2` at every frequency. Amplitude-plus-phase constrains `||q(f)||₂=1`. Thus the optimizer cannot win by deleting difficult frequencies or putting all drive into one easy tone. The band is selected explicitly by the user.

This is the ratio of **summed powers**, not an average of decibel contrasts and not independent per-frequency ratio maximization. Dinkelbach iterations choose λ and maximize each bin of `qᴴ(R_B−λ(R_D+βsI))q`. For phase-only control the best relative phase is analytic from the off-diagonal entry; amplitude-plus-phase uses the largest eigenvector of each 2×2 Hermitian difference matrix. The common phase is then aligned across adjacent frequencies without changing the objective. Different program spectra can produce different λ and filters.

The ideal sampled, regularized problem is solved to numerical convergence. That does **not** certify a global optimum among all finite-length filters, perceptual fidelity constraints, continuous frequencies, uncertain rooms, or real hardware. The displayed contrast is raw acoustic power contrast, not the regularized optimization objective.

## Causal realization and fairness

Frequency spacing is `sample_rate / taps`: at 44.1 kHz, 8192 taps give approximately 5.38 Hz. Desired complex responses use real-signal conjugate symmetry, a raised-cosine band-edge taper, inverse FFT, a shared half-length time shift, and a Hann window to make real, causal finite filters. Default shared shift is 92.88 ms. The shift is a design delay; frequency-dependent group delay can vary further.

**Linear FFT convolution** renders the entire clip and retains the FIR tail. There is no circular wraparound into the beginning. Input fades are applied identically before filtering. One normalization factor is chosen from the maximum of both output versions; there is no independent left/right normalization, per-version loudness matching, or limiter that would change the filter phase. The native helper plays the exact stored interleaved Float32 samples multiplied by the same user gain.

Finite filters need not preserve ideal per-frequency magnitudes exactly. Both realized filters and exact rendered-audio spectra are evaluated. Full-clip spectral cross-powers are accumulated into design-frequency cells, then evaluated against room response covariance. The raw contrast is computed from summed bright/dark powers on independent validation samples (a finer midpoint grid or independently scrambled Sobol points). The chart reports per-bin realized performance; the aggregate metric is weighted by the actual selected clip.

The room's frequency response uses the same image sources and desk model as tone mode. The accelerated engine grids each image-path delay onto a 2× oversampled impulse grid with a 64-tap, beta=14 Kaiser-windowed sinc and evaluates the full band with batched FFTs. This is a numerical approximation: every render checks 33 spread-out frequencies at zone probe points against direct complex exponentials and fails if normalized maximum error exceeds 1e-5. Regression tests cover long reflected paths that wrap around the FFT period, rotated sources, the finite desk and different device rates. FFT-period wrapping only evaluates the discrete transfer response; audio convolution remains linear with its full tail. The original direct recurrence remains an independent reference.

Frequency×space arrays are accumulated in small batches rather than allocated for the entire zone. A conservative 48 MiB working-array allowance determines batch size; this is not a total process memory ceiling (audio buffers, reports, Python and libraries also use memory). No frequency bins or reflection orders are silently dropped. Display slices and clouds retain a coarse fixed lattice and cannot resolve every high-frequency local null.

## Full hearing band and spatial convergence

Click **20 Hz–20 kHz · fine** to select the full band and 65,536 taps. At a 44.1 kHz device rate:

| FIR taps | Frequency spacing | Shared filter delay |
|---:|---:|---:|
| 16,384 | 2.692 Hz | 186 ms |
| 32,768 | 1.346 Hz | 372 ms |
| 65,536 | 0.673 Hz | 743 ms |
| 131,072 | 0.336 Hz | 1,486 ms |

The upper edge must be below 49% of the actual output sample rate; 44.1/48 kHz support 20 kHz, 32 kHz does not. The input clip remains limited to 30 seconds, but native PCM playback now permits up to 35 seconds including the longest FIR tail. Finer settings increase calculation time and latency. Jobs report point-by-point batch progress and can be cancelled during transfer calculations and field integration.

**Volume integration** is separate from FIR resolution:

- **Auto** retains the midpoint wavelength grid when its validation point count fits the chosen sample budget. Otherwise it uses scrambled Sobol integration, without allocating a huge dense lattice. At 20 kHz a 12 cm cube would require roughly 80,000 grid points per zone; Auto defaults to 4,096 Sobol points for training and 4,096 independently scrambled points for validation.
- **Scrambled Sobol** always uses 1,024 / 4,096 / 16,384 / 65,536 points per zone. This estimates a volume integral without requiring a wavelength-resolving regular grid. Larger zones and complex fields can need more samples.
- **Wavelength grid** retains every midpoint at the existing λ/6-or-finer spacing, with a separate finer validation grid. It streams all points; it has no old 18,000-point or two-billion-operation broadband cap. Very large volumes can still take hours or longer. The sample-budget selector does not truncate this mode.

Reports show training/validation contrast disagreement, the difference between half and all validation Sobol points, and the 95th percentile of per-bin training/validation disagreement where source energy exceeds −50 dB relative to its largest weighted bin. These are convergence diagnostics, not certified error bounds. A >0.5 dB aggregate disagreement or >3 dB active-bin 95th percentile triggers an advisory to increase spatial samples or compare with the wavelength grid. Half/full Sobol prefixes share points; they are not statistically independent error replicates. Training and validation scrambles are independent. Always compare increasing resolutions before trusting a difficult configuration.

The single-tone panel keeps its separate original sampling limits. A broadband job can run even when the dense single-tone calculation is too large. This does not alter microphone calibration or its original frequency range.

A complete 20 Hz–20 kHz music render at 65,536 taps, 4,096 samples per zone and third-order reflections (including all three field slices and the 3D cloud) took **109 seconds** on this Mac and peaked at about **387 MiB process memory**. Its transfer probe error was 5.1×10⁻⁸ normalized to the largest direct response. Exact scene/options and convergence results are saved in `examples/full-band-check.json`. Runtime varies with taps, point count and reflections; this is one benchmark, not a timing guarantee.

For the same 12 cm zones, an additional direct-path comparison at nine frequencies from 20 Hz through 20 kHz compared 4,096 Sobol validation points with all **79,507** validation-grid points per zone. The largest covariance-matrix relative error was **0.155%**. This checks that particular geometry, not arbitrary zones. Results are in `examples/full-band-spatial-check.json`.

Supporting implementation references: [SciPy scrambled Sobol integration](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.qmc.Sobol.html) and [batched real FFTs](https://docs.scipy.org/doc/scipy/reference/generated/scipy.fft.rfft.html).

## Band limitation and interpretation

Both versions remove content outside the selected band. “Source energy inside band” reports the original clip's energy in that frequency interval, before tapering and normalization. It is not a claim that the original full-band music is reproduced unchanged. The default band contains about **78.2%** of the music excerpt's energy and **97.1%** of the podcast excerpt's energy. Use a wider band if fidelity matters, while checking whether contrast deteriorates.

Predictions for the included offset geometry at 150–4,000 Hz and phase-only control are approximately **10.1 dB** for music versus **0.2 dB** equal drive, and **14.4 dB** for the podcast versus **0.4 dB** equal drive. These are model predictions, not microphone results. Reproducible 8192/16384-tap comparisons are saved in `examples/broadband-check.json`.

20 Hz–20 kHz is the supported numerical design range, not a measured usable response of these MacBook speakers. More frequency bins do not establish speaker output at 20 Hz or correct the unmeasured radiation, DSP and room model.

The existing microphone wizard is explicitly **single-tone**. No broadband calibration or actual broadband measurement is claimed. A physical broadband implementation needs measured frequency-dependent transfer responses throughout both zones, consistent relative channel phase, and independent actual-program A/B measurements. Speaker DSP/nonlinearity, room changes and unknown radiation patterns still limit an uncalibrated geometric model.

## Tests and references

The suite includes numerical comparison with exhaustive phase search for a two-bin example; phase-only versus complex control; exact tone/sweep agreement; spectral-energy conservation against a time-domain mixture; no circular wraparound; rendered WAV/PCM equality; shared A/B gain; stale-scene rejection; background-job and export routing; and single-tone-calibration rejection for broadband mode. Native PCM device access was also tested with a silent buffer.

Primary implementation references: [SciPy linear FFT convolution](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.fftconvolve.html), [SciPy FIR frequency-sampling implementation](https://github.com/scipy/scipy/blob/main/scipy/signal/_fir_filter_design.py), and [Apple AUHAL documentation](https://developer.apple.com/library/archive/technotes/tn2091/_index.html). The project implements complex two-channel FIR construction directly; `firwin2` alone does not implement these arbitrary complex responses.
