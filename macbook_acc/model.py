"""3D image-source approximation and measured-point acoustic contrast control.

Time convention: p(t)=Re{H q exp(+i wt)}; outgoing Green function exp(-ikr)/(4pi r).
There are TWO controllable sources, not six independently addressable drivers.
"""
import copy
import hashlib
import itertools
import json
import numpy as np
from scipy.linalg import eigh

DEFAULT = {
    "frequency": 700.0, "temperature": 20.0, "room": [10.0, 10.0, 6.0],
    "reflection": [0.55, 0.55, 0.55, 0.55, 0.65, 0.45], "order": 3,
    "laptop": [5.0, 5.0, 1.4], "yaw": 0.0, "pitch": 0.0, "roll": 0.0,
    "directivity": 0.0,
    "desk": {"enabled": False, "center": [5.0, 5.0], "height": 1.0, "width": 1.4, "depth": 0.7, "reflection": 0.65},
    "bright": {"center": [5.0, 5.0, 1.9], "size": [0.12, 0.12, 0.12]},
    "dark": {"center": [5.0, 5.0, 0.9], "size": [0.12, 0.12, 0.12]},
    "spacing": 0.035, "regularization": 0.01, "slice_z": 1.4,
    "view_span": 2.4, "mode": "model", "session": "session-1",
}
# Explicit engineering assumptions, not measurements from Apple drawings.
OFFSETS = np.array([[-0.15, 0.0, 0.0168], [0.15, 0.0, 0.0168]])


def finite(value, name, lo, hi):
    v = float(value)
    if not np.isfinite(v) or not lo <= v <= hi:
        raise ValueError(f"{name} must be between {lo} and {hi}.")
    return v


def vec(value, name, n=3):
    a = np.asarray(value, dtype=float)
    if a.shape != (n,) or not np.all(np.isfinite(a)):
        raise ValueError(f"{name} must contain {n} finite numbers.")
    return a


def config(raw, check_sampling=True):
    if not isinstance(raw, dict):
        raise ValueError("Scene must be an object.")
    c = copy.deepcopy(DEFAULT)
    for k, v in raw.items():
        if k not in c:
            raise ValueError(f"Unknown scene field: {k}")
        c[k] = copy.deepcopy(v)
    c["frequency"] = finite(c["frequency"], "Frequency", 80, 8000)
    c["temperature"] = finite(c["temperature"], "Temperature", 0, 40)
    room = vec(c["room"], "Room")
    if np.any(room < 1.5) or np.any(room > 15):
        raise ValueError("Room dimensions must be 1.5–15 m.")
    c["room"] = room.tolist()
    refl = vec(c["reflection"], "Pressure reflection coefficients", 6)
    if np.any(refl < 0) or np.any(refl > 0.95):
        raise ValueError("Reflection coefficients must be 0–0.95.")
    c["reflection"] = refl.tolist()
    order = finite(c["order"], "Image order", 0, 5)
    if order != int(order):
        raise ValueError("Image order must be an integer.")
    c["order"] = int(order)
    for angle in ("yaw", "pitch", "roll"):
        c[angle] = finite(c[angle], "Laptop " + angle, -180, 180)
    c["directivity"] = finite(c["directivity"], "Assumed directionality", 0, 0.45)
    laptop = vec(c["laptop"], "Laptop center")
    if np.any(laptop < [0.25, 0.25, 0.2]) or np.any(laptop > room - [0.25, 0.25, 0.3]):
        raise ValueError("Laptop must fit inside the room, above the floor.")
    c["laptop"] = laptop.tolist()
    desk = c["desk"]
    c["desk"] = {"enabled": bool(desk["enabled"]), "center": vec(desk["center"], "Desk center", 2).tolist(),
                 "height": finite(desk["height"], "Desk height", 0.2, room[2]-0.2),
                 "width": finite(desk["width"], "Desk width", 0.4, 3),
                 "depth": finite(desk["depth"], "Desk depth", 0.3, 2),
                 "reflection": finite(desk["reflection"], "Desk reflection", 0, 0.95)}
    half = np.array([c["desk"]["width"], c["desk"]["depth"]])/2
    if c["desk"]["enabled"] and (np.any(np.array(c["desk"]["center"])-half < 0) or np.any(np.array(c["desk"]["center"])+half > room[:2])):
        raise ValueError("The tabletop extends outside the room.")
    for key in ("bright", "dark"):
        z = c[key]
        center, size = vec(z["center"], key + " center"), vec(z["size"], key + " size")
        if np.any(size < 0.02) or np.any(size > 1.5) or np.any(center-size/2 < 0.03) or np.any(center+size/2 > room-0.03):
            raise ValueError("Zones must fit inside the room, with dimensions 0.02–1.5 m.")
        c[key] = {"center": center.tolist(), "size": size.tolist()}
    if np.all(np.abs(vec(c["bright"]["center"], "center")-vec(c["dark"]["center"], "center")) < (vec(c["bright"]["size"], "size")+vec(c["dark"]["size"], "size"))/2):
        raise ValueError("Bright and dark volumes must not overlap.")
    c["spacing"] = finite(c["spacing"], "Control spacing", 0.01, 0.2)
    c["regularization"] = finite(c["regularization"], "Regularization", 1e-6, 1)
    c["slice_z"] = finite(c["slice_z"], "Slice height", 0.03, room[2]-0.03)
    c["view_span"] = finite(c["view_span"], "View span", 0.8, 20)
    if c["mode"] not in ("model", "measured"):
        raise ValueError("Mode must be model or measured.")
    c["session"] = str(c["session"])[:120]
    if check_sampling:
        for key in ("bright", "dark"):
            zone_points(c, key, True)  # single-tone dense-grid allocation guard
    return c


def signature(c):
    """Calibration invalidated by physical setup/frequency/session changes, not zones."""
    keys = ("frequency", "temperature", "room", "reflection", "order", "laptop", "yaw", "pitch", "roll", "directivity", "desk", "session")
    return hashlib.sha256(json.dumps({k: c[k] for k in keys}, sort_keys=True).encode()).hexdigest()[:20]


def rotation(c):
    yaw, pitch, roll = np.deg2rad([c["yaw"], c["pitch"], c["roll"]])
    rz = np.array([[np.cos(yaw), -np.sin(yaw), 0], [np.sin(yaw), np.cos(yaw), 0], [0, 0, 1]])
    ry = np.array([[np.cos(pitch), 0, np.sin(pitch)], [0, 1, 0], [-np.sin(pitch), 0, np.cos(pitch)]])
    rx = np.array([[1, 0, 0], [0, np.cos(roll), -np.sin(roll)], [0, np.sin(roll), np.cos(roll)]])
    return rz @ ry @ rx


def sources(c):
    return OFFSETS @ rotation(c).T + np.array(c["laptop"])


def zone_points(c, key, validation=False):
    center, size = np.array(c[key]["center"]), np.array(c[key]["size"])
    spacing = min(c["spacing"], (331.3+0.606*c["temperature"])/c["frequency"]/6)
    counts = np.maximum(2, np.ceil(size/spacing).astype(int)) + (1 if validation else 0)
    if np.prod(counts) > 18000:
        raise ValueError("Zone sampling exceeds 18,000 points; reduce zone sizes/frequency or increase spacing.")
    axes = [center[i]-size[i]/2+(np.arange(counts[i])+0.5)*size[i]/counts[i] for i in range(3)]
    return np.stack(np.meshgrid(*axes, indexing="ij"), axis=-1).reshape(-1, 3)


def inside(points, zone):
    return np.all(np.abs(np.asarray(points)-np.array(zone["center"])) <= np.array(zone["size"])/2+1e-9, axis=-1)


def image_sources(c, s):
    """Rectangular-room images, truncated by total wall-reflection count."""
    dims, r, order = c["room"], c["reflection"], c["order"]
    axes = []
    for d in range(3):
        images = []
        for n in range(-order-1, order+2):
            for parity in (0, 1):
                lower, upper = abs(n-parity), abs(n)
                if lower+upper <= order:
                    images.append((2*n*dims[d]+(-1)**parity*s[d], lower+upper, r[2*d]**lower*r[2*d+1]**upper, (-1)**parity))
        axes.append(images)
    for triple in itertools.product(*axes):
        if sum(t[1] for t in triple) <= order:
            yield np.array([t[0] for t in triple]), np.prod([t[2] for t in triple]), np.array([t[3] for t in triple])


def transfer(c, points):
    """Effective L/R sources; optional unmeasured broad directivity prior."""
    points = np.asarray(points, dtype=float)
    k = 2*np.pi*c["frequency"]/(331.3+0.606*c["temperature"])
    h = np.zeros((len(points), 2), dtype=complex)
    for j, s in enumerate(sources(c)):
        normal = rotation(c)[:, 2]
        def directional(delta, norm):
            cosine = delta @ norm / np.maximum(np.linalg.norm(delta, axis=1), 1e-12)
            return 1-c["directivity"]+c["directivity"]*cosine
        for image, gain, parity in image_sources(c, s):
            if gain == 0:
                continue
            d = np.maximum(np.linalg.norm(points-image, axis=1), 0.025)
            h[:, j] += gain*directional(points-image, normal*parity)*np.exp(-1j*k*d)/(4*np.pi*d)
        # First specular reflection from finite horizontal desk, only if ray hits tabletop.
        if c["desk"]["enabled"] and c["desk"]["reflection"] and c["order"]:
            desk_z = c["desk"]["height"]
            image = s.copy(); image[2] = 2*desk_z-s[2]
            denom = points[:, 2]-image[2]
            t = np.divide(desk_z-image[2], denom, out=np.zeros(len(points)), where=np.abs(denom)>1e-9)
            hit = image + t[:, None]*(points-image)
            xy = hit[:, :2]-np.array(c["desk"]["center"])
            mask = (((points[:, 2]-desk_z)*(s[2]-desk_z) > 0) & (np.abs(xy[:, 0]) <= c["desk"]["width"]/2) & (np.abs(xy[:, 1]) <= c["desk"]["depth"]/2))
            d = np.maximum(np.linalg.norm(points-image, axis=1), 0.025)
            h[:, j] += mask*c["desk"]["reflection"]*directional(points-image, normal*np.array([1, 1, -1]))*np.exp(-1j*k*d)/(4*np.pi*d)
    return h


def optimize(hb, hd, beta):
    rb, rd = hb.conj().T@hb/len(hb), hd.conj().T@hd/len(hd)
    scale = max(float(np.trace((rb+rd)/2).real/2), 1e-20)
    _, v = eigh(rb, rd+beta*scale*np.eye(2))
    q = v[:, -1]
    q *= np.exp(-1j*np.angle(q[np.argmax(np.abs(q))]))
    return q / np.linalg.norm(q)


def metrics(hb, hd, q):
    b, d = np.abs(hb@q)**2, np.abs(hd@q)**2
    return {"contrast_db": float(10*np.log10(max(np.mean(b), 1e-30)/max(np.mean(d), 1e-30))),
            "bright_power": float(np.mean(b)), "dark_power": float(np.mean(d)),
            "bright_p10_power": float(np.percentile(b, 10)), "dark_p90_power": float(np.percentile(d, 90))}


def decode_weights(raw):
    a = np.asarray(raw, dtype=float)
    if a.shape != (2, 2) or not np.all(np.isfinite(a)):
        raise ValueError("Weights must contain two [real, imaginary] pairs.")
    q = a[:, 0]+1j*a[:, 1]
    if np.max(np.abs(q)) > 1.000001:
        raise ValueError("Each weight magnitude must be at most one.")
    return q


def encode(q):
    return [[float(v.real), float(v.imag)] for v in q]


def measured_matrices(c, records, role):
    result = []
    valid = [r for r in records if r.get("signature") == signature(c) and r.get("role") == role]
    for key in ("bright", "dark"):
        group = [r for r in valid if inside(r["position"], c[key])]
        # Avoid letting repeated clicks at one coordinate pretend to be spatial coverage.
        unique = {tuple(np.round(r["position"], 4)): r for r in group}
        rows = [np.array(r["h"])[:, 0]+1j*np.array(r["h"])[:, 1] for r in unique.values()]
        result.append(np.array(rows, dtype=complex).reshape(-1, 2))
    return result


def solve(raw, records=()):
    c = config(raw)
    bp, dp = zone_points(c, "bright"), zone_points(c, "dark")
    hb, hd = transfer(c, bp), transfer(c, dp)
    vbp, vdp = zone_points(c, "bright", True), zone_points(c, "dark", True)
    vhb, vhd = transfer(c, vbp), transfer(c, vdp)
    warnings = ["Uncalibrated 3D map: effective source centers and radiation response are estimates; colors are relative, not dB SPL."]
    warnings.append("Ceiling defaults to 6 m because its actual height is unknown. Stand/lid/body scattering and late reverberation are not modeled.")
    warnings.append("Two channels cannot generally create a large quiet volume behind the laptop. Symmetric front/back points have identical responses in the free-field omni model.")
    if c["directivity"]:
        warnings.append("Directionality is an assumed broad pattern, not measured Apple polar data. Front/back level difference may come from this assumption, not ACC.")
    if c["desk"]["enabled"]:
        warnings.append("Desk model includes a specular reflection, not transmission loss, diffraction, or acoustic shielding underneath.")
    if c["mode"] == "measured":
        ob, od = measured_matrices(c, records, "train")
        if min(len(ob), len(od)) < 3:
            raise ValueError("Measured optimization needs at least 3 distinct accepted training positions inside EACH current zone, at this frequency/setup/session.")
        warnings.append("Weights use measured points. The continuous field remains the approximate room model; no measured coverage is implied between points.")
    else:
        ob, od = hb, hd
    q = optimize(ob, od, c["regularization"])
    baseline = np.ones(2, dtype=complex)/np.sqrt(2)
    validation = metrics(vhb, vhd, q)
    measured = None
    mb, md = measured_matrices(c, records, "holdout")
    if min(len(mb), len(md)) >= 1:
        measured = {"optimized": metrics(mb, md, q), "baseline": metrics(mb, md, baseline), "counts": [len(mb), len(md)],
                    "label": "Held-out transfer prediction; run A/B measurements to verify actual playback."}
    if min(len(mb), len(md)) < 3:
        warnings.append("Real zone contrast is unverified: collect separate holdout positions and actual baseline/optimized playback measurements.")
    if abs(validation["contrast_db"] - metrics(hb, hd, q)["contrast_db"]) > 1:
        warnings.append("Model contrast changes >1 dB on a finer lattice; refine sampling before interpreting it.")
    if max(c["reflection"]) >= 0.7:
        warnings.append("Reflective room: truncated images omit late reverberation. Compare reflection orders and prefer measured optimization.")
    # All three orthogonal slices and a volumetric cloud use the same reference.
    low = np.maximum(0.03, np.array(c["laptop"])-c["view_span"]/2)
    high = np.minimum(np.array(c["room"])-0.03, np.array(c["laptop"])+c["view_span"]/2)
    axes = [np.linspace(low[i], high[i], 82) for i in range(3)]
    planes, amplitudes = {}, []
    for plane, dims, fixed, value in (("xy", (0,1), 2, c["slice_z"]), ("xz", (0,2), 1, c["laptop"][1]), ("yz", (1,2), 0, c["laptop"][0])):
        uu, vv = np.meshgrid(axes[dims[0]], axes[dims[1]])
        points = np.zeros((uu.size, 3)); points[:, dims[0]]=uu.ravel(); points[:, dims[1]]=vv.ravel(); points[:, fixed]=value
        h = transfer(c, points)
        planes[plane] = {"u": axes[dims[0]].tolist(), "v": axes[dims[1]].tolist(), "fixed": value, "dims": list(dims)}
        amplitudes.append((h@q, h@baseline))
    ref = max(max(np.max(np.abs(a)) for pair in amplitudes for a in pair), 1e-20)
    def db(values):
        return np.round(np.clip(20*np.log10(np.maximum(np.abs(values)/ref, 1e-8)), -60, 0), 2).tolist()
    for plane, values in zip(planes.values(), amplitudes):
        plane.update({"optimized": db(values[0]), "baseline": db(values[1])})
    cloud_axes = [np.linspace(low[i], high[i], n) for i, n in enumerate((18, 16, 14))]
    cloud = np.stack(np.meshgrid(*cloud_axes, indexing="ij"), axis=-1).reshape(-1, 3)
    hc = transfer(c, cloud)
    return {"config": c, "signature": signature(c), "sources": sources(c).tolist(), "rotation": rotation(c).tolist(), "weights": encode(q), "baseline_weights": encode(baseline),
            "training": metrics(ob, od, q), "model_validation": validation,
            "model_baseline": metrics(vhb, vhd, baseline), "measured_holdout": measured,
            "sampling_counts": [len(bp), len(dp), len(vbp), len(vdp)],
            "slices": planes, "view_bounds": [low.tolist(), high.tolist()],
            "cloud": {"points": np.round(cloud, 4).tolist(), "optimized": db(hc@q), "baseline": db(hc@baseline)},
            "warnings": warnings}
