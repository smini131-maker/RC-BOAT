package kr.rcboat.mobile;

import org.json.JSONObject;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;

/** Existing newline-delimited ROS gateway protocol; each request owns a socket. */
public final class GatewayClient {
    public final String host;
    public final int port;
    private final String token;
    public GatewayClient(String host, int port, String token) {
        if (host == null || !host.matches("[a-zA-Z0-9.:%_-]{1,253}") || port < 1 || port > 65535)
            throw new IllegalArgumentException("Jetson 주소/포트를 확인하세요");
        this.host=host; this.port=port; this.token=token;
    }
    public JSONObject request(String action, JSONObject args, int timeoutMs, int limit) throws Exception {
        try (Socket s=new Socket()) {
            s.connect(new InetSocketAddress(host,port),Math.min(1500,timeoutMs));
            s.setSoTimeout(timeoutMs);
            JSONObject payload=new JSONObject().put("action",action).put("arguments",args==null?new JSONObject():args);
            if (!token.isEmpty()) payload.put("token",token);
            s.getOutputStream().write((payload+"\n").getBytes(StandardCharsets.UTF_8));
            ByteArrayOutputStream bytes=new ByteArrayOutputStream();
            byte[] chunk=new byte[16384]; int count; boolean ended=false;
            while (!ended && (count=s.getInputStream().read(chunk))!=-1) {
                int length=0; while(length<count && chunk[length]!='\n') length++;
                if(bytes.size()+length>limit)throw new IOException("응답 크기 제한 초과");
                bytes.write(chunk,0,length); ended=length<count;
            }
            if(!ended)throw new EOFException("ROS gateway 응답이 중단됐습니다");
            JSONObject result=new JSONObject(bytes.toString(StandardCharsets.UTF_8.name()));
            if(!result.optBoolean("success"))throw new IOException(result.optString("error","명령 거부"));
            return result;
        }
    }
}
