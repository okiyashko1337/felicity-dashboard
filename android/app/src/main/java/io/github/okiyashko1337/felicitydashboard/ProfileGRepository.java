package io.github.okiyashko1337.felicitydashboard;

import android.content.SharedPreferences;
import android.util.Log;
import java.util.List;
import java.util.Locale;
import java.util.HashMap;
import java.util.Map;

final class ProfileGRepository {
    static final class Replay {
        final String uri,user,password,recordingName;
        Replay(String uri,String user,String password,String recordingName){this.uri=uri;this.user=user;this.password=password;this.recordingName=recordingName;}
    }
    private static String host="",user="",password="";
    private static ProfileGClient.ProbeResult catalog;
    private static final Map<String,String> replayUris=new HashMap<>();
    private ProfileGRepository(){}

    static synchronized void set(String valueHost,String valueUser,String valuePassword,ProfileGClient.ProbeResult valueCatalog){if(!valueHost.equals(host)||!valueUser.equals(user)||!valuePassword.equals(password))replayUris.clear();host=valueHost;user=valueUser;password=valuePassword;catalog=valueCatalog;}

    private static String cachedReplayUri(ProfileGClient client,String endpoint,String cacheKey,String recordingToken)throws Exception{synchronized(ProfileGRepository.class){String cached=replayUris.get(cacheKey);if(cached!=null)return cached;}String loaded=client.replayUri(endpoint,recordingToken);synchronized(ProfileGRepository.class){replayUris.put(cacheKey,loaded);}return loaded;}

    static ProfileGClient.ProbeResult load(String valueHost,String valueUser,String valuePassword)throws Exception{synchronized(ProfileGRepository.class){if(catalog!=null&&valueHost.equals(host)&&valueUser.equals(user))return catalog;}ProfileGClient.ProbeResult loaded=new ProfileGClient(valueHost,valueUser,valuePassword).probe();synchronized(ProfileGRepository.class){if(catalog==null||!valueHost.equals(host)||!valueUser.equals(user))set(valueHost,valueUser,valuePassword,loaded);return catalog;}}

    static Replay replay(SharedPreferences prefs,String camera,boolean substream)throws Exception{
        String currentHost=prefs.getString("profile_g_host","192.168.13.234:8080"),currentUser=prefs.getString("profile_g_user",""),currentPassword=prefs.getString("profile_g_password","");
        CameraCatalog.Camera selected=CameraCatalog.find(prefs,camera);String directToken=CameraCatalog.recordingToken(selected,substream);ProfileGClient client=new ProfileGClient(currentHost,currentUser,currentPassword);if(!directToken.isEmpty()){try{String key=currentHost+"|"+currentUser+"|"+currentPassword.hashCode()+"|"+directToken;Log.i("FelicityProfileG","Replay fast path · camera="+camera+" · "+(substream?"sub":"main"));String uri=cachedReplayUri(client,"http://"+currentHost+"/onvif/replay_service",key,directToken);Log.i("FelicityProfileG","Replay URI ready · camera="+camera);return new Replay(uri,currentUser,currentPassword,camera);}catch(Exception fastError){Log.w("FelicityProfileG","Replay fast path fallback · "+fastError.getMessage());}}
        ProfileGClient.ProbeResult active=load(currentHost,currentUser,currentPassword);ProfileGClient.Recording recording=find(active,camera,substream);if(recording==null)throw new Exception(camera+" is not recorded by the NVR");String key=currentHost+"|"+currentUser+"|"+currentPassword.hashCode()+"|"+recording.token;String uri=cachedReplayUri(client,active.replayEndpoint,key,recording.token);return new Replay(uri,currentUser,currentPassword,recording.name);
    }

    static List<ProfileGClient.SearchEvent> events(SharedPreferences prefs,String camera,long start,long end,boolean substream)throws Exception{
        String currentHost=prefs.getString("profile_g_host","192.168.13.234:8080"),currentUser=prefs.getString("profile_g_user",""),currentPassword=prefs.getString("profile_g_password","");CameraCatalog.Camera selected=CameraCatalog.find(prefs,camera);String directToken=CameraCatalog.recordingToken(selected,substream);ProfileGClient client=new ProfileGClient(currentHost,currentUser,currentPassword);if(!directToken.isEmpty()){try{return client.searchEvents("http://"+currentHost+"/onvif/search_service",directToken,start,end);}catch(Exception fastError){Log.w("FelicityProfileG","Timeline fast path fallback · "+fastError.getMessage());}}ProfileGClient.ProbeResult active=load(currentHost,currentUser,currentPassword);ProfileGClient.Recording recording=find(active,camera,substream);if(recording==null)throw new Exception(camera+" is not recorded by the NVR");return client.searchEvents(active.searchEndpoint,recording.token,start,end);
    }

    static ProfileGClient.Recording find(ProfileGClient.ProbeResult source,String camera){
        return find(source,camera,false);
    }

    static ProfileGClient.Recording find(ProfileGClient.ProbeResult source,String camera,boolean substream){
        String wanted=normal(camera);ProfileGClient.Recording fallback=null;
        for(ProfileGClient.Recording item:source.recordings){String name=normal(item.name),id=normal(item.sourceId);if(name.equals(wanted)||id.equals(wanted)){if(isSub(item)==substream)return item;if(fallback==null)fallback=item;}}
        for(ProfileGClient.Recording item:source.recordings){String name=normal(item.name),id=normal(item.sourceId);if(name.contains(wanted)||wanted.contains(name)||id.contains(wanted)){if(isSub(item)==substream)return item;if(fallback==null)fallback=item;}}
        return fallback;
    }

    static boolean isSub(ProfileGClient.Recording item){String value=(item.token+" "+item.name+" "+item.sourceId).toLowerCase(Locale.US);return value.contains("-sub-r")||value.contains("sub")||value.endsWith("_s")||value.contains("secondary");}
    private static String normal(String value){return value==null?"":value.toLowerCase(Locale.US).replaceAll("[^\\p{L}\\p{N}]+","");}
}
