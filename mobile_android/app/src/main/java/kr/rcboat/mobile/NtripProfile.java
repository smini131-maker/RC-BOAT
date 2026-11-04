package kr.rcboat.mobile;

import org.json.JSONObject;

/** Public connection fields only. Passwords/tokens never enter the mobile cache. */
public final class NtripProfile {
    private NtripProfile() {}
    public static JSONObject merge(JSONObject before, JSONObject incoming) throws Exception {
        JSONObject result=new JSONObject();
        for(String key:new String[]{"host","port","mountpoint","username","tls"}) {
            if(before.has(key))result.put(key,before.get(key));
            if(incoming.has(key))result.put(key,incoming.get(key));
        }
        if(result.has("port")){
            Object port=result.get("port");
            if(!(port instanceof Number)||((Number)port).doubleValue()!=((Number)port).intValue()||((Number)port).intValue()<1||((Number)port).intValue()>65535)throw new IllegalArgumentException("NTRIP port");
        }
        for(String key:new String[]{"host","mountpoint","username"})if(result.has(key)){
            Object raw=result.get(key);
            if(!(raw instanceof String)||((String)raw).length()>253||((String)raw).contains("\n")||((String)raw).contains("\r"))throw new IllegalArgumentException("NTRIP field");
        }
        if(result.has("tls")&&!(result.get("tls") instanceof Boolean))throw new IllegalArgumentException("NTRIP TLS");
        return result;
    }
}
