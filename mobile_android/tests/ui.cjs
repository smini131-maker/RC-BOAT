// Responsive UI and command-contract tests; synthetic data, never a boat connection.
const {chromium}=require('playwright');
const http=require('http'),fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const assets=path.resolve(__dirname,'../app/src/main/assets'),out=path.resolve(__dirname,'../../output/mobile-qa');fs.mkdirSync(out,{recursive:true});
const server=http.createServer((req,res)=>{const file=path.join(assets,decodeURIComponent(req.url.split('?')[0]));if(!file.startsWith(assets+path.sep)){res.writeHead(403).end();return;}fs.readFile(file,(err,data)=>{if(err){res.writeHead(404).end();return;}res.setHeader('Content-Type',file.endsWith('.css')?'text/css':file.endsWith('.js')?'text/javascript':'text/html');res.end(data);});});
const fixture={success:true,version:'2.4.9',master_online:true,gateway_online:true,mobile:{ssh:'connected',control:true},gps_settings:{navigation_max_hdop:3},ground_tests:[{id:'ground_test_20261104_120000',complete:true}],telemetry:{gps:{fix:true,healthy:true,data_validity:'valid',latitude:35.0752,longitude:129.0869,utm_easting_m:507920,utm_northing_m:3881385,utm_zone:'52N',satellites:17,hdop:.7,hacc_m:.05,cno_dbhz:37,speed_mps:.83,rtk_state:'RTK_FIXED',gps_data_age_s:.25,receiver_correction_age_status:'unsupported'},ntrip:{enabled:true,connected:true,host:'caster.example.invalid',port:2101,mountpoint:'TEST',credentials_saved:true,username:'fixture-user',correction_age_source:'JETSON_RTCM3_CRC_RECEPTION',last_correction_age_s:.4},navigation:{fresh:true,auto_cruise_pwm:6650,cruise_applied_monotonic:100,ramp_throttle_pwm:6650},safety:{mode:'AUTO_SAFE',armed:false,estop:false,actuator_locked:true},actuator:{actual_steering_pwm:6000,actual_throttle_pwm:6450},route:{selected_route_id:'c',selected_multipath_id:'a',active_route_id:'c',multipath:{enabled:true,endpoint_tolerance_m:.75},group_routes:['c','r'],recording:{active:false,point_count:0},routes:[{id:'c',name:'해수천 C',waypoints:[{lat:35.0752,lon:129.0869,waypoint_number:1},{lat:35.0753,lon:129.087,waypoint_number:2}]},{id:'r',name:'해수천 R',waypoints:[{lat:35.07519,lon:129.08691,waypoint_number:1},{lat:35.07529,lon:129.08701,waypoint_number:2}]}],multipaths:[{id:'a',name:'해수천 대루트 A',route_ids:['c','r']}]},vision:{enabled:false,configuration:{camera_type:'csi',camera_source:'/dev/video0',csi_sensor_id:0}},ground_test:{state:'idle',active:false,samples:0}}};
(async()=>{await new Promise(r=>server.listen(0,'127.0.0.1',r));let browser;try{
try{browser=await chromium.launch({channel:'chrome',headless:true});}catch{browser=await chromium.launch({headless:true});}const errors=[];
for(const [name,width,height]of[['phone-small',360,800],['phone',412,915],['tablet-portrait',800,1280],['tablet-s9plus',1400,876]]){
 const context=await browser.newContext({viewport:{width,height},deviceScaleFactor:1});const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
 await page.route('https://tile.openstreetmap.org/**',r=>r.abort());
 await page.addInitScript(()=>{window.calls=[];window.Boat={ready(){},connect(c){window.previewRequested=false;window.calls.push(['connect',JSON.parse(c)]);},disconnect(){window.previewRequested=false;window.onNative('disconnected',{});},preview(enabled){window.previewRequested=enabled;},remote(...a){window.remoteCalls??=[];window.remoteCalls.push(a);},download(a,id){window.calls.push([a,{test_id:id}]);},export(n,m,t){window.calls.push(['export',{name:n,text:t}]);},command(id,action,args){window.calls.push([action,JSON.parse(args)]);setTimeout(()=>window.onNative('ack',{id,success:true,response:{cruise_applied_monotonic:120}}),1);}};});
 await page.goto(`http://127.0.0.1:${server.address().port}/index.html`);await page.evaluate(()=>window.onNative('ntrip_profile',{host:'saved.example.invalid',port:2101,mountpoint:'SAVED',username:'saved-user',tls:false}));assert.equal(await page.locator('#nUser').inputValue(),'saved-user');assert.equal(await page.locator('#nHost').inputValue(),'saved.example.invalid');await page.evaluate(s=>window.onNative('status',s),fixture);assert.equal(await page.locator('#nUser').inputValue(),'fixture-user');
 for(const tab of ['sail','routes','camera','gps','more']){await page.locator(`[data-page="${tab}"]`).click();await page.waitForTimeout(30);assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth),false,`${name}/${tab}: horizontal clipping`);assert.equal(await page.locator('#estop').isVisible(),true);assert.equal(await page.locator('#manualAlways').isVisible(),true);assert.equal(await page.locator('#openMode').isVisible(),true);if(tab==='sail'){assert.equal(await page.locator('#startNav').isEnabled(),true);const box=await page.locator('#startNav').boundingBox();assert.ok(box.y+box.height<height-140,`${name}: start button must remain above safety controls`);await page.screenshot({path:path.join(out,`${name}-sail.png`),fullPage:true});}}
 // Dense recorded points keep their full geometry while number badges avoid overlap.
 await page.locator('[data-page="sail"]').click();
 const denseMap=structuredClone(fixture);
 denseMap.telemetry.route.routes[0].waypoints=Array.from({length:65},(_,i)=>({lat:35.0752+i*.000002,lon:129.0869+i*.000002,waypoint_number:i+1}));
 await page.evaluate(s=>window.onNative('status',s),denseMap);await page.waitForTimeout(350);
 assert.equal(await page.evaluate(()=>routeLayer.getLayers().find(l=>l instanceof L.Polyline).getLatLngs().length),65,'recorded coordinates must not be decimated');
 assert.equal(await page.evaluate(()=>{const pixels=routeLayer.getLayers().filter(l=>l instanceof L.Marker).map(l=>map.latLngToContainerPoint(l.getLatLng()));return pixels.length>0&&pixels.length<30&&pixels.every((p,i)=>pixels.slice(i+1).every(q=>p.distanceTo(q)>=31.9));}),true,'waypoint badges must leave the path readable');
 await page.evaluate(()=>map.setZoom(16,{animate:false}));await page.waitForTimeout(100);
 assert.equal(await page.evaluate(()=>routeLayer.getLayers().find(l=>l instanceof L.Polyline).getLatLngs().length),65);
 await page.evaluate(s=>window.onNative('status',s),fixture);
 // GPS may arrive before stored routes; later route data must still refit the map.
 await page.locator('[data-page="sail"]').click();
 const mapFixture=structuredClone(fixture),emptyMap=structuredClone(fixture);
 emptyMap.telemetry.route={routes:[],multipaths:[]};emptyMap.telemetry.gps.latitude=36;emptyMap.telemetry.gps.longitude=128;
 await page.evaluate(s=>{mapFitted=false;mapFocusSignature='';window.onNative('status',s);},emptyMap);
 mapFixture.telemetry.route.routes.push({id:'far',name:'먼 장소',waypoints:[{lat:37.5,lon:127,waypoint_number:11},{lat:37.5002,lon:127.0002,waypoint_number:12}]});
 await page.evaluate(s=>window.onNative('status',s),mapFixture);await page.waitForTimeout(300);
 assert.equal(await page.evaluate(()=>Math.abs(map.getCenter().lat-35.07525)<.001),true,'selected routes must be visible even after earlier GPS fit');
 assert.equal(await page.evaluate(()=>routeLayer.getLayers().filter(layer=>layer instanceof L.Polyline).length),3,'all saved paths remain available');
 await page.locator('#singleTarget').click();await page.locator('#missionTarget').selectOption('far');await page.waitForTimeout(300);
 assert.equal(await page.evaluate(()=>Math.abs(map.getCenter().lat-37.5001)<.001),true,'route selection immediately focuses its path');
 await page.locator('#multiTarget').click();await page.waitForTimeout(300);
 await page.evaluate(()=>map.panTo([35.076,129.088],{animate:false}));
 mapFixture.telemetry.route.active_route_id='r';await page.evaluate(s=>window.onNative('status',s),mapFixture);
 assert.equal(await page.evaluate(()=>Math.abs(map.getCenter().lat-35.076)<.0001),true,'active child changes must not reset user pan');
 await page.locator('#fitMap').click();await page.waitForTimeout(300);assert.equal(await page.evaluate(()=>map.getBounds().contains([37.5,127])),true,'all-routes fit is retained');
 await page.evaluate(s=>{state.targetDirty=false;window.onNative('status',s);},fixture);
 await page.locator('[data-page="camera"]').click();await page.locator('#camera details summary').click();
 await page.locator('#cameraResolution').selectOption('1280x720');await page.locator('#longRange').uncheck();
 let cameraState=structuredClone(fixture);cameraState.telemetry.vision.configuration={camera_type:'csi',camera_source:'/dev/video0',csi_sensor_id:0,width:1920,height:1080,long_range_enabled:true};await page.evaluate(s=>window.onNative('status',s),cameraState);
 assert.equal(await page.locator('#cameraResolution').inputValue(),'1280x720');assert.equal(await page.locator('#longRange').isChecked(),false);
 await page.locator('#saveCamera').click();await page.waitForTimeout(20);const savedCamera=await page.evaluate(()=>window.calls.find(c=>c[0]==='vision_configure')[1]);assert.equal(savedCamera.width,1280);assert.equal(savedCamera.height,720);assert.equal(savedCamera.long_range_enabled,false);
 // Delayed SSH/ROS stays separate from a fresh video stream; hidden panels do not rebuild.
 assert.equal(await page.locator('#previewToggle').isChecked(),true);
 assert.equal(await page.evaluate(()=>window.previewRequested),true);
 cameraState.telemetry.vision.enabled=true;await page.evaluate(s=>window.onNative('status',s),cameraState);
 await page.evaluate(()=>window.Boat.disconnect());
 assert.equal(await page.evaluate(()=>window.previewRequested),false);
 await page.evaluate(s=>window.onNative('status',s),cameraState);
 assert.equal(await page.evaluate(()=>window.previewRequested),true,'reconnect on camera tab must resume preview');
 await page.locator('#previewToggle').uncheck();
 await page.evaluate(()=>window.Boat.disconnect());
 await page.evaluate(s=>window.onNative('status',s),cameraState);
 assert.equal(await page.evaluate(()=>window.previewRequested),false,'reconnect must respect an explicitly disabled preview');
 await page.locator('#previewToggle').check();
 await page.route('https://appassets.androidplatform.net/preview.jpg**',route=>route.fulfill({contentType:'image/png',body:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jO1sAAAAASUVORK5CYII=','base64')}));
 await page.evaluate(()=>{window.savedGpsNode=document.getElementById('gpsMetrics').firstChild;window.onNative('frame',{url:'https://appassets.androidplatform.net/preview.jpg?v=1_1',source_age_ms:20});window.onNative('link_health',{ssh:'delayed',ros:'online',control:true,ros_rtt_ms:90});});
 assert.match(await page.locator('#sshHealth').innerText(),/응답 지연/);assert.match(await page.locator('#rosHealth').innerText(),/정상/);assert.equal(await page.locator('#frame').isVisible(),true);
 await page.evaluate(()=>{state.last=Date.now()-3000;window.onNative('link_health',{ssh:'connected',ros:'delayed',control:true});window.onNative('frame',{url:'https://appassets.androidplatform.net/preview.jpg?v=1_2',source_age_ms:20});});await page.waitForTimeout(550);
 assert.match(await page.locator('#rosHealth').innerText(),/응답 지연/);assert.equal(await page.locator('#frame').isVisible(),true,'ROS delay must not blank a fresh camera frame');
 for(let i=0;i<3;i++)await page.evaluate(s=>window.onNative('status',s),cameraState);
 assert.equal(await page.evaluate(()=>window.savedGpsNode===document.getElementById('gpsMetrics').firstChild),true,'hidden GPS cards must not rebuild on camera updates');
 await page.evaluate(()=>window.onNative('frame',{url:'https://appassets.androidplatform.net/preview.jpg?v=1_3',source_age_ms:4500}));assert.equal(await page.locator('#liveBadge').isVisible(),false,'old frame must not claim LIVE');
 const cameraSession=structuredClone(fixture);
 Object.assign(cameraSession.telemetry.safety,{mode:'MANUAL',mode_since_monotonic:100});
 Object.assign(cameraSession.telemetry.vision,{enabled:true,live_source:true,camera_online:false,model_ready:true,
  tracking_session:99,target:{phase:'TURN_BACK',acquired:true,predicted:true}});
 const showCameraSession=()=>page.evaluate(s=>window.onNative('status',s),cameraSession);
 await showCameraSession();
 assert.equal(await page.locator('#targetPhase').innerText(),'감지 대기');
 page.once('dialog',dialog=>dialog.accept());
 await page.locator('#trackStart').click();
 assert.equal(await page.evaluate(()=>window.calls.some(c=>c[0]==='set_mode'&&c[1].mode==='BALLOON')),false);
 cameraSession.telemetry.vision.camera_online=true;
 await showCameraSession();
 assert.deepEqual(await page.evaluate(()=>window.calls.at(-1)),
  ['set_mode',{mode:'BALLOON',armed:true,expected_mode_since_monotonic:100}]);
 Object.assign(cameraSession.telemetry.safety,{mode:'BALLOON',armed:true,mode_since_monotonic:101});
 await showCameraSession();
 assert.equal(await page.locator('#targetPhase').innerText(),'감지 대기');
 cameraSession.telemetry.vision.tracking_session=101;
 await showCameraSession();
 assert.match(await page.locator('#targetPhase').innerText(),/되돌아가기/);
 cameraSession.telemetry.safety.reason='BALLOON_CAMERA_DELAY';
 await showCameraSession();
 assert.match(await page.locator('#trackingStatus').innerText(),/카메라 응답 대기/);
 Object.assign(cameraSession.telemetry.safety,{mode:'MANUAL',armed:false,mode_since_monotonic:102,reason:''});
 await showCameraSession();
 assert.equal(await page.locator('#targetPhase').innerText(),'감지 대기');
 cameraSession.telemetry.vision.enabled=false;
 await showCameraSession();
 assert.equal(await page.locator('#trackingStatus').innerText(),'카메라 꺼짐');
 await page.evaluate(s=>window.onNative('status',s),fixture);
 await page.locator('[data-page="sail"]').click();await page.locator('#pwmNumber').fill('6900');await page.locator('#applyPwm').click();await page.waitForTimeout(30);assert.equal((await page.evaluate(()=>window.calls.find(c=>c[0]==='set_auto_cruise_pwm')))[1].value,6900);
 let update=structuredClone(fixture);update.telemetry.navigation.auto_cruise_pwm=6900;update.telemetry.navigation.cruise_applied_monotonic=120;await page.evaluate(s=>window.onNative('status',s),update);assert.match(await page.locator('#pwmStatus').innerText(),/적용 확인/);
 await page.locator('#pwmNumber').fill('6800');await page.evaluate(s=>window.onNative('status',s),update);assert.equal(await page.locator('#pwmNumber').inputValue(),'6800');
 await page.locator('#pwmNumber').fill('7397');await page.locator('#pwmPlus').click();assert.equal(await page.locator('#pwmNumber').inputValue(),'7397');await page.locator('#pwmMinus').click();assert.equal(await page.locator('#pwmNumber').inputValue(),'7390');
 await page.locator('[data-page="routes"]').click();for(const [n,enabled]of[[1,false],[2,true]]){update.telemetry.route.recording={active:true,point_count:n,gps_ready:true};await page.evaluate(s=>window.onNative('status',s),update);assert.equal(await page.locator('#recordStop').isEnabled(),enabled);}
 await page.locator('[data-page="gps"]').click();assert.match(await page.locator('#gpsMetrics').innerText(),/unsupported/);await page.locator('#ntripDetails summary').click();await page.locator('#nHost').fill('edited.example.invalid');await page.evaluate(s=>window.onNative('status',s),update);assert.equal(await page.locator('#nHost').inputValue(),'edited.example.invalid');await page.locator('#ntripSave').click();await page.waitForTimeout(20);assert.equal(await page.evaluate(()=>Object.hasOwn(window.calls.find(c=>c[0]==='configure')[1],'password')),false,'blank password must preserve Jetson credential');
 await page.locator('[data-page="more"]').click();await page.locator('#remoteDetails summary').click();update.telemetry.safety.mode='REMOTE';await page.evaluate(s=>window.onNative('status',s),update);await page.locator('#joystick').evaluate(e=>e.scrollIntoView({block:'center'}));await page.waitForTimeout(30);const stick=await page.locator('#joystick').boundingBox(),cx=stick.x+stick.width/2,cy=stick.y+stick.height/2;await page.mouse.move(cx,cy);await page.mouse.down();await page.mouse.move(cx,cy-stick.width*.34);await page.waitForTimeout(20);const debug=await page.evaluate(()=>({rect:document.getElementById('joystick').getBoundingClientRect().toJSON(),remote:window.remoteCalls.slice(-5),message:document.getElementById('toast').textContent}));assert.equal(await page.evaluate(()=>window.remoteCalls.at(-1)[1]),7397,JSON.stringify(debug));await page.mouse.up();assert.deepEqual(await page.evaluate(()=>window.remoteCalls.at(-1)),[6000,6450,false]);
 await page.mouse.move(cx,cy);await page.mouse.down();await page.mouse.move(cx+stick.width*.34,cy);assert.equal(await page.evaluate(()=>window.remoteCalls.at(-1)[0]),7300);await page.mouse.up();
 for(const [dx,dy,expected]of[[-.34,0,[4900,6450]],[0,.34,[6000,5800]]]){await page.mouse.move(cx,cy);await page.mouse.down();await page.mouse.move(cx+stick.width*dx,cy+stick.height*dy);assert.deepEqual(await page.evaluate(()=>window.remoteCalls.at(-1).slice(0,2)),expected);await page.locator('#joystick').dispatchEvent('pointercancel',{pointerId:1});assert.deepEqual(await page.evaluate(()=>window.remoteCalls.at(-1)),[6000,6450,false]);await page.mouse.up();}
 await page.locator('#manualAlways').click();await page.waitForTimeout(20);assert.deepEqual(await page.evaluate(()=>window.calls.at(-1)),['set_mode',{mode:'MANUAL'}]);await page.locator('#openMode').click();await page.locator('#modeSelect').selectOption('AUTO_SAFE');await page.locator('#applyMode').click();await page.waitForTimeout(20);assert.deepEqual(await page.evaluate(()=>window.calls.at(-1)),['set_mode',{mode:'AUTO_SAFE'}]);
 update.telemetry.safety={mode:'MANUAL',estop:true,actuator_locked:true,estop_reason:'MAINTENANCE_CHECK',estop_time_utc:'2026-11-10T10:00:00Z'};
 await page.evaluate(s=>window.onNative('status',s),update);assert.equal(await page.locator('#currentMode').innerText(),'비상정지');
 for(const tab of ['sail','routes','camera','gps','more']){await page.locator(`[data-page="${tab}"]`).click();assert.equal(await page.locator('#estopBanner').isVisible(),true);assert.match(await page.locator('#estopDetail').innerText(),/점검 중.*19:00:00 KST/);assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth),false,`${name}/${tab}: estop clipping`);}
 await page.locator('[data-page="sail"]').click();assert.equal(await page.locator('#startNav').isEnabled(),false);
 const resetsBefore=await page.evaluate(()=>window.calls.filter(c=>c[0]==='reset_estop').length);
 page.once('dialog',dialog=>dialog.dismiss());await page.locator('#bannerResetEstop').click();await page.waitForTimeout(20);
 assert.equal(await page.evaluate(()=>window.calls.filter(c=>c[0]==='reset_estop').length),resetsBefore,'cancel must not send reset');
 page.once('dialog',dialog=>dialog.accept());await page.locator('#bannerResetEstop').click();await page.waitForTimeout(20);
 assert.equal(await page.evaluate(()=>window.calls.filter(c=>c[0]==='reset_estop').length),resetsBefore+1,'accepted reset must reach native bridge');
 await page.evaluate(()=>window.onNative('link_health',{ssh:'readonly',control:false,ros:'online'}));
 await page.locator('#bannerResetEstop').click();assert.equal(await page.locator('#connectionDialog').isVisible(),true);
 assert.match(await page.locator('#toast').innerText(),/SSH 비밀번호/);
 assert.equal(await page.evaluate(()=>window.calls.filter(c=>c[0]==='reset_estop').length),resetsBefore+1,'readonly must request control connection');
 await page.locator('#closeConnect').click();await page.evaluate(s=>window.onNative('status',s),update);
 await page.screenshot({path:path.join(out,`${name}-estop.png`),fullPage:true});
 update.telemetry.safety.estop=false;await page.evaluate(s=>window.onNative('status',s),update);assert.equal(await page.locator('#estopBanner').isVisible(),false);assert.equal(await page.locator('#currentMode').innerText(),'수동');
 update.version='2.3.1';await page.evaluate(s=>window.onNative('status',s),update);await page.locator('[data-page="sail"]').click();assert.equal(await page.locator('#startNav').isEnabled(),false);await page.locator('#estop').click();await page.waitForTimeout(20);assert.equal(await page.evaluate(()=>window.calls.at(-1)[0]),'estop');
 await page.evaluate(()=>window.onNative('disconnected',{}));assert.equal(await page.locator('#startNav').isEnabled(),false);assert.match(await page.locator('#speed').innerText(),/stale/);await context.close();console.log(`PASS ${name}: layout, PWM ACK/dirty, recording, NTRIP preservation, stop/version/stale`);
}
assert.deepEqual(errors,[]);console.log('All mobile UI checks passed (synthetic backend; no hardware output).');
}finally{if(browser)await browser.close();server.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
