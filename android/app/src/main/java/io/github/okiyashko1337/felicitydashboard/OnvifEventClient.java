package io.github.okiyashko1337.felicitydashboard;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.security.MessageDigest;
import java.util.Locale;
import java.util.ArrayList;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

final class OnvifEventClient implements Runnable {
    interface Listener { void onListening(); void onEvent(String topic); void onError(String error); }
    private static final String CREATE_ACTION="http://www.onvif.org/ver10/events/wsdl/EventPortType/CreatePullPointSubscriptionRequest";
    private static final String PULL_ACTION="http://www.onvif.org/ver10/events/wsdl/PullPointSubscription/PullMessagesRequest";
    private final String host,user,password;private final Listener listener;private volatile boolean stopped;private boolean ringKnown,ringActive;
    OnvifEventClient(String host,String user,String password,Listener listener){this.host=host;this.user=user;this.password=password;this.listener=listener;}
    void stop(){stopped=true;}
    @Override public void run(){while(!stopped){try{String service="http://"+host+"/onvif/event_service";String created=post(service,create(service),CREATE_ACTION);String endpoint=match(created,"<wsa5:Address>([^<]+)</wsa5:Address>");if(endpoint==null)endpoint=match(created,"<wsa:Address>([^<]+)</wsa:Address>");if(endpoint==null)throw new Exception("No PullPoint address");listener.onListening();while(!stopped){String body=post(endpoint,pull(endpoint),PULL_ACTION);for(Notification event:parseNotifications(body)){if(event.ring()){if(acceptRing(event))listener.onEvent(event.topic);}else if(event.meaningful())listener.onEvent(event.topic);}}}catch(Exception e){if(!stopped)listener.onError(e.getMessage());try{Thread.sleep(5000);}catch(InterruptedException ignored){return;}}}}
    boolean acceptRing(Notification event){
        if(event.initialized()){ringKnown=true;ringActive=event.active;return false;}
        if(!event.changed())return false;
        boolean rising=event.active&&(!ringKnown||!ringActive);ringKnown=true;ringActive=event.active;return rising;
    }
    static List<Notification> parseNotifications(String body){
        ArrayList<Notification> events=new ArrayList<>();
        Matcher blocks=Pattern.compile("<(?:\\w+:)?NotificationMessage\\b[^>]*>(.*?)</(?:\\w+:)?NotificationMessage>",Pattern.CASE_INSENSITIVE|Pattern.DOTALL).matcher(body);
        while(blocks.find()){
            String block=blocks.group(1),topic=match(block,"<(?:\\w+:)?Topic[^>]*>([^<]+)</(?:\\w+:)?Topic>");if(topic==null)continue;
            String operation=match(block,"PropertyOperation=\"([^\"]+)\"");
            Matcher values=Pattern.compile("<(?:\\w+:)?SimpleItem\\b[^>]*\\bValue=\"([^\"]+)\"[^>]*/?>",Pattern.CASE_INSENSITIVE).matcher(block);boolean active=false,valueKnown=false;
            while(values.find()){String value=values.group(1);if(value.matches("(?i:true|1|active|on)")){active=true;valueKnown=true;break;}if(value.matches("(?i:false|0|inactive|off)"))valueKnown=true;}
            events.add(new Notification(topic,operation==null?"":operation,active,valueKnown));
        }
        return events;
    }
    static final class Notification{final String topic,operation;final boolean active,valueKnown;Notification(String topic,String operation,boolean active,boolean valueKnown){this.topic=topic;this.operation=operation;this.active=active;this.valueKnown=valueKnown;}boolean ring(){return topic.toLowerCase(Locale.US).contains("ringdetector");}boolean initialized(){return operation.equalsIgnoreCase("Initialized");}boolean changed(){return operation.equalsIgnoreCase("Changed")&&valueKnown;}boolean meaningful(){return !topic.contains("DebugHud")&&(topic.contains("MotionAlarm")||topic.contains("MotionDetector")||topic.contains("ObjectDetection/Object"));}}
    private String post(String address,String xml,String action)throws Exception{Response first=send(address,xml,action,null);if(first.code==200)return first.body;if(first.code!=401)throw new Exception("ONVIF HTTP "+first.code);String challenge=first.auth;if(challenge==null)throw new Exception("ONVIF auth challenge missing");String auth=digest(challenge,"POST",address);Response second=send(address,xml,action,auth);if(second.code!=200)throw new Exception("ONVIF auth HTTP "+second.code);return second.body;}
    private Response send(String address,String xml,String action,String auth)throws Exception{HttpURLConnection c=(HttpURLConnection)new URL(address).openConnection();c.setConnectTimeout(4000);c.setReadTimeout(30000);c.setRequestMethod("POST");c.setDoOutput(true);c.setRequestProperty("Content-Type","application/soap+xml; charset=utf-8; action=\""+action+"\"");if(auth!=null)c.setRequestProperty("Authorization",auth);byte[] bytes=xml.getBytes("UTF-8");c.setFixedLengthStreamingMode(bytes.length);try(OutputStream out=c.getOutputStream()){out.write(bytes);}int code=c.getResponseCode();String challenge=c.getHeaderField("WWW-Authenticate");if(code==401){c.disconnect();return new Response(code,"",challenge);}InputStream in=code>=400?c.getErrorStream():c.getInputStream();String body=in==null?"":read(in);c.disconnect();return new Response(code,body,challenge);}
    private String digest(String challenge,String method,String address)throws Exception{String realm=param(challenge,"realm"),nonce=param(challenge,"nonce"),uri=new URL(address).getPath();String ha1=md5(user+":"+realm+":"+password),ha2=md5(method+":"+uri),response=md5(ha1+":"+nonce+":"+ha2);return "Digest username=\""+user+"\", realm=\""+realm+"\", nonce=\""+nonce+"\", uri=\""+uri+"\", response=\""+response+"\"";}
    private static String param(String input,String name){Matcher m=Pattern.compile(name+"=\"([^\"]+)\"",Pattern.CASE_INSENSITIVE).matcher(input);return m.find()?m.group(1):"";}
    private static String md5(String value)throws Exception{byte[] data=MessageDigest.getInstance("MD5").digest(value.getBytes("ISO-8859-1"));StringBuilder out=new StringBuilder();for(byte b:data)out.append(String.format(Locale.US,"%02x",b&255));return out.toString();}
    private static String match(String body,String regex){Matcher m=Pattern.compile(regex).matcher(body);return m.find()?m.group(1):null;}
    private static String read(InputStream input)throws Exception{BufferedReader r=new BufferedReader(new InputStreamReader(input));StringBuilder b=new StringBuilder();String line;while((line=r.readLine())!=null)b.append(line);return b.toString();}
    private static String create(String endpoint){return envelope(endpoint,CREATE_ACTION,"<tev:CreatePullPointSubscription/>");}
    private static String pull(String endpoint){return envelope(endpoint,PULL_ACTION,"<tev:PullMessages><tev:Timeout>PT20S</tev:Timeout><tev:MessageLimit>20</tev:MessageLimit></tev:PullMessages>");}
    private static String envelope(String endpoint,String action,String body){return "<?xml version=\"1.0\"?><s:Envelope xmlns:s=\"http://www.w3.org/2003/05/soap-envelope\" xmlns:tev=\"http://www.onvif.org/ver10/events/wsdl\" xmlns:wsa=\"http://www.w3.org/2005/08/addressing\"><s:Header><wsa:Action s:mustUnderstand=\"1\">"+action+"</wsa:Action><wsa:MessageID>urn:uuid:"+java.util.UUID.randomUUID()+"</wsa:MessageID><wsa:ReplyTo><wsa:Address>http://www.w3.org/2005/08/addressing/anonymous</wsa:Address></wsa:ReplyTo><wsa:To s:mustUnderstand=\"1\">"+endpoint+"</wsa:To></s:Header><s:Body>"+body+"</s:Body></s:Envelope>";}
    private static final class Response{final int code;final String body,auth;Response(int code,String body,String auth){this.code=code;this.body=body;this.auth=auth;}}
}
