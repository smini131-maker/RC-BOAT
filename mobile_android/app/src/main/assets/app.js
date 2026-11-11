'use strict';
const $=id=>document.getElementById(id), VERSION='2.4.5';
const state={last:0,online:false,control:false,ssh:'disconnected',version:'',tele:{},ntripProfile:{},targetType:'multipath',routes:[],groups:[],targetDirty:false,pwmDirty:false,pwmPending:null,trackingStart:null,page:'sail',editor:null};
let sequence=0,toastTimer,routeSignature='',testSignature='',configSynced=false,frameAt=0,map,routeLayer,traceLine,boatMarker,fitBounds,lastCoords='',mapFitted=false,mapFocusSignature='';
const pending=new Map(),trace=[];
let healthState={},connectionSignature='',telemetryStale=false,videoState='waiting',frameTimes=[],mapOverlayTimer;
const fmt=(v,d=1,s='')=>typeof v==='number'&&Number.isFinite(v)?v.toFixed(d)+s:'no_data';
const set=(id,text,level)=>{const e=$(id);if(!e)return;if(e.textContent!==String(text))e.textContent=text;for(const c of ['good','bad','warn'])e.classList.toggle(c,c===level);};
const safetyReason=value=>({BALLOON_POP_ESTIMATED:'근접 풍선 소실 · 파열 추정 · 수동 전환',TARGET_ARRIVED:'목표 도착 · 수동 전환',SSH_DISCONNECTED:'SSH 단절 · 수동 전환',GUI_LINK_TIMEOUT:'관제 연결 만료 · 수동 전환',EMERGENCY_STOP:'비상정지 요청',ESTOP_CLEARED_NEUTRAL_REQUIRED:'비상정지 해제 · 스로틀 중립 확인 대기'})[value]||value;
const modeName=value=>({MANUAL:'수동',AUTO_SAFE:'자동 대기',AUTO:'자동 직진',NAVIGATION:'항로 주행',BALLOON:'풍선 추적',GROUND_TEST:'도보 테스트',REMOTE:'원격 조종'})[value]||value||'확인 전';
const elem=(tag,cls,text)=>{const e=document.createElement(tag);if(cls)e.className=cls;if(text!==undefined)e.textContent=text;return e;};
function eventLog(text){const line=elem('div');line.append(elem('time','',new Date().toLocaleTimeString('ko-KR',{hour12:false})),document.createTextNode(text));if(!$('events').firstElementChild)$('events').textContent='';$('events').prepend(line);while($('events').children.length>100)$('events').lastChild.remove();}
function toast(text){$('toast').textContent=text;$('toast').style.display='block';clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').style.display='none',4000);}
function message(text){toast(text);eventLog(text);}
function command(action,args={}){
 if(action==='estop'||action==='ground_start'||action==='ground_resume'||
    (action==='set_mode'&&args.mode!=='BALLOON')||(action==='vision_enable'&&args.enabled===false)){
  state.trackingStart=null;
 }
 return new Promise((resolve,reject)=>{if(!window.Boat){reject(new Error('Android 앱에서 실행하세요'));return;}const id=String(++sequence),timer=setTimeout(()=>{pending.delete(id);reject(new Error('명령 응답 지연 · 상태를 확인하세요'));},14000);pending.set(id,{resolve,reject,timer});Boat.command(id,action,JSON.stringify(args));});
}
async function run(action,args={},label='반영 완료'){try{const result=await command(action,args);message(label);return result;}catch(e){message(e.message);throw e;}}
function bind(id,fn){$(id).addEventListener('click',()=>Promise.resolve().then(fn).catch(()=>{}));}
function readyToMove(){return state.online&&Date.now()-state.last<2500&&state.control&&state.ssh==='connected'&&state.version===VERSION&&!state.tele.safety?.estop;}
function validatePwm(v){return Number.isInteger(v)&&v>=6480&&v<=7397&&(v===7397||(v-6480)%10===0);}
function indexPwm(i){return i===92?7397:6480+i*10;}
function editPwm(v){$('pwmNumber').value=v;$('pwmRange').value=v===7397?92:Math.max(0,Math.min(91,Math.round((v-6480)/10)));state.pwmDirty=true;set('pwmStatus','편집 중 · 적용을 눌러 반영','warn');}
function page(name){state.page=name;document.querySelectorAll('.page').forEach(e=>e.classList.toggle('active',e.id===name));document.querySelectorAll('nav button').forEach(e=>e.classList.toggle('active',e.dataset.page===name));window.scrollTo(0,0);if(window.Boat)Boat.preview(name==='camera'&&$('previewToggle').checked);if(name==='sail'){renderRoutes();updateMap();setTimeout(()=>map&&map.invalidateSize(),50);}if(name==='routes')renderRoutes();if(name==='gps')renderGps();if(name!=='camera')clearFrame();if(name!=='more')remoteRelease();}
document.querySelectorAll('nav button').forEach(b=>b.addEventListener('click',()=>page(b.dataset.page)));
function openConnect(){$('connectionDialog').showModal();}
bind('connectionBadge',openConnect);bind('openSettings',openConnect);bind('closeConnect',()=>$('connectionDialog').close());
$('connectForm').addEventListener('submit',e=>{e.preventDefault();const c={host:$('host').value.trim(),gateway_port:Number($('gatewayPort').value),ssh_port:Number($('sshPort').value),username:$('username').value.trim(),password:$('sshPassword').value,token:$('gatewayToken').value};if(!c.host||!c.username)return;configSynced=false;mapFitted=false;state.trackingStart=null;state.last=0;state.online=false;state.control=false;Boat.connect(JSON.stringify(c));$('sshPassword').value='';$('gatewayToken').value='';$('connectionDialog').close();set('connectionBadge','연결 중');});
bind('disconnect',()=>{Boat.disconnect();$('connectionDialog').close();});
bind('estop',()=>{remoteRelease();return run('estop',{origin:'mobile',reason:'OPERATOR_ESTOP'},'비상정지 요청 완료');});
async function manual(){remoteRelease();return run('set_mode',{mode:'MANUAL'},'수동 전환 완료');}
['manual','manualAlways','trackStop','remoteStop'].forEach(id=>bind(id,manual));
function resetEmergency(){
 if(!state.online||Date.now()-state.last>=2500){message('ROS 상태를 다시 연결한 뒤 해제하세요');return;}
 if(!state.control||state.ssh!=='connected'){message('해제하려면 SSH 비밀번호를 입력하고 제어 연결하세요');openConnect();return;}
 if(state.version!==VERSION){message('앱과 Jetson 버전을 맞춘 뒤 해제하세요');return;}
 if(confirm('비상정지 잠금을 해제할까요? 해제 후에는 수동 모드에서 스로틀 중립을 확인합니다. 추적·항로 주행은 별도로 시작해야 합니다.'))return run('reset_estop',{},'해제 요청 수락 · Jetson 상태 확인 중');
}
bind('resetEstop',resetEmergency);bind('bannerResetEstop',resetEmergency);
['pwmNumber','pwmRange'].forEach(id=>$(id).addEventListener('input',()=>editPwm(id==='pwmRange'?indexPwm(Number($(id).value)):Number($(id).value))));
bind('pwmMinus',()=>{let v=Number($('pwmNumber').value);editPwm(Math.max(6480,v===7397?7390:v-10));});bind('pwmPlus',()=>{let v=Number($('pwmNumber').value);editPwm(Math.min(7397,v===7390?7397:v+10));});
bind('applyPwm',async()=>{const value=Number($('pwmNumber').value);if(!validatePwm(value)){message('6480~7390은 10 간격, 최대값은 7397입니다');return;}$('applyPwm').disabled=true;try{const r=await run('set_auto_cruise_pwm',{value},'목표 PWM 전송 완료');state.pwmPending={value,stamp:(r.response||{}).cruise_applied_monotonic||0,at:Date.now()};set('pwmStatus','Jetson 적용 상태 재조회 중','warn');}finally{$('applyPwm').disabled=false;}});
function targetList(){return state.targetType==='multipath'?state.groups:state.routes;}
function target(){return targetList().find(r=>r.id===$('missionTarget').value);}
function updateTargets(force=false){const id=$('missionTarget').value,rows=targetList();$('missionTarget').replaceChildren();if(!rows.length){const o=elem('option','',!state.online?'Jetson 연결 후 항로 불러오기':!state.tele.route?'항로 불러오는 중':state.targetType==='multipath'?'저장된 대루트 없음 · 소루트 선택':'저장된 소루트 없음');o.value='';$('missionTarget').append(o);}for(const r of rows){const o=elem('option','',r.name||r.id);o.value=r.id;$('missionTarget').append(o);}const backendId=state.targetType==='multipath'?state.tele.route?.selected_multipath_id:state.tele.route?.selected_route_id;if(rows.some(r=>r.id===(force?backendId:id)))$('missionTarget').value=force?backendId:id;else if(rows.some(r=>r.id===backendId))$('missionTarget').value=backendId;set('groundTarget',target()?`${state.targetType==='multipath'?'대루트':'소루트'} · ${target().name}`:'선택 항로 없음');}
function targetType(type){state.targetType=type;state.targetDirty=true;$('multiTarget').classList.toggle('selected',type==='multipath');$('singleTarget').classList.toggle('selected',type==='single_route');updateTargets(true);updateMap();}
bind('multiTarget',()=>targetType('multipath'));bind('singleTarget',()=>targetType('single_route'));$('missionTarget').addEventListener('change',()=>{state.targetDirty=true;set('groundTarget',target()?`${state.targetType==='multipath'?'대루트':'소루트'} · ${target().name}`:'선택 항로 없음');updateMap();});
async function selectTarget(){const r=target();if(!r)throw new Error('먼저 항로를 선택하세요');await command(state.targetType==='multipath'?'select_multipath':'select_route',state.targetType==='multipath'?{multipath_id:r.id}:{route_id:r.id});await command('set_multipath',{enabled:state.targetType==='multipath',endpoint_tolerance_m:state.tele.route?.multipath?.endpoint_tolerance_m||.75});state.targetDirty=false;}
bind('startNav',async()=>{if(!confirm(`${target()?.name||'선택 항로'} 주행을 시작할까요? 실제 모터가 작동합니다.`))return;state.trackingStart=null;try{await selectTarget();await run('set_mode',{mode:'NAVIGATION',armed:true},'항로 주행 시작');}catch(e){message(e.message);}});
bind('recordStart',()=>run('record_start',{name:$('recordName').value.trim()||'모바일 항로'},'항로 기록 시작'));bind('recordStop',()=>run('record_stop',{},'항로 저장 완료'));bind('recordCancel',()=>{if(confirm('현재 항로 기록을 취소할까요?'))return run('record_cancel',{},'기록 취소');});
function editRoute(route){state.editor={type:'route',id:route?.id||''};set('editorTitle',route?'소루트 수정':'새 소루트');$('editName').value=route?.name||'';$('editPoints').value=(route?.waypoints||[]).map(p=>`${p.lat},${p.lon}`).join('\n');$('editRadius').value=route?.arrival_radius_m||3;$('routeEditor').hidden=false;$('groupEditor').hidden=true;$('deleteEditor').hidden=!route;$('editor').showModal();}
function editGroup(group){state.editor={type:'group',id:group?.id||''};set('editorTitle',group?'대루트 수정':'소루트 묶기');$('editName').value=group?.name||'';$('routeEditor').hidden=true;$('groupEditor').hidden=false;$('groupEditor').replaceChildren();for(const r of state.routes){const label=elem('label'),input=elem('input');input.type='checkbox';input.value=r.id;input.checked=(group?.route_ids||[]).includes(r.id);label.append(input,document.createTextNode(r.name||r.id));$('groupEditor').append(label);}$('deleteEditor').hidden=!group;$('editor').showModal();}
bind('newRoute',()=>editRoute());bind('newGroup',()=>editGroup());bind('closeEditor',()=>$('editor').close());
bind('saveEditor',async()=>{const name=$('editName').value.trim();if(!name){message('이름을 입력하세요');return;}const e=state.editor;try{if(e.type==='group'){const ids=[...$('groupEditor').querySelectorAll('input:checked')].map(x=>x.value);if(!ids.length)throw new Error('하나 이상 소루트를 선택하세요');await run('upsert_multipath',{multipath_id:e.id,name,route_ids:ids},'대루트 저장 완료');}else{const points=$('editPoints').value.trim().split(/\n+/).map((line,i)=>{const a=line.trim().split(/[,\s]+/).map(Number);if(a.length!==2||!a.every(Number.isFinite)||Math.abs(a[0])>90||Math.abs(a[1])>180)throw new Error(`${i+1}번째 좌표를 확인하세요`);return{lat:a[0],lon:a[1]};});if(points.length<2)throw new Error('2개 이상 좌표가 필요합니다');await run('upsert_route',{route_id:e.id,name,waypoints:points,arrival_radius_m:Number($('editRadius').value)},'소루트 저장 완료');}$('editor').close();}catch(e){message(e.message);}});
bind('deleteEditor',async()=>{const e=state.editor;if(!confirm('선택한 항로를 삭제할까요?'))return;await run(e.type==='group'?'delete_multipath':'delete_route',e.type==='group'?{multipath_id:e.id}:{route_id:e.id},'삭제 완료');$('editor').close();});
function csvCell(v){return '"'+String(v??'').replaceAll('"','""')+'"';}
bind('exportRoutes',()=>{const fields=['route_id','route_name','waypoint_number','latitude','longitude','utm_easting_m','utm_northing_m','utm_zone'];const lines=[fields.join(',')];for(const r of state.routes)for(const [i,p]of(r.waypoints||[]).entries())lines.push([r.id,r.name,p.waypoint_number??i+1,p.lat,p.lon,p.utm_easting_m,p.utm_northing_m,p.utm_zone].map(csvCell).join(','));Boat.export('reference_routes.csv','text/csv','\ufeff'+lines.join('\r\n'));Boat.export('reference_routes.json','application/json',JSON.stringify({routes:state.routes,multipaths:state.groups},null,2));});
bind('cameraOn',()=>run('vision_enable',{enabled:true},'카메라 켜기 요청'));bind('cameraOff',async()=>{state.trackingStart=null;if(state.tele.safety?.mode==='BALLOON')await manual();await run('vision_enable',{enabled:false},'카메라 끄기');});
bind('trackStart',async()=>{
 if(state.trackingStart||state.tele.safety?.mode==='BALLOON')return;
 if(!confirm('핑크 풍선을 향해 자동 접근합니다. 실제 모터가 작동합니다. 시작할까요?'))return;
 if(!readyToMove()){message('SSH 제어 연결과 같은 버전의 ROS backend가 필요합니다');return;}
 const request={deadline:Date.now()+30000,modeSince:state.tele.safety?.mode_since_monotonic,ready:false};
 state.trackingStart=request;
 motionAvailability();
 set('trackingStatus','카메라 준비 대기','warn');
 try{
  if(!state.tele.vision?.enabled)await run('vision_enable',{enabled:true},'카메라 시작');
  request.ready=true;
 }catch(error){
  if(state.trackingStart===request)state.trackingStart=null;
  motionAvailability();
  throw error;
 }
});
$('previewToggle').addEventListener('change',()=>{Boat.preview(state.page==='camera'&&$('previewToggle').checked);if(!$('previewToggle').checked)clearFrame();});
bind('saveCamera',()=>run('vision_configure',{camera_type:$('cameraType').value,camera_source:$('cameraSource').value,csi_sensor_id:Number($('sensorId').value),width:Number($('cameraResolution').value.split('x')[0]),height:Number($('cameraResolution').value.split('x')[1]),long_range_enabled:$('longRange').checked},'카메라 설정 저장'));bind('visionDownload',()=>{message('추적 로그 다운로드 중');Boat.download('download_vision_log','');});
bind('groundStart',async()=>{const t=target();if(!t){message('운항 화면에서 항로를 선택하세요');return;}if($('groundOutput').checked&&!confirm('도보 테스트 중 실제 조향·모터가 작동합니다. 시작할까요?'))return;await run('ground_start',{target_type:state.targetType,target_id:t.id,actuation_enabled:$('groundOutput').checked},'도보 테스트 시작');});bind('groundStop',()=>run('ground_stop',{},'도보 테스트 정지'));bind('groundResume',()=>run('ground_resume',{},'같은 로그에서 테스트 출력 재개'));
bind('downloadTest',()=>{message('테스트 ZIP 다운로드 중');Boat.download('download_ground_test',$('testSelect').value);});
bind('saveHdop',async()=>{await run('set_gps_settings',{navigation_max_hdop:Number($('hdopLimit').value)},'HDOP 진단 기준 저장');$('hdopLimit').dataset.dirty='';});
bind('ntripSave',async()=>{const args={enabled:true,host:$('nHost').value.trim(),port:Number($('nPort').value),mountpoint:$('nMount').value.trim(),tls:$('nTls').checked};if(!args.host||!args.mountpoint){message('Host와 Mount Point를 확인하세요');return;}if($('nUser').value.trim())args.username=$('nUser').value.trim();if($('nPassword').value)args.password=$('nPassword').value;await run('configure',args,'NTRIP 설정 저장 · 연결 요청');$('nPassword').value='';$('ntripDetails').dataset.dirty='';});bind('ntripOff',()=>run('configure',{enabled:false},'NTRIP 연결 해제'));bind('gpsLogStart',()=>run('gps_log_start',{},'GPS 원시 기록 시작'));bind('gpsLogStop',()=>run('gps_log_stop',{},'GPS 원시 기록 정지'));bind('clearEvents',()=>$('events').replaceChildren());
['cameraType','cameraSource','sensorId','cameraResolution','longRange'].forEach(id=>$(id).addEventListener('input',()=>$(id).dataset.dirty='1'));['nHost','nPort','nMount','nUser','nPassword','nTls'].forEach(id=>$(id).addEventListener('input',()=>$('ntripDetails').dataset.dirty='1'));$('hdopLimit').addEventListener('input',()=>$('hdopLimit').dataset.dirty='1');
bind('remoteMode',()=>run('set_mode',{mode:'REMOTE'},'원격 모드 전환 · 조이스틱을 누를 때만 출력'));$('remoteDetails').addEventListener('toggle',()=>{if($('remoteDetails').open)setTimeout(()=>$('remotePanel').scrollIntoView({block:'start'}),0);});
let holdTimer,stickPointer=null,stickSteer=6000,stickThrottle=6450;
function remoteRelease(){if(holdTimer){clearInterval(holdTimer);holdTimer=null;}stickPointer=null;stickSteer=6000;stickThrottle=6450;if(window.Boat)Boat.remote(6000,6450,false);$('joystickKnob').style.transform='translate(-50%,-50%)';$('joystick').classList.remove('held');set('remoteValues','조향 6000 · 스로틀 6450');}
function stickOutput(){Boat.remote(stickSteer,stickThrottle,true);}
function stickMove(e){if(e.pointerId!==stickPointer)return;const r=$('joystick').getBoundingClientRect(),radius=r.width*.34;let x=(e.clientX-r.left-r.width/2)/radius,y=(e.clientY-r.top-r.height/2)/radius;const length=Math.hypot(x,y);if(length>1){x/=length;y/=length;}const axis=v=>Math.abs(v)<=.08?0:Math.sign(v)*(Math.abs(v)-.08)/.92;const sx=axis(x),forward=axis(-y);stickSteer=Math.round(6000+sx*(sx<0?1100:1300));stickThrottle=Math.round(6450+forward*(forward<0?650:947));$('joystickKnob').style.transform=`translate(calc(-50% + ${x*radius}px),calc(-50% + ${y*radius}px))`;set('remoteValues',`조향 ${stickSteer} · 스로틀 ${stickThrottle}`);stickOutput();}
$('joystick').addEventListener('pointerdown',e=>{if(stickPointer!==null)return;if(state.tele.safety?.mode!=='REMOTE'||!readyToMove()){message('먼저 원격 제어 모드에 연결하세요');return;}e.preventDefault();stickPointer=e.pointerId;$('joystick').setPointerCapture(e.pointerId);$('joystick').classList.add('held');stickMove(e);holdTimer=setInterval(stickOutput,150);});$('joystick').addEventListener('pointermove',stickMove);['pointerup','pointercancel','lostpointercapture'].forEach(e=>$('joystick').addEventListener(e,remoteRelease));
bind('openMode',()=>{$('modeSelect').value=['MANUAL','AUTO_SAFE','AUTO','REMOTE','NAVIGATION','BALLOON','GROUND_TEST'].includes(state.tele.safety?.mode)?state.tele.safety.mode:'MANUAL';$('modeDialog').showModal();});bind('closeMode',()=>$('modeDialog').close());
bind('applyMode',async()=>{const mode=$('modeSelect').value;$('modeDialog').close();if(mode==='MANUAL'){await manual();return;}if(mode==='NAVIGATION'){page('sail');if(!target()){message('주행할 항로를 선택하세요');return;}$('startNav').click();return;}if(mode==='BALLOON'){page('camera');$('trackStart').click();return;}if(mode==='GROUND_TEST'){page('more');$('groundStart').click();return;}if(mode==='AUTO'&&!confirm('설정한 순항 PWM으로 자동 직진합니다. 실제 모터가 작동합니다. 시작할까요?'))return;await run('set_mode',{mode},mode==='AUTO_SAFE'?'안전 대기 전환':mode==='REMOTE'?'조이스틱 원격 모드 전환':'자동 직진 시작');if(mode==='REMOTE'){page('more');$('remoteDetails').open=true;$('remotePanel').scrollIntoView({block:'start'});}});
function initMap(){if(!window.L)return;$('map').replaceChildren();map=L.map('map',{zoomControl:false,attributionControl:true}).setView([35.0752,129.0869],18);L.control.zoom({position:'topright'}).addTo(map);L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'© OpenStreetMap',keepBuffer:1}).addTo(map);routeLayer=L.layerGroup().addTo(map);map.on('moveend',()=>{clearTimeout(mapOverlayTimer);mapOverlayTimer=setTimeout(()=>{routeSignature='';updateMap();},0);});traceLine=L.polyline([],{color:'#f4cf69',weight:3,opacity:.95}).addTo(map);bind('fitMap',()=>{if(fitBounds?.isValid())map.fitBounds(fitBounds,{padding:[30,30],maxZoom:19});else if(trace.length)map.setView(trace[trace.length-1],18);});}
function updateMap(){
if(!map)return;
const r=state.tele.route||{},choice=target();
const chosenIds=choice?(state.targetType==='multipath'?(choice.route_ids||[]):[choice.id]):(r.multipath?.enabled?(r.group_routes||[]):[r.selected_route_id]);
const selected=new Set(chosenIds),signature=JSON.stringify([state.routes,[...selected],r.active_route_id]);
if(signature!==routeSignature){
 routeSignature=signature;routeLayer.clearLayers();const all=[],focused=[],labelPositions=[],size=map.getSize();
 for(const item of state.routes){
  const valid=(item.waypoints||[]).filter(p=>Number.isFinite(p.lat)&&Math.abs(p.lat)<=90&&Number.isFinite(p.lon)&&Math.abs(p.lon)<=180);
  const points=valid.map(p=>[p.lat,p.lon]);all.push(...points);if(selected.has(item.id))focused.push(...points);
  const active=item.id===r.active_route_id,color=active?'#53dfbd':selected.has(item.id)?'#57b8eb':'#6c8293';
  L.polyline(points,{color,weight:active?5:3,opacity:(selected.has(item.id)||active)?0.95:0.5}).addTo(routeLayer);
  if(selected.has(item.id)||active)points.slice(0,300).forEach((p,i)=>{
   const pixel=map.latLngToContainerPoint(p);
   if(pixel.x<12||pixel.y<12||pixel.x>size.x-12||pixel.y>size.y-12||labelPositions.some(previous=>previous.distanceTo(pixel)<32))return;
   labelPositions.push(pixel);
   L.marker(p,{icon:L.divIcon({className:'wp-label',html:String(Number(valid[i].waypoint_number)||i+1),iconSize:[20,20],iconAnchor:[10,10]})}).addTo(routeLayer);
  });
 }
 fitBounds=all.length?L.latLngBounds(all):null;
 const focus=focused.length?focused:all,focusSignature=JSON.stringify([chosenIds,focus]);
 if(focus.length&&(!mapFitted||focusSignature!==mapFocusSignature)){
  map.invalidateSize(false);map.fitBounds(L.latLngBounds(focus),{padding:[35,35],maxZoom:19});mapFitted=true;mapFocusSignature=focusSignature;
 }
}
const g=state.tele.gps||{};if(g.fix&&Number.isFinite(g.latitude)&&Number.isFinite(g.longitude)){const p=[g.latitude,g.longitude],key=p.join(',');if(key!==lastCoords){lastCoords=key;trace.push(p);if(trace.length>2000)trace.shift();traceLine.setLatLngs(trace);}if(!boatMarker)boatMarker=L.circleMarker(p,{radius:8,color:'#c9fff0',weight:3,fillColor:'#24b88e',fillOpacity:1}).addTo(map);else boatMarker.setLatLng(p);boatMarker.setStyle({fillColor:g.healthy?'#24b88e':'#deae49'});if(!mapFitted&&!fitBounds){map.setView(p,18);mapFitted=true;}}}
function renderRoutes(){const r=state.tele.route||{},sig=JSON.stringify([state.routes,state.groups,r.selected_route_id,r.selected_multipath_id]);if(sig===renderRoutes.signature)return;renderRoutes.signature=sig;for(const [id,rows,type]of[['routeList',state.routes,'route'],['groupList',state.groups,'group']]){const box=$(id);box.replaceChildren();for(const row of rows){const line=elem('div','item'+((type==='route'?r.selected_route_id:r.selected_multipath_id)===row.id?' selected':'')),text=elem('div','item-name');text.append(elem('b','',row.name||row.id),elem('small','',type==='route'?`${row.waypoints?.length||0} waypoints`:`${row.route_ids?.length||0} 소루트`));const select=elem('button','secondary','선택'),edit=elem('button','','수정');select.addEventListener('click',()=>{targetType(type==='group'?'multipath':'single_route');$('missionTarget').value=row.id;page('sail');});edit.addEventListener('click',()=>type==='group'?editGroup(row):editRoute(row));line.append(text,select,edit);box.append(line);}if(!rows.length)box.append(elem('div','empty',!state.online?'Jetson 연결 후 항로 불러오기':!state.tele.route?'항로 불러오는 중':type==='group'?'저장된 대루트 없음':'저장된 소루트 없음'));}updateTargets(!state.targetDirty);}
function metric(name,value,range='',level='',long=false){const e=elem('div','metric'+(long?' long':''));e.append(elem('small','',name),elem('b',level,value));if(range)e.append(elem('span','range',range));return e;}
function renderGps(){const g=state.tele.gps||{},n=state.tele.ntrip||{};const low=(x,a,b)=>typeof x!=='number'?'':x<=a?'good':x<=b?'warn':'bad';const transport=n.correction_age_source==='JETSON_RTCM3_CRC_RECEPTION';$('gpsMetrics').replaceChildren(
metric('위치 FIX',g.data_validity||'no_data','',g.healthy?'good':g.fix?'warn':'bad'),metric('RTK 위치해',g.rtk_state||'no_data','',g.rtk_state==='RTK_FIXED'?'good':g.rtk_state==='RTK_FLOAT'?'warn':''),metric('실제 GNSS 속도',fmt(g.speed_mps,2,' m/s')),metric('GPS 데이터 지연',fmt(g.gps_data_age_s??g.age_s,2,' s'),'정상 ≤2 s',low(g.gps_data_age_s??g.age_s,2,5)),metric('HDOP',fmt(g.hdop,2),'좋음 ≤2 · 주의 ≤3',low(g.hdop,2,3)),metric('위성 수',fmt(g.satellites,0),'좋음 ≥8 · 주의 6~7',typeof g.satellites!=='number'?'':g.satellites>=8?'good':g.satellites>=6?'warn':'bad'),metric('수평 정확도',fmt(g.hacc_m,2,' m'),'좋음 ≤1.5 m · 주의 ≤3 m',low(g.hacc_m,1.5,3)),metric('평균 C/N0',fmt(g.cno_dbhz,1,' dB-Hz'),'좋음 ≥30 · 주의 ≥25',typeof g.cno_dbhz!=='number'?'':g.cno_dbhz>=30?'good':g.cno_dbhz>=25?'warn':'bad'),metric('보정 수신 후 경과',transport?fmt(n.last_correction_age_s??n.correction_age,2,' s'): 'unsupported','정상 ≤5 s · Jetson 수신 기준',transport?low(n.last_correction_age_s??n.correction_age,5,10):''),metric('수신기 보정 나이',g.receiver_correction_age_s==null?(g.receiver_correction_age_status||'unsupported'):fmt(g.receiver_correction_age_s,2,' s')),metric('위도 / 경도',`${fmt(g.latitude,7)} / ${fmt(g.longitude,7)}`,'WGS84','',true),metric('UTM',g.utm_easting_m==null||g.utm_northing_m==null?(g.utm_status||'no_data'):`${g.utm_zone||''} ${fmt(g.utm_easting_m,2)}, ${fmt(g.utm_northing_m,2)}`,'m','',true),metric('GPS UTC',g.measurement_time_utc||g.utc_time||'no_data','','',true),metric('GPS 진행 방향',fmt(g.heading_deg,1,'°'),g.heading_source||'unsupported'),metric('PDOP / VDOP',`${fmt(g.pdop,2)} / ${fmt(g.vdop,2)}`),metric('RTCM 누적 수신',fmt(n.bytes_received,0,' bytes')));
set('gnssState',g.data_validity||'no_data',g.healthy?'good':'bad');set('ntripState',n.connected?'연결됨':n.last_error?'연결 실패':n.enabled?'연결 대기':'비활성',n.connected?'good':n.last_error?'bad':'');if(n.host)set('ntripSummary',n.host?`${n.host}:${n.port} / ${n.mountpoint} · ${n.credentials_saved?'Jetson 자격정보 저장됨':'자격정보 미확인'}`:'Jetson 저장 설정 수신 대기');set('ntripError',n.last_error||'보정 연결과 RTK FIX는 서로 다른 상태입니다',n.last_error?'bad':'');
if(!$('ntripDetails').dataset.dirty){if(n.host!==undefined)$('nHost').value=n.host;if(n.port!==undefined)$('nPort').value=n.port;if(n.mountpoint!==undefined)$('nMount').value=n.mountpoint;if(n.username!==undefined)$('nUser').value=n.username;if(n.tls!==undefined)$('nTls').checked=n.tls;}
if(!$('hdopLimit').dataset.dirty&&state.latest?.gps_settings?.navigation_max_hdop!=null)$('hdopLimit').value=state.latest.gps_settings.navigation_max_hdop;
set('gpsLogState',state.tele.gps_logging?.active?`기록 중 · ${state.tele.gps_logging.samples} samples`:'기록 정지');}
function updateHealth(d={}){
healthState={...healthState,...d};if(d.ssh!==undefined)state.ssh=d.ssh;if(d.control!==undefined)state.control=!!d.control;
const ssh=state.ssh,ros=healthState.ros||(state.online?'online':'offline');
const names={connected:'정상',online:'정상',delayed:'응답 지연',offline:'연결 끊김',disconnected:'연결 끊김',connecting:'확인 중',readonly:'조회 전용'};
set('sshHealth','SSH '+(names[ssh]||'확인 중'),ssh==='connected'?'good':ssh==='delayed'||ssh==='connecting'?'warn':ssh==='readonly'?'':'bad');
set('rosHealth','ROS '+(names[ros]||'확인 중'),ros==='online'?'good':ros==='delayed'||ros==='connecting'?'warn':'bad');
set('linkAge',healthState.ros_rtt_ms>=0?`${healthState.ros_rtt_ms} ms`:'');
const delayed=ssh==='delayed'||ros==='delayed';set('connectionBadge',ros==='offline'?'ROS 끊김':delayed?'응답 지연':state.control?(ssh==='connected'?'제어 연결':'SSH 확인 중'):'상태 조회',delayed?'warn':ros==='offline'?'bad':'');$('connectionBadge').classList.toggle('online',ros==='online'&&!delayed);
if(ros==='offline')state.online=false;
const rows=[['SSH',names[ssh]||ssh],['ROS master',state.latest?.master_online?'online':'offline'],['ROS gateway',`${names[ros]||ros} · v${state.version}`],['Logger',state.tele.ground_test?.active?'recording':'idle'],['앱',`v${VERSION}`]],sig=JSON.stringify(rows);
if(sig!==connectionSignature){connectionSignature=sig;$('connections').replaceChildren(...rows.map(([label,value])=>{const div=elem('div');div.append(elem('span','',label),elem('b',/끊김|offline/.test(value)?'bad':/지연|확인/.test(value)?'warn':'good',value));return div;}));}
motionAvailability();
}
function motionAvailability(){
 const ground=state.tele.ground_test||{};
 document.querySelectorAll('.motion').forEach(b=>b.disabled=!readyToMove()||
  (b.id==='groundStart'&&ground.active)||(b.id==='groundResume'&&!ground.active)||
  (b.id==='trackStart'&&(state.trackingStart!==null||state.tele.safety?.mode==='BALLOON')));
}
function emergencyDisplay(safe){
set('currentMode',safe.estop?'비상정지':modeName(safe.mode),safe.estop?'bad':safe.armed?'good':'');$('openMode').setAttribute('aria-label','현재 상태 '+(safe.estop?'비상정지':modeName(safe.mode))+' · 모드 변경');
const active=safe.estop===true;$('estopBanner').hidden=!active;document.body.classList.toggle('estop-active',active);
$('estop').textContent=active?'■ 비상정지 ON':'■ 비상정지';
if(active){const reason=safe.estop_reason==='MAINTENANCE_CHECK'?'점검 중 출력 잠금':'조작자 비상정지 요청',at=safe.estop_time_utc?new Date(safe.estop_time_utc).toLocaleTimeString('en-GB',{hour12:false,timeZone:'Asia/Seoul'})+' KST':'시각 확인 전';set('estopDetail',`${reason} · ${at}`);set('trackingStatus','비상정지 잠금 · 해제 후 추적을 시작하세요','bad');}
$('bannerResetEstop').disabled=!state.online||state.version!==VERSION;
}
function markTelemetryStale(){if(telemetryStale)return;telemetryStale=true;$('bannerResetEstop').disabled=true;state.trackingStart=null;remoteRelease();set('currentMode','상태 지연','warn');set('modePill','상태 stale','warn');['gpsQuick','rtkQuick','lockQuick','speed','rampPwm','finalPwm'].forEach(id=>set(id,'stale','warn'));$('gpsMetrics').querySelectorAll('b').forEach(e=>{e.textContent='stale';e.className='warn';});motionAvailability();}
function videoHealth(){
if(!$('previewToggle').checked||state.page!=='camera'){set('videoState','미리보기 꺼짐');return;}
if(!state.tele.vision?.enabled){clearFrame();set('videoState','카메라 꺼짐');return;}
const age=frameAt?Date.now()-frameAt:Infinity;
if(age<1500){$('liveBadge').textContent='LIVE';$('liveBadge').classList.remove('warn');const elapsed=frameTimes.length>1?(frameTimes[frameTimes.length-1]-frameTimes[0])/1000:0;const fps=elapsed>0?(frameTimes.length-1)/elapsed:0;set('videoState',`미리보기 ${fps.toFixed(1)} fps · ${(age/1000).toFixed(1)} s`,'good');}
else if(age<4000){$('liveBadge').textContent='영상 지연';$('liveBadge').classList.add('warn');set('videoState',`영상 응답 지연 · ${(age/1000).toFixed(1)} s`,'warn');}
else{clearFrame();$('framePlaceholder').textContent=videoState==='delayed'?'영상 응답 지연 · 다시 수신 중':'새 영상 수신 대기';set('videoState','영상 수신 대기','warn');}
}
function balloonSession(safety){
 return safety.mode==='BALLOON'&&safety.armed&&!safety.estop?safety.mode_since_monotonic??null:null;
}

function renderBalloon(safety,vision,session){
 const active=session!==null;
 const target=active&&vision.tracking_session===session?vision.target||{}:{};
 const delay=active&&safety.reason==='BALLOON_CAMERA_DELAY';
 const phaseLabels={TRACKING:'실시간 추적',ACQUIRING:'감지 확인',PREDICTING:'위치 예측',
  TURN_BACK:'되돌아가기',POSITION_REACQUIRE:'추정 위치 접근',SEARCHING:'예측 추적',
  POP_PENDING:'근접 풍선 소실 확인',POP_ESTIMATED:'파열 추정'};
 const phase=delay?'카메라 응답 대기':phaseLabels[target.phase]||'감지 대기';
 set('visionState',delay?'카메라 응답 지연':vision.camera_online?'실시간 영상':
  vision.error?'카메라 오류':vision.enabled?'영상 대기':'카메라 꺼짐',delay?'warn':vision.camera_online?'good':vision.error?'bad':'');
 set('targetPhase',phase,target.phase==='TRACKING'&&!delay?'good':'warn');

 const request=state.trackingStart;
 if(request&&(!readyToMove()||Date.now()>request.deadline||request.modeSince!==safety.mode_since_monotonic)){
  state.trackingStart=null;
 }
 if(state.trackingStart&&request.ready&&vision.enabled&&vision.live_source&&vision.model_ready&&vision.camera_online){
  state.trackingStart=null;
  run('set_mode',{mode:'BALLOON',armed:true,expected_mode_since_monotonic:request.modeSince},'풍선 감지 시작').catch(()=>{});
 }
 let label=vision.enabled?phase:'카메라 꺼짐';
 if(state.trackingStart)label='카메라 준비 대기';
 if(delay)label='카메라 응답 대기 · 출력 정지';
 else if(active&&target.phase==='POP_PENDING')label='근접 풍선 소실 확인 중 · 정지';
 if(safety.estop)label='비상정지 잠금 · 해제 후 추적을 시작하세요';
 set('trackingStatus',label,safety.estop?'bad':phase==='실시간 추적'?'good':'warn');
}

function render(s){
const previousSafety=state.tele.safety||{};
const previousCameraEnabled=state.tele.vision?.enabled;
state.last=Date.now();state.online=true;telemetryStale=false;state.latest=s;state.tele=s.telemetry||{};state.version=s.version||'';state.control=!!s.mobile?.control;state.ssh=s.mobile?.ssh||'disconnected';state.routes=state.tele.route?.routes||[];state.groups=state.tele.route?.multipaths||[];const g=state.tele.gps||{},safe=state.tele.safety||{},nav=state.tele.navigation||{},act=state.tele.actuator||{},ground=state.tele.ground_test||{},record=state.tele.route?.recording||{},vision=state.tele.vision||{};
const session=balloonSession(safe);
if(session!==balloonSession(previousSafety)||previousCameraEnabled!==vision.enabled)clearFrame();
emergencyDisplay(safe);
updateHealth({...s.mobile,ros:s.mobile?.ros||'online'});const publicNtrip=state.tele.ntrip||{};if(!$('ntripDetails').dataset.dirty){for(const [id,key]of[['nHost','host'],['nPort','port'],['nMount','mountpoint'],['nUser','username']])if(publicNtrip[key]!==undefined&&$(id).value!==String(publicNtrip[key]))$(id).value=publicNtrip[key];if(publicNtrip.tls!==undefined)$('nTls').checked=publicNtrip.tls;}
set('modePill',modeName(safe.mode),safe.estop?'bad':safe.armed?'good':'');set('speed',fmt(g.speed_mps,2)+' m/s');set('gpsQuick',g.data_validity||'no_data',g.healthy?'good':'bad');set('rtkQuick',g.rtk_state||'no_data',g.rtk_state==='RTK_FIXED'?'good':'warn');set('lockQuick',safe.actuator_locked?'잠금':'출력 허용',safe.actuator_locked?'warn':'good');set('rampPwm',fmt(nav.ramp_throttle_pwm,0));set('finalPwm',fmt(act.actual_throttle_pwm,0));set('failsafe',safetyReason(safe.failsafe_reason||safe.reason)||'안전 전환 사유 없음',safe.failsafe_reason||safe.reason?'warn':'');set('safetyText',safe.estop?'비상정지 잠금':`${safe.actuator_locked?'출력 잠금':'출력 허용'} · ${fmt(act.actual_steering_pwm,0)} / ${fmt(act.actual_throttle_pwm,0)}`,safe.estop?'bad':'');
set('coords',g.latitude==null?'좌표 no_data':`${fmt(g.latitude,6)}, ${fmt(g.longitude,6)}`);const active=state.routes.find(r=>r.id===state.tele.route?.active_route_id);set('activeRoute',active?.name||'—');set('missionStatus',state.version!==VERSION?`Jetson v${state.version} · v${VERSION} 배포 필요`:!state.control?'조회 전용 · 제어하려면 SSH 연결 필요':`WP ${state.tele.route?.target_waypoint_index??'—'} · 항로 거리 ${fmt(state.tele.route?.distance_to_route_m,2,' m')}`,state.version!==VERSION?'bad':'');
if(state.pwmPending){const p=state.pwmPending;if(nav.auto_cruise_pwm===p.value&&nav.cruise_applied_monotonic>=p.stamp){set('pwmStatus',`Jetson 적용 확인 · ${p.value} PWM`,'good');state.pwmPending=null;if(Number($('pwmNumber').value)===p.value)state.pwmDirty=false;}else if(Date.now()-p.at>12000){set('pwmStatus','적용 상태 확인 지연 · 다시 조회 후 적용하세요','warn');state.pwmPending=null;}}
else if(!state.pwmDirty&&Number.isInteger(nav.auto_cruise_pwm)){$('pwmNumber').value=nav.auto_cruise_pwm;$('pwmRange').value=nav.auto_cruise_pwm===7397?92:(nav.auto_cruise_pwm-6480)/10;set('pwmStatus',`Jetson 적용값 · ${nav.auto_cruise_pwm} PWM`,'good');}
set('recordCount',`${record.point_count||0} 지점`,record.active?'good':'');$('recordStart').disabled=!!record.active;$('recordStop').disabled=!record.active||(record.point_count||0)<2;$('recordCancel').disabled=!record.active;set('recordStatus',record.active?(record.gps_ready?`기록 중 · ${record.point_count||0} 지점 · ${record.point_count<2?'2개 이상 지점 필요':'저장 가능'}`:'기록 중 · 유효 GPS FIX 대기'):'기록 정지 · 저장한 항로는 아래에 표시됩니다');
set('loggerState',ground.state||ground.status||(ground.active?'recording':'idle'),ground.error?'bad':ground.active?'good':'');set('groundStatus',`${ground.active?'기록 중':'정지'} · ${ground.samples??0} samples${ground.output_paused?' · 출력 일시정지':''}${ground.pause_reason?' · '+ground.pause_reason:''}${ground.error?' · '+ground.error:''}`);$('groundStart').disabled=!!ground.active||!readyToMove();$('groundResume').disabled=!ground.active||!readyToMove();
renderBalloon(safe,vision,session);
set('visionMetric',`${fmt(vision.processed_fps,1,' fps')} · ${fmt(vision.inference_ms,0,' ms')}`);$('saveCamera').disabled=!!vision.enabled;const c=vision.configuration||{};if(!$('cameraResolution').dataset.dirty&&c.width&&c.height){const size=`${c.width}x${c.height}`;if(![...$('cameraResolution').options].some(o=>o.value===size)){const o=elem('option','',size);o.value=size;$('cameraResolution').append(o);}$('cameraResolution').value=size;}if(!$('longRange').dataset.dirty&&c.long_range_enabled!==undefined)$('longRange').checked=c.long_range_enabled;for(const [id,key]of[['cameraType','camera_type'],['cameraSource','camera_source'],['sensorId','csi_sensor_id']])if(!$(id).dataset.dirty&&c[key]!==undefined)$(id).value=c[key];
if(state.page==='sail'){renderRoutes();updateMap();}else if(state.page==='routes')renderRoutes();else if(state.page==='gps')renderGps();const tests=s.ground_tests||[],ts=JSON.stringify(tests);if(ts!==testSignature){testSignature=ts;const old=$('testSelect').value;$('testSelect').replaceChildren(elem('option','','최신 완료 테스트'));$('testSelect').firstChild.value='';for(const t of tests.filter(t=>t.complete)){const o=elem('option','',t.id);o.value=t.id;$('testSelect').append(o);}$('testSelect').value=[...$('testSelect').options].some(o=>o.value===old)?old:'';}
motionAvailability();videoHealth();}
function clearFrame(){if(!$('frame').hidden){$('frame').hidden=true;$('frame').removeAttribute('src');}$('liveBadge').hidden=true;$('framePlaceholder').hidden=false;}
function disconnected(text){frameAt=0;frameTimes=[];$('bannerResetEstop').disabled=true;if(!$('estopBanner').hidden)set('estopDetail','마지막 확인: 비상정지 · 연결이 끊겨 현재 출력 확인 불가');healthState={ros:'offline',ssh:'disconnected'};remoteRelease();state.online=false;state.control=false;state.trackingStart=null;updateHealth(healthState);set('connectionBadge',text||'연결 해제','bad');$('connectionBadge').classList.remove('online');document.querySelectorAll('.motion').forEach(b=>b.disabled=true);set('safetyText','연결 상태를 확인하세요 · 원격 출력 확인 불가','warn');set('currentMode','연결 끊김','bad');set('modePill','상태 stale','warn');['gpsQuick','rtkQuick','lockQuick','speed','rampPwm','finalPwm'].forEach(id=>set(id,'stale','warn'));$('connections').replaceChildren(elem('div','bad','연결 끊김 · 이전 상태 만료'));$('gpsMetrics').querySelectorAll('b').forEach(e=>{e.textContent='stale';e.className='warn';});['gnssState','ntripState','visionState','loggerState','targetPhase'].forEach(id=>set(id,'stale','warn'));['recordStart','recordStop','recordCancel'].forEach(id=>$(id).disabled=true);clearFrame();}
function localProfile(p){state.ntripProfile=p;if(!$('ntripDetails').dataset.dirty){for(const [id,key]of[['nHost','host'],['nPort','port'],['nMount','mountpoint'],['nUser','username']])if(p[key]!==undefined)$(id).value=p[key];if(p.tls!==undefined)$('nTls').checked=p.tls;}if(p.host)set('ntripSummary',`${p.host}:${p.port||2101} / ${p.mountpoint||''} · ${p.username||'사용자 미설정'} · 휴대폰에 저장됨`);}
window.onNative=(event,d)=>{if(event==='ntrip_profile'){localProfile(d);return;}if(event==='settings'){$('host').value=d.host;$('username').value=d.username;$('gatewayPort').value=d.gateway_port;$('sshPort').value=d.ssh_port;set('appVersion',d.version);return;}if(event==='status'){render(d);return;}if(event==='link_health'){updateHealth(d);if(state.last&&Date.now()-state.last>2500)markTelemetryStale();return;}if(event==='frame_health'){videoState=d.state;videoHealth();return;}if(event==='ack'){const p=pending.get(d.id);if(!p)return;clearTimeout(p.timer);pending.delete(d.id);if(d.success)p.resolve(d);else p.reject(new Error(d.error||'명령 거부'));return;}if(event==='message'){message(d.text);return;}if(event==='offline'){updateHealth({ros:'delayed'});if(Date.now()-state.last>2500)markTelemetryStale();return;}if(event==='disconnected'){disconnected('연결 해제');return;}if(event==='frame'&&state.page==='camera'&&$('previewToggle').checked){frameAt=Date.now()-Math.max(0,d.source_age_ms||0);videoState='online';if(d.url&&/^https:\/\/appassets\.androidplatform\.net\/preview\.jpg\?v=[0-9_]+$/.test(d.url))$('frame').src=d.url;else if(d.image)$('frame').src='data:image/jpeg;base64,'+d.image;else return;$('frame').hidden=false;$('liveBadge').hidden=false;$('framePlaceholder').hidden=true;videoHealth();}};
$('frame').addEventListener('load',()=>{frameTimes.push(Date.now());while(frameTimes.length>1&&Date.now()-frameTimes[0]>3000)frameTimes.shift();videoHealth();});
setInterval(()=>{if(state.last&&Date.now()-state.last>2500){markTelemetryStale();updateHealth({ros:Date.now()-state.last>8000?'offline':'delayed'});}videoHealth();},500);
document.addEventListener('visibilitychange',()=>{if(document.hidden){state.trackingStart=null;remoteRelease();clearFrame();}});initMap();document.querySelectorAll('.motion').forEach(b=>b.disabled=true);if(window.Boat)Boat.ready();
