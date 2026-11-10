package kr.rcboat.mobile;
import org.junit.Test;
import static org.junit.Assert.*;
public class PreviewStoreTest {
    private byte[] jpeg(int v){return new byte[]{(byte)255,(byte)216,(byte)v,(byte)217};}
    @Test public void keepsOnlyNewestAndDuplicatesDoNotRefreshAge(){PreviewStore p=new PreviewStore();byte[] first=jpeg(1),second=jpeg(2);assertTrue(p.offer(first,"a",100));assertFalse(p.offer(jpeg(3),"a",1000));assertEquals(900,p.age(1000));assertSame(first,p.snapshot());assertTrue(p.offer(second,"b",1200));assertSame(second,p.snapshot());p.clear();assertNull(p.snapshot());assertEquals(-1,p.age(2000));}
    @Test public void invalidJpegAndOversizedPayloadCannotEnterCache(){PreviewStore p=new PreviewStore();for(byte[] bad:new byte[][]{new byte[0],new byte[150001],new byte[]{1,2,3,4}}){try{p.offer(bad,"x",1);fail();}catch(IllegalArgumentException expected){}}assertNull(p.snapshot());}
}
