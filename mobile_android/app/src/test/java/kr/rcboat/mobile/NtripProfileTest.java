package kr.rcboat.mobile;
import org.junit.Test;
import org.json.JSONObject;
import static org.junit.Assert.*;
public class NtripProfileTest {
    @Test public void neverCachesPasswordsOrTokens()throws Exception{
        JSONObject p=NtripProfile.merge(new JSONObject().put("password","old"),new JSONObject().put("host","caster.example.invalid").put("password","secret").put("token","secret").put("username","test-user"));
        assertFalse(p.has("password"));assertFalse(p.has("token"));assertEquals("test-user",p.getString("username"));
    }
    @Test public void keepsUnchangedSavedFields()throws Exception{
        JSONObject p=NtripProfile.merge(new JSONObject().put("host","saved.example.invalid").put("username","saved-user"),new JSONObject().put("port",2101));
        assertEquals("saved.example.invalid",p.getString("host"));assertEquals("saved-user",p.getString("username"));assertEquals(2101,p.getInt("port"));
    }
    @Test public void rejectsInvalidPorts()throws Exception{for(Object v:new Object[]{0,65536,2101.5,true,"2101"}){try{NtripProfile.merge(new JSONObject(),new JSONObject().put("port",v));fail();}catch(IllegalArgumentException expected){}}}
    @Test public void rejectsMultilineOrNonStringFields()throws Exception{for(Object v:new Object[]{"x\nmalformed",27}){try{NtripProfile.merge(new JSONObject(),new JSONObject().put("host",v));fail();}catch(IllegalArgumentException expected){}}}
}
