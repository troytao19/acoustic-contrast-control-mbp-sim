"""Audio-weighted 3D ACC, global band objective, and realizable stereo FIRs.

The discrete ideal problem fixes total drive power at each frequency. Dinkelbach
iterations maximize the RATIO OF SUMMED POWERS, not a mean of per-bin dB ratios.
Real finite filters are rendered by linear convolution and evaluated separately.
"""
import copy
import hashlib
import json
import math
from pathlib import Path
import numpy as np
from scipy.io import wavfile
from scipy.signal import fftconvolve, resample_poly
from scipy.fft import rfft
from scipy.stats import qmc
from . import model

ROOT = Path(__file__).resolve().parent.parent
MEDIA = ROOT / 'media'


def options(raw, rate):
    lo = model.finite(raw.get('low', 150), 'Band lower edge', 20, 19980)
    hi = model.finite(raw.get('high', 4000), 'Band upper edge (limited by output sample rate)', 40, min(20000, rate*.49))
    if hi-lo < 20: raise ValueError('Frequency band must be at least 20 Hz wide.')
    n = raw.get('fft_size', 8192)
    if n not in (4096, 8192, 16384, 32768, 65536, 131072): raise ValueError('Choose 4096–131072 power-of-two FIR taps.')
    n = int(n)
    spatial = raw.get('spatial_method', 'auto')
    if spatial not in ('auto', 'sobol', 'grid'): raise ValueError('Choose automatic, Sobol, or wavelength-grid spatial integration.')
    samples = raw.get('spatial_samples', 4096)
    if samples not in (1024, 4096, 16384, 65536): raise ValueError('Choose 1024, 4096, 16384, or 65536 spatial samples.')
    mode = raw.get('control', 'phase')
    if mode not in ('phase', 'complex'): raise ValueError('Choose phase-only or amplitude + phase control.')
    return {'low': lo, 'high': hi, 'fft_size': n, 'control': mode,
            'spatial_method': spatial, 'spatial_samples': int(samples)}


def read_audio(path, rate=44100):
    sr, a = wavfile.read(path)
    if a.ndim not in (1, 2) or (a.ndim == 2 and a.shape[1] not in (1, 2)):
        raise ValueError('Audio must be mono or stereo WAV.')
    if not 8000 <= sr <= 192000 or not .5 <= len(a)/sr <= 30:
        raise ValueError('Use a 0.5–30 second WAV at 8–192 kHz.')
    if a.dtype == np.uint8: x = (a.astype(float)-128)/128
    elif np.issubdtype(a.dtype, np.integer): x = a.astype(float)/max(abs(np.iinfo(a.dtype).min), np.iinfo(a.dtype).max)
    else: x = a.astype(float)
    if not np.all(np.isfinite(x)): raise ValueError('Audio contains non-finite samples.')
    # ACC needs one coherent program feeding two spatial control filters.
    if x.ndim == 2: x = np.mean(x, axis=1)
    x -= np.mean(x)
    if np.max(np.abs(x)) < 1e-7: raise ValueError('Audio is silent (possibly an anti-phase stereo downmix).')
    g = math.gcd(int(sr), int(rate))
    if sr != rate: x = resample_poly(x, rate//g, sr//g)
    x /= max(1.0, np.max(np.abs(x)))
    # Fade the INPUT identically before filtering; never apply independent output envelopes.
    fade = min(int(.025*rate), len(x)//4)
    envelope = np.sin(np.linspace(0, np.pi/2, fade))**2
    x[:fade] *= envelope; x[-fade:] *= envelope[::-1]
    return x, {'source_rate': int(sr), 'sample_rate': int(rate), 'duration': len(x)/rate,
               'mono_downmix': a.ndim == 2 and a.shape[1] == 2}


def path_arrays(c, points, channel):
    """Geometry only; same images/directions/finite-desk term as model.transfer."""
    points = np.asarray(points)
    s = model.sources(c)[channel]; normal = model.rotation(c)[:, 2]
    distances, gains = [], []
    def append(image, gain, norm):
        delta = points-image; raw = np.linalg.norm(delta, axis=1)
        d = np.maximum(raw, .025)
        direct = 1-c['directivity']+c['directivity']*(delta@norm)/np.maximum(raw, 1e-12)
        distances.append(d); gains.append(gain*direct/(4*np.pi*d))
    for image, gain, parity in model.image_sources(c, s):
        if gain: append(image, gain, normal*parity)
    if c['desk']['enabled'] and c['desk']['reflection'] and c['order']:
        z = c['desk']['height']; image = s.copy(); image[2] = 2*z-s[2]
        denom = points[:, 2]-image[2]
        t = np.divide(z-image[2], denom, out=np.zeros(len(points)), where=np.abs(denom)>1e-9)
        hit = image+t[:, None]*(points-image); xy = hit[:, :2]-c['desk']['center']
        mask = ((points[:, 2]-z)*(s[2]-z)>0)&(np.abs(xy[:, 0])<=c['desk']['width']/2)&(np.abs(xy[:, 1])<=c['desk']['depth']/2)
        append(image, mask*c['desk']['reflection'], normal*[1, 1, -1])
    return np.array(distances).T/(331.3+.606*c['temperature']), np.array(gains).T


def sweep(c, points, frequencies, cancelled=lambda: False):
    """Exact uniform-frequency path recurrence, avoiding repeated trig per image."""
    f = np.asarray(frequencies)
    if len(f)<2 or not np.allclose(np.diff(f), f[1]-f[0]): raise ValueError('Uniform frequency grid required.')
    h = np.empty((len(f), len(points), 2), complex)
    for j in range(2):
        delay, gains = path_arrays(c, points, j)
        values = gains*np.exp(-2j*np.pi*f[0]*delay)
        step = np.exp(-2j*np.pi*(f[1]-f[0])*delay)
        for i in range(len(f)):
            if i%32 == 0 and cancelled(): raise ValueError('Broadband optimization cancelled.')
            h[i, :, j] = np.sum(values, axis=1)
            values *= step
    return h


def covariance(h): return np.einsum('fna,fnb->fab', h.conj(), h)/h.shape[1]
def energy(r, q): return np.einsum('fa,fab,fb->f', q.conj(), r, q).real


def batch_size(n):
    # Conservative working-array allowance: FFT input/output, stereo responses,
    # covariance temporaries and gridding kernels. Independent of zone size.
    limit = max(1, min(32, 48*1024**2//(128*n)))
    return 1 << (int(limit).bit_length()-1)


def fft_response(c, points, bins, n, rate, cancelled=lambda: False):
    """Bounded batch of image-source responses using oversampled delay gridding.

    Deposit each path onto a 2x-rate periodic impulse grid using a 64-tap,
    beta=14 Kaiser-windowed sinc. FFT bins k then represent exactly k*rate/n.
    Periodic wrapping is valid for evaluating these discrete frequencies; audio
    convolution remains linear. This is a numerical approximation, checked
    against direct complex exponentials in regression tests and every render.
    """
    h = np.empty((len(bins), len(points), 2), complex)
    for channel in range(2):
        if cancelled(): raise ValueError('Broadband optimization cancelled.')
        delay, gains = path_arrays(c, points, channel)
        position = delay*(2*rate); base = np.floor(position).astype(np.int64)
        impulse = np.zeros((len(points), 2*n))
        rows = np.arange(len(points))[:, None]
        for offset in range(-31, 33):
            if offset%8 == 0 and cancelled(): raise ValueError('Broadband optimization cancelled.')
            index = base+offset; delta = index-position
            kernel = np.sinc(delta)*np.i0(14*np.sqrt(np.maximum(0, 1-(delta/32)**2)))/np.i0(14)
            kernel[np.abs(delta)>32] = 0
            np.add.at(impulse, (rows, index%(2*n)), gains*kernel)
        h[:, :, channel] = rfft(impulse, axis=1, workers=2)[:, bins].T
    return h


class VolumeSamples:
    """Lazy midpoint lattice or reproducible scrambled Sobol volume samples."""
    def __init__(self, c, key, high, opts, validation=False):
        self.center = np.array(c[key]['center']); self.size = np.array(c[key]['size'])
        spacing = min(c['spacing'], (331.3+.606*c['temperature'])/high/6)
        self.counts = np.maximum(2, np.ceil(self.size/spacing).astype(int))+(1 if validation else 0)
        self.grid_count = int(np.prod(self.counts))
        self.method = opts['spatial_method']
        if self.method == 'auto':
            # Make the same method choice for training and validation.
            check = np.maximum(2, np.ceil(self.size/spacing).astype(int))+1
            self.method = 'grid' if np.prod(check)<=opts['spatial_samples'] else 'sobol'
        self.count = self.grid_count if self.method == 'grid' else opts['spatial_samples']
        self.seed = (71 if key == 'bright' else 193)+(1009 if validation else 0)

    def batches(self, size):
        # Sobol sets are powers of two. Materializing coordinates only uses at
        # most 1.5 MB; frequency×space response arrays are never materialized.
        unit = None if self.method == 'grid' else qmc.Sobol(3, scramble=True, seed=self.seed).random_base2(int(math.log2(self.count)))
        for start in range(0, self.count, size):
            end = min(self.count, start+size)
            if unit is None:
                ijk = np.stack(np.unravel_index(np.arange(start, end), tuple(self.counts)), axis=1)
                u = (ijk+.5)/self.counts
            else: u = unit[start:end]
            yield self.center+(u-.5)*self.size


def integrate_volume(c, samples, bins, n, rate, progress, cancelled):
    total = np.zeros((len(bins), 2, 2), complex)
    first_half = None; done = 0
    # A half-size Sobol prefix is itself balanced, allowing a convergence check.
    for points in samples.batches(batch_size(n)):
        h = fft_response(c, points, bins, n, rate, cancelled)
        total += np.einsum('fna,fnb->fab', h.conj(), h)
        done += len(points)
        if samples.method == 'sobol' and done == samples.count//2:
            first_half = total/done
        progress(done/samples.count)
    return total/samples.count, first_half


def check_fft_response(c, points, bins, n, rate, cancelled):
    # Spread probes across the entire requested band, including its extremes.
    check_bins = bins[np.unique(np.linspace(0, len(bins)-1, min(33, len(bins))).astype(int))]
    batch = batch_size(n)
    fast = np.concatenate([fft_response(c, points[i:i+batch], check_bins, n, rate, cancelled)
                           for i in range(0, len(points), batch)], axis=1)
    exact = []
    for k in check_bins:
        if cancelled(): raise ValueError('Broadband optimization cancelled.')
        tone = dict(c, frequency=k*rate/n)
        exact.append(model.transfer(tone, points))
    exact = np.asarray(exact)
    error = float(np.max(np.abs(fast-exact))/max(np.max(np.abs(exact)), 1e-30))
    if error>1e-5: raise ValueError('Fast transfer-response accuracy check failed; no audio was rendered.')
    return error


def optimize_band(rb, rd, weights, beta, control='phase'):
    w = np.asarray(weights, float); w = w/max(np.sum(w), 1e-30)
    scale = np.maximum(np.trace((rb+rd)/2, axis1=1, axis2=2).real/2, 1e-20)
    denom = rd+beta*scale[:, None, None]*np.eye(2)[None, :, :]
    q = np.ones((len(rb), 2), complex)/np.sqrt(2)
    ratio = float(w@energy(rb, q)/max(w@energy(denom, q), 1e-30))
    history = [ratio]
    for _ in range(100):
        a = rb-ratio*denom
        if control == 'phase':
            q[:, 0] = 1/np.sqrt(2)
            q[:, 1] = np.exp(-1j*np.angle(a[:, 0, 1]))/np.sqrt(2)
        else:
            _, v = np.linalg.eigh(a); q = v[:, :, -1]
        new = float(w@energy(rb, q)/max(w@energy(denom, q), 1e-30))
        history.append(new)
        if abs(new-ratio) <= 1e-10*max(1, abs(new)):
            ratio = new; break
        ratio = new
    # Smooth ONLY the irrelevant common phase. Relative phase/magnitudes stay intact.
    if control == 'phase':
        phi = np.unwrap(np.angle(q[:, 1]/q[:, 0]))
        q = np.column_stack([np.exp(-.5j*phi), np.exp(.5j*phi)])/np.sqrt(2)
    else:
        q[0] *= np.exp(-1j*np.angle(q[0, np.argmax(np.abs(q[0]))]))
        for i in range(1, len(q)):
            q[i] *= np.exp(-1j*np.angle(np.vdot(q[i-1], q[i])))
    return q, history


def band_taper(f, low, high):
    width = min(100., (high-low)/8)
    x = np.minimum((f-low)/width, (high-f)/width)
    return np.sin(np.clip(x, 0, 1)*np.pi/2)**2


def make_firs(q, mask, n, taper):
    target = np.zeros((n//2+1, 2), complex); target[mask] = q*taper[:, None]
    ir = np.fft.irfft(target, n=n, axis=0)
    fir = np.roll(ir, n//2, axis=0)*np.hanning(n)[:, None]
    # Full length causal FIR, with a shared latency; no circular audio convolution.
    actual = np.fft.rfft(fir, axis=0)[mask]
    return fir, actual


def spectral_covariance(y, rate, frequencies):
    """Sum exact clip DFT cross-powers into nearest design-frequency cells.

This measures the rendered audio, including FIR distortion and tail, instead of
assuming desired bin weights survived realization. DC/Nyquist are counted once.
"""
    if y.ndim == 1: y = y[:, None]
    z = np.fft.rfft(y, axis=0); f = np.fft.rfftfreq(len(y), 1/rate)
    df = frequencies[1]-frequencies[0]
    selection = (f >= frequencies[0]-df/2)&(f <= frequencies[-1]+df/2)
    factor = np.full(len(f), 2.); factor[0] = 1
    if len(y)%2 == 0: factor[-1] = 1
    total = float(np.sum(abs(z)**2*factor[:, None])/len(y)**2)
    z = z[selection]; factor = factor[selection]/len(y)**2
    idx = np.clip(np.rint((f[selection]-frequencies[0])/df).astype(int), 0, len(frequencies)-1)
    result = np.zeros((len(frequencies), y.shape[1], y.shape[1]), complex)
    for a in range(y.shape[1]):
        for b in range(y.shape[1]):
            v = z[:, a].conj()*z[:, b]*factor
            result[:, a, b] = np.bincount(idx, weights=v.real, minlength=len(frequencies))+1j*np.bincount(idx, weights=v.imag, minlength=len(frequencies))
    inside = float(np.trace(result, axis1=1, axis2=2).real.sum())
    return result, inside/max(total, 1e-30)


def summarize(rb, rd, spectra):
    b = np.maximum(np.einsum('fab,fab->f', rb, spectra).real, 0)
    d = np.maximum(np.einsum('fab,fab->f', rd, spectra).real, 0)
    return {'contrast_db': float(10*np.log10(max(b.sum(), 1e-30)/max(d.sum(), 1e-30))),
            'bright_power': float(b.sum()), 'dark_power': float(d.sum()),
            'curve_db': (10*np.log10(np.maximum(b, 1e-30)/np.maximum(d, 1e-30))).tolist()}


def field(c, f, spectra, progress, cancelled, n, rate, bins):
    low = np.maximum(.03, np.array(c['laptop'])-c['view_span']/2)
    high = np.minimum(np.array(c['room'])-.03, np.array(c['laptop'])+c['view_span']/2)
    axes = [np.linspace(low[i], high[i], 26) for i in range(3)]
    planes, points = {}, []
    for name, dims, fixed, value in (('xy',(0,1),2,c['slice_z']),('xz',(0,2),1,c['laptop'][1]),('yz',(1,2),0,c['laptop'][0])):
        u,v = np.meshgrid(axes[dims[0]], axes[dims[1]])
        p = np.zeros((u.size, 3));p[:, dims[0]]=u.ravel();p[:, dims[1]]=v.ravel();p[:, fixed]=value
        planes[name]={'u':axes[dims[0]].tolist(),'v':axes[dims[1]].tolist(),'dims':list(dims),'fixed':value}
        points.append(p)
    cloud_axes=[np.linspace(low[i],high[i],n) for i,n in enumerate((10,10,8))]
    cloud=np.stack(np.meshgrid(*cloud_axes,indexing='ij'),axis=-1).reshape(-1,3)
    points.append(cloud)
    allpoints=np.concatenate(points); powers={key:[] for key in spectra}
    batch=batch_size(n)
    for start in range(0,len(allpoints),batch):
        h=fft_response(c,allpoints[start:start+batch],bins,n,rate,cancelled)
        for key,cov in spectra.items():
            powers[key].extend(np.maximum(np.einsum('fna,fab,fnb->n',h.conj(),cov,h).real,1e-30))
        progress(.72+.23*min(1,(start+batch)/len(allpoints)),'Integrating the 3D audio-energy field')
    ref=max(max(p) for p in powers.values())
    db={k:np.clip(10*np.log10(np.array(v)/ref),-60,0) for k,v in powers.items()}
    size=26*26
    for i,p in enumerate(planes.values()):
        for k,v in db.items():p[k]=np.round(v[i*size:(i+1)*size],2).tolist()
    return {'slices':planes,'cloud':{'points':cloud.tolist(),**{k:np.round(v[3*size:],2).tolist() for k,v in db.items()}},'view_bounds':[low.tolist(),high.tolist()]}


def render(raw, raw_options, audio_path, rate, output, progress=lambda *_:None, cancelled=lambda:False, make_field=True):
    c=model.config(raw,check_sampling=False)
    if c['mode']!='model':
        raise ValueError('Broadband currently needs the approximate room model. Single-tone calibration does not establish transfer functions across a band; it will not be extrapolated silently.')
    o=options(raw_options,rate); n=o['fft_size']
    f_all=np.fft.rfftfreq(n,1/rate); mask=(f_all>=o['low'])&(f_all<=o['high']); f=f_all[mask]
    bins=np.flatnonzero(mask)
    if len(f)<2:raise ValueError('Use more FIR taps to resolve this narrow band.')
    taper=band_taper(f,o['low'],o['high'])
    progress(.02,'Reading the audio and its spectrum')
    x,audio=read_audio(audio_path,rate)
    input_cov,retained=spectral_covariance(x,rate,f); weights=input_cov[:,0,0].real*taper**2
    if np.sum(weights)<1e-12:raise ValueError('Selected audio has too little energy in this band.')
    samples=[VolumeSamples(c,z,o['high'],o,v) for v in (False,True) for z in ('bright','dark')]
    probe_points=np.concatenate([next(s.batches(4)) for s in samples])
    transfer_error=check_fft_response(c,probe_points,bins,n,rate,cancelled)
    matrices=[];halves=[]
    for i,s in enumerate(samples):
        def report(fraction):
            progress(.05+(i+fraction)*.12,('Training' if i<2 else 'Validation')+' '+('bright' if i%2==0 else 'dark')+f' volume · {s.method} · {int(fraction*s.count):,}/{s.count:,} points')
        matrix,half=integrate_volume(c,s,bins,n,rate,report,cancelled)
        matrices.append(matrix);halves.append(half)
    rb,rd,vb,vd=matrices
    progress(.55,'Optimizing total audio-weighted contrast')
    q,history=optimize_band(rb,rd,weights,c['regularization'],o['control'])
    fir,actual=make_firs(q,mask,n,taper)
    base_fir,base_actual=make_firs(np.ones_like(q)/np.sqrt(2),mask,n,taper)
    progress(.60,'Rendering causal FIR audio and checking the actual output spectrum')
    output.mkdir(parents=True,exist_ok=True)
    y=np.column_stack([fftconvolve(x,fir[:,j],mode='full') for j in range(2)])
    baseline=np.column_stack([fftconvolve(x,base_fir[:,j],mode='full') for j in range(2)])
    # ONE gain for both versions preserves a fair A/B comparison; no per-channel limiter.
    common=.9/max(np.max(np.abs(y)),np.max(np.abs(baseline)),1e-12)
    y*=common;baseline*=common
    cov_opt,inside_opt=spectral_covariance(y,rate,f);cov_base,inside_base=spectral_covariance(baseline,rate,f)
    opt=summarize(vb,vd,cov_opt);base=summarize(vb,vd,cov_base)
    ideal_cov=weights[:,None,None]*(q.conj()[:,:,None]*q[:,None,:])
    ideal=summarize(rb,rd,ideal_cov)
    training=summarize(rb,rd,cov_opt)
    spatial={'methods':[s.method for s in samples], 'points':[s.count for s in samples],
             'equivalent_grid_points':[s.grid_count for s in samples],
             'training_validation_difference_db':abs(training['contrast_db']-opt['contrast_db']),
             'transfer_probe_relative_error':transfer_error,'response_batch_points':batch_size(n),
             'half_to_full_validation_difference_db':None}
    if halves[2] is not None and halves[3] is not None:
        half_result=summarize(halves[2],halves[3],cov_opt)
        spatial['half_to_full_validation_difference_db']=abs(half_result['contrast_db']-opt['contrast_db'])
    active=weights>weights.max()*1e-5
    spatial['active_bin_difference_p95_db']=float(np.percentile(np.abs(np.array(training['curve_db'])[active]-np.array(opt['curve_db'])[active]),95))
    # Rendered buffers contain exact A/B FIR output before user playback gain.
    wavfile.write(output/'optimized.wav',rate,y.astype(np.float32))
    wavfile.write(output/'baseline.wav',rate,baseline.astype(np.float32))
    y.astype('<f4').tofile(output/'optimized.f32');baseline.astype('<f4').tofile(output/'baseline.f32')
    np.savez(output/'filters.npz',optimized=fir,baseline=base_fir,sample_rate=rate,common_gain=common,frequencies=f,ideal_weights=q)
    notices=['Model prediction only: no broadband microphone validation has been performed.',
             'Input is downmixed to one coherent mono program, then two different FIR filters drive L/R.',
             'Audio outside the selected band is removed in BOTH versions; the metric covers this rendered band, not the unfiltered source.',
             'Finite FIRs and frequency/spatial sampling limit accuracy. Re-run with finer resolution to check convergence.']
    if 'sobol' in spatial['methods']:notices.append('Volume averages use independently scrambled Sobol samples. Increase spatial samples to check convergence; this does not resolve every local pressure null.')
    if spatial['training_validation_difference_db']>.5 or (spatial['half_to_full_validation_difference_db'] or 0)>.5 or spatial['active_bin_difference_p95_db']>3:
        notices.append('Spatial integration needs a convergence check: increase spatial samples or use the wavelength grid before relying on these predictions.')
    if o['high']>8000 or o['low']<80:notices.append('20 Hz–20 kHz is a numerical design range, not a measured MacBook speaker bandwidth. Unmeasured speaker DSP, frequency response and directivity limit physical predictions.')
    if opt['contrast_db']<base['contrast_db']:notices.append('Realized filters underperform equal drive on validation; this configuration should not be treated as successful.')
    if abs(10*np.log10(np.sum(y*y)/np.sum(baseline*baseline)))>.5:notices.append('Finite filters changed total electrical drive energy by more than 0.5 dB; inspect filter realization and use finer resolution.')
    result={'config':c,'options':o,'audio':audio,'frequencies':f.tolist(),'frequency_step_hz':float(rate/n),
            'optimized':opt,'baseline':base,'training':training,'ideal_training':ideal,
            'improvement_db':opt['contrast_db']-base['contrast_db'],
            'input_band_energy_percent':100*retained,
            'rendered_in_band_percent':{'optimized':100*inside_opt,'baseline':100*inside_base},
            'duration':len(y)/rate,'sample_rate':rate,'fir_taps':n,'common_delay_ms':1000*(n//2)/rate,
            'common_normalization':common,'drive_energy_ratio':float(np.sum(y*y)/np.sum(baseline*baseline)),
            'sampling_counts':[s.count for s in samples],'spatial_integration':spatial,'iterations':len(history)-1,
            'relative_phase_deg':np.rad2deg(np.angle(actual[:,1]*actual[:,0].conj())).tolist(),
            'amplitudes':np.abs(actual).tolist(),'ideal_weights':np.stack([q.real,q.imag],axis=-1).tolist(),'realized_weights':np.stack([actual.real,actual.imag],axis=-1).tolist(),'input_spectrum_db':(10*np.log10(np.maximum(weights/np.max(weights),1e-10))).tolist(),
            'warnings':notices,'signature':hashlib.sha256(json.dumps({'config':c,'options':o},sort_keys=True).encode()).hexdigest()[:24]}
    if make_field:result['field']=field(c,f,{'optimized':cov_opt,'baseline':cov_base},progress,cancelled,n,rate,bins)
    if cancelled():raise ValueError('Broadband optimization cancelled.')
    (output/'report.json').write_text(json.dumps(result,indent=2,allow_nan=False))
    progress(1.,'Ready: rendered stereo filters and audio')
    return result
