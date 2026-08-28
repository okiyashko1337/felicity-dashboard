package io.github.okiyashko1337.felicitydashboard;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.RectF;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.MotionEvent;
import android.view.View;
import android.view.WindowManager;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.Toast;
import java.io.File;
import java.io.FileOutputStream;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;
import java.util.Locale;
import java.util.TimeZone;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public final class EventsActivity extends Activity {
    private final ThreeEyeState state=new ThreeEyeState();
    private final ThreeEyeClient client=new ThreeEyeClient(state);
    private final ExecutorService network=Executors.newSingleThreadExecutor();
    private final Handler main=new Handler(Looper.getMainLooper());
    private EventsView view;
    private SharedPreferences prefs;
    private String doorbell="";
    private String backLabel="‹ ENERGY";
    private boolean showAllCameras;

    @Override protected void onCreate(Bundle saved){super.onCreate(saved);getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);immersive();prefs=getSharedPreferences("felicity",MODE_PRIVATE);String requested=getIntent().getStringExtra("camera_name");doorbell=requested==null||requested.isEmpty()?prefs.getString("threeeye_doorbell_camera",""):requested;String requestedBack=getIntent().getStringExtra("back_label");if(requestedBack!=null&&!requestedBack.isEmpty())backLabel=requestedBack;String user=prefs.getString("threeeye_user",prefs.getString("ajax_user",""));String password=prefs.getString("threeeye_password",prefs.getString("ajax_password",""));client.configure(prefs.getString("threeeye_base_url",state.baseUrl),user,password);view=new EventsView(this);setContentView(view);reload();}
    @Override protected void onResume(){super.onResume();immersive();}
    @Override protected void onDestroy(){network.shutdownNow();super.onDestroy();}
    private void immersive(){DeviceUi.apply(this);}

    private void reload(){state.camera=showAllCameras||doorbell.isEmpty()?"ALL":doorbell;EventFilters.apply(state,eventMask());state.status="LOADING";view.invalidate();network.execute(()->client.load((ok,error)->main.post(()->{if(ok){chooseDoorbell();synchronized(state.cameras){CameraCatalog.save(prefs,state.channels);}}view.invalidate();})));}
    private void chooseDoorbell(){if(!doorbell.isEmpty())return;List<String> cameras; synchronized(state.cameras){cameras=new ArrayList<>(state.cameras);}for(String camera:cameras){String n=camera.toLowerCase(Locale.US);if(n.contains("door")||n.contains("bell")||n.contains("ajax")||n.contains("entrance")||n.contains("front")){doorbell=camera;break;}}if(doorbell.isEmpty()&&cameras.size()==1)doorbell=cameras.get(0);if(!doorbell.isEmpty())prefs.edit().putString("threeeye_doorbell_camera",doorbell).apply();}
    private List<ThreeEyeState.Event> events(){List<ThreeEyeState.Event> all=state.snapshot();ArrayList<ThreeEyeState.Event> result=new ArrayList<>();for(ThreeEyeState.Event event:all)if(event.thumbnail!=null&&(showAllCameras||doorbell.isEmpty()||doorbell.equalsIgnoreCase(event.camera)))result.add(event);return result;}
    private void pickCamera(){startActivityForResult(new Intent(this,CameraPickerActivity.class),CameraPickerActivity.REQUEST);}
    private int eventMask(){return showAllCameras?prefs.getInt("event_filter_all_cameras",EventFilters.ALL):EventFilters.get(prefs,CameraCatalog.find(prefs,doorbell));}
    private void toggleScope(){showAllCameras=!showAllCameras;view.page=0;reload();}
    private void toggleFilter(int flag){int mask=eventMask(),next=mask^flag;if(next==0){Toast.makeText(this,"Keep at least one event type",Toast.LENGTH_SHORT).show();return;}if(showAllCameras)prefs.edit().putInt("event_filter_all_cameras",next).apply();else EventFilters.set(prefs,CameraCatalog.find(prefs,doorbell),next);EventFilters.apply(state,next);reload();}
    @Override protected void onActivityResult(int request,int result,Intent data){super.onActivityResult(request,result,data);if(request!=CameraPickerActivity.REQUEST||result!=RESULT_OK||data==null)return;doorbell=data.getStringExtra("camera_name");if(doorbell==null)return;showAllCameras=false;view.page=0;prefs.edit().putString("threeeye_doorbell_camera",doorbell).apply();CameraCatalog.select(prefs,CameraCatalog.find(prefs,doorbell));reload();}
    private void configureThreeEye(){LinearLayout fields=new LinearLayout(this);fields.setOrientation(LinearLayout.VERTICAL);int pad=(int)(18*getResources().getDisplayMetrics().density);fields.setPadding(pad,0,pad,0);EditText url=new EditText(this);url.setHint("3ye API URL");url.setSingleLine(true);url.setText(prefs.getString("threeeye_base_url",state.baseUrl));fields.addView(url);EditText user=new EditText(this);user.setHint("3ye user");user.setSingleLine(true);user.setText(prefs.getString("threeeye_user",""));fields.addView(user);EditText password=new EditText(this);password.setHint("3ye password");password.setSingleLine(true);password.setInputType(android.text.InputType.TYPE_CLASS_TEXT|android.text.InputType.TYPE_TEXT_VARIATION_PASSWORD);fields.addView(password);new AlertDialog.Builder(this).setTitle("3ye events").setMessage("Credentials stay in Android private preferences.").setView(fields).setNegativeButton("Cancel",null).setPositiveButton("Save",(dialog,which)->{String base=url.getText().toString().trim(),u=user.getText().toString().trim(),pw=password.getText().toString();if(base.isEmpty())return;if(!base.startsWith("http://")&&!base.startsWith("https://"))base="http://"+base;if(pw.isEmpty())pw=prefs.getString("threeeye_password","");prefs.edit().putString("threeeye_base_url",base).putString("threeeye_user",u).putString("threeeye_password",pw).apply();client.configure(base,u,pw);reload();}).show();}
    private void openLive(){CameraCatalog.Camera camera=CameraCatalog.find(prefs,doorbell);CameraCatalog.select(prefs,camera);startActivity(new Intent(this,CameraActivity.class).putExtra("manual",true).putExtra("trigger","EVENTS_LIVE").putExtra("back_label","‹ EVENTS").putExtra("camera_id",camera.id).putExtra("camera_name",camera.name));}
    private void openEvent(ThreeEyeState.Event event){long eventTime=ArchiveActivity.parseUtc(event.capturedAt);if(eventTime>0)ArchiveSession.set(prefs,eventTime,System.currentTimeMillis());CameraCatalog.select(prefs,CameraCatalog.find(prefs,event.camera));state.status="OPENING BEST VIEW";view.invalidate();network.execute(()->client.loadSelectedImage(event,(ok,error)->{String path="";if(ok&&event.image!=null){File file=new File(getCacheDir(),"best-view-"+event.trackId+".jpg");try(FileOutputStream out=new FileOutputStream(file)){event.image.compress(Bitmap.CompressFormat.JPEG,92,out);path=file.getAbsolutePath();}catch(Exception ignored){}}String imagePath=path;main.post(()->{state.status="LIVE";view.invalidate();startActivity(new Intent(this,ArchiveActivity.class).putExtra("best_view_path",imagePath).putExtra("captured_at_utc",event.capturedAt).putExtra("camera",event.camera).putExtra("track_id",event.trackId).putExtra("from_event",true).putExtra("back_label","‹ EVENTS"));});}));}

    private final class EventsView extends View {
        private final Paint p=new Paint(3);private final RectF r=new RectF();private int pressed=-1,page;private float scale=1,downX;
        private final int bg=Color.rgb(7,17,15),header=Color.rgb(14,48,43),card=Color.rgb(13,39,35),cyan=Color.rgb(89,222,209),text=Color.rgb(232,248,244),muted=Color.rgb(150,190,184),amber=Color.rgb(255,184,103);
        EventsView(Context c){super(c);setBackgroundColor(bg);}
        @Override protected void onDraw(Canvas c){super.onDraw(c);scale=Math.min(getWidth()/960f,getHeight()/480f);p.setColor(header);c.drawRect(0,0,getWidth(),64*scale,p);p.setColor(pressed==-2?0xff1c4e46:0xff123d37);c.drawRoundRect(new RectF(8*scale,7*scale,128*scale,57*scale),8*scale,8*scale,p);label(c,backLabel,68*scale,40,12,text,Paint.Align.CENTER,true);label(c,"3YE · "+shortName(showAllCameras?"ALL":doorbell.isEmpty()?"EVENTS":doorbell,10),138*scale,40,14,cyan,Paint.Align.LEFT,true);p.setColor(pressed==-3?0xff24675d:0xff174a43);c.drawRoundRect(new RectF(288*scale,8*scale,406*scale,56*scale),10*scale,10*scale,p);label(c,showAllCameras?"ALL CAMERAS":"THIS CAMERA",347*scale,39,10,text,Paint.Align.CENTER,true);int mask=eventMask();drawFilter(c,"PERSON",EventFilters.PERSON,412,mask);drawFilter(c,"VEHICLE",EventFilters.VEHICLE,548,mask);drawFilter(c,"ANIMAL",EventFilters.ANIMAL,684,mask);drawFilter(c,"FACE",EventFilters.FACE,820,mask);
            List<ThreeEyeState.Event> items=events();if(!"LIVE".equals(state.status)){label(c,state.status,getWidth()/2f,92,14,"OFFLINE".equals(state.status)?amber:muted,Paint.Align.CENTER,true);}float pad=16*scale,gap=10*scale,top=76*scale,bottomPad=30*scale,cw=(getWidth()-pad*2-gap*2)/3f,ch=(getHeight()-top-bottomPad-gap)/2f;int offset=page*6,count=Math.max(0,Math.min(6,items.size()-offset));if(items.isEmpty()){label(c,"OFFLINE".equals(state.status)?state.error:"No matching events with images",getWidth()/2f,getHeight()/2f-8*scale,20,muted,Paint.Align.CENTER,false);if("OFFLINE".equals(state.status))label(c,"Tap to configure 3ye",getWidth()/2f,getHeight()/2f+28*scale,14,cyan,Paint.Align.CENTER,true);}else if(count==0)label(c,"NO EVENTS ON PAGE "+(page+1),getWidth()/2f,getHeight()/2f,18,muted,Paint.Align.CENTER,true);for(int slot=0;slot<count;slot++){int index=offset+slot;float x=pad+(slot%3)*(cw+gap),y=top+(slot/3)*(ch+gap),inset=pressed==slot?4*scale:0;r.set(x+inset,y+inset,x+cw-inset,y+ch-inset);p.setColor(card);c.drawRoundRect(r,14*scale,14*scale,p);Bitmap b=items.get(index).thumbnail;if(b!=null){RectF image=new RectF(r.left+3*scale,r.top+3*scale,r.right-3*scale,r.bottom-49*scale);p.setColor(Color.BLACK);c.drawRect(image,p);c.save();c.clipRect(image);c.drawBitmap(b,null,fitInside(b,image),p);c.restore();}p.setColor(0xd9112925);c.drawRect(r.left,r.bottom-50*scale,r.right,r.bottom,p);label(c,eventTime(items.get(index).capturedAt),r.left+10*scale,r.bottom-27*scale,14,text,Paint.Align.LEFT,true);label(c,items.get(index).objectClass.toUpperCase(Locale.US),r.right-10*scale,r.bottom-27*scale,11,cyan,Paint.Align.RIGHT,true);label(c,"BEST VIEW · "+items.get(index).camera,r.left+10*scale,r.bottom-9*scale,10,muted,Paint.Align.LEFT,false);}for(int i=0;i<3;i++){p.setColor(i==page?cyan:0xff3e6962);c.drawCircle(getWidth()/2f+(i-1)*20*scale,getHeight()-11*scale,(i==page?5:3)*scale,p);}label(c,(page+1)+"/3",getWidth()/2f+48*scale,getHeight()/scale-7,10,muted,Paint.Align.LEFT,true);
        }
        @Override public boolean onTouchEvent(MotionEvent e){float x=e.getX(),y=e.getY();if(e.getAction()==MotionEvent.ACTION_DOWN){downX=x;pressed=hit(x,y);invalidate();return true;}if(e.getAction()==MotionEvent.ACTION_UP){float delta=x-downX;if(Math.abs(delta)>80*scale){page=Math.max(0,Math.min(2,page+(delta<0?1:-1)));pressed=-1;invalidate();return true;}int target=hit(x,y);pressed=-1;invalidate();if(target==-2){finish();return true;}if(target==-3){toggleScope();return true;}if(target<=-10&&target>=-13){int[] flags={EventFilters.PERSON,EventFilters.VEHICLE,EventFilters.ANIMAL,EventFilters.FACE};toggleFilter(flags[-10-target]);return true;}if("OFFLINE".equals(state.status)){configureThreeEye();return true;}List<ThreeEyeState.Event> items=events();int index=page*6+target;if(target>=0&&index<items.size())openEvent(items.get(index));return true;}if(e.getAction()==MotionEvent.ACTION_CANCEL){pressed=-1;invalidate();}return true;}
        private int hit(float x,float y){if(y<64*scale){if(x<132*scale)return -2;if(x>=288*scale&&x<408*scale)return -3;int[] starts={412,548,684,820};for(int i=0;i<starts.length;i++)if(x>=starts[i]*scale&&x<(starts[i]+128)*scale)return -10-i;return -1;}float pad=16*scale,gap=10*scale,top=76*scale,bottomPad=30*scale,cw=(getWidth()-pad*2-gap*2)/3f,ch=(getHeight()-top-bottomPad-gap)/2f;if(y>=getHeight()-bottomPad)return -1;int col=(int)((x-pad)/(cw+gap)),row=(int)((y-top)/(ch+gap));return col>=0&&col<3&&row>=0&&row<2?row*3+col:-1;}
        private void drawFilter(Canvas c,String value,int flag,float left,int mask){int index=flag==EventFilters.PERSON?0:flag==EventFilters.VEHICLE?1:flag==EventFilters.ANIMAL?2:3;boolean enabled=(mask&flag)!=0;p.setColor(pressed==-10-index?0xff24675d:enabled?0xff174a43:0xff0b2723);c.drawRoundRect(new RectF(left*scale,8*scale,(left+128)*scale,56*scale),10*scale,10*scale,p);p.setStyle(Paint.Style.STROKE);p.setStrokeWidth(1.5f*scale);p.setColor(enabled?cyan:0xff52756f);c.drawRoundRect(new RectF(left*scale,8*scale,(left+128)*scale,56*scale),10*scale,10*scale,p);p.setStyle(Paint.Style.FILL);label(c,value,(left+64)*scale,39,12,enabled?text:muted,Paint.Align.CENTER,true);}
        private RectF fitInside(Bitmap bitmap,RectF bounds){float ratio=Math.min(bounds.width()/bitmap.getWidth(),bounds.height()/bitmap.getHeight()),w=bitmap.getWidth()*ratio,h=bitmap.getHeight()*ratio;return new RectF(bounds.centerX()-w/2f,bounds.centerY()-h/2f,bounds.centerX()+w/2f,bounds.centerY()+h/2f);}
        private void label(Canvas c,String value,float x,float y,float size,int color,Paint.Align align,boolean bold){p.setTypeface(bold?android.graphics.Typeface.DEFAULT_BOLD:android.graphics.Typeface.DEFAULT);p.setTextSize(size*scale);p.setTextAlign(align);p.setColor(color);c.drawText(value,x,y*scale,p);}
        private String shortName(String value,int max){return value.length()<=max?value:value.substring(0,max-1)+"…";}
    }

    static String eventTime(String iso){try{SimpleDateFormat input=new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss",Locale.US);input.setTimeZone(TimeZone.getTimeZone("UTC"));Date d=input.parse(iso.length()>=19?iso.substring(0,19):iso);return new SimpleDateFormat("dd MMM  HH:mm:ss",Locale.getDefault()).format(d);}catch(Exception ignored){return iso;}}
}
