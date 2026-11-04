package kr.rcboat.mobile;
import org.junit.Test;
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
}
