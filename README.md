# MacBook ACC 3D

An independent local project for single-tone and audio-band acoustic contrast control using the **2021 16-inch MacBook Pro's actual stereo output**. It includes a native Core Audio AUHAL tone generator, a 3D simulator, full MacBook pose controls, and microphone calibration / A/B validation.

**Physical accuracy is conditional on measurement.** Apple publishes six drivers, but not the acoustic centers, polar responses, crossover transfer functions, or DSP needed for an exact acoustic model. On this Mac, Core Audio reports **two controllable output channels**. Six independent driver controls are not available through the verified public audio interface. The uncalibrated field is explicitly an estimate. No real acoustic contrast has yet been measured.

## Music and podcast bands

Full-band design supports **20 Hz–20 kHz**, up to **131,072 taps** (0.336 Hz spacing at 44.1 kHz), bounded-memory transfer calculations, and independent spatial-resolution controls. Use **20 Hz–20 kHz · fine** for a 65,536-tap starting point. Large jobs stream rather than failing the old workload cap; convergence diagnostics distinguish frequency resolution from spatial integration accuracy.

The **Program Audio** panel now optimizes phase at each frequency for a whole music or podcast clip. Choose either included sample or upload a WAV, set the band, click **Optimize audio band**, and use the native audio A/B playback buttons. Phase-only and amplitude-plus-phase designs are supported, along with realized-filter validation, integrated 3D fields, frequency plots, and WAV/FIR exports. Both versions play the same band-limited mono program. [Broadband guide and mathematical objective](docs/broadband.md).

## Start

Double-click `run.command`, or run:

```sh
cd "/Users/troytao/acoustic contrast control/macbook-acc-3d"
./run.command
```

Open **http://127.0.0.1:8767**. Run outside Codex's filesystem/process sandbox so Core Audio can enumerate the real device. The server binds only to loopback. Close its Terminal / press Ctrl+C to stop it and playback. The microphone workflow requires a browser supporting localhost microphone access and AudioWorklet (use a normal Chrome or Safari window if the embedded browser cannot grant access).

The launcher compiles the C helper with Apple Command Line Tools, uses its own `.venv` if present, otherwise reuses the adjacent ACC `.venv`. If neither exists it creates a local environment and installs NumPy/SciPy. For a fully independent environment:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
./native/build.sh
.venv/bin/python -m macbook_acc.server
```

`--port 8768` and `--no-browser` are supported. No external JS libraries/CDNs or cloud audio services are used.

## Your room and stand setup

- Room: **10 × 10 m**. **6 m ceiling is only an editable placeholder**, since “very high” does not establish a height. Wall pressure reflection coefficients are also assumptions, not measured material properties.
- MacBook center: initially `(5, 5, 1.4)` m. Change its x/y/z coordinates and **yaw, pitch, roll** freely. The rotation convention is `Rz(yaw) Ry(pitch) Rx(roll)`, applied to local coordinates in metres. Local +z points out of the keyboard/top face; local +x points right, +y toward the user/front edge.
- Sources remain fixed to the MacBook, with estimated effective L/R centers `(±0.15, 0, 0.0168)` m relative to its bottom-plane center. These are **engineering assumptions**, not Apple-measured acoustic centers. Model sound is singularity-softened within 2.5 cm; do not interpret near-source fields literally.
- Optional horizontal desk: 1 m high, initially **disabled** because you use a stand. Enabling it adds a finite specular reflection. It does **not** simulate acoustic blocking beneath a desk, finite-edge diffraction, stand scattering, or lid/body diffraction. The drawn lid is contextual only.
- Initial bright/dark volumes are 12 cm cubes above/below the MacBook. Use “Place zones in front / behind top face” after changing orientation. Those volumes remain world-fixed until you explicitly move them.
- The default radiation model is omnidirectional. Optional broad front-bias patterns are **unmeasured sensitivity assumptions**, not manufacturer polar data. The arrow is a top-face reference, not a certified driver axis.

With the default front/behind setup, the model produces only about **0.66 dB** contrast, essentially the same as equal drive. That is not a meaningful noise-reduction claim. Under reflection-free omnidirectional assumptions, points mirrored across the two-source plane cannot be separated at all: their L/R transfer vectors are identical. Real chassis directivity, diffraction, and reflections may break this symmetry, but only measurement can establish useful improvement. A native front/back level difference must also be distinguished from an improvement caused by ACC.

## A more promising first experiment

The **Try offset front / rear zones** preset moves the bright center 25 cm left and 50 cm out from the top face, and the dark center 25 cm right and 50 cm behind it, in MacBook-local coordinates. With the initial horizontal pose and room assumptions, the model predicts about **19.2 dB** contrast versus **−0.1 dB** equal drive. These are simulation results, not measured hardware performance. The offset breaks the front/back symmetry and is a useful calibration experiment. The main default remains the symmetric geometry so its limitation is visible. A loadable copy is in `examples/offset-front-back.json`.

## Interface

- Orbit/zoom the 3D field; select XY/XZ/YZ sections. Drag a zone on the section to edit its two displayed coordinates; edit full x/y/z centers and volume dimensions numerically. Dashed rectangles indicate zones projected from outside the section plane.
- Set frequency (80–8,000 Hz), temperature, dimensions, each of six pressure-reflection coefficients, reflection order, control spacing and regularization. Sampling automatically refines to at least six points per wavelength in zone integration, subject to explicit workload limits. Display slices/clouds have fixed resolution and can under-resolve high-frequency fields, especially in Room view; they are not the integration grid.
- Compare optimized and equal-drive fields on a shared color scale. Values are **relative pressure**, never uncalibrated dB SPL. View bright/dark level changes as well as contrast, since reducing both zones is not a useful outcome by itself.
- **Play** sends the exact solved complex weights to the native helper, for the displayed optimized/baseline variant. Both variants have unit total squared drive. A shared sample counter produces phase-coherent stereo PCM. Duration is bounded at 30 seconds. Stop, scene edits, closing the page, and server exit stop playback; the native duration deadline also prevents endless sound after a browser failure.
- Digital peak/gain scales the unit-norm playback vector. Default 0.025; per-channel peak is capped at 0.08. This is not a calibrated acoustic loudness limit. System volume is left unchanged; the app detects mute/zero volume and asks you to set a modest volume and re-solve.
- Save/load scenes and export solutions, complex weights, measurements, and listening notes. Persistent measurement data live in `data/measurements.json` and are excluded from source control. No microphone recordings leave the browser; only narrowband powers and metadata are stored locally.

## Calibrate the actual field

You need a **movable microphone** at the bright/dark positions. Keeping the laptop stationary is essential. The built-in microphone cannot sample remote points; moving the laptop to move its microphone invalidates the setup. A fixed-gain measurement microphone is preferable. Phone/continuity microphones may apply processing that the browser cannot disable; treat them as exploratory unless stability is established.

1. Set room, MacBook pose, lid/support, zones, frequency, system volume and digital gain. Keep the physical room still. Choose a measurement session name. Start a new session after changing physical setup, gain, microphone, or volume.
2. Connect the microphone in the browser. Echo cancellation, noise suppression and AGC are requested **off**. Capture is refused if the browser reports these active. Browser settings cannot prove absence of hardware processing; use fixed gain and confirm the checkbox.
3. Enter the microphone's physical x/y/z coordinate. Select **Training**, choose a zone, and use **Next sample point** to propose positions. Physically move the microphone to each coordinate before clicking **Capture channel calibration**. Capture at least **3 distinct positions in each zone**; 6–12 distributed points per zone is a better initial experiment. Do not normalize or change microphone gain between positions.
4. The app plays a background interval, L alone, R alone, eight relative phases of L+R, and L again. Default settle/capture times are 1.5 seconds each (~40 seconds per point). For your large high-ceiling room, increase settling if the tone is still changing; compare repeated measurements. It rejects poor SNR, clipping, repeat drift, power fluctuations, and inconsistent phase fits.
5. Select **Measured calibration points** under optimization. The solver now optimizes the **measured** transfer matrix; it includes the actual chassis, room, support, Apple processing and reflections at those sampled positions. The continuously rendered field is still the geometric approximation, explicitly labeled. We do not fabricate a measured 3D map by interpolating unknown inter-position phase.
6. Collect additional **Holdout** channel-calibration positions at least 1 cm from training positions. These are excluded from the optimization; their predicted contrast is reported separately.
7. Freeze the optimized solution. At new holdout positions, click **Measure actual A/B playback**. It records background, equal drive, optimized, optimized repeat, equal-drive repeat. Keep the same microphone and gain across all bright/dark measurements. The actual contrast card aggregates equal-weight unique sampled positions; at least 3 per zone are required before it is labeled sampled verification. This is evidence at samples, not a certificate of uniform volume suppression. Use a dense spatial scan for stronger claims.
8. If the measured dark zone is poor, add **training** measurements around the failure location and re-optimize, then use fresh holdout locations to avoid tuning to the validation set. Subjective notes are saved but do not alter pressure values automatically.

Calibration is invalidated by frequency, pose, room-model setup, or session changes. Device/sample rate/system volume/mute changes are also checked. Records from incompatible devices are excluded. Microphone identity and digital gain must remain consistent within a session. An unchanged browser label cannot detect manually changed microphone gain: starting a new session remains your responsibility.

Deep nulls below the measured background floor are rejected as unquantifiable; the app does not turn microphone noise into exaggerated contrast. Actual A/B validation compares narrowband powers at the selected frequency, not broadband loudness or harmonic distortion. To claim perceptible improvement, compare both contrast and bright-zone audibility, use repeat trials, and measure multiple spatial positions. A practical experimental target is ≥6 dB measured bright/dark contrast with ≥3 dB gain over equal drive and useful bright-zone level; these are project targets, not psychoacoustic guarantees.

## Numerics and limitations

`H(p,j) = Σ_images r_image D(direction) exp(-ikR)/(4πR)` with `k=2πf/c`, `c=331.3+0.606T`. Room images are truncated by total wall reflection order (0–5). Desk first-bounce reflection is added when its specular point falls on the tabletop. No late diffuse reverberation, frequency-dependent absorption, air absorption, or edge diffraction is included. Finite reflection order is especially approximate for steady tones in reflective halls. Increase order and compare; measured transfer responses are the reliable correction mechanism here.

The optimizer maximizes `qᴴ R_B q / qᴴ (R_D + β·s I) q`, where `R=HᴴH/N`, `s=trace((R_B+R_D)/2)/2`, and `||q||₂=1`. A denser independent model lattice checks zone sampling. Raw contrast is `10 log10(mean|H_B q|² / mean|H_D q|²)`; the regularized objective is not reported as raw acoustic contrast. Training contrast is not validation contrast.

Phase-stepped calibration fits `P(q)=noise+a|qL|²+b|qR|²+2 Re(qL·conj(qR)·c)` for `c=hL·conj(hR)`. Fixing `hL` real positive gives `hR=√b exp(-i arg c)`. A common unknown phase at each spatial point cancels in `HᴴH`, so playback/recording clocks need not synchronize. Per-position amplitude is preserved; fitting must use fixed microphone gain. See [methods](docs/methods.md).

The native AUHAL backend bypasses browser playback, selects the actual built-in speaker device, maps its stereo channels explicitly and uses its current nominal sample rate. It does **not** bypass Apple's internal crossover/protection/EQ, expose six raw DACs, claim exclusive hardware ownership, or stop other apps from playing sound. Pause other audio during calibration. Browser microphone input is separate from the low-level native output path.

The **Program Audio** extension implements frequency-dependent model-based ACC and causal stereo FIR playback for music and podcasts. It does not reuse a single tone vector across the whole recording. The microphone wizard remains single-tone; broadband measured calibration and physical validation remain outstanding. See [the broadband guide](docs/broadband.md).

## Verification

```sh
python -m unittest discover -s tests -v
./bin/macbook-audio devices
# Optional native stream check that emits silence on both channels:
./bin/macbook-audio play 700 0 0 0 0 0.2
```

34 automated tests currently cover 3D propagation, rigid rotations, impossible symmetric front/back separation, image reflections, phase recovery, drift/noise rejection, eigen-solver correctness, calibration invalidation, loopback API controls, measured optimization, actual-measurement aggregation, frequency-band optimization, causal FIR realization, PCM exports, and background-job routing using explicitly synthetic test data in a temporary directory. Integration tests require permission to bind a loopback port. The native stream was opened successfully on the actual MacBook at **44.1 kHz**, with zero-amplitude samples. No actual acoustic or microphone validation was performed.

See [hardware research](docs/hardware-research.md) for sources and the distinction between verified facts and assumptions.
