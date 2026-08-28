package io.github.okiyashko1337.felicitydashboard;

import android.content.Context;
import android.content.SharedPreferences;

final class StreamQuality {
    static final String KEY="live_stream_quality";
    static final String AUTO="auto";
    static final String MAIN="main";
    static final String SUB="sub";

    private StreamQuality(){}

    static boolean useSubstream(Context context,SharedPreferences prefs){
        String preference=prefs.getString(KEY,AUTO);
        if(SUB.equals(preference))return true;
        if(MAIN.equals(preference))return false;
        return context.getResources().getDisplayMetrics().widthPixels<=1200;
    }

    static void select(SharedPreferences prefs,boolean substream){
        prefs.edit().putString(KEY,substream?SUB:MAIN).apply();
    }
}
