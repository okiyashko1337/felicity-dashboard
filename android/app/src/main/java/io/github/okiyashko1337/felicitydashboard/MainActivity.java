package io.github.okiyashko1337.felicitydashboard;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.location.Address;
import android.location.Geocoder;
import android.location.Location;
import android.location.LocationListener;
import android.location.LocationManager;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.View;
import android.view.WindowManager;
import android.widget.EditText;
import android.widget.LinearLayout;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.List;
import java.util.Locale;

public final class MainActivity extends Activity implements DashboardView.Listener {
    private static final String DEFAULT_URL = "http://homeassistant.local:8000";
    private final Handler main = new Handler(Looper.getMainLooper());
    private final ExecutorService network = Executors.newSingleThreadExecutor();
    private final DashboardState state = new DashboardState();
    private DashboardView dashboard;
    private ApiClient api;
    private boolean active;
    private long nextCurrent, nextSummary, nextStatus, nextChart, nextWeather;
    private boolean locating;
    private LocationManager locationManager;
    private static final int LOCATION_PERMISSION = 41;
    private OnvifEventClient onvif;
    private Thread onvifThread;
    private long lastCameraMs;

    @Override protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setVolumeControlStream(android.media.AudioManager.STREAM_MUSIC);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        SharedPreferences preferences=getSharedPreferences("felicity", Context.MODE_PRIVATE);
        api=new ApiClient(state, preferences.getString("base_url", DEFAULT_URL));
        state.serverUrl=api.baseUrl();
        if(preferences.contains("weather_latitude")){state.latitude=Double.longBitsToDouble(preferences.getLong("weather_latitude",0));state.longitude=Double.longBitsToDouble(preferences.getLong("weather_longitude",0));state.location=preferences.getString("weather_location","DEVICE LOCATION");}
        if(!preferences.getString("ajax_user","").isEmpty())state.ajaxStatus="Configured · "+preferences.getString("ajax_host","192.168.13.209:8080");
        dashboard=new DashboardView(this, state); dashboard.setListener(this); setContentView(dashboard); immersive();
        locationManager=(LocationManager)getSystemService(LOCATION_SERVICE); if(Double.isNaN(state.latitude))requestDeviceLocation();
    }

    @Override protected void onResume() { super.onResume(); active=true; nextCurrent=nextSummary=nextStatus=nextChart=nextWeather=0; dashboard.reloadCameraPreview();main.post(tick); startOnvif(); immersive(); }
    @Override protected void onPause() { active=false; main.removeCallbacks(tick); stopOnvif(); super.onPause(); }
    @Override protected void onDestroy() { stopOnvif();network.shutdownNow(); super.onDestroy(); }
    @Override public void onWindowFocusChanged(boolean focus) { super.onWindowFocusChanged(focus); if(focus) immersive(); }
    @Override public void onBackPressed() { if(dashboard.isDetail()) dashboard.showHome(); else immersive(); }

    private void immersive() {
        getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY|View.SYSTEM_UI_FLAG_FULLSCREEN|View.SYSTEM_UI_FLAG_HIDE_NAVIGATION|View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN|View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION|View.SYSTEM_UI_FLAG_LAYOUT_STABLE);
    }

    private final Runnable tick = new Runnable() { @Override public void run() {
        if(!active)return; long now=System.currentTimeMillis();
        if(now>=nextCurrent){nextCurrent=now+2000; call(() -> api.current(done));}
        if(now>=nextStatus){nextStatus=now+5000; call(() -> api.status(done));}
        if(now>=nextSummary){nextSummary=now+10000; call(() -> api.summary(done));}
        if(now>=nextWeather){nextWeather=now+15*60*1000;if(Double.isNaN(state.latitude))requestDeviceLocation();else call(()->api.weather(done));}
        if(dashboard.isChartDetail() && now>=nextChart){nextChart=now+(dashboard.metric().equals("system")?10000:60000); requestChart();}
        dashboard.invalidate(); main.postDelayed(this,500);
    }};
    private final ApiClient.Callback done=(ok,error)->main.post(()->{if(!ok){state.error=error==null?"Connection failed":error;} dashboard.invalidate();});
    private void call(Runnable runnable){network.execute(runnable);}
    private void requestChart(){String metric=dashboard.metric(); call(()->api.chart(metric,done));}
    private void startOnvif(){SharedPreferences p=getSharedPreferences("felicity",MODE_PRIVATE);String user=p.getString("ajax_user","");if(user.isEmpty()||onvifThread!=null)return;String host=p.getString("ajax_host","192.168.13.209:8080"),password=p.getString("ajax_password","");state.ajaxStatus="Connecting · "+host;onvif=new OnvifEventClient(host,user,password,new OnvifEventClient.Listener(){
        @Override public void onListening(){main.post(()->{state.ajaxStatus="Listening · "+host;dashboard.invalidate();});}
        @Override public void onEvent(String topic){main.post(()->{state.ajaxStatus="Event · "+shortTopic(topic);long now=System.currentTimeMillis();if(active&&isRingTopic(topic)&&now-lastCameraMs>30000){lastCameraMs=now;startActivity(new Intent(MainActivity.this,CameraActivity.class).putExtra("topic",topic).putExtra("ring",true));}dashboard.invalidate();});}
        @Override public void onError(String error){main.post(()->{state.ajaxStatus="Error · "+error;dashboard.invalidate();});}
    });onvifThread=new Thread(onvif,"ajax-onvif-events");onvifThread.start();}
    private void stopOnvif(){if(onvif!=null)onvif.stop();if(onvifThread!=null)onvifThread.interrupt();onvif=null;onvifThread=null;}
    private static String shortTopic(String topic){int slash=topic.lastIndexOf('/');return slash>=0?topic.substring(slash+1):topic;}
    private static boolean isRingTopic(String topic){return topic!=null&&topic.toLowerCase(Locale.US).contains("ringdetector");}
    private final LocationListener deviceLocation = new LocationListener() {
        @Override public void onLocationChanged(Location location){
            state.latitude=location.getLatitude();state.longitude=location.getLongitude();state.location="DEVICE LOCATION";locating=false;
            try{locationManager.removeUpdates(this);}catch(SecurityException ignored){}
            call(()->{try{List<Address> addresses=new Geocoder(MainActivity.this,Locale.getDefault()).getFromLocation(state.latitude,state.longitude,1);if(addresses!=null&&!addresses.isEmpty()){Address a=addresses.get(0);String city=a.getLocality()!=null?a.getLocality():a.getSubAdminArea();if(city!=null)state.location=city+(a.getCountryCode()!=null?", "+a.getCountryCode():"");}}catch(Exception ignored){}api.weather(done);});
        }
        @Override public void onStatusChanged(String provider,int status,Bundle extras){}
        @Override public void onProviderEnabled(String provider){}
        @Override public void onProviderDisabled(String provider){}
    };
    private void requestDeviceLocation(){
        if(locating||locationManager==null)return;
        if(checkSelfPermission(android.Manifest.permission.ACCESS_COARSE_LOCATION)!=PackageManager.PERMISSION_GRANTED){requestPermissions(new String[]{android.Manifest.permission.ACCESS_COARSE_LOCATION,android.Manifest.permission.ACCESS_FINE_LOCATION},LOCATION_PERMISSION);return;}
        locating=true;state.location="LOCATING DEVICE…";
        try{Location last=locationManager.getLastKnownLocation("fused");if(last==null)last=locationManager.getLastKnownLocation(LocationManager.PASSIVE_PROVIDER);if(last!=null){deviceLocation.onLocationChanged(last);return;}locationManager.requestLocationUpdates("fused",1000,0,deviceLocation,Looper.getMainLooper());main.postDelayed(()->{if(locating){locating=false;state.location="LOCATION UNAVAILABLE";dashboard.invalidate();}},20000);}catch(Exception e){locating=false;state.location="LOCATION UNAVAILABLE";}
    }
    @Override public void onRequestPermissionsResult(int requestCode,String[] permissions,int[] results){super.onRequestPermissionsResult(requestCode,permissions,results);if(requestCode==LOCATION_PERMISSION&&results.length>0&&results[0]==PackageManager.PERMISSION_GRANTED)requestDeviceLocation();}

    @Override public void onPageChanged(String metric) { nextChart=0; if("system".equals(metric)||"today".equals(metric)) nextSummary=0; }
    @Override public void onCameraRequested(){lastCameraMs=System.currentTimeMillis();startActivity(new Intent(this,CameraActivity.class).putExtra("manual",true));}
    @Override public void onSettingsRequested() {
        final EditText input=new EditText(this); input.setSingleLine(true); input.setText(api.baseUrl()); input.setTextColor(Color.BLACK); input.setSelectAllOnFocus(true);
        new AlertDialog.Builder(this).setTitle("Felicity server").setMessage("Local API address").setView(input)
                .setNegativeButton("Cancel",null).setPositiveButton("Save",(dialog,which)->{
                    String value=input.getText().toString().trim(); if(!value.startsWith("http://")&&!value.startsWith("https://"))value="http://"+value;
                    api.setBaseUrl(value);state.serverUrl=value; getSharedPreferences("felicity",MODE_PRIVATE).edit().putString("base_url",value).apply(); state.serverOnline=false; state.error="Connecting…"; nextCurrent=nextSummary=nextStatus=0;
                }).show();
    }
    @Override public void onWeatherSettingsRequested(){
        final EditText input=new EditText(this);input.setSingleLine(true);input.setHint("City or town");input.setTextColor(Color.BLACK);
        new AlertDialog.Builder(this).setTitle("Weather location").setMessage("Enter the device city once. Long-press weather to change it later.").setView(input).setNegativeButton("Cancel",null).setPositiveButton("Find",(dialog,which)->{
            String city=input.getText().toString().trim();if(city.isEmpty())return;state.location="SEARCHING…";call(()->api.geocode(city,(ok,error)->{if(ok){getSharedPreferences("felicity",MODE_PRIVATE).edit().putLong("weather_latitude",Double.doubleToRawLongBits(state.latitude)).putLong("weather_longitude",Double.doubleToRawLongBits(state.longitude)).putString("weather_location",state.location).apply();api.weather(done);}else done.done(false,error);}));
        }).show();
    }
    @Override public void onAjaxSettingsRequested(){
        SharedPreferences prefs=getSharedPreferences("felicity",MODE_PRIVATE);LinearLayout fields=new LinearLayout(this);fields.setOrientation(LinearLayout.VERTICAL);int pad=(int)(18*getResources().getDisplayMetrics().density);fields.setPadding(pad,0,pad,0);
        EditText host=new EditText(this);host.setHint("Host:port");host.setSingleLine(true);host.setText(prefs.getString("ajax_host","192.168.13.209:8080"));fields.addView(host);
        EditText user=new EditText(this);user.setHint("ONVIF user");user.setSingleLine(true);user.setText(prefs.getString("ajax_user",""));fields.addView(user);
        EditText password=new EditText(this);password.setHint("ONVIF password");password.setSingleLine(true);password.setInputType(android.text.InputType.TYPE_CLASS_TEXT|android.text.InputType.TYPE_TEXT_VARIATION_PASSWORD);fields.addView(password);
        new AlertDialog.Builder(this).setTitle("Ajax ONVIF").setMessage("Credentials stay in Android private preferences.").setView(fields).setNegativeButton("Cancel",null).setPositiveButton("Save",(dialog,which)->{String h=host.getText().toString().trim(),u=user.getText().toString().trim(),pw=password.getText().toString();if(h.isEmpty()||u.isEmpty())return;if(pw.isEmpty())pw=prefs.getString("ajax_password","");prefs.edit().putString("ajax_host",h).putString("ajax_user",u).putString("ajax_password",pw).apply();stopOnvif();startOnvif();}).show();
    }
}
