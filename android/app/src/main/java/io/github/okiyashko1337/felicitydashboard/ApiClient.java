package io.github.okiyashko1337.felicitydashboard;

import org.json.JSONArray;
import org.json.JSONObject;
import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;

final class ApiClient {
    interface Callback { void done(boolean ok, String error); }
    private final DashboardState state;
    private volatile String baseUrl;

    ApiClient(DashboardState state, String baseUrl) { this.state = state; setBaseUrl(baseUrl); }
    void setBaseUrl(String value) {
        String v = value == null ? "" : value.trim();
        while (v.endsWith("/")) v = v.substring(0, v.length() - 1);
        baseUrl = v;
    }
    String baseUrl() { return baseUrl; }

    void current(Callback callback) { run("/api/device/current", json -> {
        JSONObject p = json.getJSONObject("parsed");
        JSONObject pv = p.optJSONObject("pv_power_w"), pvv = p.optJSONObject("pv_voltage_v");
        JSONObject load = p.optJSONObject("load_power_w"), gridV = p.optJSONObject("grid_voltage_v");
        JSONObject gridW = p.optJSONObject("grid_power_w");
        state.pv = n(pv,"total"); state.pv1=n(pv,"pv1"); state.pv2=n(pv,"pv2");
        state.mppt1=n(pvv,"mppt1"); state.mppt2=n(pvv,"mppt2");
        state.load=n(load,"total"); state.l1=n(load,"l1"); state.l2=n(load,"l2"); state.l3=n(load,"l3");
        state.soc=p.optDouble("soc_percent"); state.batteryV=p.optDouble("battery_voltage_v"); state.batteryW=p.optDouble("battery_power_w");
        JSONArray batteries=p.optJSONArray("batteries");
        if (batteries != null && batteries.length()>0) state.bms1=batteries.optJSONObject(0).optDouble("soc_percent");
        if (batteries != null && batteries.length()>1) state.bms2=batteries.optJSONObject(1).optDouble("soc_percent");
        state.gridV1=n(gridV,"l1"); state.gridV2=n(gridV,"l2"); state.gridV3=n(gridV,"l3");
        state.gridW=n(gridW,"total"); state.frequency=p.optDouble("grid_frequency_hz"); state.lastCurrentMs=System.currentTimeMillis();
    }, callback); }

    void summary(Callback callback) { run("/api/device/summary", json -> {
        JSONObject s=json.getJSONObject("system"), t=json.getJSONObject("today");
        state.cpu=s.optDouble("cpu_percent"); state.ram=s.optDouble("memory_percent"); state.temperature=s.optDouble("temperature_c"); state.disk=s.optDouble("disk_percent");
        state.todayPv=t.optDouble("pv_kwh"); state.todayLoad=t.optDouble("load_kwh"); state.coverage=t.optDouble("coverage_percent");
        state.gridImport=t.optDouble("grid_import_kwh"); state.gridExport=t.optDouble("grid_export_kwh"); state.lastSummaryMs=System.currentTimeMillis();
    }, callback); }

    void status(Callback callback) { run("/api/status", json -> { state.serverOnline=json.optBoolean("online", true); state.version=json.optString("app_version", "—"); }, callback); }

    void chart(String metric, Callback callback) { run("/api/device/chart?metric=" + metric, json -> {
        JSONArray samples=json.getJSONArray("samples"); state.chart.clear(); state.chartChannels=json.optInt("channels", 1);
        for(int i=0;i<samples.length();i++) {
            JSONArray row=samples.optJSONArray(i); if(row==null){state.chart.add(null); continue;}
            float[] values=new float[row.length()]; for(int j=0;j<row.length();j++) values[j]=(float)row.optDouble(j); state.chart.add(values);
        }
    }, callback); }

    void geocode(String city, Callback callback) {
        try { city=java.net.URLEncoder.encode(city,"UTF-8"); } catch(Exception ignored) {}
        runAbsolute("https://geocoding-api.open-meteo.com/v1/search?name="+city+"&count=1&language=en&format=json", json -> {
            JSONArray results=json.optJSONArray("results");if(results==null||results.length()==0)throw new Exception("City not found");JSONObject place=results.getJSONObject(0);
            state.latitude=place.getDouble("latitude");state.longitude=place.getDouble("longitude");String name=place.optString("name","Device location"),country=place.optString("country_code","");state.location=name+(country.length()>0?", "+country:"");
        },callback);
    }

    void weather(Callback callback) {
        if(Double.isNaN(state.latitude)||Double.isNaN(state.longitude)){callback.done(false,"Location unavailable");return;}
        String url="https://api.open-meteo.com/v1/forecast?latitude="+state.latitude+"&longitude="+state.longitude
                +"&current=temperature_2m,weather_code&daily=weather_code,temperature_2m_max,temperature_2m_min&timezone=auto&forecast_days=7";
        runAbsolute(url, json -> {
            JSONObject current=json.getJSONObject("current"),daily=json.getJSONObject("daily");
            state.weatherTemperature=current.optDouble("temperature_2m"); state.weatherCode=current.optInt("weather_code",-1);
            JSONArray dates=daily.getJSONArray("time"),codes=daily.getJSONArray("weather_code"),mins=daily.getJSONArray("temperature_2m_min"),maxs=daily.getJSONArray("temperature_2m_max");
            for(int i=0;i<7;i++){state.forecastDate[i]=dates.optString(i);state.forecastCode[i]=codes.optInt(i,-1);state.forecastMin[i]=mins.optDouble(i);state.forecastMax[i]=maxs.optDouble(i);}
            state.weatherUpdatedMs=System.currentTimeMillis();
        },callback);
    }

    private interface Parser { void parse(JSONObject json) throws Exception; }
    private void run(String path, Parser parser, Callback callback) {
        runAbsolute(baseUrl+path,parser,callback);
    }
    private void runAbsolute(String address, Parser parser, Callback callback) {
        HttpURLConnection connection=null;
        try {
            connection=(HttpURLConnection)new URL(address).openConnection(); connection.setConnectTimeout(4500); connection.setReadTimeout(6000); connection.setUseCaches(false);
            int status=connection.getResponseCode(); if(status!=200) throw new Exception("HTTP "+status);
            parser.parse(new JSONObject(read(connection.getInputStream()))); callback.done(true, null);
        } catch(Exception e) { callback.done(false, e.getMessage()); }
        finally { if(connection!=null) connection.disconnect(); }
    }
    private static String read(InputStream input) throws Exception { BufferedReader r=new BufferedReader(new InputStreamReader(input)); StringBuilder b=new StringBuilder(); String line; while((line=r.readLine())!=null)b.append(line); return b.toString(); }
    private static double n(JSONObject object,String key){return object==null?0:object.optDouble(key);}
}
