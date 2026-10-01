import copy
import json
import tempfile
import threading
import time
import unittest
import urllib.request
import urllib.error
from pathlib import Path
from unittest.mock import patch
import numpy as np
from macbook_acc import server, model, calibration, band_jobs
from scipy.io import wavfile

STAMP={'id':79,'name':'MacBook Pro Speakers','output_channels':2,'input_channels':0,'built_in':True,'speaker_route':True,'sample_rate':44100,'volume_scalar':[.2,-1,-1],'muted':False}
HARDWARE={'devices':[STAMP],'selected_output':79}

class APITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.original=server.DATA;server.DATA=Path(cls.temp.name)
        cls.patch=patch.object(server,'hardware',return_value=HARDWARE);cls.patch.start()
        cls.http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        cls.thread=threading.Thread(target=cls.http.serve_forever,daemon=True);cls.thread.start();cls.url=f'http://127.0.0.1:{cls.http.server_port}'
    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown();cls.http.server_close();cls.patch.stop();server.DATA=cls.original;cls.temp.cleanup()
    def post(self,path,p,token=True,origin=None):
        headers={'Content-Type':'application/json'}
        if token:headers['X-ACC-Token']=server.TOKEN
        if origin:headers['Origin']=origin
        req=urllib.request.Request(self.url+'/api/'+path,json.dumps(p).encode(),headers=headers)
        with urllib.request.urlopen(req) as r:return json.load(r)
    def test_token_and_origin_required(self):
        for token,origin in ((False,None),(True,'https://example.com')):
            with self.assertRaises(urllib.error.HTTPError) as err:self.post('solve',{},token,origin)
            self.assertEqual(err.exception.code,403)
    def test_solve_and_play_exact_weights(self):
        s=self.post('solve',{'config':model.DEFAULT})
        with patch.object(server,'play',return_value={'playing':True}) as play:
            self.post('play',{'id':s['id'],'variant':'optimized','peak':.02,'seconds':1})
            np.testing.assert_allclose(play.call_args.args[1],model.decode_weights(s['weights']))
        with patch.object(server,'hardware',return_value={'devices':[],'selected_output':0}):
            with self.assertRaises(urllib.error.HTTPError):self.post('play',{'id':s['id']})
    def test_calibration_measured_optimization_and_ab(self):
        c=copy.deepcopy(model.DEFAULT);c['session']='automated-test-only';s=self.post('solve',{'config':c});peak=.025
        for zi,z in enumerate(('bright','dark')):
            for i,dx in enumerate((-.03,0,.03)):
                h=np.array([1+0j,(.8 if zi==0 else -.8)+.1j*i]);powers=[1e-10+abs(h@q*peak)**2 for q in calibration.probes()]
                pos=c[z]['center'].copy();pos[0]+=dx
                r=self.post('calibrate',{'id':s['id'],'config':c,'position':pos,'role':'train','peak':peak,'powers':powers,'scatter':[0]*12,'microphone':'synthetic-test','fixed_gain_confirmed':True})
        c['mode']='measured';s=self.post('solve',{'config':c});self.assertGreater(s['training']['contrast_db'],10)
        for zi,z in enumerate(('bright','dark')):
            for dx in (-.025,0,.025):
                pos=c[z]['center'].copy();pos[0]+=dx;pos[1]+=.025
                # Distinct fixed-weight A/B points; synthetic values are never saved to the real data directory.
                powers=[1e-8,.001,.002 if zi==0 else .00002,.002 if zi==0 else .00002,.001]
                r=self.post('validate',{'id':s['id'],'position':pos,'powers':powers,'scatter':[0]*5,'microphone':'synthetic-test','peak':peak})
        self.assertTrue(r['summary']['verified']);self.assertGreater(r['summary']['optimized_db'],19)
        changed=copy.deepcopy(c);changed['pitch']=10
        with self.assertRaises(urllib.error.HTTPError):self.post('solve',{'config':changed})
    def test_broadband_job_export_and_exact_pcm_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(band_jobs,'ROOT',Path(tmp)):
            root=Path(tmp);(root/'media').mkdir()
            sr=44100;t=np.arange(sr)/sr
            wavfile.write(root/'media'/'test.wav',sr,(.2*np.cos(2*np.pi*700*t)).astype(np.float32))
            (root/'media'/'sources.json').write_text(json.dumps([{'id':'test','file':'test.wav','name':'Test audio'}]))
            c=copy.deepcopy(model.DEFAULT);c['order']=0
            c['bright']['center']=[4.75,5,1.9];c['dark']['center']=[5.25,5,.9]
            job=self.post('broadband-start',{'config':c,'options':{'low':200,'high':1600,'fft_size':4096},'audio_id':'test'})
            deadline=time.monotonic()+10
            while time.monotonic()<deadline:
                result=self.post('broadband-status',{'id':job['id']})
                if result['status']!='running':break
                time.sleep(.02)
            self.assertEqual(result['status'],'ready',result.get('message'))
            with patch.object(server,'play_pcm',return_value={'playing':True}) as play:
                self.post('broadband-play',{'id':job['id'],'config':c,'variant':'optimized','peak':.02})
                self.assertEqual(play.call_args.args[0].name,'optimized.f32')
                self.assertEqual(play.call_args.args[1],sr)
                self.assertEqual(play.call_args.args[2],.02)
            with urllib.request.urlopen(self.url+'/api/broadband-file/'+job['id']+'/optimized.wav') as response:
                self.assertTrue(response.read(4)==b'RIFF')
            changed=copy.deepcopy(c);changed['yaw']=15
            with self.assertRaises(urllib.error.HTTPError):self.post('broadband-play',{'id':job['id'],'config':changed})
    def test_no_arbitrary_static_file_reads(self):
        with self.assertRaises(urllib.error.HTTPError):urllib.request.urlopen(self.url+'/../requirements.txt')

if __name__=='__main__':unittest.main()
