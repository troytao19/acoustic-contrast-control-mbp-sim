"""Bounded local background jobs for broadband design and sample management."""
import base64
import json
from pathlib import Path
import secrets
import threading
import time
from . import broadband, model

ROOT = Path(__file__).resolve().parent.parent
JOBS = {}
LOCK = threading.RLock()


def sources():
    rows=json.loads((ROOT/'media'/'sources.json').read_text())
    index=ROOT/'data'/'uploads'/'index.json'
    if index.exists():rows+=json.loads(index.read_text())
    return [{**r,'available':audio_path(r).is_file()} for r in rows]


def audio_path(row):
    return (ROOT/'data'/'uploads' if row.get('uploaded') else ROOT/'media')/row['file']


def upload(p):
    raw=base64.b64decode(p['data'],validate=True)
    if not 44<=len(raw)<=24_000_000:raise ValueError('WAV upload must be below 24 MB.')
    folder=ROOT/'data'/'uploads';folder.mkdir(exist_ok=True,parents=True)
    uid=secrets.token_hex(12);path=folder/(uid+'.wav')
    path.write_bytes(raw)
    try:_,meta=broadband.read_audio(path)
    except Exception:
        path.unlink(missing_ok=True);raise
    item={'id':uid,'name':str(p.get('name','Uploaded WAV'))[:120], 'file':path.name,'uploaded':True,'source':'Local WAV upload','credit':'User supplied audio','license':'User supplied','duration':meta['duration']}
    with LOCK:
        index=folder/'index.json';rows=json.loads(index.read_text()) if index.exists() else []
        rows.append(item);temp=index.with_suffix('.tmp');temp.write_text(json.dumps(rows));temp.replace(index)
    return item


def start(config,opts,audio_id,hardware):
    c=model.config(config,check_sampling=False);rate=int((hardware or {}).get('sample_rate',44100))
    if rate not in (32000,44100,48000,88200,96000):raise ValueError('Use an output sample rate between 32 and 96 kHz supported by this renderer.')
    o=broadband.options(opts,rate)
    item=next((s for s in sources() if s['id']==audio_id),None)
    if item is None or not item['available']:raise ValueError('Select an available audio sample or upload a WAV.')
    with LOCK:
        if any(j['status']=='running' for j in JOBS.values()):raise ValueError('A broadband job is already running. Cancel it or wait for completion.')
        uid=secrets.token_hex(12);folder=ROOT/'data'/'broadband'/uid
        job={'id':uid,'status':'running','progress':0,'message':'Starting','cancel':threading.Event(),'folder':folder,'hardware':hardware,'created':time.time()}
        JOBS[uid]=job
        while len(JOBS)>8:JOBS.pop(next(iter(JOBS)))
    def progress(value,message):
        with LOCK:job.update(progress=value,message=message)
    def run():
        try:
            result=broadband.render(c,o,audio_path(item),rate,folder,progress,job['cancel'].is_set)
            result.update(id=uid,source=item,hardware=hardware)
            (folder/'report.json').write_text(json.dumps(result,indent=2,allow_nan=False))
            with LOCK:job.update(status='ready',result=result,progress=1)
        except Exception as e:
            with LOCK:job.update(status='cancelled' if job['cancel'].is_set() else 'error',message=str(e))
    threading.Thread(target=run,daemon=True).start()
    return {'id':uid,'status':'running'}


def get(uid):
    with LOCK:
        job=JOBS.get(uid)
        if job is None:raise ValueError('Broadband job expired. Optimize the band again.')
        return job


def status(uid):
    job=get(uid)
    with LOCK:return {k:job[k] for k in ('id','status','progress','message','result') if k in job}


def cancel(uid):
    get(uid)['cancel'].set();return {'cancel_requested':True}
