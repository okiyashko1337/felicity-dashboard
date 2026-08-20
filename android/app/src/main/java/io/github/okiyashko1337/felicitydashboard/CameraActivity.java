package io.github.okiyashko1337.felicitydashboard;

import android.app.Activity;
import android.content.pm.PackageManager;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.RectF;
import android.net.Uri;
import android.os.Bundle;
import android.view.GestureDetector;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.SurfaceView;
import android.view.View;
import android.view.VelocityTracker;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.OverScroller;
import android.widget.TextView;
import java.io.File;
import java.io.FileOutputStream;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.Locale;
import org.videolan.libvlc.LibVLC;
import org.videolan.libvlc.Media;
import org.videolan.libvlc.MediaPlayer;
import org.videolan.libvlc.interfaces.IMedia;
import org.videolan.libvlc.interfaces.IVLCVout;

public final class CameraActivity extends Activity {
    private LibVLC vlc;private MediaPlayer player;private SurfaceView surface;private TextView clock,stats;private Button talk;private PrivacyButton muteButton,micButton;private ImageView ringSnapshot;private Bitmap ringBitmap;private boolean muted=true,listenEnabled,audioReady,micEnabled,ringEvent;private BackchannelSession backchannel;private float zoom=1f,panX,panY,smoothedFps=-1f;private int videoWidth=1024,videoHeight=576,lastPictures;private long lastStatsMs;private OverScroller scroller;
    private final android.os.Handler handler=new android.os.Handler(android.os.Looper.getMainLooper());private boolean snapshotTaken;
    private final Runnable finishRunnable=this::finish;
    private final Runnable uiTick=new Runnable(){@Override public void run(){clock.setText(new SimpleDateFormat("dd.MM.yyyy   HH:mm:ss",Locale.getDefault()).format(new Date()));updateStats();handler.postDelayed(this,1000);}};

    @Override protected void onCreate(Bundle state){super.onCreate(state);ringEvent=getIntent().getBooleanExtra("ring",false);getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);getWindow().getDecorView().setSystemUiVisibility(5894);FrameLayout root=new FrameLayout(this);root.setBackgroundColor(Color.BLACK);
        surface=new SurfaceView(this);FrameLayout.LayoutParams videoParams=new FrameLayout.LayoutParams(-1,-1);videoParams.topMargin=64;root.addView(surface,videoParams);scroller=new OverScroller(this);installZoom();
        ringSnapshot=new ImageView(this);ringSnapshot.setScaleType(ImageView.ScaleType.CENTER_CROP);ringSnapshot.setVisibility(View.GONE);android.graphics.drawable.GradientDrawable snapshotFrame=new android.graphics.drawable.GradientDrawable();snapshotFrame.setColor(0xff07110f);snapshotFrame.setStroke(3,Color.rgb(89,222,209));snapshotFrame.setCornerRadius(12);ringSnapshot.setBackground(snapshotFrame);ringSnapshot.setPadding(3,3,3,3);FrameLayout.LayoutParams rp=new FrameLayout.LayoutParams(250,142,Gravity.BOTTOM|Gravity.LEFT);rp.setMargins(18,0,0,18);root.addView(ringSnapshot,rp);
        talk=button("HOLD TO TALK");FrameLayout.LayoutParams tp=new FrameLayout.LayoutParams(250,72,Gravity.BOTTOM|Gravity.CENTER_HORIZONTAL);tp.setMargins(0,0,0,18);root.addView(talk,tp);talk.setOnTouchListener((v,event)->{if(event.getAction()==MotionEvent.ACTION_DOWN){beginTalk();return true;}if(event.getAction()==MotionEvent.ACTION_UP||event.getAction()==MotionEvent.ACTION_CANCEL){endTalk();return true;}return true;});
        View header=new HeaderBackground(this);root.addView(header,new FrameLayout.LayoutParams(-1,64,Gravity.TOP));Button back=button("‹ ENERGY");back.setTextSize(16);back.setBackgroundColor(Color.TRANSPARENT);FrameLayout.LayoutParams bp=new FrameLayout.LayoutParams(155,58,Gravity.TOP|Gravity.LEFT);bp.setMargins(42,3,0,0);root.addView(back,bp);back.setOnClickListener(v->finish());
        stats=new TextView(this);stats.setText("CONNECTING…");stats.setTextColor(Color.WHITE);stats.setTextSize(12);stats.setGravity(Gravity.CENTER);stats.setTypeface(android.graphics.Typeface.DEFAULT_BOLD);stats.setLines(2);FrameLayout.LayoutParams sp=new FrameLayout.LayoutParams(245,58,Gravity.TOP);sp.setMargins(190,3,0,0);root.addView(stats,sp);
        muteButton=new PrivacyButton(this,false);FrameLayout.LayoutParams mup=new FrameLayout.LayoutParams(54,52,Gravity.TOP);mup.setMargins(442,6,0,0);root.addView(muteButton,mup);muteButton.setOnClickListener(v->toggleMute());
        micButton=new PrivacyButton(this,true);FrameLayout.LayoutParams mip=new FrameLayout.LayoutParams(54,52,Gravity.TOP);mip.setMargins(502,6,0,0);root.addView(micButton,mip);micButton.setOnClickListener(v->toggleMic());
        clock=new TextView(this);clock.setTextColor(Color.WHITE);clock.setTextSize(22);clock.setGravity(Gravity.RIGHT|Gravity.CENTER_VERTICAL);clock.setTypeface(android.graphics.Typeface.DEFAULT_BOLD);FrameLayout.LayoutParams cp=new FrameLayout.LayoutParams(330,58,Gravity.TOP|Gravity.RIGHT);cp.setMargins(0,3,16,0);root.addView(clock,cp);
        setContentView(root);updateStatus();startPlayer();handler.post(uiTick);scheduleFinish();}

    private void installZoom(){
        GestureDetector doubleTap=new GestureDetector(this,new GestureDetector.SimpleOnGestureListener(){
            @Override public boolean onDown(MotionEvent e){return true;}
            @Override public boolean onDoubleTap(MotionEvent e){
                if(zoom>1.05f){zoom=1f;panX=panY=0;applyZoom();}
                else{float[] point=screenPoint(e,0);zoomAt(point[0],point[1],2.5f);}
                return true;
            }
        });
        surface.setOnTouchListener(new View.OnTouchListener(){
            float pinchStartSpan,pinchStartZoom,pinchFocusX,pinchFocusY,lastX,lastY;
            boolean pinching,moved;
            VelocityTracker velocity;

            @Override public boolean onTouch(View view,MotionEvent event){
                doubleTap.onTouchEvent(event);
                switch(event.getActionMasked()){
                    case MotionEvent.ACTION_DOWN:
                        scroller.forceFinished(true);pinching=false;moved=false;
                        lastX=event.getX();lastY=event.getY();
                        velocity=VelocityTracker.obtain();velocity.addMovement(event);
                        return true;
                    case MotionEvent.ACTION_POINTER_DOWN:
                        if(event.getPointerCount()>=2){
                            scroller.forceFinished(true);pinching=true;moved=true;
                            float[] geometry=pinchGeometry(event);
                            pinchStartSpan=Math.max(1f,geometry[0]);pinchFocusX=geometry[1];pinchFocusY=geometry[2];
                            pinchStartZoom=zoom;
                            if(velocity!=null)velocity.clear();
                        }
                        return true;
                    case MotionEvent.ACTION_MOVE:
                        if(pinching&&event.getPointerCount()>=2){
                            float[] geometry=pinchGeometry(event);
                            float next=Math.max(1f,Math.min(6f,pinchStartZoom*geometry[0]/pinchStartSpan));
                            if(next<1.035f)next=1f;
                            panX+=geometry[1]-pinchFocusX;panY+=geometry[2]-pinchFocusY;
                            pinchFocusX=geometry[1];pinchFocusY=geometry[2];
                            zoomAt(pinchFocusX,pinchFocusY,next);
                        }else if(!pinching&&event.getPointerCount()==1&&zoom>1f){
                            float x=event.getX(),y=event.getY();
                            panX+=(x-lastX)*zoom;panY+=(y-lastY)*zoom;lastX=x;lastY=y;moved=true;applyZoom();
                            if(velocity!=null)velocity.addMovement(event);
                        }
                        return true;
                    case MotionEvent.ACTION_POINTER_UP:
                        if(pinching){
                            pinching=false;
                            if(zoom<1.08f){zoom=1f;panX=panY=0;applyZoom();}
                            int remaining=event.getActionIndex()==0?1:0;
                            if(remaining<event.getPointerCount()){lastX=event.getX(remaining);lastY=event.getY(remaining);}
                        }
                        return true;
                    case MotionEvent.ACTION_UP:
                        if(zoom<1.08f){zoom=1f;panX=panY=0;applyZoom();}
                        else if(!moved&&zoom>1f){applyZoom();}
                        fling(velocity);recycleVelocity();return true;
                    case MotionEvent.ACTION_CANCEL:
                        recycleVelocity();pinching=false;return true;
                    default:return true;
                }
            }

            private void fling(VelocityTracker tracker){
                if(tracker==null||pinching||zoom<=1f)return;
                tracker.computeCurrentVelocity(1000);
                float[] bounds=panBounds();
                scroller.fling(Math.round(panX),Math.round(panY),Math.round(tracker.getXVelocity()*zoom),Math.round(tracker.getYVelocity()*zoom),Math.round(-bounds[0]),Math.round(bounds[0]),Math.round(-bounds[1]),Math.round(bounds[1]));
                surface.postOnAnimation(CameraActivity.this::continueFling);
            }
            private void recycleVelocity(){if(velocity!=null){velocity.recycle();velocity=null;}}
        });
    }
    private float[] screenPoint(MotionEvent event,int index){float[] point={event.getX(index),event.getY(index)};surface.getMatrix().mapPoints(point);return point;}
    private float[] pinchGeometry(MotionEvent event){float[] a=screenPoint(event,0),b=screenPoint(event,1);float dx=b[0]-a[0],dy=b[1]-a[1];return new float[]{(float)Math.hypot(dx,dy),(a[0]+b[0])/2f,(a[1]+b[1])/2f};}
    private void zoomAt(float focusX,float focusY,float next){float old=zoom,ratio=next/old,cx=surface.getWidth()/2f,cy=surface.getHeight()/2f;panX=ratio*panX+(1-ratio)*(focusX-cx);panY=ratio*panY+(1-ratio)*(focusY-cy);zoom=next;if(zoom<=1.001f){zoom=1f;panX=panY=0;}applyZoom();}
    private float[] panBounds(){float vw=surface.getWidth(),vh=surface.getHeight(),videoAspect=videoWidth/(float)Math.max(1,videoHeight),viewAspect=vw/Math.max(1f,vh),baseW,baseH;if(videoAspect>viewAspect){baseW=vw;baseH=vw/videoAspect;}else{baseH=vh;baseW=vh*videoAspect;}return new float[]{Math.max(0,(baseW*zoom-vw)/2f),Math.max(0,(baseH*zoom-vh)/2f)};}
    private void applyZoom(){float[] bounds=panBounds();panX=Math.max(-bounds[0],Math.min(bounds[0],panX));panY=Math.max(-bounds[1],Math.min(bounds[1],panY));surface.setPivotX(surface.getWidth()/2f);surface.setPivotY(surface.getHeight()/2f);surface.setScaleX(zoom);surface.setScaleY(zoom);surface.setTranslationX(panX);surface.setTranslationY(panY);updateStats();}
    private void continueFling(){if(scroller.computeScrollOffset()){panX=scroller.getCurrX();panY=scroller.getCurrY();applyZoom();surface.postOnAnimation(this::continueFling);}}
    private void startPlayer(){android.content.SharedPreferences prefs=getSharedPreferences("felicity",MODE_PRIVATE);String user=prefs.getString("ajax_user",""),password=prefs.getString("ajax_password",""),host=prefs.getString("ajax_host","192.168.13.209:8080").split(":")[0];String url="rtsp://"+Uri.encode(user)+":"+Uri.encode(password)+"@"+host+":8554/040d84a53698-0_s";ArrayList<String> options=new ArrayList<>();options.add("--rtsp-tcp");options.add("--network-caching=250");vlc=new LibVLC(this,options);player=new MediaPlayer(vlc);player.setVolume(0);player.setVideoScale(MediaPlayer.ScaleType.SURFACE_FIT_SCREEN);IVLCVout output=player.getVLCVout();output.setVideoView(surface);output.attachViews();player.setEventListener(event->{if(event.type==MediaPlayer.Event.Vout&&event.getVoutCount()>0){runOnUiThread(()->{player.setVideoScale(MediaPlayer.ScaleType.SURFACE_FIT_SCREEN);audioReady=true;setInboundVolume();updateStatus();takePreview();});}else if(event.type==MediaPlayer.Event.EncounteredError)runOnUiThread(()->stats.setText("STREAM ERROR"));});Media media=new Media(vlc,Uri.parse(url));media.setHWDecoderEnabled(true,false);media.addOption(":rtsp-tcp");media.addOption(":network-caching=250");player.setMedia(media);media.release();player.play();}
    private void updateStats(){if(player==null)return;IMedia.VideoTrack track=player.getCurrentVideoTrack();IMedia media=player.getMedia();IMedia.Stats live=media==null?null:media.getStats();String codec="H264";int width=videoWidth,height=videoHeight;float fps=25;int bitrate=256;if(track!=null){String raw=track.codec==null?"":track.codec.toUpperCase(Locale.US);codec=raw.contains("H264")||raw.contains("AVC")?"H264":raw;width=track.width;height=track.height;videoWidth=width;videoHeight=height;if(track.frameRateDen>0)fps=(float)track.frameRateNum/track.frameRateDen;if(track.bitrate>0)bitrate=track.bitrate/1000;}if(live!=null){long now=System.currentTimeMillis();if(lastStatsMs>0&&now>lastStatsMs&&live.displayedPictures>=lastPictures){float measuredFps=(live.displayedPictures-lastPictures)*1000f/(now-lastStatsMs);smoothedFps=smoothedFps<0f?measuredFps:smoothedFps*.9f+measuredFps*.1f;}lastPictures=live.displayedPictures;lastStatsMs=now;int measured=Math.round(live.inputBitrate*8000f);if(measured>0)bitrate=measured;}if(smoothedFps>=0f)fps=smoothedFps;stats.setText(String.format(Locale.US,"%d kbps · %.1f FPS\n%s · %d×%d",bitrate,fps,codec,width,height));}
    private void toggleMute(){muted=!muted;if(muted){listenEnabled=false;micEnabled=false;if(backchannel!=null)endTalk();}else listenEnabled=true;setInboundVolume();updateStatus();}
    private void toggleMic(){micEnabled=!micEnabled;if(micEnabled){muted=false;listenEnabled=true;}else if(backchannel!=null)endTalk();setInboundVolume();updateStatus();}
    private void setInboundVolume(){if(player!=null)player.setVolume(!muted&&listenEnabled&&backchannel==null?100:0);}
    private void updateStatus(){if(muteButton!=null)muteButton.setCrossed(muted);if(micButton!=null)micButton.setCrossed(!micEnabled);if(talk!=null){talk.setEnabled(!muted&&micEnabled);talk.setAlpha(!muted&&micEnabled?1f:.45f);}}
    private void beginTalk(){if(muted||!micEnabled){talk.setText("ENABLE MIC");return;}handler.removeCallbacks(finishRunnable);if(checkSelfPermission(android.Manifest.permission.RECORD_AUDIO)!=PackageManager.PERMISSION_GRANTED){requestPermissions(new String[]{android.Manifest.permission.RECORD_AUDIO},52);talk.setText("ALLOW MICROPHONE");return;}if(backchannel!=null)return;if(player!=null)player.setVolume(0);talk.setText("CONNECTING…");android.content.SharedPreferences p=getSharedPreferences("felicity",MODE_PRIVATE);backchannel=new BackchannelSession(this,p.getString("ajax_host","192.168.13.209:8080"),p.getString("ajax_user",""),p.getString("ajax_password",""),new BackchannelSession.Listener(){public void onStarted(){runOnUiThread(()->talk.setText("TALKING…"));}public void onError(String error){runOnUiThread(()->{talk.setText("TALK ERROR");endTalk();});}});backchannel.start();}
    private void endTalk(){if(backchannel!=null){backchannel.stop();backchannel=null;}talk.setText("HOLD TO TALK");setInboundVolume();updateStatus();scheduleFinish();}
    private void scheduleFinish(){handler.removeCallbacks(finishRunnable);handler.postDelayed(finishRunnable,60000);}
    private void takePreview(){if(snapshotTaken||player==null)return;snapshotTaken=true;handler.postDelayed(()->{if(surface.getWidth()<1||surface.getHeight()<1){snapshotTaken=false;return;}Bitmap bitmap=Bitmap.createBitmap(surface.getWidth(),surface.getHeight(),Bitmap.Config.ARGB_8888);android.view.PixelCopy.request(surface,bitmap,result->{if(result==android.view.PixelCopy.SUCCESS){try(FileOutputStream out=new FileOutputStream(new File(getFilesDir(),"ajax-preview.jpg"))){bitmap.compress(Bitmap.CompressFormat.JPEG,86,out);}catch(Exception ignored){}if(ringEvent){ringBitmap=bitmap;ringSnapshot.setImageBitmap(ringBitmap);ringSnapshot.setVisibility(View.VISIBLE);}else bitmap.recycle();}else{snapshotTaken=false;bitmap.recycle();}},handler);},700);}
    private Button button(String label){Button b=new Button(this);b.setText(label);b.setTextColor(Color.WHITE);b.setTextSize(17);b.setBackgroundColor(0xcc103b36);return b;}
    @Override protected void onDestroy(){handler.removeCallbacksAndMessages(null);if(backchannel!=null)backchannel.stop();if(player!=null){player.stop();player.getVLCVout().detachViews();player.release();}if(vlc!=null)vlc.release();if(ringBitmap!=null){ringSnapshot.setImageDrawable(null);ringBitmap.recycle();ringBitmap=null;}super.onDestroy();}

    private static final class PrivacyButton extends View {
        private final Paint paint=new Paint(3);private final boolean microphone;private boolean crossed;
        PrivacyButton(android.content.Context context,boolean microphone){super(context);this.microphone=microphone;setClickable(true);setFocusable(true);setContentDescription(microphone?"Microphone":"Speaker");}
        void setCrossed(boolean crossed){this.crossed=crossed;setContentDescription((microphone?"Microphone":"Speaker")+(crossed?" off":" on"));invalidate();}
        @Override protected void drawableStateChanged(){super.drawableStateChanged();invalidate();}
        @Override protected void onDraw(Canvas canvas){super.onDraw(canvas);float w=getWidth(),h=getHeight(),cx=w/2f,cy=h/2f;paint.setStyle(Paint.Style.FILL);paint.setColor(isPressed()?0x9959ded1:0x351ca99d);canvas.drawRoundRect(new RectF(2,2,w-2,h-2),12,12,paint);paint.setColor(Color.WHITE);paint.setStrokeWidth(3.2f);paint.setStrokeCap(Paint.Cap.ROUND);paint.setStrokeJoin(Paint.Join.ROUND);
            if(microphone){paint.setStyle(Paint.Style.STROKE);canvas.drawRoundRect(new RectF(cx-7,10,cx+7,31),7,7,paint);canvas.drawArc(new RectF(cx-13,18,cx+13,38),0,180,false,paint);canvas.drawLine(cx,38,cx,44,paint);canvas.drawLine(cx-7,44,cx+7,44,paint);}
            else{paint.setStyle(Paint.Style.FILL);canvas.drawRect(cx-14,20,cx-7,32,paint);Path cone=new Path();cone.moveTo(cx-7,20);cone.lineTo(cx+3,12);cone.lineTo(cx+3,40);cone.lineTo(cx-7,32);cone.close();canvas.drawPath(cone,paint);paint.setStyle(Paint.Style.STROKE);canvas.drawArc(new RectF(cx-4,17,cx+13,35),-58,116,false,paint);canvas.drawArc(new RectF(cx-7,12,cx+21,40),-52,104,false,paint);}
            if(crossed){paint.setStyle(Paint.Style.STROKE);paint.setStrokeWidth(4.5f);paint.setColor(0xffff6b6b);canvas.drawLine(11,10,w-11,h-10,paint);}
        }
    }

    private static final class HeaderBackground extends View {private final Paint p=new Paint(3);HeaderBackground(android.content.Context c){super(c);setBackgroundColor(Color.rgb(14,48,43));}@Override protected void onDraw(Canvas c){super.onDraw(c);float x=29,y=32,r=17;p.setColor(Color.rgb(89,222,209));c.drawCircle(x,y,r,p);Path dark=new Path();dark.moveTo(x,y-r);dark.cubicTo(x+r*.67f,y-r,x+r*.67f,y,x,y);dark.cubicTo(x-r*.67f,y,x-r*.67f,y+r,x,y+r);dark.arcTo(new RectF(x-r,y-r,x+r,y+r),90,-180);dark.close();p.setColor(Color.rgb(7,17,15));c.drawPath(dark,p);c.drawCircle(x,y-r/2,r*.18f,p);p.setColor(Color.rgb(89,222,209));c.drawCircle(x,y+r/2,r*.18f,p);}}
}
