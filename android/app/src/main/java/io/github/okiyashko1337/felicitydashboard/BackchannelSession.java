package io.github.okiyashko1337.felicitydashboard;

import android.content.Context;
import android.media.AudioFormat;
import android.media.AudioRecord;
import android.media.MediaRecorder;
import android.os.ParcelFileDescriptor;
import java.io.BufferedInputStream;
import java.io.BufferedOutputStream;
import java.io.ByteArrayOutputStream;
import java.io.FileDescriptor;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.DatagramSocket;
import java.net.Socket;
import java.net.URL;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Locale;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import org.videolan.libvlc.LibVLC;
import org.videolan.libvlc.Media;
import org.videolan.libvlc.MediaPlayer;

final class BackchannelSession {
    interface Listener { void onStarted(); void onError(String message); }
    private final Context context;private final String host,user,password;private final Listener listener;private volatile boolean stopped;private Socket rtsp;private AudioRecord recorder;private Thread thread,recordThread;private LibVLC vlc;private MediaPlayer encoder;private ParcelFileDescriptor readPipe,writePipe;
    BackchannelSession(Context context,String host,String user,String password,Listener listener){this.context=context;this.host=host.split(":")[0];this.user=user;this.password=password;this.listener=listener;}
    void start(){thread=new Thread(this::run,"ajax-talk-rtsp");thread.start();}
    void stop(){stopped=true;if(recorder!=null)try{recorder.stop();}catch(Exception ignored){}if(encoder!=null)encoder.stop();close();}
    private void run(){try{String base="rtsp://"+host+":8554/040d84a53698-0_s";rtsp=new Socket(host,8554);rtsp.setSoTimeout(7000);Response first=request("DESCRIBE",base,1,"Accept: application/sdp\r\nRequire: www.onvif.org/ver20/backchannel\r\n",null);String challenge=first.auth;if(challenge==null)throw new Exception("Digest challenge missing");Response described=request("DESCRIBE",base,2,"Accept: application/sdp\r\nRequire: www.onvif.org/ver20/backchannel\r\n",digest(challenge,"DESCRIBE",base));if(described.code!=200)throw new Exception("DESCRIBE "+described.code);
            int clientPort;try(DatagramSocket probe=new DatagramSocket(0)){clientPort=probe.getLocalPort();}String track=base+"/trackID=3";Response setup=request("SETUP",track,3,"Transport: RTP/AVP;unicast;client_port="+clientPort+"-"+(clientPort+1)+"\r\nRequire: www.onvif.org/ver20/backchannel\r\n",digest(challenge,"SETUP",track));if(setup.code!=200)throw new Exception("SETUP "+setup.code);String session=match(setup.head,"Session:\\s*([^;\\r\\n]+)"),port=match(setup.head,"server_port=(\\d+)");if(session==null||port==null)throw new Exception("Backchannel transport missing");Response play=request("PLAY",base,4,"Session: "+session+"\r\nRange: npt=0.000-\r\nRequire: www.onvif.org/ver20/backchannel\r\n",digest(challenge,"PLAY",base));if(play.code!=200)throw new Exception("PLAY "+play.code);startAudio(Integer.parseInt(port));Thread.sleep(500);if(!stopped)listener.onStarted();while(!stopped){Thread.sleep(1000);request("GET_PARAMETER",base,5,"Session: "+session+"\r\n",digest(challenge,"GET_PARAMETER",base));}}
        catch(Exception e){if(!stopped)listener.onError(e.getMessage()==null?e.getClass().getSimpleName():e.getMessage());}finally{close();}}
    private void startAudio(int port)throws Exception{int min=AudioRecord.getMinBufferSize(16000,AudioFormat.CHANNEL_IN_MONO,AudioFormat.ENCODING_PCM_16BIT);recorder=new AudioRecord(MediaRecorder.AudioSource.VOICE_COMMUNICATION,16000,AudioFormat.CHANNEL_IN_MONO,AudioFormat.ENCODING_PCM_16BIT,Math.max(min,4096));if(recorder.getState()!=AudioRecord.STATE_INITIALIZED)throw new Exception("Microphone unavailable");ParcelFileDescriptor[] pipes=ParcelFileDescriptor.createPipe();readPipe=pipes[0];writePipe=pipes[1];ArrayList<String> options=new ArrayList<>();options.add("--no-video");vlc=new LibVLC(context,options);FileDescriptor fd=readPipe.getFileDescriptor();Media media=new Media(vlc,fd);media.addOption(":demux=rawaud");media.addOption(":rawaud-channels=1");media.addOption(":rawaud-samplerate=16000");media.addOption(":rawaud-fourcc=s16l");media.addOption(":sout=#transcode{acodec=G722,channels=1,samplerate=16000}:rtp{dst="+host+",port="+port+",pt=9}");media.addOption(":sout-keep");encoder=new MediaPlayer(vlc);encoder.setMedia(media);media.release();encoder.play();recorder.startRecording();recordThread=new Thread(()->{byte[] data=new byte[2048];try(OutputStream out=new ParcelFileDescriptor.AutoCloseOutputStream(writePipe)){while(!stopped){int n=recorder.read(data,0,data.length);if(n>0)out.write(data,0,n);}}catch(Exception ignored){}},"ajax-talk-mic");recordThread.start();}
    private Response request(String method,String uri,int cseq,String extra,String auth)throws Exception{StringBuilder b=new StringBuilder(method+" "+uri+" RTSP/1.0\r\nCSeq: "+cseq+"\r\nUser-Agent: Felicity-Android/0.15\r\n");if(auth!=null)b.append("Authorization: ").append(auth).append("\r\n");b.append(extra).append("\r\n");OutputStream out=new BufferedOutputStream(rtsp.getOutputStream());out.write(b.toString().getBytes("ISO-8859-1"));out.flush();InputStream in=new BufferedInputStream(rtsp.getInputStream());ByteArrayOutputStream head=new ByteArrayOutputStream();int state=0,v;while((v=in.read())>=0){head.write(v);state=(state==0&&v=='\r')?1:(state==1&&v=='\n')?2:(state==2&&v=='\r')?3:(state==3&&v=='\n')?4:0;if(state==4)break;}String h=head.toString("ISO-8859-1");String length=match(h,"Content-Length:\\s*(\\d+)");int n=length==null?0:Integer.parseInt(length);byte[] body=new byte[n];for(int off=0;off<n;){int got=in.read(body,off,n-off);if(got<0)break;off+=got;}String status=match(h,"RTSP/1.0\\s+(\\d+)");return new Response(status==null?0:Integer.parseInt(status),h,match(h,"WWW-Authenticate:\\s*Digest\\s+([^\\r\\n]+)"));}
    private String digest(String challenge,String method,String address)throws Exception{String realm=param(challenge,"realm"),nonce=param(challenge,"nonce"),ha1=md5(user+":"+realm+":"+password),ha2=md5(method+":"+address),response=md5(ha1+":"+nonce+":"+ha2);return "Digest username=\""+user+"\", realm=\""+realm+"\", nonce=\""+nonce+"\", uri=\""+address+"\", response=\""+response+"\"";}
    private void close(){if(recordThread!=null)recordThread.interrupt();if(recorder!=null){recorder.release();recorder=null;}if(encoder!=null){encoder.release();encoder=null;}if(vlc!=null){vlc.release();vlc=null;}try{if(readPipe!=null)readPipe.close();}catch(Exception ignored){}try{if(writePipe!=null)writePipe.close();}catch(Exception ignored){}try{if(rtsp!=null)rtsp.close();}catch(Exception ignored){}}
    private static String param(String s,String name){Matcher m=Pattern.compile(name+"=\"([^\"]+)\"",Pattern.CASE_INSENSITIVE).matcher(s);return m.find()?m.group(1):"";}private static String match(String s,String re){Matcher m=Pattern.compile(re,Pattern.CASE_INSENSITIVE).matcher(s);return m.find()?m.group(1):null;}private static String md5(String s)throws Exception{byte[] d=MessageDigest.getInstance("MD5").digest(s.getBytes("ISO-8859-1"));StringBuilder b=new StringBuilder();for(byte v:d)b.append(String.format(Locale.US,"%02x",v&255));return b.toString();}
    private static final class Response{final int code;final String head,auth;Response(int code,String head,String auth){this.code=code;this.head=head;this.auth=auth;}}
}
