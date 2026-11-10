package kr.rcboat.mobile;

/** One immutable JPEG, no queues/base64 copies across the JavaScript bridge. */
public final class PreviewStore {
    private byte[] bytes;
    private String etag="";
    private long received=-1;
    public synchronized boolean offer(byte[] jpeg,String key,long now){
        if(jpeg==null||jpeg.length<4||jpeg.length>150000||(jpeg[0]&255)!=255||(jpeg[1]&255)!=216)throw new IllegalArgumentException("Invalid preview JPEG");
        if(!key.isEmpty()&&key.equals(etag))return false;
        bytes=jpeg;etag=key;received=now;return true;
    }
    public synchronized byte[] snapshot(){return bytes;}
    public synchronized String etag(){return etag;}
    public synchronized long age(long now){return received<0?-1:Math.max(0,now-received);}
    public synchronized void clear(){bytes=null;etag="";received=-1;}
}
