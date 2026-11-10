package kr.rcboat.mobile;

/** Reply-based health. A single timeout is delay, not proof of disconnection. */
public final class ConnectionHealth {
    public static final long STALE_MS=2500, OFFLINE_MS=8000;
    private long lastReply=-1,firstFailure=-1,rtt=-1;
    private int failures;
    private boolean definiteOffline;
    public synchronized void reset(long now){lastReply=-1;firstFailure=-1;rtt=-1;failures=0;definiteOffline=false;}
    public synchronized void success(long now,long duration){lastReply=now;rtt=Math.max(0,duration);firstFailure=-1;failures=0;definiteOffline=false;}
    public synchronized void failure(long now,boolean definite){if(firstFailure<0)firstFailure=now;failures++;definiteOffline=definiteOffline||definite;}
    public synchronized String state(long now){
        if(definiteOffline || failures>=3 && now-firstFailure>=OFFLINE_MS)return "offline";
        if(failures>0 || lastReply>=0 && now-lastReply>STALE_MS || rtt>600)return "delayed";
        return lastReply<0?"connecting":"online";
    }
    public synchronized long age(long now){return lastReply<0?-1:Math.max(0,now-lastReply);}
    public synchronized long rtt(){return rtt;}
    public synchronized int failures(){return failures;}
}
