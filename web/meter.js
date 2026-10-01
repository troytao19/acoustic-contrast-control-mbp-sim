// Narrowband Hann-windowed quadrature amplitude estimator; no audio is sent to server.
class ToneMeter extends AudioWorkletProcessor {
  constructor(){super();this.frequency=700;this.buf=new Float32Array(4096);this.index=0;this.port.onmessage=e=>{this.frequency=e.data.frequency;this.index=0;};}
  process(inputs,outputs){
    const x=inputs[0]?.[0];
    // Explicitly silence output to prevent microphone monitoring/feedback.
    for(const channel of outputs[0]||[])channel.fill(0);
    if(!x)return true;
    for(const value of x){this.buf[this.index++]=value;if(this.index===this.buf.length){
      let re=0,im=0,wSum=0,peak=0;const n=this.buf.length;
      for(let i=0;i<n;i++){const w=.5-.5*Math.cos(2*Math.PI*i/(n-1)),a=2*Math.PI*this.frequency*i/sampleRate;re+=w*this.buf[i]*Math.cos(a);im-=w*this.buf[i]*Math.sin(a);wSum+=w;peak=Math.max(peak,Math.abs(this.buf[i]));}
      this.port.postMessage({power:4*(re*re+im*im)/(wSum*wSum),peak,time:currentTime});this.index=0;
    }}
    return true;
  }
}
registerProcessor('tone-meter',ToneMeter);
