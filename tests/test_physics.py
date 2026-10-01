import copy
import unittest
import numpy as np
from macbook_acc.model import DEFAULT, config, rotation, sources, transfer, optimize, metrics, solve, signature, zone_points, image_sources
from macbook_acc.calibration import probes, recover

class PhysicsTests(unittest.TestCase):
    def scene(self): return config(copy.deepcopy(DEFAULT))
    def test_3d_inverse_distance_and_phase(self):
        c=self.scene();c['order']=0;c['directivity']=0
        s=sources(c)[0];p=np.array([s+[0,0,.5],s+[0,0,1.]])
        h=transfer(c,p)[:,0];k=2*np.pi*c['frequency']/(331.3+.606*c['temperature'])
        self.assertAlmostEqual(abs(h[0])/abs(h[1]),2)
        np.testing.assert_allclose(h[1]/h[0],.5*np.exp(-1j*k*.5),atol=1e-12)
    def test_rotation_rigid_geometry(self):
        c=self.scene();c.update(yaw=40,pitch=90,roll=-37)
        r=rotation(c);np.testing.assert_allclose(r.T@r,np.eye(3),atol=1e-14)
        self.assertAlmostEqual(np.linalg.norm(sources(c)[1]-sources(c)[0]),.3)
        np.testing.assert_allclose(np.mean(sources(c),axis=0),np.array(c['laptop'])+r@np.array([0,0,.0168]))
    def test_symmetric_front_back_cannot_be_separated(self):
        c=self.scene();c['order']=0;c.update(yaw=20,pitch=45,roll=15)
        center=np.mean(sources(c),axis=0);n=rotation(c)[:,2]
        h=transfer(c,np.array([center+.5*n,center-.5*n]))
        np.testing.assert_allclose(h[0],h[1],atol=1e-13)
        q=optimize(h[:1],h[1:],.01)
        self.assertAlmostEqual(metrics(h[:1],h[1:],q)['contrast_db'],0,places=8)
    def test_first_order_images(self):
        c=self.scene();c['order']=1
        images=list(image_sources(c,sources(c)[0]));self.assertEqual(len(images),7)
        gains=sorted(round(float(g),6) for _,g,_ in images)
        self.assertEqual(gains,sorted(c['reflection']+[1.0]))
    def test_zero_reflection_matches_freefield(self):
        c=self.scene();c['reflection']=[0]*6;c['desk']['enabled']=False
        p=np.array([[5,5,2],[4,5,1]])
        h=transfer(c,p);c['order']=0
        np.testing.assert_allclose(h,transfer(c,p))
    def test_calibration_phase_convention(self):
        for h in (np.array([1.3+.8j,-.7+.2j]),np.array([.2j,2+1j])):
            peak=.025;noise=1e-9;p=[noise+abs(h@q*peak)**2 for q in probes()]
            result=recover(p,peak);a=np.array(result['h']);actual=a[:,0]+1j*a[:,1]
            expected=h*np.exp(-1j*np.angle(h[0]))
            np.testing.assert_allclose(actual,expected,rtol=1e-9,atol=1e-9)
            # Row phase must leave both cross-channel covariance and arbitrary playback power unchanged.
            np.testing.assert_allclose(np.outer(actual.conj(),actual),np.outer(h.conj(),h),atol=1e-9)
    def test_calibration_rejects_gain_drift_and_noise(self):
        h=np.array([1+.2j,.7-.4j]);peak=.025;p=np.array([1e-9+abs(h@q*peak)**2 for q in probes()]);p[-1]*=1.5
        with self.assertRaisesRegex(ValueError,'Rejected'):recover(p,peak)
        with self.assertRaisesRegex(ValueError,'Rejected'):recover(np.ones(12),peak)
    def test_acc_matches_dense_amplitude_phase_search(self):
        rng=np.random.default_rng(7);hb=rng.normal(size=(12,2))+1j*rng.normal(size=(12,2));hd=rng.normal(size=(12,2))+1j*rng.normal(size=(12,2));beta=.01
        q=optimize(hb,hd,beta);rb=hb.conj().T@hb/len(hb);rd=hd.conj().T@hd/len(hd);rd+=beta*np.trace((rb+rd)/2).real/2*np.eye(2)
        def score(w):return ((w.conj()@rb@w)/(w.conj()@rd@w)).real
        best=score(q)
        for a in np.linspace(0,np.pi/2,35):
            for p in np.linspace(-np.pi,np.pi,60):self.assertGreaterEqual(best+1e-9,score(np.array([np.cos(a),np.sin(a)*np.exp(1j*p)])))
    def test_calibration_invalidated_by_pose_not_display(self):
        c=self.scene();s=signature(c);c['slice_z']+=.1;self.assertEqual(signature(c),s)
        c['roll']+=1;self.assertNotEqual(signature(c),s)
    def test_small_zone_sampling_and_holdout(self):
        c=self.scene();p=zone_points(c,'bright');q=zone_points(c,'bright',True)
        self.assertTrue(len(q)>len(p));self.assertTrue(np.ptp(p[:,2])>0)
    def test_invalid_overlapping_and_nan_scenes(self):
        c=self.scene();c['dark']=copy.deepcopy(c['bright'])
        with self.assertRaises(ValueError):config(c)
        c=self.scene();c['pitch']=float('nan')
        with self.assertRaises(ValueError):config(c)
    def test_measured_mode_requires_real_spatial_data(self):
        c=self.scene();c['mode']='measured'
        with self.assertRaisesRegex(ValueError,'distinct'):solve(c)
    def test_finite_table_reflects_on_both_sides(self):
        c=self.scene();c['order']=1;c['reflection']=[0]*6;c['desk']['enabled']=True;c['desk']['height']=1
        p=np.array([[5,5,1.8],[5,5,.6]])
        with_desk=transfer(c,p);c['desk']['enabled']=False;without=transfer(c,p)
        self.assertGreater(np.max(abs(with_desk[0]-without[0])),1e-3)
        np.testing.assert_allclose(with_desk[1],without[1])
    def test_solve_genuine_volume_and_planes(self):
        s=solve(self.scene());self.assertEqual(set(s['slices']),{'xy','xz','yz'})
        self.assertGreater(np.ptp(np.array(s['cloud']['points'])[:,2]),1)
        self.assertTrue(np.isfinite(s['model_validation']['contrast_db']))
        self.assertAlmostEqual(np.linalg.norm(np.array(s['weights'])),1)

if __name__=='__main__':unittest.main()
