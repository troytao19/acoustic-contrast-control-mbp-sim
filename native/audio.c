// Native macOS AUHAL output. No AVAudioEngine, browser playback, or default route.
#include <AudioUnit/AudioUnit.h>
#include <CoreAudio/CoreAudio.h>
#include <CoreFoundation/CoreFoundation.h>
#include <math.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <time.h>
static volatile sig_atomic_t stopping = 0;
static double rate=48000, frequency=700, amplitude[2]={0,0}, phase[2]={0,0};
static unsigned long long frame=0, total=0;
static float *pcm=NULL;
static double pcm_rate=0, pcm_gain=0;
static void stop(int s) { (void)s; stopping=1; }
static void check(OSStatus s,const char *what) { if(s){fprintf(stderr,"%s: Core Audio error %d\n",what,(int)s);exit(2);} }
static UInt32 channels(AudioDeviceID id, AudioObjectPropertyScope scope) {
 AudioObjectPropertyAddress p={kAudioDevicePropertyStreamConfiguration,scope,kAudioObjectPropertyElementMain};
 UInt32 size=0,n=0; if(AudioObjectGetPropertyDataSize(id,&p,0,NULL,&size)) return 0;
 AudioBufferList *b=malloc(size); if(!b)return 0;
 if(!AudioObjectGetPropertyData(id,&p,0,NULL,&size,b)) for(UInt32 i=0;i<b->mNumberBuffers;i++)n+=b->mBuffers[i].mNumberChannels;
 free(b);return n;
}
static UInt32 transport(AudioDeviceID id) {
 UInt32 v=0,size=sizeof(v);AudioObjectPropertyAddress p={kAudioDevicePropertyTransportType,kAudioObjectPropertyScopeGlobal,kAudioObjectPropertyElementMain};
 AudioObjectGetPropertyData(id,&p,0,NULL,&size,&v);return v;
}
static void name(AudioDeviceID id,char *out,size_t cap) {
 CFStringRef str=NULL;UInt32 size=sizeof(str);AudioObjectPropertyAddress p={kAudioObjectPropertyName,kAudioObjectPropertyScopeGlobal,kAudioObjectPropertyElementMain};
 out[0]=0;if(!AudioObjectGetPropertyData(id,&p,0,NULL,&size,&str)&&str){CFStringGetCString(str,out,cap,kCFStringEncodingUTF8);CFRelease(str);}
}
static double scalar(AudioDeviceID id, AudioObjectPropertySelector selector, UInt32 element) {
 Float32 v=0;UInt32 size=sizeof(v);AudioObjectPropertyAddress p={selector,kAudioDevicePropertyScopeOutput,element};
 return AudioObjectGetPropertyData(id,&p,0,NULL,&size,&v)==noErr?v:-1;
}
static void settings(AudioDeviceID id) {
 Float64 sr=0;UInt32 size=sizeof(sr);AudioObjectPropertyAddress p={kAudioDevicePropertyNominalSampleRate,kAudioObjectPropertyScopeGlobal,kAudioObjectPropertyElementMain};
 AudioObjectGetPropertyData(id,&p,0,NULL,&size,&sr);
 UInt32 mute=0;size=sizeof(mute);p=(AudioObjectPropertyAddress){kAudioDevicePropertyMute,kAudioDevicePropertyScopeOutput,kAudioObjectPropertyElementMain};
 int muteok=AudioObjectGetPropertyData(id,&p,0,NULL,&size,&mute)==noErr;
 printf(",\"sample_rate\":%.0f,\"volume_scalar\":[%.8f,%.8f,%.8f],\"muted\":%s",sr,scalar(id,kAudioDevicePropertyVolumeScalar,0),scalar(id,kAudioDevicePropertyVolumeScalar,1),scalar(id,kAudioDevicePropertyVolumeScalar,2),muteok?(mute?"true":"false"):"null");
}
static void jsonstring(const char *s) { putchar('"');for(;*s;s++){unsigned char c=*s;if(c=='"'||c=='\\')putchar('\\');if(c>=32)putchar(c);}putchar('"'); }
static AudioDeviceID devices(int list) {
 AudioObjectPropertyAddress p={kAudioHardwarePropertyDevices,kAudioObjectPropertyScopeGlobal,kAudioObjectPropertyElementMain};
 UInt32 size=0; check(AudioObjectGetPropertyDataSize(kAudioObjectSystemObject,&p,0,NULL,&size),"Enumerate devices");
 AudioDeviceID *ids=malloc(size?size:1);check(AudioObjectGetPropertyData(kAudioObjectSystemObject,&p,0,NULL,&size,ids),"Read devices");
 AudioDeviceID selected=0;int first=1;if(list)printf("{\"devices\":[");
 for(UInt32 i=0;i<size/sizeof(*ids);i++){
  char n[512];name(ids[i],n,sizeof(n));UInt32 out=channels(ids[i],kAudioDevicePropertyScopeOutput),in=channels(ids[i],kAudioDevicePropertyScopeInput);
  // Do not silently select headphones or an external output. Require identified internal speaker route.
  int builtin=transport(ids[i])==kAudioDeviceTransportTypeBuiltIn;
  int speaker=builtin&&out==2&&(strstr(n,"Speaker")||strstr(n,"speaker"));if(speaker)selected=ids[i];
  if(list){if(!first)putchar(',');first=0;printf("{\"id\":%u,\"name\":",ids[i]);jsonstring(n);printf(",\"output_channels\":%u,\"input_channels\":%u,\"built_in\":%s,\"speaker_route\":%s",out,in,builtin?"true":"false",speaker?"true":"false");settings(ids[i]);putchar('}');}
 }
 free(ids);if(list)printf("],\"selected_output\":%u,\"backend\":\"Core Audio AUHAL\"}\n",selected);return selected;
}
static OSStatus render(void *ref,AudioUnitRenderActionFlags *flags,const AudioTimeStamp *time,UInt32 bus,UInt32 count,AudioBufferList *data){
 (void)ref;(void)flags;(void)time;(void)bus;
 if(data->mNumberBuffers!=1||data->mBuffers[0].mNumberChannels!=2)return kAudio_ParamError;
 float *out=data->mBuffers[0].mData; double ramp=rate*0.025;
 for(UInt32 i=0;i<count;i++,frame++){
  if(pcm){for(int c=0;c<2;c++)out[2*i+c]=frame<total?(float)(pcm[2*frame+c]*pcm_gain):0;continue;}
  double env=frame>=total?0:fmin(1.0,fmin(frame/ramp,(total-frame)/ramp));
  double a=2*M_PI*frequency*(double)frame/rate;
  for(int c=0;c<2;c++)out[2*i+c]=(float)(env*amplitude[c]*cos(a+phase[c]));
 }
 return noErr;
}
int main(int argc,char **argv){
 if(argc==2&&!strcmp(argv[1],"devices")){devices(1);return 0;}
 double seconds=0;
 if(argc==5&&!strcmp(argv[1],"pcm")){
  pcm_rate=strtod(argv[3],NULL);pcm_gain=strtod(argv[4],NULL);
  if(!isfinite(pcm_rate)||pcm_rate<8000||pcm_rate>192000||!isfinite(pcm_gain)||pcm_gain<0||pcm_gain>0.08){fprintf(stderr,"Invalid PCM sample rate/gain\n");return 2;}
  FILE *file=fopen(argv[2],"rb");if(!file){perror("Open PCM");return 2;}
  if(fseek(file,0,SEEK_END)){fclose(file);return 2;}long bytes=ftell(file);rewind(file);
  if(bytes<=0||bytes%8||bytes>64*1024*1024){fclose(file);fprintf(stderr,"Invalid stereo Float32 PCM length\n");return 2;}
  total=(unsigned long long)bytes/8;seconds=total/pcm_rate;
  if(seconds>35){fclose(file);fprintf(stderr,"PCM clip exceeds 35 seconds including filter tail\n");return 2;}
  pcm=malloc((size_t)bytes);if(!pcm||fread(pcm,1,(size_t)bytes,file)!=(size_t)bytes){fclose(file);free(pcm);return 2;}fclose(file);
  for(unsigned long long i=0;i<total*2;i++)if(!isfinite(pcm[i])||fabs(pcm[i])>1.00001){fprintf(stderr,"PCM must be finite and within full scale\n");free(pcm);return 2;}
 }else{
  if(argc!=8||strcmp(argv[1],"play")){fprintf(stderr,"Usage: audio devices | audio play frequency aL phaseL aR phaseR seconds | audio pcm path sample_rate gain\n");return 2;}
  frequency=strtod(argv[2],NULL);amplitude[0]=strtod(argv[3],NULL);phase[0]=strtod(argv[4],NULL);amplitude[1]=strtod(argv[5],NULL);phase[1]=strtod(argv[6],NULL);seconds=strtod(argv[7],NULL);
  if(!isfinite(frequency)||frequency<80||frequency>8000||!isfinite(seconds)||seconds<0.1||seconds>30){fprintf(stderr,"Invalid frequency/duration\n");return 2;}
  for(int c=0;c<2;c++)if(!isfinite(amplitude[c])||amplitude[c]<0||amplitude[c]>0.08||!isfinite(phase[c])){fprintf(stderr,"Invalid amplitude/phase (peak ceiling 0.08)\n");return 2;}
 }
 AudioDeviceID device=devices(0);if(!device){fprintf(stderr,"No identified built-in stereo speaker device. Check macOS audio access; no fallback route is used.\n");return 3;}
 AudioObjectPropertyAddress p={kAudioDevicePropertyNominalSampleRate,kAudioObjectPropertyScopeGlobal,kAudioObjectPropertyElementMain};UInt32 sz=sizeof(rate);check(AudioObjectGetPropertyData(device,&p,0,NULL,&sz,&rate),"Read sample rate");
 if(pcm&&fabs(rate-pcm_rate)>.01){fprintf(stderr,"Device sample rate changed; re-render filters before playback\n");free(pcm);return 2;}
 if(!pcm&&frequency>=rate/2){fprintf(stderr,"Frequency exceeds Nyquist\n");return 2;}
 AudioComponentDescription desc={kAudioUnitType_Output,kAudioUnitSubType_HALOutput,kAudioUnitManufacturer_Apple,0,0};
 AudioComponent component=AudioComponentFindNext(NULL,&desc);if(!component){fprintf(stderr,"AUHAL unavailable\n");return 3;}
 AudioUnit unit;check(AudioComponentInstanceNew(component,&unit),"Create AUHAL");
 UInt32 enable=1;check(AudioUnitSetProperty(unit,kAudioOutputUnitProperty_EnableIO,kAudioUnitScope_Output,0,&enable,sizeof(enable)),"Enable output");
 check(AudioUnitSetProperty(unit,kAudioOutputUnitProperty_CurrentDevice,kAudioUnitScope_Global,0,&device,sizeof(device)),"Select internal speakers");
 AudioStreamBasicDescription fmt={0};fmt.mSampleRate=rate;fmt.mFormatID=kAudioFormatLinearPCM;fmt.mFormatFlags=kAudioFormatFlagIsFloat|kAudioFormatFlagIsPacked;fmt.mBytesPerPacket=8;fmt.mFramesPerPacket=1;fmt.mBytesPerFrame=8;fmt.mChannelsPerFrame=2;fmt.mBitsPerChannel=32;
 check(AudioUnitSetProperty(unit,kAudioUnitProperty_StreamFormat,kAudioUnitScope_Input,0,&fmt,sizeof(fmt)),"Set stereo Float32 PCM");
 SInt32 map[2]={0,1};check(AudioUnitSetProperty(unit,kAudioOutputUnitProperty_ChannelMap,kAudioUnitScope_Output,0,map,sizeof(map)),"Map L/R");
 AURenderCallbackStruct cb={render,NULL};check(AudioUnitSetProperty(unit,kAudioUnitProperty_SetRenderCallback,kAudioUnitScope_Input,0,&cb,sizeof(cb)),"Set render callback");
 check(AudioUnitInitialize(unit),"Initialize output");if(!pcm)total=(unsigned long long)(seconds*rate);
 signal(SIGTERM,stop);signal(SIGINT,stop);check(AudioOutputUnitStart(unit),"Start output");
 printf("{\"playing\":true,\"device_id\":%u,\"sample_rate\":%.0f}\n",device,rate);fflush(stdout);
 // Main thread deadline avoids reading the render thread's mutable frame counter.
 struct timespec start,now;clock_gettime(CLOCK_MONOTONIC,&start);
 do{usleep(10000);clock_gettime(CLOCK_MONOTONIC,&now);}while(!stopping&&((now.tv_sec-start.tv_sec)+(now.tv_nsec-start.tv_nsec)/1e9)<seconds+0.1);
 AudioOutputUnitStop(unit);AudioUnitUninitialize(unit);AudioComponentInstanceDispose(unit);free(pcm);return 0;
}
