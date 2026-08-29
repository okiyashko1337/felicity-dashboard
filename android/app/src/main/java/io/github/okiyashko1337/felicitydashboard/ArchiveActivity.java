package io.github.okiyashko1337.felicitydashboard;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.graphics.BitmapFactory;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.RectF;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.StateListDrawable;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.TextureView;
import android.view.View;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.GridLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.TextView;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Calendar;
import java.util.Collections;
import java.util.Date;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import org.videolan.libvlc.LibVLC;
import org.videolan.libvlc.Media;
import org.videolan.libvlc.MediaPlayer;
import org.videolan.libvlc.interfaces.IMedia;

public final class ArchiveActivity extends Activity {
    private static final long KEYFRAME_PREROLL_MS=4000;
    private final ExecutorService network=Executors.newCachedThreadPool();
    private final ExecutorService metadataNetwork=Executors.newSingleThreadExecutor();
    private final Handler main=new Handler(Looper.getMainLooper());
    private final ThreeEyeState eventsState=new ThreeEyeState();
    private ThreeEyeClient eventsClient;
    private SharedPreferences prefs;private CameraCatalog.Camera camera;
    private FrameLayout videoContainer;private TextureView surface;private ImageView bestView;private ArchiveOverlay overlay;
    private LibVLC vlc;private MediaPlayer player;private OnvifReplayProxy proxy;private AjaxMetadataSession metadataSession;
    private long syncTime,actualTime,fallbackTime,replayBaseTime,replayClockSourceTime,replayStartedAt,playbackAnchorRealtime,playbackAnchorArchiveTime,lastStatsMs,profileLoadedStart=Long.MAX_VALUE,profileLoadedEnd=Long.MIN_VALUE;private boolean fallbackTried,paused=true,timelineRequested,substream,destroyed,videoLayoutKnown,initialFramePaused,strictEventTarget,profileLoadRunning,playWhenReady;private int eventLoadAttempts,videoWidth,videoHeight,replayRequest,lastPictures,lastReadBytes=-1;private float displayAspect=16f/9f,smoothedFps=-1f,smoothedKbps=-1f;
    private List<ThreeEyeState.Event> archiveEvents=new ArrayList<>();private List<ProfileGClient.SearchEvent> profileEvents=new ArrayList<>();private Button playPause;private TextView streamStats,playbackClock;private String backLabel="‹ LIVE";private float ui=1f;
    private final Runnable firstFrameTimeout=()->{if(player!=null&&bestView.getVisibility()==View.VISIBLE)replayFailed();};
    private final Runnable timelineTick=new Runnable(){@Override public void run(){if(player!=null&&initialFramePaused)updateActualTimeFromPlayer();fitSurface();updateStreamStats();updatePlaybackClock();if(overlay!=null)overlay.invalidate();main.postDelayed(this,500);}};

    @Override protected void onCreate(Bundle saved){super.onCreate(saved);getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);immersive();prefs=getSharedPreferences("felicity",MODE_PRIVATE);substream=StreamQuality.useSubstream(this,prefs);strictEventTarget=getIntent().getBooleanExtra("from_event",false);camera=CameraCatalog.find(prefs,getIntent().getStringExtra("camera"));backLabel=strictEventTarget?"‹ EVENTS":"‹ LIVE";String requestedBack=getIntent().getStringExtra("back_label");if(requestedBack!=null&&!requestedBack.isEmpty())backLabel=requestedBack;int[] fallback=CameraCatalog.fallbackVideoSize(camera,substream);videoWidth=fallback[0];videoHeight=fallback[1];videoLayoutKnown=true;displayAspect=CameraAspectRepository.get(prefs,camera);CameraAspectRepository.probe(this,prefs,camera);CameraCatalog.select(prefs,camera);EventFilters.apply(eventsState,EventFilters.get(prefs,camera));long explicit=parseUtc(getIntent().getStringExtra("captured_at_utc"));if(explicit>0){syncTime=explicit;ArchiveSession.set(prefs,syncTime,System.currentTimeMillis());}else syncTime=ArchiveSession.validTime(prefs,System.currentTimeMillis());buildUi();String bestViewPath=getIntent().getStringExtra("best_view_path");if(bestViewPath!=null&&!bestViewPath.isEmpty())bestView.setImageBitmap(BitmapFactory.decodeFile(bestViewPath));resolveArchive();}
    @Override protected void onResume(){super.onResume();immersive();}
    private void immersive(){DeviceUi.apply(this);}

    private void buildUi(){ui=Math.min(getResources().getDisplayMetrics().widthPixels/960f,getResources().getDisplayMetrics().heightPixels/480f);FrameLayout root=new FrameLayout(this);root.setBackgroundColor(Color.BLACK);videoContainer=new FrameLayout(this);FrameLayout.LayoutParams video=new FrameLayout.LayoutParams(-1,-1);video.topMargin=u(64);video.bottomMargin=u(80);root.addView(videoContainer,video);surface=new TextureView(this);videoContainer.addView(surface,new FrameLayout.LayoutParams(-1,-1,Gravity.CENTER));bestView=new ImageView(this);bestView.setScaleType(ImageView.ScaleType.FIT_CENTER);bestView.setBackgroundColor(Color.BLACK);videoContainer.addView(bestView,new FrameLayout.LayoutParams(-1,-1,Gravity.CENTER));CameraOrientation.apply(videoContainer,surface,camera);overlay=new ArchiveOverlay(this);root.addView(overlay,new FrameLayout.LayoutParams(-1,-1));
        Button back=button(backLabel);back.setTextSize(12*ui);FrameLayout.LayoutParams backParams=new FrameLayout.LayoutParams(u(118),u(48),Gravity.TOP|Gravity.LEFT);backParams.setMargins(u(8),u(8),0,0);root.addView(back,backParams);back.setOnClickListener(v->finish());
        Button cameraButton=button(camera.name);cameraButton.setTextSize(11*ui);FrameLayout.LayoutParams cameraParams=new FrameLayout.LayoutParams(u(144),u(48),Gravity.TOP|Gravity.LEFT);cameraParams.setMargins(u(132),u(8),0,0);root.addView(cameraButton,cameraParams);cameraButton.setOnClickListener(v->pickCamera());
        streamStats=new TextView(this);streamStats.setText("CONNECTING…");streamStats.setTextColor(Color.WHITE);streamStats.setTextSize(10*ui);streamStats.setGravity(Gravity.CENTER);streamStats.setTypeface(android.graphics.Typeface.DEFAULT_BOLD);streamStats.setLines(2);FrameLayout.LayoutParams statsParams=new FrameLayout.LayoutParams(u(174),u(58),Gravity.TOP|Gravity.LEFT);statsParams.setMargins(u(278),u(3),0,0);root.addView(streamStats,statsParams);
        playbackClock=new TextView(this);playbackClock.setTextColor(Color.WHITE);playbackClock.setTextSize(12*ui);playbackClock.setGravity(Gravity.CENTER);playbackClock.setTypeface(android.graphics.Typeface.DEFAULT_BOLD);playbackClock.setLines(2);FrameLayout.LayoutParams playbackParams=new FrameLayout.LayoutParams(u(270),u(58),Gravity.TOP|Gravity.LEFT);playbackParams.setMargins(u(462),u(3),0,0);root.addView(playbackClock,playbackParams);
        playPause=control("▶",22);addControl(root,playPause,12,58);playPause.setContentDescription("Play archive");playPause.setOnClickListener(v->togglePlayback());
        Button previous=control("│◀",20);addControl(root,previous,78,58);previous.setContentDescription("Previous recording");previous.setOnClickListener(v->jumpEvent(-1));
        Button next=control("▶│",20);addControl(root,next,144,58);next.setContentDescription("Next recording");next.setOnClickListener(v->jumpEvent(1));
        Button calendar=control("▦  DATE",12);addControl(root,calendar,210,92);calendar.setContentDescription("Recording calendar");calendar.setOnClickListener(v->showCalendar());setContentView(root);main.post(timelineTick);}

    private int u(float value){return Math.round(value*ui);}
    private Button button(String text){Button button=new Button(this);button.setText(text);button.setTextColor(Color.WHITE);button.setTextSize(18*ui);ControlStyle.apply(button,false);return button;}
    private Button control(String text,float size){Button b=button(text);b.setTextSize(size*ui);b.setTypeface(android.graphics.Typeface.DEFAULT_BOLD);b.setPadding(u(4),0,u(4),u(1));b.setBackground(controlBackground());return b;}
    private android.graphics.drawable.Drawable controlShape(int fill,int stroke){GradientDrawable shape=new GradientDrawable();shape.setShape(GradientDrawable.RECTANGLE);shape.setColor(fill);shape.setCornerRadius(11);shape.setStroke(1,stroke);return shape;}
    private StateListDrawable controlBackground(){StateListDrawable states=new StateListDrawable();states.addState(new int[]{android.R.attr.state_pressed},controlShape(0xff168b7d,0xff43e0cc));states.addState(new int[]{android.R.attr.state_focused},controlShape(0xff176b61,0xff43e0cc));states.addState(new int[]{},controlShape(0xee303836,0xff55716c));return states;}
    private void addControl(FrameLayout root,Button b,int left,int width){FrameLayout.LayoutParams p=new FrameLayout.LayoutParams(u(width),u(48),Gravity.BOTTOM|Gravity.LEFT);p.setMargins(u(left),0,0,u(84));root.addView(b,p);}

    private void resolveArchive(){
        overlay.status="LOADING EVENTS";overlay.invalidate();eventsState.camera=camera.name;eventsState.limit=200;eventsState.loadThumbnails=false;eventsClient=new ThreeEyeClient(eventsState);eventsClient.configure(prefs.getString("threeeye_base_url",eventsState.baseUrl),prefs.getString("threeeye_user",prefs.getString("ajax_user","")),prefs.getString("threeeye_password",prefs.getString("ajax_password","")));
        network.execute(()->eventsClient.load((ok,error)->{List<ThreeEyeState.Event> events=ok?eventsState.snapshot():new ArrayList<>();archiveEvents=events;if(syncTime<=0)syncTime=events.isEmpty()?System.currentTimeMillis()-5000:parseUtc(events.get(0).capturedAt);ArchiveSession.set(prefs,syncTime,System.currentTimeMillis());ThreeEyeState.Event nearest=nearest(events,syncTime);fallbackTime=nearest==null?syncTime:parseUtc(nearest.capturedAt);actualTime=syncTime;loadBestViewIfNeeded(nearest);long target=syncTime;main.post(()->{timelineRequested=true;paused=true;bestView.setVisibility(View.VISIBLE);overlay.status="BEST VIEW · PAUSED";overlay.showAdaptive(target,eventCountOnDay(events,target));ensureProfileTimeline(overlay.visibleStart(),overlay.visibleEnd());playPause.setText("▶");updatePlaybackClock();});}));
    }
    private void loadBestViewIfNeeded(ThreeEyeState.Event event){if(event==null||bestView.getDrawable()!=null)return;eventsClient.loadSelectedImage(event,(ok,error)->{if(ok&&event.image!=null)main.post(()->{bestView.setImageBitmap(event.image);bestView.setVisibility(View.VISIBLE);overlay.invalidate();});});}
    private void ensureProfileTimeline(long visibleStart,long visibleEnd){
        long span=Math.max(ArchiveTimeline.HOUR,visibleEnd-visibleStart),margin=Math.max(ArchiveTimeline.HOUR,span/2),wantedStart=ArchiveTimeline.dayStart(visibleStart-margin),wantedEnd=ArchiveTimeline.dayStart(visibleEnd+margin)+ArchiveTimeline.DAY;
        synchronized(profileEvents){if(profileLoadRunning)return;if(profileLoadedStart==Long.MAX_VALUE){profileLoadRunning=true;requestProfileTimeline(wantedStart,wantedEnd);return;}if(wantedStart<profileLoadedStart){profileLoadRunning=true;requestProfileTimeline(wantedStart,profileLoadedStart);return;}if(wantedEnd>profileLoadedEnd){profileLoadRunning=true;requestProfileTimeline(profileLoadedEnd,wantedEnd);}}
    }
    private void requestProfileTimeline(long start,long end){metadataNetwork.execute(()->{try{List<ProfileGClient.SearchEvent> loaded=ProfileGRepository.events(prefs,camera.name,start,end,substream);synchronized(profileEvents){for(ProfileGClient.SearchEvent candidate:loaded){boolean duplicate=false;for(ProfileGClient.SearchEvent existing:profileEvents)if(existing.time==candidate.time&&existing.type.equals(candidate.type)){duplicate=true;break;}if(!duplicate)profileEvents.add(candidate);}Collections.sort(profileEvents,(left,right)->Long.compare(left.time,right.time));profileLoadedStart=Math.min(profileLoadedStart,start);profileLoadedEnd=Math.max(profileLoadedEnd,end);profileLoadRunning=false;}main.post(()->{overlay.invalidate();ensureProfileTimeline(overlay.visibleStart(),overlay.visibleEnd());});}catch(Exception profileError){synchronized(profileEvents){profileLoadRunning=false;}Log.w("FelicityProfileG","Timeline metadata · "+profileError.getMessage());}});}

    private void startReplay(long time){
        if(destroyed||network.isShutdown())return;if(player!=null){updateActualTimeFromPlayer();try{player.pause();}catch(Exception ignored){}}int request=++replayRequest;replayStartedAt=android.os.SystemClock.elapsedRealtime();playbackAnchorRealtime=0;playbackAnchorArchiveTime=actualTime;replayBaseTime=time;replayClockSourceTime=0;initialFramePaused=false;lastStatsMs=0;lastReadBytes=-1;lastPictures=0;smoothedFps=-1;smoothedKbps=-1;Log.i("FelicityReplay","Seek requested · "+camera.name+" · "+time(time));if(player==null)bestView.setVisibility(View.VISIBLE);paused=true;if(playPause!=null)playPause.setText("▶");overlay.status="SEEKING · "+time(time);overlay.invalidate();
        network.execute(()->{AjaxMetadataSession metadata=null;try{ProfileGRepository.Replay replay=ProfileGRepository.replay(prefs,camera.name,substream);if(prefs.getBoolean("ajax_metadata_enrichment",false)){metadata=new AjaxMetadataSession(replay.uri,replay.user,replay.password,time,this::acceptAjaxFigure);metadata.start();}OnvifReplayProxy next=new OnvifReplayProxy(replay.uri,replay.user,replay.password,time);String local=next.start();AjaxMetadataSession readyMetadata=metadata;main.post(()->{if(destroyed||request!=replayRequest){if(readyMetadata!=null)readyMetadata.stop();next.close();}else{startPlayer(next,local);metadataSession=readyMetadata;}});}catch(Exception error){if(metadata!=null)metadata.stop();main.post(()->{if(!destroyed&&request==replayRequest)showError(error.getMessage());});}});
    }

    private void acceptAjaxFigure(AjaxMetadataDecoder.Figure figure){long at=parseUtc(figure.utc);String type=figure.type();if(at<=0||type.isEmpty())return;main.post(()->{synchronized(profileEvents){for(ProfileGClient.SearchEvent existing:profileEvents)if(existing.time==at&&existing.type.equals(type))return;profileEvents.add(new ProfileGClient.SearchEvent(at,type));Collections.sort(profileEvents,(left,right)->Long.compare(left.time,right.time));}if(overlay!=null)overlay.invalidate();});}

    private void startPlayer(OnvifReplayProxy next,String uri){
        stopReplay(false);proxy=next;ArrayList<String> options=new ArrayList<>();options.add("--rtsp-tcp");options.add("--network-caching=1200");if(vlc==null)vlc=new LibVLC(this,options);player=new MediaPlayer(vlc);player.setUseOrientationFromBounds(false);player.setVideoScale(MediaPlayer.ScaleType.SURFACE_BEST_FIT);player.getVLCVout().setVideoView(surface);player.getVLCVout().attachViews((vout,width,height,visibleWidth,visibleHeight,sarNum,sarDen)->runOnUiThread(()->{if(visibleWidth>0&&visibleHeight>0){videoWidth=visibleWidth;videoHeight=visibleHeight;}fitSurface();}));player.setEventListener(event->{if(event.type==MediaPlayer.Event.Vout&&event.getVoutCount()>0)runOnUiThread(()->{main.removeCallbacks(firstFrameTimeout);Log.i("FelicityReplay","First frame · "+camera.name+" · "+(android.os.SystemClock.elapsedRealtime()-replayStartedAt)+" ms");if(!initialFramePaused){initialFramePaused=true;updateActualTimeFromPlayer();if(playWhenReady){paused=false;playbackAnchorArchiveTime=actualTime;playbackAnchorRealtime=android.os.SystemClock.elapsedRealtime();playPause.setText("Ⅱ");}else{player.pause();paused=true;playbackAnchorArchiveTime=actualTime;playbackAnchorRealtime=0;playPause.setText("▶");}}fitSurface();bestView.setVisibility(View.GONE);overlay.status=paused?"ARCHIVE · PAUSED":"ARCHIVE · PLAYING";updatePlaybackClock();overlay.invalidate();});else if(event.type==MediaPlayer.Event.EncounteredError||event.type==MediaPlayer.Event.EndReached)runOnUiThread(this::replayFailed);});Media media=new Media(vlc,Uri.parse(uri));media.setHWDecoderEnabled(true,false);media.addOption(":rtsp-tcp");media.addOption(":network-caching=1200");player.setMedia(media);media.release();player.play();main.removeCallbacks(firstFrameTimeout);main.postDelayed(firstFrameTimeout,15000);
    }

    private void updateActualTimeFromPlayer(){
        if(player==null)return;long resolved=proxy==null?0:proxy.replayStartTimeMs(),position=Math.max(0,player.getTime());
        if(resolved>0&&resolved!=replayClockSourceTime){long requestedBase=replayBaseTime;replayClockSourceTime=resolved;replayBaseTime=resolved;actualTime=resolved+position;Log.i("FelicityReplay","Playhead resolved · requested="+time(requestedBase)+" · actual="+time(actualTime));if(overlay!=null)overlay.reveal(actualTime);return;}
        if(replayClockSourceTime>0)actualTime=replayBaseTime+position;else if(!paused&&playbackAnchorRealtime>0)actualTime=playbackAnchorArchiveTime+android.os.SystemClock.elapsedRealtime()-playbackAnchorRealtime;
    }

    private void fitSurface(){if(player==null||videoContainer==null)return;displayAspect=CameraAspectRepository.get(prefs,camera);int cw=videoContainer.getWidth(),ch=videoContainer.getHeight();if(cw<1||ch<1)return;float playerAspect=CameraCatalog.playerAspect(camera);player.setVideoScale(MediaPlayer.ScaleType.SURFACE_BEST_FIT);player.setAspectRatio(Math.max(1,Math.round(playerAspect*1000))+":1000");player.setScale(0);player.getVLCVout().setWindowSize(cw,ch);}
    private void updateStreamStats(){
        if(streamStats==null||player==null)return;
        IMedia.VideoTrack track=player.getCurrentVideoTrack();IMedia media=player.getMedia();IMedia.Stats live=media==null?null:media.getStats();String codec="H264";int width=videoWidth,height=videoHeight;float fps=0;
        if(track!=null){String raw=track.codec==null?"":track.codec.toUpperCase(Locale.US);codec=raw.contains("H265")||raw.contains("HEVC")?"H265":raw.contains("H264")||raw.contains("AVC")?"H264":raw.length()>8?raw.substring(0,8):raw;if(track.width>0&&track.height>0){width=track.width;height=track.height;videoWidth=width;videoHeight=height;}if(track.frameRateDen>0)fps=(float)track.frameRateNum/track.frameRateDen;}
        if(live!=null){long now=System.currentTimeMillis(),elapsed=lastStatsMs>0?now-lastStatsMs:0;int trafficBytes=Math.max(live.readBytes,live.demuxReadBytes);if(elapsed>0&&live.displayedPictures>=lastPictures){float measured=(live.displayedPictures-lastPictures)*1000f/elapsed;smoothedFps=smoothedFps<0?measured:smoothedFps*.9f+measured*.1f;}float measuredKbps=0;if(elapsed>0&&lastReadBytes>=0&&trafficBytes>=lastReadBytes)measuredKbps=(trafficBytes-lastReadBytes)*8f/elapsed;if(measuredKbps<=0){float nativeRate=Math.max(live.inputBitrate,live.demuxBitrate);if(nativeRate>0)measuredKbps=nativeRate*8000f;}if(measuredKbps>0)smoothedKbps=smoothedKbps<0?measuredKbps:smoothedKbps*.8f+measuredKbps*.2f;lastPictures=live.displayedPictures;lastReadBytes=trafficBytes;lastStatsMs=now;}
        if(camera.corridor&&width<height){int swap=width;width=height;height=swap;}if(smoothedFps>=0)fps=smoothedFps;
        String bitrate=smoothedKbps<0?"—":Integer.toString(Math.round(smoothedKbps)),first=bitrate+" kbps · "+String.format(Locale.US,"%.1f",fps)+" FPS",resolution=width+"×"+height,value=first+"\n"+resolution+" · "+codec;android.text.SpannableString styled=new android.text.SpannableString(value);styled.setSpan(new android.text.style.RelativeSizeSpan(1.2f),0,bitrate.length(),android.text.Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);int resolutionStart=first.length()+1;styled.setSpan(new android.text.style.RelativeSizeSpan(1.24f),resolutionStart,resolutionStart+resolution.length(),android.text.Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);styled.setSpan(new android.text.style.RelativeSizeSpan(.72f),value.length()-codec.length(),value.length(),android.text.Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);streamStats.setText(styled);
    }
    private void updatePlaybackClock(){if(playbackClock==null)return;String current=time(actualTime),value="PLAYBACK\n"+current;android.text.SpannableString styled=new android.text.SpannableString(value);styled.setSpan(new android.text.style.RelativeSizeSpan(.72f),0,8,android.text.Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);styled.setSpan(new android.text.style.RelativeSizeSpan(1.35f),9,value.length(),android.text.Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);playbackClock.setText(styled);}

    private void replayFailed(){if(destroyed)return;if(!strictEventTarget&&!fallbackTried&&fallbackTime>0&&fallbackTime!=actualTime){fallbackTried=true;startReplay(fallbackTime);return;}showError("Archive stream unavailable at "+time(actualTime));}
    private void showError(String error){overlay.status=error==null?"ARCHIVE UNAVAILABLE":error;overlay.invalidate();}

    private void seek(long target){syncTime=target;strictEventTarget=false;fallbackTried=false;ThreeEyeState.Event nearest=nearest(archiveEvents,target);fallbackTime=nearest==null?target:parseUtc(nearest.capturedAt);ArchiveSession.set(prefs,target,System.currentTimeMillis());ensureProfileTimeline(overlay.visibleStart(),overlay.visibleEnd());playFromTarget(target);}

    private void playFromTarget(long target){playWhenReady=true;bestView.setVisibility(View.VISIBLE);startReplay(Math.max(0,target-KEYFRAME_PREROLL_MS));}

    private void togglePlayback(){if(player==null){playFromTarget(syncTime);return;}if(paused){player.play();paused=false;playbackAnchorArchiveTime=actualTime;playbackAnchorRealtime=android.os.SystemClock.elapsedRealtime();bestView.setVisibility(View.GONE);playPause.setText("Ⅱ");overlay.status="ARCHIVE · PLAYING";}else{if(playbackAnchorRealtime>0)actualTime=playbackAnchorArchiveTime+android.os.SystemClock.elapsedRealtime()-playbackAnchorRealtime;player.pause();paused=true;playbackAnchorRealtime=0;playPause.setText("▶");overlay.status="ARCHIVE · PAUSED";}updatePlaybackClock();overlay.invalidate();}
    private void jumpEvent(int direction){long best=direction<0?Long.MIN_VALUE:Long.MAX_VALUE;for(ThreeEyeState.Event event:archiveEvents){long at=parseUtc(event.capturedAt);if(direction<0&&at<actualTime&&at>best)best=at;if(direction>0&&at>actualTime&&at<best)best=at;}for(ProfileGClient.SearchEvent event:profileEvents){long at=event.time;if(direction<0&&at<actualTime&&at>best)best=at;if(direction>0&&at>actualTime&&at<best)best=at;}if(best!=Long.MIN_VALUE&&best!=Long.MAX_VALUE)seek(best);}
    private void showCalendar(){Set<Long> days=new HashSet<>();Calendar calendar=Calendar.getInstance();for(ThreeEyeState.Event event:archiveEvents)addDay(days,calendar,parseUtc(event.capturedAt));for(ProfileGClient.SearchEvent event:profileEvents)addDay(days,calendar,event.time);if(days.isEmpty()){showError("No indexed recording days");return;}ArrayList<Long> sorted=new ArrayList<>(days);Collections.sort(sorted,Collections.reverseOrder());LinearLayout body=new LinearLayout(this);body.setOrientation(LinearLayout.VERTICAL);body.setPadding(18,10,18,10);TextView note=new TextView(this);note.setText("Days with Profile G / AI records · "+camera.name);note.setTextColor(Color.LTGRAY);note.setTextSize(13);body.addView(note);GridLayout grid=new GridLayout(this);grid.setColumnCount(4);body.addView(grid);SimpleDateFormat label=new SimpleDateFormat("EEE\ndd MMM",Locale.getDefault());final AlertDialog[] dialog=new AlertDialog[1];for(Long day:sorted){Button choice=button(label.format(new Date(day)));choice.setTextSize(12);GridLayout.LayoutParams p=new GridLayout.LayoutParams();p.width=0;p.height=64;p.columnSpec=GridLayout.spec(GridLayout.UNDEFINED,1,1f);p.setMargins(4,4,4,4);grid.addView(choice,p);choice.setOnClickListener(v->{Calendar current=Calendar.getInstance();current.setTimeInMillis(actualTime>0?actualTime:System.currentTimeMillis());Calendar selected=Calendar.getInstance();selected.setTimeInMillis(day);selected.set(Calendar.HOUR_OF_DAY,current.get(Calendar.HOUR_OF_DAY));selected.set(Calendar.MINUTE,current.get(Calendar.MINUTE));selected.set(Calendar.SECOND,current.get(Calendar.SECOND));ThreeEyeState.Event nearest=nearestOnDay(archiveEvents,selected.getTimeInMillis(),day);if(dialog[0]!=null)dialog[0].dismiss();seek(nearest==null?selected.getTimeInMillis():parseUtc(nearest.capturedAt));});}dialog[0]=new AlertDialog.Builder(this).setTitle("Recording calendar").setView(body).setNegativeButton("Close",null).create();dialog[0].show();}
    private static void addDay(Set<Long> days,Calendar calendar,long at){if(at<=0)return;calendar.setTimeInMillis(at);calendar.set(Calendar.HOUR_OF_DAY,0);calendar.set(Calendar.MINUTE,0);calendar.set(Calendar.SECOND,0);calendar.set(Calendar.MILLISECOND,0);days.add(calendar.getTimeInMillis());}
    private static ThreeEyeState.Event nearestOnDay(List<ThreeEyeState.Event> events,long target,long day){ThreeEyeState.Event result=null;long distance=Long.MAX_VALUE;for(ThreeEyeState.Event event:events){long at=parseUtc(event.capturedAt);Calendar c=Calendar.getInstance();c.setTimeInMillis(at);c.set(Calendar.HOUR_OF_DAY,0);c.set(Calendar.MINUTE,0);c.set(Calendar.SECOND,0);c.set(Calendar.MILLISECOND,0);if(c.getTimeInMillis()!=day)continue;long next=Math.abs(at-target);if(next<distance){distance=next;result=event;}}return result;}

    private void pickCamera(){startActivityForResult(new Intent(this,CameraPickerActivity.class),CameraPickerActivity.REQUEST);}
    @Override protected void onActivityResult(int request,int result,Intent data){super.onActivityResult(request,result,data);if(request!=CameraPickerActivity.REQUEST||result!=RESULT_OK||data==null)return;CameraCatalog.Camera selected=CameraCatalog.find(prefs,data.getStringExtra("camera_name"));ArchiveSession.touch(prefs,System.currentTimeMillis());CameraCatalog.select(prefs,selected);startActivity(new Intent(this,ArchiveActivity.class).putExtra("camera",selected.name).putExtra("camera_switch",true).putExtra("back_label",backLabel));finish();}
    private void openLive(){startActivity(new Intent(this,CameraActivity.class).putExtra("manual",true).putExtra("camera_id",camera.id).putExtra("camera_name",camera.name).putExtra("back_label","‹ ARCHIVE"));}
    private void openEvents(){startActivity(new Intent(this,EventsActivity.class).putExtra("camera_name",camera.name).putExtra("back_label","‹ ARCHIVE"));}

    private void stopReplay(boolean releaseEngine){main.removeCallbacks(firstFrameTimeout);if(player!=null){try{player.setEventListener(null);player.stop();player.getVLCVout().detachViews();}catch(Exception ignored){}player.release();player=null;}if(releaseEngine&&vlc!=null){vlc.release();vlc=null;}if(proxy!=null){proxy.close();proxy=null;}if(metadataSession!=null){metadataSession.stop();metadataSession=null;}}
    @Override protected void onDestroy(){destroyed=true;replayRequest++;main.removeCallbacksAndMessages(null);network.shutdownNow();metadataNetwork.shutdownNow();stopReplay(true);super.onDestroy();}

    private static ThreeEyeState.Event nearest(List<ThreeEyeState.Event> events,long target){ThreeEyeState.Event result=null;long distance=Long.MAX_VALUE;for(ThreeEyeState.Event event:events){long value=parseUtc(event.capturedAt),next=Math.abs(value-target);if(value>0&&next<distance){distance=next;result=event;}}return result;}
    static long parseUtc(String iso){return ArchiveTimeline.parseIso8601(iso);}
    private static String time(long value){return value<=0?"—":new SimpleDateFormat("HH:mm:ss",Locale.getDefault()).format(new Date(value));}

    private final class ArchiveOverlay extends View {
        private final Paint p=new Paint(3);private float scale=1,downX;private long viewportCenter,downViewportCenter,visibleSpan=ArchiveTimeline.DAY;private double millisPerPixel=90_000;private boolean dragging,moved;String status="";
        ArchiveOverlay(Context context){super(context);}
        long dayStart(long value){return ArchiveTimeline.dayStart(value);}
        void showAdaptive(long value,int eventCount){visibleSpan=ArchiveTimeline.adaptiveSpan(eventCount);viewportCenter=visibleSpan>=ArchiveTimeline.DAY?dayStart(value)+ArchiveTimeline.DAY/2:value;millisPerPixel=visibleSpan/(double)Math.max(1,getWidth()>0?getWidth():960);invalidate();}
        void reveal(long value){long start=visibleStart(),end=visibleEnd();if(value<start||value>end){viewportCenter=value;ensureProfileTimeline(visibleStart(),visibleEnd());}invalidate();}
        long visibleStart(){return timeAt(0);}
        long visibleEnd(){return timeAt(Math.max(1,getWidth()));}
        private void ensureViewport(long value){if(viewportCenter<=0)showAdaptive(value,eventCountOnDay(archiveEvents,value));}
        private long timeAt(float x){return viewportCenter+(long)((x-getWidth()/2f)*millisPerPixel);}
        private float xAt(long value){return getWidth()/2f+(float)((value-viewportCenter)/millisPerPixel);}
        @Override protected void onSizeChanged(int width,int height,int oldWidth,int oldHeight){super.onSizeChanged(width,height,oldWidth,oldHeight);if(width>0)millisPerPixel=visibleSpan/(double)width;}
        @Override protected void onDraw(Canvas canvas){super.onDraw(canvas);scale=Math.min(getWidth()/960f,getHeight()/480f);ensureViewport(actualTime);p.setColor(Color.rgb(14,48,43));canvas.drawRect(0,0,getWidth(),64*scale,p);if(!status.isEmpty()){p.setColor(0xa8000000);canvas.drawRoundRect(new RectF(12*scale,74*scale,360*scale,108*scale),8*scale,8*scale,p);label(canvas,status,22*scale,98,12,Color.rgb(150,190,184),Paint.Align.LEFT,true);}drawTimeline(canvas,actualTime);}
        private void drawTimeline(Canvas canvas,long playhead){float top=getHeight()-80*scale,base=top+36*scale;p.setStyle(Paint.Style.FILL);p.setColor(0xff101615);canvas.drawRect(0,top,getWidth(),getHeight(),p);p.setStyle(Paint.Style.STROKE);p.setStrokeWidth(.8f*scale);p.setColor(0xff596460);canvas.drawLine(0,base,getWidth(),base,p);double desiredMajor=Math.max(60_000,millisPerPixel*120*scale);long[] steps={60_000,5*60_000,15*60_000,30*60_000,60*60_000,2*60*60_000,3*60*60_000,6*60*60_000};long major=steps[steps.length-1];for(long step:steps)if(step>=desiredMajor){major=step;break;}long minor=Math.max(60_000,major/4),first=ArchiveTimeline.ceil(timeAt(0),minor);for(long at=first;at<=timeAt(getWidth());at+=minor){float x=xAt(at);boolean isMajor=ArchiveTimeline.isMajor(at,major);float length=(isMajor?23:11)*scale;p.setStrokeWidth((isMajor?1.35f:.7f)*scale);p.setColor(isMajor?0xffaeb8b4:0xff69736f);canvas.drawLine(x,base-length/2,x,base+length/2,p);if(isMajor)label(canvas,shortTime(at),x,getHeight()/scale-7,10,0xffb8c1bd,Paint.Align.CENTER,false);}p.setStyle(Paint.Style.FILL);for(ThreeEyeState.Event event:archiveEvents)drawEvent(canvas,parseUtc(event.capturedAt),event.objectClass,top,base);synchronized(profileEvents){for(ProfileGClient.SearchEvent event:profileEvents)drawEvent(canvas,event.time,event.type,top,base);}float marker=xAt(playhead);if(marker>=0&&marker<=getWidth()){p.setStyle(Paint.Style.STROKE);p.setStrokeWidth(1.6f*scale);p.setColor(Color.WHITE);canvas.drawLine(marker,top-5*scale,marker,getHeight()-3*scale,p);p.setStyle(Paint.Style.FILL);canvas.drawCircle(marker,top-5*scale,3*scale,p);}}
        private void drawEvent(Canvas canvas,long at,String type,float top,float base){int color=eventColor(type);if(color==Color.TRANSPARENT)return;float x=xAt(at);if(x<-6||x>getWidth()+6)return;p.setColor(color);canvas.drawRoundRect(new RectF(x-1.5f*scale,top+3*scale,x+1.5f*scale,base-3*scale),1.5f*scale,1.5f*scale,p);}
        private int eventColor(String value){String type=value==null?"":value.toLowerCase(Locale.US);if(type.contains("person")||type.contains("human"))return 0xff2fa9e8;if(type.contains("animal")||type.contains("pet"))return 0xff8247f5;if(type.contains("vehicle")||type.contains("car"))return 0xff7acb2f;if(type.contains("face"))return 0xff21b7d5;return Color.TRANSPARENT;}
        @Override public boolean onTouchEvent(MotionEvent event){if(event.getY()<getHeight()-90*scale&&!dragging)return true;if(event.getActionMasked()==MotionEvent.ACTION_DOWN){downX=event.getX();downViewportCenter=viewportCenter;moved=false;dragging=true;invalidate();return true;}if(event.getActionMasked()==MotionEvent.ACTION_MOVE){float delta=downX-event.getX();if(Math.abs(delta)>6*scale)moved=true;viewportCenter=downViewportCenter+(long)(delta*millisPerPixel);ensureProfileTimeline(visibleStart(),visibleEnd());invalidate();return true;}if(event.getActionMasked()==MotionEvent.ACTION_UP){long selected=moved?viewportCenter:timeAt(event.getX());dragging=false;ensureProfileTimeline(visibleStart(),visibleEnd());seek(selected);return true;}if(event.getActionMasked()==MotionEvent.ACTION_CANCEL){dragging=false;invalidate();return true;}return true;}
        private void label(Canvas canvas,String value,float x,float y,float size,int color,Paint.Align align,boolean bold){p.setTypeface(bold?android.graphics.Typeface.DEFAULT_BOLD:android.graphics.Typeface.DEFAULT);p.setTextSize(size*scale);p.setTextAlign(align);p.setColor(color);canvas.drawText(value,x,y*scale,p);}
    }
    private static int eventCountOnDay(List<ThreeEyeState.Event> events,long target){long start=ArchiveTimeline.dayStart(target),end=start+ArchiveTimeline.DAY;int count=0;for(ThreeEyeState.Event event:events){long at=parseUtc(event.capturedAt);if(at>=start&&at<end)count++;}return count;}
    private static String shortTime(long value){String full=time(value);return full.length()>=5?full.substring(0,5):full;}
}
