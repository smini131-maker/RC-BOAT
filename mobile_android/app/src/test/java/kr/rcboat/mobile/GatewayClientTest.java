package kr.rcboat.mobile;
import org.junit.Test;
import org.json.JSONArray;
import org.json.JSONObject;
import java.net.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.*;
import static org.junit.Assert.*;

public class GatewayClientTest {
    private String exchange(String response,int limit,boolean expectFailure)throws Exception{
        try(ServerSocket server=new ServerSocket(0)){
            ExecutorService thread=Executors.newSingleThreadExecutor();
            Future<String> request=thread.submit(()->{try(Socket c=server.accept()){
                String line=new BufferedReader(new InputStreamReader(c.getInputStream(),StandardCharsets.UTF_8)).readLine();
                byte[] raw=response.getBytes(StandardCharsets.UTF_8);
                for(int i=0;i<raw.length;i+=3){c.getOutputStream().write(raw,i,Math.min(3,raw.length-i));c.getOutputStream().flush();}
                return line;
            }});
            try{JSONObject answer=new GatewayClient("127.0.0.1",server.getLocalPort(),"test-token").request("ground_stop",new JSONObject(),1000,limit);if(expectFailure)fail("must reject");assertTrue(answer.getBoolean("success"));}
            catch(IOException e){if(!expectFailure)throw e;}
            finally{thread.shutdown();}
            try{return request.get(2,TimeUnit.SECONDS);}catch(ExecutionException e){if(!expectFailure)throw e;return "";}
        }
    }
    @Test public void preservesProtocolAndUtf8AcrossTcpChunks()throws Exception{JSONObject p=new JSONObject(exchange("{\"success\":true,\"name\":\"해수천\"}\n",4096,false));assertEquals("ground_stop",p.getString("action"));assertEquals("test-token",p.getString("token"));assertEquals(0,p.getJSONObject("arguments").length());}
    @Test public void rejectsBackendFailure()throws Exception{exchange("{\"success\":false,\"error\":\"E-STOP\"}\n",4096,true);}
    @Test public void rejectsTruncatedResponses()throws Exception{exchange("{\"success\":true}",4096,true);}
    @Test public void rejectsOversizedResponses()throws Exception{exchange("{\"success\":true,\"payload\":\""+"x".repeat(1000)+"\"}\n",64,true);}
    @Test public void validatesEndpoint(){for(String host:new String[]{"", "http://jetson", "a\nb", "jetson/path"}){try{new GatewayClient(host,8765,"");fail(host);}catch(IllegalArgumentException expected){}}}

    @Test public void reusesOnlyMatchingCatalogsAndStartsFreshOnReconnect() throws Exception {
        try (ServerSocket server = new ServerSocket(0)) {
            ExecutorService executor = Executors.newSingleThreadExecutor();
            String[] revision = {"a", "a", "b", "b", "c", null, "d"};
            String[] expected = {"", "a", "a", "", "", "c", ""};
            String[] routeId = {"first", null, null, "second", "other", "legacy", "current"};
            Future<?> responder = executor.submit(() -> {
                for (int i = 0; i < revision.length; i++) {
                    try (Socket client = server.accept()) {
                        String line = new BufferedReader(new InputStreamReader(
                            client.getInputStream(), StandardCharsets.UTF_8)).readLine();
                        JSONObject request = new JSONObject(line);
                        assertEquals("status", request.getString("action"));
                        assertEquals(expected[i], request.getJSONObject("arguments").getString("route_catalog_revision"));
                        JSONObject route = new JSONObject().put("target_waypoint_index", i);
                        if (routeId[i] != null) {
                            route.put("routes", new JSONArray().put(new JSONObject().put("id", routeId[i])));
                            route.put("multipaths", new JSONArray().put(new JSONObject().put("id", "group-" + routeId[i])));
                        }
                        JSONObject reply = new JSONObject().put("success", true)
                            .put("telemetry", new JSONObject().put("route", route));
                        reply.put("route_catalog_revision", revision[i] == null ? JSONObject.NULL : revision[i]);
                        client.getOutputStream().write((reply + "\n").getBytes(StandardCharsets.UTF_8));
                    }
                }
                return null;
            });
            try {
                GatewayClient gateway = new GatewayClient("127.0.0.1", server.getLocalPort(), "");
                assertCatalog(gateway.requestStatus(1000, 4096), "first", 0);
                assertCatalog(gateway.requestStatus(1000, 4096), "first", 1);
                assertFalse(gateway.requestStatus(1000, 4096).getJSONObject("telemetry").getJSONObject("route").has("routes"));
                assertCatalog(gateway.requestStatus(1000, 4096), "second", 3);
                GatewayClient reconnect = new GatewayClient("127.0.0.1", server.getLocalPort(), "");
                assertCatalog(reconnect.requestStatus(1000, 4096), "other", 4);
                assertCatalog(reconnect.requestStatus(1000, 4096), "legacy", 5);
                assertCatalog(reconnect.requestStatus(1000, 4096), "current", 6);
                responder.get(2, TimeUnit.SECONDS);
            } finally {
                executor.shutdownNow();
            }
        }
    }

    private static void assertCatalog(JSONObject status, String routeId, int waypoint) throws Exception {
        JSONObject route = status.getJSONObject("telemetry").getJSONObject("route");
        assertEquals(routeId, route.getJSONArray("routes").getJSONObject(0).getString("id"));
        assertEquals("group-" + routeId, route.getJSONArray("multipaths").getJSONObject(0).getString("id"));
        assertEquals(waypoint, route.getInt("target_waypoint_index"));
    }
}
