import copy
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
from scipy.io import wavfile
from scipy.signal import fftconvolve
from macbook_acc import broadband as bb, model

class BroadbandTests(unittest.TestCase):
    def scene(self):
        c=copy.deepcopy(model.DEFAULT);c['bright']['center']=[4.75,5,1.9];c['dark']['center']=[5.25,5,.9];return c
    def test_sweep_matches_exact_tone_transfer(self):
        c=self.scene();c.update(pitch=17,roll=23,yaw=-37,directivity=.25);c['desk']['enabled']=True
        p=np.array([[5,5,2],[5.2,5,.7],[4.8,5.3,1.4]])
        f=np.linspace(100,8000,71);h=bb.sweep(c,p,f)
        for i in (0,1,35,70):
            c['frequency']=f[i]
            np.testing.assert_allclose(h[i],model.transfer(c,p),rtol=1e-10,atol=1e-12)
    def test_global_phase_objective_matches_exhaustive_two_bin_search(self):
        rng=np.random.default_rng(314)
        h=rng.normal(size=(2,8,2))+1j*rng.normal(size=(2,8,2));g=rng.normal(size=(2,8,2))+1j*rng.normal(size=(2,8,2))
        rb,rd=bb.covariance(h),bb.covariance(g);w=np.array([.8,.2]);beta=.02
        q,history=bb.optimize_band(rb,rd,w,beta,'phase')
        np.testing.assert_allclose(abs(q),1/np.sqrt(2))
        denom=rd+beta*np.trace((rb+rd)/2,axis1=1,axis2=2).real[:,None,None]/2*np.eye(2)
        score=w@bb.energy(rb,q)/(w@bb.energy(denom,q))
        phi=np.linspace(-np.pi,np.pi,361);vectors=np.column_stack([np.ones(len(phi)),np.exp(1j*phi)])/np.sqrt(2)
        b=np.array([np.einsum('na,ab,nb->n',vectors.conj(),r,vectors).real for r in rb])
        d=np.array([np.einsum('na,ab,nb->n',vectors.conj(),r,vectors).real for r in denom])
        best=np.max((w[0]*b[0,:,None]+w[1]*b[1,None,:])/(w[0]*d[0,:,None]+w[1]*d[1,None,:]))
        self.assertGreaterEqual(score+1e-9,best);self.assertLess(score-best,.001)
        self.assertTrue(np.all(np.diff(history)>=-1e-10))
    def test_complex_objective_is_no_worse_than_phase_target(self):
        rng=np.random.default_rng(2);rb=bb.covariance(rng.normal(size=(20,5,2))+1j*rng.normal(size=(20,5,2)));rd=bb.covariance(rng.normal(size=(20,5,2))+1j*rng.normal(size=(20,5,2)))
        _,phase=bb.optimize_band(rb,rd,np.ones(20),.01,'phase');q,complex_=bb.optimize_band(rb,rd,np.ones(20),.01,'complex')
        self.assertGreaterEqual(complex_[-1],phase[-1]-1e-10);np.testing.assert_allclose(np.linalg.norm(q,axis=1),1)
    def test_covariance_aggregation_matches_time_domain_linear_mix(self):
        sr=16000;t=np.arange(sr)/sr
        y=np.column_stack([.3*np.sin(2*np.pi*1000*t)+.2*np.sin(2*np.pi*1500*t),.2*np.cos(2*np.pi*1000*t)+.1*np.sin(2*np.pi*1500*t)])
        f=np.arange(500,2001,10);cov,kept=bb.spectral_covariance(y,sr,f)
        h=np.array([.6,-.4]);r=np.tile(np.outer(h,h),(len(f),1,1))
        expected=np.mean((y@h)**2);actual=np.einsum('fab,fab->',r,cov).real
        self.assertAlmostEqual(expected,actual,places=12);self.assertAlmostEqual(kept,1,places=12)
    def test_shared_fir_delay_and_linear_convolution_no_wraparound(self):
        n=4096;f=np.fft.rfftfreq(n,1/44100);mask=(f>=200)&(f<=3000);q=np.ones((mask.sum(),2),complex)/np.sqrt(2)
        fir,_=bb.make_firs(q,mask,n,bb.band_taper(f[mask],200,3000))
        self.assertEqual(np.argmax(abs(fir[:,0])),n//2)
        x=np.zeros(1000);x[-1]=1;y=fftconvolve(x,fir[:,0],mode='full')
        self.assertEqual(len(y),len(x)+n-1);np.testing.assert_allclose(y[:999],0,atol=1e-14)
    def test_actual_render_spectra_and_shared_normalization(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp);sr=44100;t=np.arange(sr)/sr
            wavfile.write(path/'input.wav',sr,(.3*np.cos(2*np.pi*700*t)+.1*np.cos(2*np.pi*1300*t)).astype(np.float32))
            c=self.scene();c['order']=0
            r=bb.render(c,{'low':200,'high':1600,'fft_size':4096},path/'input.wav',sr,path/'result',make_field=False)
            self.assertGreater(r['optimized']['contrast_db'],r['baseline']['contrast_db']+4)
            _,audio=wavfile.read(path/'result'/'optimized.wav');raw=np.fromfile(path/'result'/'optimized.f32',dtype='<f4').reshape(-1,2)
            np.testing.assert_array_equal(audio,raw);self.assertLessEqual(np.max(np.abs(audio)),.900001)
            self.assertLess(abs(r['drive_energy_ratio']-1),.02)
            self.assertGreater(r['rendered_in_band_percent']['optimized'],99)
            self.assertTrue((path/'result'/'filters.npz').exists())
    def test_silent_and_invalid_bands_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'silent.wav';wavfile.write(p,44100,np.zeros(44100,dtype=np.float32))
            with self.assertRaisesRegex(ValueError,'silent'):bb.read_audio(p)
        for options in ({'low':3000,'high':500},{'fft_size':9},{'low':float('nan')},{'control':'invalid'}):
            with self.assertRaises(ValueError):bb.options(options,44100)
    def test_measured_tone_not_silently_extrapolated(self):
        c=self.scene();c['mode']='measured'
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError,'Single-tone'):bb.render(c,{},Path('none'),44100,Path(tmp),make_field=False)
    def test_cancellation_interrupts_frequency_sweep(self):
        with self.assertRaisesRegex(ValueError,'cancelled'):bb.sweep(self.scene(),np.array([[5,5,2]]),np.arange(100,200,10),lambda:True)

    def test_full_hearing_band_options_and_nyquist(self):
        for n in (32768,65536,131072):
            o=bb.options({'low':20,'high':20000,'fft_size':n},44100)
            self.assertEqual(o['high'],20000)
        for o in ({'high':20001},{'low':19},{'fft_size':8192.5},{'spatial_samples':1000},{'spatial_method':'invalid'}):
            with self.assertRaises(ValueError):bb.options(o,44100)
        with self.assertRaises(ValueError):bb.options({'high':20000},32000)

    def test_fast_full_band_response_matches_direct_paths(self):
        c=self.scene();c.update(order=5,yaw=31,pitch=-17,roll=53,directivity=.4)
        c['desk']['enabled']=True
        points=np.array([[5,5,2],[5.2,5,.7],[4.8,5.3,1.4],[1,9,5]])
        # Short FFT periods force long reflection delays to wrap on the impulse
        # grid; frequency responses must still match direct path exponentials.
        for rate,n in ((44100,4096),(44100,131072),(48000,65536),(96000,8192)):
            bins=np.unique(np.linspace(np.ceil(20*n/rate),np.floor(20000*n/rate),73).astype(int))
            fast=bb.fft_response(c,points,bins,n,rate)
            exact=np.array([model.transfer(dict(c,frequency=k*rate/n),points) for k in bins])
            self.assertLess(np.max(abs(fast-exact))/np.max(abs(exact)),2e-6)

    def test_lazy_grid_keeps_all_points_and_streamed_covariance(self):
        c=self.scene();o=bb.options({'spatial_method':'grid'},44100)
        samples=bb.VolumeSamples(c,'bright',4000,o)
        points=np.concatenate(list(samples.batches(17)))
        expected=model.zone_points(dict(c,frequency=4000),'bright')
        np.testing.assert_allclose(points,expected,atol=1e-14)
        n=4096;bins=np.arange(10,300);f=bins*44100/n
        matrix,half=bb.integrate_volume(c,samples,bins,n,44100,lambda _:None,lambda:False)
        np.testing.assert_allclose(matrix,bb.covariance(bb.sweep(c,points,f)),rtol=3e-5,atol=1e-10)
        self.assertIsNone(half)
        full_band_grid=bb.VolumeSamples(c,'bright',20000,o,True)
        self.assertGreater(full_band_grid.count,18000)
        self.assertEqual(sum(len(p) for p in full_band_grid.batches(32)),full_band_grid.grid_count)

    def test_large_volume_sobol_is_independent_and_bounded(self):
        c=self.scene();c['bright']['size']=[1.5,1.5,.5]
        o=bb.options({'low':20,'high':20000,'spatial_samples':1024},44100)
        train=bb.VolumeSamples(c,'bright',20000,o)
        valid=bb.VolumeSamples(c,'bright',20000,o,True)
        self.assertGreater(train.grid_count,40_000_000)
        self.assertEqual(train.count,1024);self.assertEqual(train.method,'sobol')
        points=np.concatenate(list(train.batches(32)));holdout=np.concatenate(list(valid.batches(32)))
        self.assertTrue(np.all(model.inside(points,c['bright'])))
        self.assertFalse(np.allclose(points,holdout))
        np.testing.assert_allclose(points,np.concatenate(list(train.batches(16))))

    def test_sobol_half_sample_convergence_and_cancellation(self):
        c=self.scene();c['order']=0
        o=bb.options({'spatial_method':'sobol','spatial_samples':1024},44100)
        samples=bb.VolumeSamples(c,'dark',20000,o,True);bins=np.arange(2,1800,30)
        matrix,half=bb.integrate_volume(c,samples,bins,4096,44100,lambda _:None,lambda:False)
        points=np.concatenate(list(samples.batches(32)))[:512]
        exact=bb.covariance(bb.sweep(c,points,bins*44100/4096))
        np.testing.assert_allclose(half,exact,rtol=3e-5,atol=1e-10)
        self.assertTrue(np.all(np.isfinite(matrix)))
        with self.assertRaisesRegex(ValueError,'cancelled'):
            bb.fft_response(c,points[:2],bins,4096,44100,lambda:True)

    def test_model_geometry_validation_can_skip_only_tone_allocation_guard(self):
        c=self.scene();c['frequency']=8000;c['bright']['size']=[1,1,.4]
        with self.assertRaisesRegex(ValueError,'18,000'):model.config(c)
        self.assertEqual(model.config(c,check_sampling=False)['bright'],c['bright'])
        c['bright']['size']=[-1,1,.4]
        with self.assertRaises(ValueError):model.config(c,check_sampling=False)

if __name__=='__main__':unittest.main()
