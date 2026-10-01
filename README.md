# MacBook ACC 3D
> **AI use disclaimer**: I wrote this simulation software as an experiment for an interest project. AI agents participated extensively in developing the optimization algorithm and the interactive interface, as well as the README.md. Please use and read them with caution. 

An experimental 3D acoustic contrast control (ACC) app for the **2021 16-inch MacBook Pro**. Define a bright zone and a dark zone, optimize the relative phase and amplitude of the laptop's two speaker channels, and compare optimized audio with an equal-drive baseline through the built-in speakers.

The app runs locally with a Python solver, a browser interface, and a native Core Audio playback helper.

> **Simulation results are predictions, not measured sound levels.** Speaker locations and radiation patterns are approximate. Microphone calibration and validation are available for single tones; broadband microphone calibration is not implemented. Physical broadband contrast has not been verified.

## Features

- Interactive 3D room and XY/XZ/YZ field views with editable bright and dark volumes.
- Adjustable MacBook position, yaw, pitch, and roll; speaker groups remain fixed to the chassis.
- Configurable room reflections and an optional finite tabletop reflection.
- Single-tone optimization and frequency-dependent filters for music, speech, or uploaded WAV files.
- Native stereo playback with optimized/equal-drive comparisons and a Stop control.
- Single-tone microphone calibration, independent validation measurements, and listening notes.
- Scene, report, WAV, and FIR-filter exports.

## Requirements

- **macOS** for native Core Audio playback. The target hardware is the 2021 16-inch MacBook Pro; other models are not validated.
- **Python 3.10 or newer**, with NumPy and SciPy from [requirements.txt](requirements.txt).
- **Apple Command Line Tools** to compile the audio helper. Install them with `xcode-select --install` if needed.
- A browser with Canvas support. Microphone measurements also require AudioWorklet and permission to access a microphone on localhost.
- A **movable microphone** for measurements at the listening zones. The laptop's built-in microphone cannot sample remote positions while the laptop stays fixed.

A microphone is optional for simulation and playback.

## Installation and launch

Clone or download this repository, open a terminal in its root directory, then run:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
./run.command
```

The launcher compiles the native helper and opens **http://127.0.0.1:8767/**. Keep the terminal running; press **Ctrl+C** to stop the server and playback. After installation, double-clicking `run.command` also launches the app.

Optional launch settings:

```sh
./run.command --port 8768
./run.command --no-browser
```

Creating the project-local `.venv` as shown above keeps dependencies independent. If it is absent, the launcher also checks for a parent `.venv` before creating its own environment.

No JavaScript packages, CDNs, or cloud audio services are required. The server listens only on `127.0.0.1`.

## Quick start

1. **Set the scene.** Enter the room dimensions and MacBook position and orientation. The initial 10 × 10 × 6 m room, reflection coefficients, and disabled tabletop are example settings—not measurements of your room.
2. **Place the zones.** Drag them in a section view or edit their centers and dimensions. Start with **Try offset front / rear zones** to break the default front/back symmetry. Zones remain fixed in world coordinates when the MacBook rotates until you reposition them.
3. **Choose audio.** In **Program Audio**, select a sample or upload a mono/stereo WAV lasting 0.5–30 seconds and no larger than 24 MB.
4. **Choose a band.** Begin with the default 150–4,000 Hz band, or click **20 Hz–20 kHz · fine** for a full-band design. Choose phase-only or amplitude-plus-phase control.
5. **Optimize.** Click **Optimize audio band** and wait for the render. Larger jobs report progress and can be cancelled.
6. **Compare playback.** Use **Play optimized audio** and **Play equal-drive audio** at the same playback gain and system volume. The app leaves system volume unchanged. Compare bright-zone level, dark-zone level, and contrast together.
7. **Inspect or export.** View the integrated audio field and frequency plot, or export the rendered WAVs, FIR filters, and report.

Stereo input is downmixed to one mono program before separate filters drive the left and right speaker groups. Both playback versions remove content outside the selected band and use a shared normalization. Original stereo imaging is not preserved. Exported WAVs do not include the additional playback-gain setting.

For a single-tone experiment, set **Frequency** in the source panel, click **Optimize contrast**, and open **Single-tone audition and channel weights**.

## Frequency and spatial resolution

Broadband design supports **20 Hz–20 kHz**, subject to the output device's sample rate. A 44.1 or 48 kHz output rate supports the full range; a 32 kHz rate does not. Single-tone controls and microphone measurements use **80–8,000 Hz**.

At a 44.1 kHz output rate:

| FIR taps | Frequency spacing | Shared filter delay |
| ---: | ---: | ---: |
| 8,192 | 5.383 Hz | 93 ms |
| 16,384 | 2.692 Hz | 186 ms |
| 32,768 | 1.346 Hz | 372 ms |
| 65,536 | 0.673 Hz | 743 ms |
| 131,072 | 0.336 Hz | 1,486 ms |

Finer filters take longer to calculate and add playback delay. They do not improve an inaccurate physical model by themselves.

**Volume integration** controls spatial accuracy separately:

- **Auto** uses a wavelength-based grid for smaller jobs and scrambled Sobol samples for larger jobs.
- **Scrambled Sobol** uses the selected sample count, up to 65,536 points per zone, with independent training and validation sets.
- **Wavelength grid** retains every grid point and processes them in batches. Large volumes can take much longer to calculate.

The solver processes responses in bounded-memory batches. Review the convergence diagnostics and compare increasing resolutions before relying on a prediction. The displayed field uses a coarser grid and cannot show every local pressure minimum.

See the [broadband guide](docs/broadband.md) for the objective, filter construction, spatial checks, and benchmarks.

## Microphone calibration

This workflow measures **one frequency at a time**. It does not calibrate or validate a whole music or podcast band.

1. Keep the laptop, stand, lid angle, room, system volume, and playback gain fixed. Start a measurement session and connect a movable microphone with stable gain.
2. Move the microphone to each entered coordinate and capture **Training** channel calibration at at least three distinct positions in each zone. Distribute points throughout the volumes.
3. Select **Measured calibration points** to optimize using those measurements. The continuous 3D map remains a geometric estimate.
4. Collect separate **Holdout** positions, then use **Measure actual tone A/B playback** to compare the fixed optimized solution against equal drive. At least three distinct positions per zone are required for sampled verification.
5. If the result is poor, add training points and re-optimize, then validate at fresh positions. Listening notes are saved but do not automatically change the pressure model.

The app checks clipping, background noise, repeat drift, and reported microphone processing. Start a new session when the physical setup or microphone gain changes. Verification at a few positions does not establish uniform suppression throughout a volume.

See [measurement methods and acceptance checks](docs/methods.md) for the protocol and its limits.

## Hardware and model limitations

The laptop contains six physical drivers, but the tested macOS interface exposes **two controllable output channels**. This app controls the left and right groups; it does not address six independent drivers or bypass Apple's internal crossover, equalization, or protection processing.

The effective source centers at ±15 cm, radiation patterns, and reflection coefficients are modeling assumptions. The model includes truncated image-source reflections and an optional specular tabletop reflection. It omits late diffuse reverberation, frequency-dependent absorption, acoustic shielding, and diffraction from the chassis, lid, tabletop edges, or stand. Field colors are relative levels, not calibrated dB SPL.

With two omnidirectional sources, symmetric points in front of and behind the source plane have identical free-field responses. No stereo weighting can separate those points under that model. The offset preset avoids this symmetry, but useful physical contrast still needs measurement. Supporting a 20 Hz–20 kHz numerical range does not establish usable MacBook speaker output across that range.

See [hardware research and Apple sources](docs/hardware-research.md) for verified specifications and assumptions.

## Project layout and local data

| Location | Contents |
| --- | --- |
| `macbook_acc/` | Acoustic model, optimizers, calibration, and HTTP server |
| `native/` | Core Audio C helper and build script |
| `web/` | Browser interface |
| `docs/` | Hardware research, measurement methods, and broadband details |
| `examples/` | Example scene and numerical checks |
| `media/` | Sample audio and source metadata |
| `tests/` | Numerical and local API regression tests |
| `data/measurements.json` | Local calibration records, validation results, and notes |
| `data/uploads/` | Uploaded WAV files |
| `data/broadband/` | Rendered audio, filters, and reports |

Generated data, virtual environments, and compiled binaries are excluded by [.gitignore](.gitignore). Microphone recordings remain in the browser; only derived measurement powers and metadata are sent to the local server. Uploads and renders stay on the machine. Export links refer to recent jobs in the current server session; generated files remain on disk after a restart.

## Tests

From the repository root:

```sh
.venv/bin/python -m unittest discover -s tests -v
```

The suite covers propagation, calibration, optimization, full-band transfer accuracy, streamed spatial integration, FIR rendering, and local API behavior. API tests bind a loopback port and use temporary data and mocked audio playback.

To inspect the native device route after building:

```sh
./bin/macbook-audio devices
```

Automated tests and successful device access do not substitute for acoustic measurements.

## Troubleshooting

| Problem | What to check |
| --- | --- |
| Native helper fails to build | Install Apple Command Line Tools and verify `xcrun clang --version` works. |
| Missing NumPy or SciPy | Install requirements using `.venv/bin/python -m pip`; use the same environment to launch and test. |
| Port 8767 is occupied | Launch with `./run.command --port 8768`. |
| No built-in speaker route | Inspect `./bin/macbook-audio devices`. The helper requires built-in stereo speakers and currently recognizes English speaker names. It does not fall back to headphones or Bluetooth. |
| Microphone access fails | Grant browser and macOS microphone permission. Try a regular browser window if an embedded browser cannot grant access. |
| Playback becomes stale | Re-optimize after changing the scene, band, source, device rate, or output settings. |
| Full-band optimization is slow | Reduce FIR taps or spatial samples for a preview, then increase them and compare convergence. Use **Cancel optimization** to stop the job. |
| Prediction differs from listening | Check coordinates, pose, volume, and model assumptions. Use single-tone microphone calibration to investigate; broadband physical calibration remains unimplemented. |

## Sample audio and licensing

Sample attribution and source metadata are recorded in [media/sources.json](media/sources.json). The music sample comes from Samplelib; the speech excerpt comes from LibriVox Community Podcast #66. The podcast archive metadata did not specify an item-level license, so the local excerpt should not be assumed cleared for redistribution.

No project software license is currently included. Sample-audio terms are separate from any software license added to the project.
