# Hardware evidence and assumptions

Research and local inspection: 2026-09-29 (local date). Target machine: MacBookPro18,1 / Apple M1 Pro. No device serial numbers are stored in this project.

| Item | Evidence | Consequence |
|---|---|---|
| Chassis | Apple: 35.57 cm wide × 24.81 cm deep × 1.68 cm high | Drawing uses these dimensions; closed height is not measured radiator height. |
| Six drivers | Apple launch announcement: two tweeters and four force-cancelling woofers | Driver count does not imply six software-addressable channels. |
| Physical assemblies | Apple's exploded view identifies left/right speaker assemblies; repair procedure replaces both | Assembly location is established qualitatively. |
| Acoustic centers/directions | No dimensioned acoustic centers or polar data found in consulted official material; replacement procedure says some images may depict other models | Do not derive purported millimetre-accurate acoustic positions or radiation axes from these drawings. |
| macOS output | Native HAL inspection: MacBook Pro Speakers, 2 output channels, built-in transport, 44,100 Hz | Optimize two group signals; identify this route rather than the default output. |
| macOS input | HAL inspection: built-in microphone exposes one input channel | Not three separately accessible microphones; cannot sample remote listening zones. |
| Low-level interface | Apple AUHAL technical note documents device selection, PCM formats and channel mapping | C helper uses AUHAL render callbacks and explicit built-in device binding. |
| Electroacoustic response | No published complex group transfer function, crossover phase or polar response found in consulted sources | Empirical per-position transfer calibration is required. |

Sources:

1. [Apple technical specifications](https://support.apple.com/en-us/111901): dimensions, six-speaker system, force-cancelling woofers, wide stereo, microphone array.
2. [Apple's 2021 MacBook Pro announcement](https://www.apple.com/newsroom/2021/10/apple-unveils-game-changing-macbook-pro/): explicit two-tweeter/four-woofer description.
3. [Apple repair manual](https://support.apple.com/en-sa/100568): official manual ID HFXVCU.
4. [Apple exploded view and parts](https://support.apple.com/en-sa/100569): left/right assemblies; not a dimensioned acoustic drawing.
5. [Apple speaker replacement procedure](https://support.apple.com/en-sa/122025): paired replacement; illustrations may depict other models.
6. [Apple TN2091: HAL Output Audio Unit](https://developer.apple.com/library/archive/technotes/tn2091/_index.html): AUHAL device selection, stream formats and channel maps. This project uses the output side.

The ±150 mm lateral offsets, centerline longitudinal positions, top-surface offsets, optional broad directional patterns, reflection coefficients, and 6 m ceiling placeholder are **model assumptions**, not manual measurements. Cone orientation and assembled-laptop effective radiation direction differ. Mechanical force cancellation does not establish an acoustic rear null.

The two-channel limit is established by querying this machine, not inferred from stereo marketing. The helper fails if it cannot identify a built-in stereo speaker route; it never substitutes Bluetooth, headphones, ZoomAudioDevice, or a guessed six-channel layout. Name matching currently recognizes English speaker labels; localized names may need an explicit audited route mapping.

A silent AUHAL stream proves device access only. It does not prove acoustic response, channel separation, sound level, model accuracy, or achievable contrast. Physical validation remains outstanding.
