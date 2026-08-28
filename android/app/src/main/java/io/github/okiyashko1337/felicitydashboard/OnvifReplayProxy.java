package io.github.okiyashko1337.felicitydashboard;

import android.net.Uri;
import android.util.Log;
import java.io.ByteArrayOutputStream;
import java.io.Closeable;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.ServerSocket;
import java.net.Socket;
import java.net.URI;
import java.security.MessageDigest;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;
import java.util.TimeZone;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

final class OnvifReplayProxy implements Closeable {
    private final String upstream,user,password,upstreamBase;
    private final long startMs;
    private final ServerSocket server;
    private final ExecutorService threads=Executors.newCachedThreadPool();
    private volatile String challenge="",localBase="";private volatile boolean closed;private Socket client,remote;

    OnvifReplayProxy(String upstream,String user,String password,long startMs)throws Exception{
        this.upstream=upstream;this.user=user;this.password=password;this.startMs=startMs;
        URI parsed=new URI(upstream);int port=parsed.getPort()>0?parsed.getPort():554;this.upstreamBase="rtsp://"+parsed.getHost()+":"+port;
        server=new ServerSocket(0,1,java.net.InetAddress.getByName("127.0.0.1"));
    }

    String start(){localBase="rtsp://127.0.0.1:"+server.getLocalPort();threads.execute(this::accept);return "rtsp://"+Uri.encode(user)+":"+Uri.encode(password)+"@127.0.0.1:"+server.getLocalPort()+"/replay";}

    private void accept(){try{client=server.accept();URI parsed=new URI(upstream);remote=new Socket();remote.connect(new java.net.InetSocketAddress(parsed.getHost(),parsed.getPort()>0?parsed.getPort():554),5000);remote.setTcpNoDelay(true);client.setTcpNoDelay(true);threads.execute(()->relay(client,remote,true));relay(remote,client,false);}catch(Exception ignored){close();}}

    private void relay(Socket from,Socket to,boolean requestDirection){try{InputStream in=from.getInputStream();OutputStream out=to.getOutputStream();while(!closed){int first=in.read();if(first<0)break;if(first=='$'){byte[] prefix=new byte[3];readFully(in,prefix);int length=((prefix[1]&255)<<8)|(prefix[2]&255);byte[] payload=new byte[length];readFully(in,payload);synchronized(out){out.write(first);out.write(prefix);out.write(payload);out.flush();}continue;}byte[] header=readHeader(in,first);String text=new String(header,"ISO-8859-1");int length=contentLength(text);byte[] body=new byte[length];readFully(in,body);String bodyText=length==0?"":new String(body,"ISO-8859-1");String rewritten=requestDirection?rewriteRequest(text):rewriteResponse(text);bodyText=requestDirection?toUpstream(bodyText):toLocal(bodyText);rewritten=setContentLength(rewritten,bodyText.getBytes("ISO-8859-1").length);synchronized(out){out.write(rewritten.getBytes("ISO-8859-1"));out.write(bodyText.getBytes("ISO-8859-1"));out.flush();}}}catch(Exception ignored){}finally{close();}}

    private String rewriteRequest(String header)throws Exception{
        String result=toUpstream(header);String first=line(result,0);String[] words=first.split(" ");String method=words.length>0?words[0]:"",requestUri=words.length>1?words[1]:upstream;
        if("SETUP".equals(method)||"PLAY".equals(method)){result=removeHeader(result,"Require");result=insertHeader(result,"Require: onvif-replay");}
        if("PLAY".equals(method)){String localRange=headerValue(result,"Range");result=removeHeader(result,"Range");result=insertHeader(result,"Range: clock="+clock(startMs)+"-");result=removeHeader(result,"Rate-Control");result=insertHeader(result,"Rate-Control: yes");result=removeHeader(result,"Scale");result=insertHeader(result,"Scale: 1.0");Log.i("FelicityReplay","RTSP PLAY · local="+localRange+" · upstream="+headerValue(result,"Range")+" · require="+headerValue(result,"Require")+" · rate="+headerValue(result,"Rate-Control"));}
        if(!challenge.isEmpty()){result=removeHeader(result,"Authorization");result=insertHeader(result,"Authorization: "+digest(challenge,method,requestUri));}
        return result;
    }

    private String rewriteResponse(String header){String auth=headerValue(header,"WWW-Authenticate");if(auth!=null&&!auth.isEmpty())challenge=auth;String range=headerValue(header,"Range"),rtp=headerValue(header,"RTP-Info");if(range!=null||rtp!=null)Log.i("FelicityReplay","RTSP response · status="+line(header,0)+" · range="+range+" · rtp="+(rtp==null?"—":"present"));return toLocal(header);}
    private String toUpstream(String value){return value.replace(localBase+"/replay",upstream).replace(localBase,upstreamBase);}
    private String toLocal(String value){return value.replace(upstream,localBase+"/replay").replace(upstreamBase,localBase);}

    private String digest(String source,String method,String uri)throws Exception{
        String realm=parameter(source,"realm"),nonce=parameter(source,"nonce"),qop=parameter(source,"qop"),opaque=parameter(source,"opaque"),algorithm=parameter(source,"algorithm");if(algorithm.isEmpty())algorithm="MD5";
        String ha1=md5(user+":"+realm+":"+password),ha2=md5(method+":"+uri),response,extra="";
        if(!qop.isEmpty()){String selected=qop.toLowerCase(Locale.US).contains("auth")?"auth":qop.split(",")[0].trim(),nc="00000001",cnonce=md5(Long.toHexString(System.nanoTime())).substring(0,16);response=md5(ha1+":"+nonce+":"+nc+":"+cnonce+":"+selected+":"+ha2);extra=", qop="+selected+", nc="+nc+", cnonce=\""+cnonce+"\"";}else response=md5(ha1+":"+nonce+":"+ha2);
        return "Digest username=\""+user+"\", realm=\""+realm+"\", nonce=\""+nonce+"\", uri=\""+uri+"\", response=\""+response+"\", algorithm="+algorithm+(opaque.isEmpty()?"":", opaque=\""+opaque+"\"")+extra;
    }

    private static byte[] readHeader(InputStream in,int first)throws Exception{ByteArrayOutputStream result=new ByteArrayOutputStream();result.write(first);int state=first=='\r'?1:0;while(state<4){int value=in.read();if(value<0)throw new java.io.EOFException();result.write(value);if((state==0||state==2)&&value=='\r')state++;else if((state==1||state==3)&&value=='\n')state++;else state=value=='\r'?1:0;if(result.size()>256*1024)throw new Exception("RTSP header too large");}return result.toByteArray();}
    private static void readFully(InputStream in,byte[] buffer)throws Exception{int offset=0;while(offset<buffer.length){int count=in.read(buffer,offset,buffer.length-offset);if(count<0)throw new java.io.EOFException();offset+=count;}}
    private static int contentLength(String header){String value=headerValue(header,"Content-Length");try{return value==null?0:Integer.parseInt(value.trim());}catch(Exception ignored){return 0;}}
    private static String setContentLength(String header,int length){if(headerValue(header,"Content-Length")==null)return header;if(length==0)return removeHeader(header,"Content-Length");return header.replaceFirst("(?im)^Content-Length\\s*:\\s*\\d+\\s*$","Content-Length: "+length);}
    private static String removeHeader(String header,String name){return header.replaceFirst("(?im)^"+Pattern.quote(name)+"\\s*:[^\\r\\n]*(?:\\r?\\n)","");}
    private static String insertHeader(String header,String value){int end=header.indexOf("\r\n\r\n");return end<0?header:header.substring(0,end)+"\r\n"+value+header.substring(end);}
    private static String headerValue(String header,String name){Matcher matcher=Pattern.compile("(?im)^"+Pattern.quote(name)+"\\s*:\\s*([^\\r\\n]+)").matcher(header);return matcher.find()?matcher.group(1).trim():null;}
    private static String line(String text,int index){String[] lines=text.split("\\r?\\n");return index<lines.length?lines[index]:"";}
    private static String parameter(String input,String name){Matcher matcher=Pattern.compile("(?:^|[, ])"+name+"\\s*=\\s*(?:\"([^\"]*)\"|([^, ]+))",Pattern.CASE_INSENSITIVE).matcher(input);return matcher.find()?(matcher.group(1)!=null?matcher.group(1):matcher.group(2)):"";}
    private static String md5(String value)throws Exception{byte[] bytes=MessageDigest.getInstance("MD5").digest(value.getBytes("ISO-8859-1"));StringBuilder result=new StringBuilder();for(byte valueByte:bytes)result.append(String.format(Locale.US,"%02x",valueByte&255));return result.toString();}
    private static String clock(long time){SimpleDateFormat format=new SimpleDateFormat("yyyyMMdd'T'HHmmss'Z'",Locale.US);format.setTimeZone(TimeZone.getTimeZone("UTC"));return format.format(new Date(time));}

    @Override public synchronized void close(){if(closed)return;closed=true;try{server.close();}catch(Exception ignored){}try{if(client!=null)client.close();}catch(Exception ignored){}try{if(remote!=null)remote.close();}catch(Exception ignored){}threads.shutdownNow();}
}
