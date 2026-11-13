package kr.rcboat.mobile;

import android.app.*;
import android.os.*;
import android.webkit.*;
import android.view.*;
import android.widget.FrameLayout;
import android.content.*;
import android.net.Uri;
import android.provider.MediaStore;
import androidx.webkit.WebViewAssetLoader;
import com.jcraft.jsch.*;
import org.json.*;
import java.io.*;
import java.net.*;
import java.security.MessageDigest;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;

public class MainActivity extends Activity {
    private WebView web;
    private AlertDialog jsConfirmDialog;
    private JsResult pendingJsConfirm;
    private int confirmGeneration;
    private final Handler main=new Handler(Looper.getMainLooper());
    private final ScheduledExecutorService poll=Executors.newSingleThreadScheduledExecutor();
    private final ScheduledExecutorService lease=Executors.newSingleThreadScheduledExecutor();
    private final ScheduledExecutorService health=Executors.newSingleThreadScheduledExecutor();
    private final ExecutorService commands=Executors.newSingleThreadExecutor();
    private final ExecutorService urgent=Executors.newSingleThreadExecutor();
    private final ScheduledExecutorService frames=Executors.newSingleThreadScheduledExecutor();
    private final ConnectionHealth rosHealth=new ConnectionHealth(),sshHealth=new ConnectionHealth();
    private final PreviewStore previewStore=new PreviewStore();
    private volatile long nextFrameAt=0;
    private volatile HttpURLConnection activeFrame;
    private final AtomicBoolean frameBusy=new AtomicBoolean(false);
    private volatile GatewayClient gateway;
    private volatile Session ssh;
    private volatile boolean connected=false, owned=false, foreground=true, preview=false, remoteHeld=false, ready=false;
    private volatile int generation=0, remoteSteering=6000, remoteThrottle=6450;
    private volatile long remoteAt=0,lastStatus=0;
    private volatile String sshState="disconnected", backendVersion="", mode="";
    private volatile JSONObject latest=new JSONObject();
    private volatile int previewPort=8766;
    private String token="";
    private final Set<String> allowed=new HashSet<>(Arrays.asList("estop","reset_estop","set_mode","set_auto_cruise_pwm","nav_curve_slowdown","select_route","select_multipath","set_multipath","record_start","record_stop","record_cancel","upsert_route","delete_route","upsert_multipath","delete_multipath","ground_start","ground_resume","ground_stop","vision_enable","vision_configure","vision_reset_tracking","set_gps_settings","configure","gps_log_start","gps_log_stop","set_tracking_mode"));

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        getWindow().setStatusBarColor(0xff0b1520);getWindow().setNavigationBarColor(0xff0b1520);
        FrameLayout root=new FrameLayout(this);root.setBackgroundColor(0xff0b1520);
        web=new WebView(this);web.setBackgroundColor(0xff0b1520);root.addView(web,new FrameLayout.LayoutParams(-1,-1));setContentView(root);
        root.setOnApplyWindowInsetsListener((v,i)->{if(Build.VERSION.SDK_INT>=30){android.graphics.Insets b=i.getInsets(WindowInsets.Type.systemBars()|WindowInsets.Type.displayCutout());v.setPadding(b.left,b.top,b.right,b.bottom);return WindowInsets.CONSUMED;}else{v.setPadding(i.getSystemWindowInsetLeft(),i.getSystemWindowInsetTop(),i.getSystemWindowInsetRight(),i.getSystemWindowInsetBottom());return i.consumeSystemWindowInsets().consumeDisplayCutout();}});
        if(Build.VERSION.SDK_INT>=30)getWindow().getInsetsController().setSystemBarsAppearance(0,WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS|WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS);
        else getWindow().getDecorView().setSystemUiVisibility(0);
        WebSettings s=web.getSettings();s.setJavaScriptEnabled(true);s.setDomStorageEnabled(true);s.setAllowFileAccess(false);s.setAllowContentAccess(false);s.setSupportMultipleWindows(false);
        s.setUserAgentString(s.getUserAgentString()+" RCBoatMobile/"+BuildConfig.VERSION_NAME);
        web.setWebChromeClient(new WebChromeClient(){
            @Override public boolean onJsConfirm(WebView view,String url,String message,JsResult result){
                Uri origin=Uri.parse(url);
                if(!foreground||isFinishing()||!"https".equals(origin.getScheme())||!"appassets.androidplatform.net".equals(origin.getHost())){result.cancel();return true;}
                closeJsConfirm(false);pendingJsConfirm=result;confirmGeneration=generation;
                jsConfirmDialog=new AlertDialog.Builder(MainActivity.this).setTitle("명령 확인").setMessage(message)
                    .setPositiveButton("확인",(d,w)->closeJsConfirm(true)).setNegativeButton("취소",(d,w)->closeJsConfirm(false))
                    .setOnCancelListener(d->closeJsConfirm(false)).create();
                jsConfirmDialog.show();return true;
            }
        });
        WebViewAssetLoader assets=new WebViewAssetLoader.Builder().addPathHandler("/assets/",new WebViewAssetLoader.AssetsPathHandler(this)).build();
        web.setWebViewClient(new WebViewClient(){
            @Override public WebResourceResponse shouldInterceptRequest(WebView view,WebResourceRequest req){
                Uri u=req.getUrl();
                if("appassets.androidplatform.net".equals(u.getHost())){
                    if("/preview.jpg".equals(u.getPath())){
                        byte[] jpeg=previewStore.snapshot();
                        return new WebResourceResponse("image/jpeg",null,jpeg==null?503:200,jpeg==null?"No current frame":"OK",Collections.singletonMap("Cache-Control","no-store"),new ByteArrayInputStream(jpeg==null?new byte[0]:jpeg));
                    }
                    return assets.shouldInterceptRequest(u);
                }
                if("https".equals(u.getScheme()) && "tile.openstreetmap.org".equals(u.getHost()) && u.getPath().matches("/\\d+/\\d+/\\d+\\.png"))return null;
                return new WebResourceResponse("text/plain","UTF-8",new ByteArrayInputStream(new byte[0]));
            }
            @Override public boolean shouldOverrideUrlLoading(WebView v,WebResourceRequest r){return true;}
        });
        web.addJavascriptInterface(new AppBridge(),"Boat");
        web.loadUrl("https://appassets.androidplatform.net/assets/index.html");
        poll.scheduleWithFixedDelay(this::pollStatus,300,1000,TimeUnit.MILLISECONDS);
        frames.scheduleWithFixedDelay(this::previewTick,300,10,TimeUnit.MILLISECONDS);
        lease.scheduleWithFixedDelay(this::heartbeat,100,250,TimeUnit.MILLISECONDS);
        health.scheduleWithFixedDelay(this::checkSsh,500,2500,TimeUnit.MILLISECONDS);
        importProfile(getIntent());
    }
    private JSONObject savedProfile(){try{return new JSONObject(getPreferences(MODE_PRIVATE).getString("ntrip_profile","{}"));}catch(Exception e){return new JSONObject();}}
    private void cacheProfile(JSONObject incoming){try{JSONObject p=NtripProfile.merge(savedProfile(),incoming);if(p.optString("host").isEmpty()||p.optString("mountpoint").isEmpty())return;if(!p.toString().equals(savedProfile().toString())){getPreferences(MODE_PRIVATE).edit().putString("ntrip_profile",p.toString()).apply();emit("ntrip_profile",p);}}catch(Exception ignored){}}
    private void importProfile(Intent intent){
        if(intent==null||!Intent.ACTION_SEND.equals(intent.getAction()))return;
        String raw=intent.getStringExtra(Intent.EXTRA_TEXT);if(raw==null||raw.length()>4096)return;
        try{JSONObject input=new JSONObject(raw);if(input.optInt("rcboat_ntrip_profile")!=1)return;JSONObject profile=NtripProfile.merge(new JSONObject(),input);
            if(profile.optString("host").isEmpty()||profile.optString("mountpoint").isEmpty())return;
            new AlertDialog.Builder(this).setTitle("RTK 로컬 설정 가져오기").setMessage(profile.optString("host")+":"+profile.optInt("port",2101)+"\n"+profile.optString("mountpoint")+"\n사용자: "+profile.optString("username")+"\n\n휴대폰에 설정만 저장합니다. Jetson 연결·보정 서버 접속은 시작하지 않습니다. 비밀번호는 가져오지 않습니다.")
                .setPositiveButton("저장",(d,w)->{cacheProfile(profile);notice("기존 RTK 프로필을 휴대폰에 저장했습니다");}).setNegativeButton("취소",null).show();
        }catch(Exception e){notice("RTK 프로필 형식 오류");}
        intent.removeExtra(Intent.EXTRA_TEXT);
    }
    @Override protected void onNewIntent(Intent intent){super.onNewIntent(intent);setIntent(intent);importProfile(intent);}
    private void emit(String event,JSONObject data){main.post(()->{if(web!=null)web.evaluateJavascript("window.onNative&&window.onNative("+JSONObject.quote(event)+","+data+")",null);});}
    private static JSONObject obj(String raw)throws JSONException{return new JSONObject(raw);}
    private static JSONObject data(String k,Object v){JSONObject o=new JSONObject();try{o.put(k,v);}catch(Exception ignored){}return o;}
    private void notice(String text){emit("message",data("text",text));}
    private void pollStatus(){
        GatewayClient g=gateway;int gen=generation;
        if(!connected || !foreground || g==null || g!=gateway)return;
        try{
            long start=SystemClock.elapsedRealtime();
            JSONObject status=g.requestStatus(1500,6*1024*1024);
            if(gen!=generation || g!=gateway || !connected || !foreground)return;
            latest=status;backendVersion=status.optString("version");lastStatus=SystemClock.elapsedRealtime();rosHealth.success(lastStatus,lastStatus-start);
            JSONObject tele=status.optJSONObject("telemetry");JSONObject safe=tele==null?null:tele.optJSONObject("safety");mode=safe==null?"":safe.optString("mode");
            JSONObject vision=tele==null?null:tele.optJSONObject("vision");if(vision!=null)previewPort=vision.optInt("preview_port",8766);
            JSONObject ntrip=tele==null?null:tele.optJSONObject("ntrip");if(ntrip!=null&&!ntrip.optString("host").isEmpty()&&!ntrip.optString("mountpoint").isEmpty())cacheProfile(ntrip);
            status.put("mobile",healthSnapshot());emit("status",status);
        }catch(Exception e){if(gen==generation && g==gateway && connected && foreground){rosHealth.failure(SystemClock.elapsedRealtime(),e instanceof ConnectException||e instanceof NoRouteToHostException);emit("link_health",healthSnapshot());}}
    }
    private JSONObject healthSnapshot(){
        long now=SystemClock.elapsedRealtime();JSONObject value=new JSONObject();
        try{value.put("ssh",sshState).put("control",owned).put("app_version",BuildConfig.VERSION_NAME)
            .put("ros",rosHealth.state(now)).put("ros_age_ms",rosHealth.age(now)).put("ros_rtt_ms",rosHealth.rtt()).put("ros_failures",rosHealth.failures())
            .put("ssh_age_ms",sshHealth.age(now)).put("ssh_rtt_ms",sshHealth.rtt()).put("ssh_failures",sshHealth.failures());}catch(JSONException ignored){}
        return value;
    }
    private void heartbeat(){
        GatewayClient g=gateway;if(!connected || !foreground || !owned || g==null)return;
        try{
            g.request("operator_link",new JSONObject().put("ssh_connected",!sshState.equals("disconnected")).put("ssh_state",sshState),700,4096);
            if(mode.equals("REMOTE") && remoteHeld && SystemClock.elapsedRealtime()-remoteAt<500 && SystemClock.elapsedRealtime()-lastStatus<2500){
                g.request("set_remote_pwm",new JSONObject().put("steering_pwm",remoteSteering).put("throttle_pwm",remoteThrottle),600,8192);
            }
        }catch(Exception ignored){}
    }
    private void checkSsh(){
        Session current=ssh;int gen=generation;if(current==null)return;
        ChannelExec channel=null;long start=SystemClock.elapsedRealtime();
        try{
            if(!current.isConnected())throw new EOFException("SSH transport closed");
            channel=(ChannelExec)current.openChannel("exec");channel.setCommand("true");channel.setInputStream(null);channel.setOutputStream(new ByteArrayOutputStream());channel.setErrStream(new ByteArrayOutputStream());channel.connect(1200);
            long deadline=SystemClock.elapsedRealtime()+1200;
            while(!channel.isClosed()&&SystemClock.elapsedRealtime()<deadline)Thread.sleep(30);
            if(!channel.isClosed())throw new SocketTimeoutException("SSH reply delayed");
            if(channel.getExitStatus()!=0)throw new IOException("SSH probe failed");
            if(gen==generation){sshHealth.success(SystemClock.elapsedRealtime(),SystemClock.elapsedRealtime()-start);sshState=sshHealth.state(SystemClock.elapsedRealtime()).equals("online")?"connected":"delayed";}
        }catch(Exception e){if(gen==generation){sshHealth.failure(SystemClock.elapsedRealtime(),!current.isConnected());sshState=sshHealth.state(SystemClock.elapsedRealtime()).equals("offline")?"disconnected":"delayed";}}
        finally{if(channel!=null)channel.disconnect();}
        if(gen==generation)emit("link_health",healthSnapshot());
    }
    private void connectSsh(JSONObject c,int gen){
        if(c.optString("password").isEmpty()){sshState="readonly";emit("link_health",healthSnapshot());notice("조회 연결 · 제어하려면 SSH 비밀번호를 입력하세요");return;}
        Session session=null;
        try{
            JSch j=new JSch();File known=new File(getFilesDir(),"known_hosts");if(!known.exists())known.createNewFile();j.setKnownHosts(known.getPath());
            session=j.getSession(c.optString("username","jetson"),c.getString("host"),c.optInt("ssh_port",22));
            session.setPassword(c.getString("password"));session.setConfig("StrictHostKeyChecking","ask");session.setTimeout(2500);
            session.setUserInfo(new UserInfo(){public String getPassphrase(){return null;}public String getPassword(){return null;}public boolean promptPassword(String m){return false;}public boolean promptPassphrase(String m){return false;}public void showMessage(String m){}
                public boolean promptYesNo(String message){CountDownLatch wait=new CountDownLatch(1);AtomicBoolean yes=new AtomicBoolean(false);
                    main.post(()->{if(isFinishing()||gen!=generation){wait.countDown();return;}new AlertDialog.Builder(MainActivity.this).setTitle("Jetson SSH 호스트 키").setMessage(message).setPositiveButton("확인 후 저장",(d,w)->{if(gen==generation)yes.set(true);wait.countDown();}).setNegativeButton("취소",(d,w)->wait.countDown()).setOnCancelListener(d->wait.countDown()).show();});
                    try{return wait.await(45,TimeUnit.SECONDS)&&yes.get()&&gen==generation;}catch(InterruptedException e){return false;}}
            });
            session.setServerAliveInterval(1500);session.setServerAliveCountMax(3);session.connect(5000);
            if(gen!=generation || !foreground){session.disconnect();return;}
            ssh=session;owned=true;sshHealth.success(SystemClock.elapsedRealtime(),0);sshState="connected";emit("link_health",healthSnapshot());notice("SSH 제어 연결 완료");
        }catch(Exception e){if(session!=null)session.disconnect();if(gen==generation){sshState="disconnected";sshHealth.failure(SystemClock.elapsedRealtime(),true);emit("link_health",healthSnapshot());notice("SSH 연결 실패 · ROS 상태 조회는 계속합니다");}}
        finally{c.remove("password");}
    }
    private boolean canMove()throws Exception {
        if(!owned || !sshState.equals("connected"))throw new IOException("SSH 제어 연결이 필요합니다");
        if(!BuildConfig.VERSION_NAME.equals(backendVersion))throw new IOException("Jetson v"+backendVersion+" · v"+BuildConfig.VERSION_NAME+" 배포 후 시작하세요");
        if(SystemClock.elapsedRealtime()-lastStatus>2000)throw new IOException("ROS 상태가 오래됐습니다");return true;
    }
    private void perform(String id,String action,JSONObject args,int gen){
        try{
            if(gen!=generation)throw new IOException("이전 연결의 명령은 취소됐습니다");
            GatewayClient g=gateway;if(g==null||!connected)throw new IOException("먼저 Jetson에 연결하세요");
            if(!allowed.contains(action))throw new IOException("지원하지 않는 명령");
            if(action.equals("nav_curve_slowdown")||action.equals("ground_start")||action.equals("ground_resume")||action.equals("set_mode")&&Arrays.asList("NAVIGATION","BALLOON","REMOTE","AUTO").contains(args.optString("mode")))canMove();
            JSONObject result=g.request(action,args,10000,6*1024*1024);if(action.equals("configure"))cacheProfile(args);result.put("id",id).put("action",action);emit("ack",result);
            if(action.equals("reset_estop"))poll.execute(this::pollStatus);
        }catch(Exception e){JSONObject failure=data("id",id);try{failure.put("success",false).put("error",e.getMessage());}catch(JSONException ignored){}emit("ack",failure);}
    }
    private void disconnect(boolean notify){
        GatewayClient g=gateway;boolean wasOwned=owned;connected=false;owned=false;remoteHeld=false;preview=false;generation++;sshState="disconnected";previewStore.clear();HttpURLConnection active=activeFrame;if(active!=null)active.disconnect();
        main.post(()->closeJsConfirm(false));
        Session old=ssh;ssh=null;if(old!=null)old.disconnect();
        if(g!=null && wasOwned)urgent.execute(()->{try{g.request("set_mode",data("mode","MANUAL"),1200,8192);}catch(Exception ignored){}try{g.request("operator_link",data("ssh_connected",false),700,4096);}catch(Exception ignored){}});
        if(notify)emit("disconnected",new JSONObject());
    }
    private void previewTick(){
        GatewayClient g=gateway;int gen=generation;long now=SystemClock.elapsedRealtime();
        JSONObject vision=latest.optJSONObject("telemetry");vision=vision==null?null:vision.optJSONObject("vision");
        if(!connected||!foreground||!preview||g==null||vision==null||!vision.optBoolean("enabled")||now<nextFrameAt||!frameBusy.compareAndSet(false,true))return;
        try{fetchFrame(g,gen);}finally{frameBusy.set(false);}
    }
    private void fetchFrame(GatewayClient g,int gen){HttpURLConnection conn=null;boolean reusable=false;long start=SystemClock.elapsedRealtime();
        try{
            String h=g.host.contains(":")?"["+g.host+"]":g.host;
            conn=(HttpURLConnection)new URL("http://"+h+":"+previewPort+"/frame.jpg").openConnection();activeFrame=conn;conn.setConnectTimeout(1000);conn.setReadTimeout(1500);conn.setUseCaches(false);
            if(!token.isEmpty())conn.setRequestProperty("X-RCBoat-Token",token);
            String previous=previewStore.etag();if(!previous.isEmpty())conn.setRequestProperty("If-None-Match",previous);
            int code=conn.getResponseCode();long duration=SystemClock.elapsedRealtime()-start;
            if(code==304){conn.getInputStream().close();reusable=true;if(gen==generation)emit("frame_health",data("state","waiting"));nextFrameAt=Math.max(start+60,SystemClock.elapsedRealtime()+15);return;}
            if(code!=200)throw new IOException(code==503?"새 카메라 영상 대기":"영상 HTTP "+code);
            String etag=conn.getHeaderField("ETag");double age=0;
            try{age=Double.parseDouble(conn.getHeaderField("X-Frame-Age"))*1000;}catch(Exception ignored){}
            if(!Double.isFinite(age)||age<0||age>2000)throw new IOException("Jetson 영상이 오래됐습니다");
            byte[] raw=readLimited(conn.getInputStream(),150000);
            reusable=true;
            if(gen!=generation||!preview||!foreground)return;
            if(previewStore.offer(raw,etag==null?"":etag,SystemClock.elapsedRealtime())){
                JSONObject packet=new JSONObject().put("url","https://appassets.androidplatform.net/preview.jpg?v="+gen+"_"+SystemClock.elapsedRealtime())
                    .put("source_age_ms",Math.round(age)).put("request_ms",duration).put("bytes",raw.length);
                emit("frame",packet);
            }
            nextFrameAt=start+60;
        }catch(Exception e){if(gen==generation&&preview){emit("frame_health",data("state","delayed"));nextFrameAt=SystemClock.elapsedRealtime()+1000;}}
        finally{if(conn!=null&&!reusable)conn.disconnect();activeFrame=null;}
    }
    private static byte[] readLimited(InputStream in,int limit)throws IOException{try(InputStream input=in;ByteArrayOutputStream out=new ByteArrayOutputStream()){byte[] b=new byte[16384];int n;while((n=input.read(b))!=-1){if(out.size()+n>limit)throw new IOException("파일 크기 제한 초과");out.write(b,0,n);}return out.toByteArray();}}
    private void saveFile(String filename,String mime,byte[] raw)throws Exception{
        if(!filename.matches("[\\p{L}\\p{N}_. -]{1,160}"))throw new IOException("잘못된 파일 이름");
        ContentValues values=new ContentValues();values.put(MediaStore.Downloads.DISPLAY_NAME,filename);values.put(MediaStore.Downloads.MIME_TYPE,mime);values.put(MediaStore.Downloads.RELATIVE_PATH,"Download/RCBoat");values.put(MediaStore.Downloads.IS_PENDING,1);
        Uri uri=getContentResolver().insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI,values);if(uri==null)throw new IOException("다운로드 저장 실패");
        try{try(OutputStream out=getContentResolver().openOutputStream(uri)){if(out==null)throw new IOException("파일 열기 실패");out.write(raw);}values.clear();values.put(MediaStore.Downloads.IS_PENDING,0);getContentResolver().update(uri,values,null,null);}
        catch(Exception e){getContentResolver().delete(uri,null,null);throw e;}
        notice("다운로드/RCBoat/"+filename+" 저장 완료");
    }
    public class AppBridge {
        @JavascriptInterface public void ready(){ready=true;JSONObject c=new JSONObject();android.content.SharedPreferences p=getPreferences(MODE_PRIVATE);try{c.put("host",p.getString("host","")).put("username",p.getString("username","jetson")).put("gateway_port",p.getInt("gateway_port",8765)).put("ssh_port",p.getInt("ssh_port",22)).put("version",BuildConfig.VERSION_NAME);}catch(Exception ignored){}emit("settings",c);emit("ntrip_profile",savedProfile());}
        @JavascriptInterface public void connect(String json){try{JSONObject c=obj(json);String host=c.getString("host").trim();int port=c.optInt("gateway_port",8765);GatewayClient next=new GatewayClient(host,port,c.optString("token"));MainActivity.this.disconnect(false);gateway=next;token=c.optString("token");connected=true;long now=SystemClock.elapsedRealtime();lastStatus=0;rosHealth.reset(now);sshHealth.reset(now);sshState=c.optString("password").isEmpty()?"readonly":"connecting";int gen=generation;c.put("host",host);
            getPreferences(MODE_PRIVATE).edit().putString("host",host).putString("username",c.optString("username","jetson")).putInt("gateway_port",port).putInt("ssh_port",c.optInt("ssh_port",22)).apply();
            health.execute(()->connectSsh(c,gen));notice("ROS gateway 연결 중");}catch(Exception e){notice(e.getMessage());}}
        @JavascriptInterface public void disconnect(){MainActivity.this.disconnect(true);}
        @JavascriptInterface public void command(String id,String action,String json){try{JSONObject args=obj(json);int gen=generation;(action.equals("estop")||action.equals("ground_stop")||action.equals("set_mode")&&Arrays.asList("MANUAL","AUTO_SAFE").contains(args.optString("mode"))?urgent:commands).execute(()->perform(id,action,args,gen));}catch(Exception e){notice(e.getMessage());}}
        @JavascriptInterface public void preview(boolean enabled){preview=enabled;nextFrameAt=0;if(!enabled){previewStore.clear();HttpURLConnection active=activeFrame;if(active!=null)active.disconnect();}}
        @JavascriptInterface public void remote(int steering,int throttle,boolean held){if(steering<4900||steering>7300||throttle<5800||throttle>7397)return;remoteSteering=steering;remoteThrottle=throttle;remoteAt=SystemClock.elapsedRealtime();remoteHeld=held;
            if(!held && gateway!=null && mode.equals("REMOTE"))urgent.execute(()->{try{gateway.request("set_remote_pwm",new JSONObject().put("steering_pwm",6000).put("throttle_pwm",6450),700,8192);}catch(Exception ignored){}});}
        @JavascriptInterface public void export(String filename,String mime,String text){commands.execute(()->{try{if(text.length()>4*1024*1024)throw new IOException("내보내기 크기 제한");saveFile(filename,mime,text.getBytes(java.nio.charset.StandardCharsets.UTF_8));}catch(Exception e){notice(e.getMessage());}});}
        @JavascriptInterface public void download(String action,String testId){if(!Arrays.asList("download_ground_test","download_vision_log").contains(action))return;commands.execute(()->{try{if(gateway==null)throw new IOException("연결 필요");JSONObject r=gateway.request(action,data("test_id",testId),30000,48*1024*1024).getJSONObject("response");byte[] raw=android.util.Base64.decode(r.getString("zip_base64"),android.util.Base64.DEFAULT);byte[] digest=MessageDigest.getInstance("SHA-256").digest(raw);StringBuilder hex=new StringBuilder();for(byte b:digest)hex.append(String.format(Locale.ROOT,"%02x",b&255));if(!hex.toString().equals(r.getString("sha256")))throw new IOException("ZIP 무결성 검증 실패");saveFile(r.getString("filename"),"application/zip",raw);}catch(Exception e){notice(e.getMessage());}});}
    }
    @Override protected void onResume(){super.onResume();foreground=true;}
    private void closeJsConfirm(boolean accept){
        JsResult result=pendingJsConfirm;pendingJsConfirm=null;
        AlertDialog dialog=jsConfirmDialog;jsConfirmDialog=null;if(dialog!=null)dialog.dismiss();
        if(result!=null){if(accept&&foreground&&confirmGeneration==generation&&!isFinishing())result.confirm();else result.cancel();}
    }
    @Override protected void onPause(){foreground=false;closeJsConfirm(false);disconnect(true);super.onPause();}
    @Override protected void onDestroy(){closeJsConfirm(false);disconnect(false);poll.shutdownNow();lease.shutdownNow();health.shutdownNow();commands.shutdownNow();frames.shutdownNow();urgent.shutdown();if(web!=null){web.removeJavascriptInterface("Boat");web.destroy();web=null;}super.onDestroy();}
}
