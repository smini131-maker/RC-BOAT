package kr.rcboat.mobile;
import org.junit.Test;
import static org.junit.Assert.*;
public class ConnectionHealthTest {
    @Test public void timeoutIsDelayAndRecoveryPreservesConnection(){ConnectionHealth h=new ConnectionHealth();h.reset(0);assertEquals("connecting",h.state(0));h.success(100,30);h.failure(300,false);assertEquals("delayed",h.state(300));h.success(600,40);assertEquals("online",h.state(600));assertEquals(0,h.failures());assertEquals(40,h.rtt());}
    @Test public void sustainedTimeoutNeedsCountAndDuration(){ConnectionHealth h=new ConnectionHealth();h.reset(0);h.success(100,10);h.failure(500,false);h.failure(3000,false);h.failure(5000,false);assertEquals("delayed",h.state(8499));assertEquals("offline",h.state(8500));h.success(8600,20);assertEquals("online",h.state(8600));}
    @Test public void closedTransportIsOfflineImmediately(){ConnectionHealth h=new ConnectionHealth();h.reset(0);h.failure(1,true);assertEquals("offline",h.state(1));}
    @Test public void slowReplyAndStaleReplyAreVisible(){ConnectionHealth h=new ConnectionHealth();h.reset(0);h.success(100,750);assertEquals("delayed",h.state(100));h.success(200,20);assertEquals("delayed",h.state(2701));assertEquals(2501,h.age(2701));}
}
