"""Loopback-only UI, numerical solver, persistence, and native Core Audio bridge."""
import argparse
import atexit
import copy
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import secrets
import selectors
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import webbrowser
import numpy as np
from . import model, calibration, band_jobs

ROOT = Path(__file__).resolve().parent.parent
NATIVE = ROOT / "bin" / "macbook-audio"
DATA = ROOT / "data"
TOKEN = secrets.token_urlsafe(32)
LOCK = threading.RLock()
SOLVE_LOCK = threading.Lock()
SOLUTIONS = {}
PROCESS = None


def hardware():
    if not NATIVE.exists():
        return {"devices": [], "selected_output": 0, "error": "Build the native helper with ./native/build.sh."}
    try:
        p = subprocess.run([str(NATIVE), "devices"], capture_output=True, text=True, timeout=5, check=True)
        d = json.loads(p.stdout)
        if not d["selected_output"]:
            d["error"] = "Core Audio cannot see built-in stereo speakers. Launch ./run.command in Terminal outside the Codex sandbox."
        return d
    except (subprocess.SubprocessError, ValueError, OSError) as e:
        return {"devices": [], "selected_output": 0, "error": str(e)}


def hardware_stamp(d):
    selected = next((v for v in d["devices"] if v["id"] == d["selected_output"]), None)
    return selected


def stop():
    global PROCESS
    with LOCK:
        if PROCESS and PROCESS.poll() is None:
            PROCESS.terminate()
            try: PROCESS.wait(timeout=2)
            except subprocess.TimeoutExpired:
                PROCESS.kill(); PROCESS.wait()
        PROCESS = None


def play(c, q, peak, seconds):
    global PROCESS
    peak = model.finite(peak, "Digital peak", 0.001, 0.08)
    seconds = model.finite(seconds, "Playback duration", 0.1, 30)
    with LOCK:
        stamp = hardware_stamp(hardware())
        if not stamp: raise ValueError("Built-in stereo speaker output unavailable.")
        if stamp.get("muted") or stamp.get("volume_scalar", [-1])[0] == 0:
            raise ValueError("MacBook speakers are muted or system volume is zero. Set a modest system volume, then re-solve before playback/calibration.")
        stop()
        args = [str(NATIVE), "play", str(c["frequency"]), str(abs(q[0])*peak), str(np.angle(q[0])), str(abs(q[1])*peak), str(np.angle(q[1])), str(seconds)]
        PROCESS = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        with selectors.DefaultSelector() as sel:
            sel.register(PROCESS.stdout, selectors.EVENT_READ)
            if not sel.select(5):
                stop(); raise ValueError("Native output did not start within 5 seconds.")
        line = PROCESS.stdout.readline()
        if not line:
            error = PROCESS.stderr.read()
            stop(); raise ValueError(error.strip() or "Native output failed.")
        return json.loads(line)


def play_pcm(path,rate,peak,duration):
    global PROCESS
    peak=model.finite(peak,'Digital gain',.001,.08)
    with LOCK:
        stamp=hardware_stamp(hardware())
        if not stamp:raise ValueError('Built-in stereo output is unavailable.')
        if stamp.get('muted') or stamp.get('volume_scalar',[-1])[0]==0:raise ValueError('System speakers are muted. Set volume, then re-optimize the band.')
        stop()
        PROCESS=subprocess.Popen([str(NATIVE),'pcm',str(path),str(rate),str(peak)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        with selectors.DefaultSelector() as sel:
            sel.register(PROCESS.stdout,selectors.EVENT_READ)
            if not sel.select(5):stop();raise ValueError('Native PCM output did not start within 5 seconds.')
        line=PROCESS.stdout.readline()
        if not line:
            error=PROCESS.stderr.read();stop();raise ValueError(error.strip() or 'Native PCM output failed.')
        return {**json.loads(line),'duration':duration}


def load_data():
    path = DATA / "measurements.json"
    if not path.exists(): return {"records": [], "validations": [], "feedback": []}
    return json.loads(path.read_text())


def save_data(data):
    DATA.mkdir(exist_ok=True)
    temp = DATA / "measurements.tmp"
    temp.write_text(json.dumps(data, indent=2, allow_nan=False))
    temp.replace(DATA / "measurements.json")


def solution_key(s):
    return hashlib.sha256(json.dumps({"signature": s["signature"], "weights": np.round(s["weights"], 9).tolist(), "bright": s["config"]["bright"], "dark": s["config"]["dark"]}, sort_keys=True).encode()).hexdigest()[:24]


def validation_summary(s, data, stamp):
    rows = [r for r in data["validations"] if r["solution_key"] == solution_key(s) and r.get("hardware") == stamp]
    groups = []
    for zone in ("bright", "dark"):
        # Equal spatial weight; latest repeated position replaces earlier records.
        unique = {tuple(np.round(r["position"], 4)): r for r in rows if model.inside(r["position"], s["config"][zone])}
        groups.append(list(unique.values()))
    if min(map(len, groups)) == 0:
        return {"counts": list(map(len, groups)), "verified": False}
    powers = np.array([[np.mean([r[key] for r in group]) for key in ("baseline_power", "optimized_power")] for group in groups])
    db = 10*np.log10(np.maximum(powers[0], 1e-30)/np.maximum(powers[1], 1e-30))
    return {"counts": list(map(len, groups)), "verified": min(map(len, groups)) >= 3,
            "baseline_db": float(db[0]), "optimized_db": float(db[1]), "improvement_db": float(db[1]-db[0]),
            "label": "Actual narrowband microphone powers at sampled positions; sparse samples do not certify an entire volume."}


class Handler(BaseHTTPRequestHandler):
    server_version = "MacBookACC/1.0"
    def log_message(self, fmt, *args):
        if args and str(args[0]).startswith("POST"): return
        super().log_message(fmt, *args)
    def reply(self, obj, status=200):
        raw = json.dumps(obj, allow_nan=False).encode()
        self.send_response(status); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(raw))); self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(raw)
    def valid_host(self):
        return self.headers.get("Host") in (f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}")
    def do_GET(self):
        if not self.valid_host(): return self.reply({"error": "Invalid Host"}, 403)
        path = self.path.split("?", 1)[0]
        if path == "/api/state":
            with LOCK: data = load_data()
            return self.reply({"default": model.DEFAULT, "hardware": hardware(), "data": data, "audio_sources": band_jobs.sources()})
        if path.startswith("/api/broadband-file/"):
            parts=path.split('/')
            if len(parts)!=5 or parts[4] not in ('optimized.wav','baseline.wav','filters.npz','report.json'):
                return self.reply({"error":"Unknown export"},404)
            try:
                job=band_jobs.get(parts[3])
                if job['status']!='ready':raise ValueError('Render is not ready.')
                file=job['folder']/parts[4];raw=file.read_bytes()
            except (ValueError,OSError) as e:return self.reply({"error":str(e)},404)
            self.send_response(200);self.send_header('Content-Type',mimetypes.guess_type(file)[0] or 'application/octet-stream');self.send_header('Content-Length',str(len(raw)));self.send_header('Content-Disposition','attachment; filename="'+parts[4]+'"');self.end_headers();self.wfile.write(raw);return
        files = {"/": "index.html", "/app.js": "app.js", "/style.css": "style.css", "/meter.js": "meter.js", "/band.js": "band.js"}
        if path not in files: return self.reply({"error": "Not found"}, 404)
        p = ROOT / "web" / files[path]
        raw = p.read_bytes().replace(b"__TOKEN__", TOKEN.encode()) if path == "/" else p.read_bytes()
        self.send_response(200); self.send_header("Content-Type", mimetypes.guess_type(p)[0] or "text/plain"); self.send_header("Content-Length", str(len(raw))); self.send_header("Cache-Control", "no-store"); self.send_header("X-Content-Type-Options", "nosniff"); self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'"); self.end_headers(); self.wfile.write(raw)
    def do_POST(self):
        origin = self.headers.get("Origin")
        origins = (f"http://127.0.0.1:{self.server.server_port}", f"http://localhost:{self.server.server_port}")
        if not self.valid_host() or self.headers.get("X-ACC-Token") != TOKEN or (origin is not None and origin not in origins):
            return self.reply({"error": "Same-origin session token required."}, 403)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= (34_000_000 if self.path == "/api/audio-upload" else 2_000_000): raise ValueError("Request too large or empty.")
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict): raise ValueError("JSON object required.")
            result = self.action(self.path, payload)
            self.reply(result)
        except (ValueError, TypeError, KeyError, OSError, subprocess.SubprocessError) as e:
            self.reply({"error": str(e)}, 400)
    def action(self, path, p):
        if path == '/api/audio-upload':return {'source':band_jobs.upload(p),'sources':band_jobs.sources()}
        if path == '/api/broadband-start':return band_jobs.start(p['config'],p.get('options',{}),p['audio_id'],hardware_stamp(hardware()))
        if path == '/api/broadband-status':return band_jobs.status(p['id'])
        if path == '/api/broadband-cancel':return band_jobs.cancel(p['id'])
        if path == '/api/broadband-play':
            job=band_jobs.get(p['id'])
            if job['status']!='ready':raise ValueError('Render is not ready.')
            if job['hardware']!=hardware_stamp(hardware()):raise ValueError('Audio device, rate, volume or mute changed. Re-optimize the band before playback.')
            variant=p.get('variant','optimized')
            if variant not in ('optimized','baseline'):raise ValueError('Unknown playback version.')
            if model.config(p['config'],check_sampling=False)!=job['result']['config']:raise ValueError('Scene changed since broadband rendering. Optimize the band again.')
            return play_pcm(job['folder']/(variant+'.f32'),job['result']['sample_rate'],p.get('peak',.025),job['result']['duration'])
        if path == "/api/stop": stop(); return {"playing": False}
        if path == "/api/solve":
            with SOLVE_LOCK:
                stamp = hardware_stamp(hardware())
                with LOCK: data = load_data()
                compatible = [r for r in data["records"] if r.get("hardware") == stamp]
                s = model.solve(p.get("config", {}), compatible)
                s["hardware"] = stamp
                s["id"] = secrets.token_hex(12)
                s["actual_validation"] = validation_summary(s, data, stamp)
                with LOCK:
                    SOLUTIONS[s["id"]] = s
                    if len(SOLUTIONS) > 12: SOLUTIONS.pop(next(iter(SOLUTIONS)))
                return s
        if path == "/api/play":
            with LOCK:
                s = SOLUTIONS.get(p.get("id"))
            if s is None: raise ValueError("Solve the current scene before playback.")
            if s["hardware"] != hardware_stamp(hardware()): raise ValueError("Audio device/settings changed. Re-solve and recalibrate.")
            variant = p.get("variant", "optimized")
            if variant not in ("optimized", "baseline"): raise ValueError("Invalid playback mode.")
            return play(s["config"], model.decode_weights(s["weights"] if variant == "optimized" else s["baseline_weights"]), p.get("peak", .025), p.get("seconds", 15))
        if path == "/api/probe":
            c = model.config(p["config"])
            with LOCK: s = SOLUTIONS.get(p.get("id"))
            if not s or s["signature"] != model.signature(c) or s["hardware"] != hardware_stamp(hardware()):
                raise ValueError("Setup or output changed during calibration. Re-solve and start a new session.")
            i = int(p["index"])
            if not 0 <= i < 12: raise ValueError("Invalid probe index.")
            return play(c, calibration.probes()[i], p.get("peak", .025), p.get("seconds", 4.0))
        if path == "/api/calibrate":
            c = model.config(p["config"])
            with LOCK: solution = SOLUTIONS.get(p.get("id"))
            if not solution or solution["signature"] != model.signature(c): raise ValueError("Calibration solution expired or setup changed.")
            r = calibration.record(c, p)
            r["hardware"] = hardware_stamp(hardware())
            if not r["hardware"]: raise ValueError("Built-in output unavailable.")
            if r["hardware"] != solution["hardware"]: raise ValueError("Output settings changed during calibration.")
            r["timestamp"] = time.time(); r["id"] = secrets.token_hex(8)
            with LOCK:
                data = load_data()
                relevant = [v for v in data["records"] if v["signature"] == r["signature"]]
                if any(v["role"] != r["role"] and np.linalg.norm(np.array(v["position"])-np.array(r["position"])) < .01 for v in relevant):
                    raise ValueError("Keep training and holdout points at least 1 cm apart.")
                if relevant and any(v["microphone"] != r["microphone"] or v["peak"] != r["peak"] or v.get("hardware") != r["hardware"] for v in relevant):
                    raise ValueError("Microphone, drive level, or output settings differ from this session. Start a new session and recalibrate.")
                if len(data["records"]) >= 2000: raise ValueError("Record limit reached. Export and start a fresh data file.")
                data["records"].append(r); save_data(data)
            return {"record": r, "data": data}
        if path == "/api/validate":
            with LOCK: s = SOLUTIONS.get(p.get("id"))
            if not s: raise ValueError("Solution expired; solve again.")
            position = model.vec(p["position"], "Microphone position")
            if not np.any([model.inside(position, s["config"][z]) for z in ("bright", "dark")]): raise ValueError("Validation microphone must be inside a current zone.")
            raw = np.asarray(p["powers"], dtype=float)
            if raw.shape != (5,) or not np.all(np.isfinite(raw)) or np.any(raw < 0): raise ValueError("Need background, baseline, optimized, optimized, baseline powers.")
            scatter = np.asarray(p.get("scatter"), dtype=float)
            if scatter.shape != (5,) or not np.all(np.isfinite(scatter)) or np.any(scatter < 0): raise ValueError("Need within-probe scatter for each A/B step.")
            if np.any(scatter[1:]/np.maximum(raw[1:], 1e-30) > .25): raise ValueError("Microphone tone power varied >25% within an A/B step.")
            noise = raw[0]; signal = raw[1:]-noise
            if np.any(signal <= max(noise*10, 1e-15)): raise ValueError("Validation tone too close to background; need >10 dB SNR at every playback.")
            if max(abs(signal[0]-signal[3])/max(signal[0],signal[3]), abs(signal[1]-signal[2])/max(signal[1],signal[2])) > .15:
                raise ValueError("A/B repeats differ by >15%; keep microphone/gain/room still and retry.")
            stamp = hardware_stamp(hardware())
            if stamp != s["hardware"] or stamp is None: raise ValueError("Output changed since solve.")
            microphone = str(p["microphone"])[:250]
            peak = model.finite(p["peak"], "Drive", .001, .08)
            with LOCK:
                data = load_data()
                records = [r for r in data["records"] if r["signature"] == s["signature"]]
                if any(r["role"] == "train" and np.linalg.norm(position-np.array(r["position"])) < .01 for r in records):
                    raise ValueError("Use a holdout position at least 1 cm from calibration training points.")
                prior = [r for r in data["validations"] if r["solution_key"] == solution_key(s)]
                if any(r["microphone"] != microphone or r["peak"] != peak for r in prior+records):
                    raise ValueError("Keep the same microphone and drive level across this measurement session.")
                r = {"position": position.tolist(), "solution_key": solution_key(s), "powers": raw.tolist(), "baseline_power": float((signal[0]+signal[3])/2), "optimized_power": float((signal[1]+signal[2])/2), "microphone": microphone, "peak": peak, "hardware": stamp, "timestamp": time.time()}
                data["validations"].append(r); save_data(data)
                summary = validation_summary(s, data, stamp)
            return {"record": r, "summary": summary, "data": data}
        if path == "/api/feedback":
            note = str(p.get("note", "")).strip()
            if not note or len(note)>4000: raise ValueError("Feedback must contain 1–4000 characters.")
            with LOCK:
                data = load_data(); data["feedback"].append({"note": note, "config": model.config(p["config"]), "timestamp": time.time()}); save_data(data)
            return {"saved": True, "next_step": "Subjective feedback is saved. To adjust the optimizer, capture channel calibration points and select measured optimization."}
        raise ValueError("Unknown endpoint.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8767)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    atexit.register(stop)
    print(f"MacBook ACC 3D: http://127.0.0.1:{server.server_port}", flush=True)
    if not args.no_browser: webbrowser.open(f"http://127.0.0.1:{server.server_port}")
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: stop(); server.server_close()

if __name__ == "__main__": main()
