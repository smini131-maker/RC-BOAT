function outputFiles = plot_ground_test_week7(testFolder, outputFolder)
%PLOT_GROUND_TEST_WEEK7 Week-7 walking-validation figures made by MATLAB.
% Reference layouts: lecture PDF pp.20-23 and walking-test PPTX slides 3-6.

testFolder = string(testFolder);
if nargin < 2 || strlength(string(outputFolder)) == 0
    outputFolder = fullfile(testFolder, "week7_matlab_analysis");
else
    outputFolder = string(outputFolder);
end
if ~isfolder(outputFolder), mkdir(outputFolder); end

S = readtable(fullfile(testFolder,"ground_test.csv"),"Delimiter",",","VariableNamingRule","preserve");
R = readtable(fullfile(testFolder,"reference_routes.csv"),"Delimiter",",","VariableNamingRule","preserve");
M = readtable(fullfile(testFolder,"route_metrics.csv"),"Delimiter",",","VariableNamingRule","preserve");
W = readtable(fullfile(testFolder,"route_switches.csv"),"Delimiter",",","VariableNamingRule","preserve");
assert(height(S)>=2 && height(R)>=2,"Ground-test CSV files are empty");

set(groot,"defaultFigureColor","w");
set(groot,"defaultAxesColor","w");
set(groot,"defaultAxesXColor","k");
set(groot,"defaultAxesYColor","k");
set(groot,"defaultTextColor","k");
set(groot,"defaultLegendColor","w");
set(groot,"defaultLegendTextColor","k");
set(groot,"defaultAxesFontName","Malgun Gothic");
set(groot,"defaultAxesFontSize",10);
set(groot,"defaultLineLineWidth",1.5);

routeIds = unique(string(R.route_id),"stable");
routeNames = strings(size(routeIds)); roles = strings(size(routeIds));
for k=1:numel(routeIds)
    row=find(string(R.route_id)==routeIds(k),1);
    routeNames(k)=string(R.route_name(row)); roles(k)=routeRole(routeNames(k));
end
t=S.elapsed_time_s; switchTimes=W.elapsed_time_s; outputFiles=strings(0,1);
ordered=["R","C","L"];

%% 1. PPT summary: steering, three heading errors, speed
fig=figure("Position",[30 20 1700 1050]); L=tiledlayout(fig,5,1,"TileSpacing","compact","Padding","compact");
title(L,"GPS-based Path-tracking Algorithm Validation: Ground Test","FontSize",20,"FontWeight","bold","Color","black");
ax=nexttile(L); hold(ax,"on"); grid(ax,"on");
angle=S.final_rudder_angle_deg; right=angle; right(right>=0)=NaN; left=angle; left(left<0)=NaN;
plot(ax,t,zeros(size(t)),":","Color",[.25 .85 .30],"DisplayName","Neutral");
plot(ax,t,right,":","Color",[1 .2 .15],"DisplayName","Right Turn");
plot(ax,t,left,":","Color",[.05 .45 1],"DisplayName","Left Turn");
shadeActive(ax,S,routeIds,roles,true); drawSwitchLines(ax,switchTimes,false);
ylabel(ax,"Steering Angle (deg)"); title(ax,"Rudder Steering Command");
legend(ax,"Location","southeast","Orientation","horizontal"); xlim(ax,[t(1) t(end)]);
for p=1:3
    ax=nexttile(L); hold(ax,"on"); grid(ax,"on");
    idx=find(roles==ordered(p),1); if isempty(idx),idx=min(p,numel(routeIds));end
    rows=string(M.route_id)==routeIds(idx); role=roles(idx);
    plot(ax,M.elapsed_time_s(rows),M.heading_error_deg(rows),":","Color",roleColor(role),"DisplayName","Heading Error - "+roleWord(role));
    yline(ax,0,":","Color",[.25 .85 .30],"DisplayName","Desired");
    shadeActive(ax,S,routeIds,roles,false); drawSwitchLines(ax,switchTimes,false); ylim(ax,[-180 180]);
    ylabel(ax,role+newline+"Error (deg)"); legend(ax,"Location","northwest","Orientation","horizontal");
    text(ax,.99,.84,roleWord(role)+" Path","Units","normalized","HorizontalAlignment","right","Color",roleColor(role),"FontWeight","bold");
end
ax=nexttile(L); hold(ax,"on"); grid(ax,"on");
plot(ax,t,S.target_speed_mps,"Color",[.25 .85 .30],"DisplayName","Desired");
plot(ax,t,S.speed_mps,"Color",[.10 .65 .90],"DisplayName","Actual");
shadeActive(ax,S,routeIds,roles,false); drawSwitchLines(ax,switchTimes,false);
xlabel(ax,"Time (s)"); ylabel(ax,"Speed (m/s)"); title(ax,"Speed"); legend(ax,"Location","northeast");
outputFiles(end+1)=saveFigure(fig,outputFolder,"01_week7_full_summary.png");

%% 2. Reference paths and actual path
fig=figure("Position",[40 40 1650 930]); ax=axes(fig); hold(ax,"on"); grid(ax,"on"); plotRoutes(ax,R,routeIds,roles);
plot(ax,S.utm_easting_m,S.utm_northing_m,"-","Color",[.95 .85 .05],"LineWidth",2.5,"DisplayName","Actual Path");
scatter(ax,S.utm_easting_m(1),S.utm_northing_m(1),80,[.15 .65 .2],"filled","MarkerEdgeColor","k","DisplayName","Start");
scatter(ax,S.utm_easting_m(end),S.utm_northing_m(end),90,"k","s","filled","DisplayName","End");
for k=1:height(W)
    idx=max(1,min(height(S),round(W.sample_index(k)))); name="Target Path Switch"; vis="off"; if k==1,vis="on";end
    scatter(ax,S.utm_easting_m(idx),S.utm_northing_m(idx),65,[.9 .08 .08],"filled","MarkerEdgeColor","w","DisplayName",name,"HandleVisibility",vis);
    text(ax,S.utm_easting_m(idx),S.utm_northing_m(idx),sprintf("  S%d  %.1fs",k,W.elapsed_time_s(k)),"Color",[.7 0 0],"FontWeight","bold");
end
axis(ax,"equal"); xlabel(ax,"UTM Easting (m)"); ylabel(ax,"UTM Northing (m)");
title(ax,"Reference Paths and Actual Path with Target Path Switches","FontSize",18,"FontWeight","bold"); legend(ax,"Location","best");
outputFiles(end+1)=saveFigure(fig,outputFolder,"02_reference_and_actual_path.png");

%% 3. Target Path 2 m decision
fig=figure("Position",[50 50 1650 930]); L=tiledlayout(fig,2,1,"TileSpacing","compact","Padding","compact");
ax=nexttile(L); hold(ax,"on"); grid(ax,"on");
plot(ax,t,S.target_path_distance_m,"Color",[.05 .35 .95],"DisplayName","Current Target Path Distance");
plot(ax,t,S.candidate_route_distance_m,"Color",[0 .65 .65],"DisplayName","Nearest Candidate Distance");
plot(ax,t,S.multipath_switch_threshold_m,"--","Color",[.95 .1 .2],"DisplayName","Switch Threshold (2 m)");
for k=1:height(W)
    name="Target Path Switch"; vis="off"; if k==1,vis="on";end
    scatter(ax,W.elapsed_time_s(k),W.previous_target_path_distance_m(k),55,[.85 .05 .08],"filled","MarkerEdgeColor","w","DisplayName",name,"HandleVisibility",vis);
    text(ax,W.elapsed_time_s(k),W.previous_target_path_distance_m(k),"  S"+k);
end
shadeActive(ax,S,routeIds,roles,true); ylabel(ax,"Distance (m)");
title(ax,"Target Path Decision: <= 2 m Keep, > 2 m Select Nearest Path","FontSize",18,"FontWeight","bold");
legend(ax,"Location","northeast","Orientation","horizontal");
ax=nexttile(L); hold(ax,"on"); grid(ax,"on"); active=string(S.active_route_id); y=zeros(height(S),1);
for k=1:numel(routeIds), y(active==routeIds(k))=roleIndex(roles(k)); end
stairs(ax,t,y,"k","LineWidth",1.8,"DisplayName","Active Target Path"); drawSwitchLines(ax,switchTimes,true);
yticks(ax,[1 2 3]); yticklabels(ax,["Left Path","Center Path","Right Path"]); ylim(ax,[.5 3.5]);
xlabel(ax,"Time (s)"); ylabel(ax,"Target Path"); legend(ax,"Location","northeast");
outputFiles(end+1)=saveFigure(fig,outputFolder,"03_target_path_2m_decision.png");

%% 4. Heading error for all paths
fig=figure("Position",[60 60 1650 930]); L=tiledlayout(fig,3,1,"TileSpacing","compact","Padding","compact");
title(L,"Heading Angular Error for Every Reference Path","FontSize",18,"FontWeight","bold","Color","black");
for p=1:3
    ax=nexttile(L); hold(ax,"on"); grid(ax,"on"); idx=find(roles==ordered(p),1); if isempty(idx),idx=min(p,numel(routeIds));end
    role=roles(idx); rows=string(M.route_id)==routeIds(idx);
    plot(ax,M.elapsed_time_s(rows),M.heading_error_deg(rows),":","Color",roleColor(role),"DisplayName","Heading Error - "+roleWord(role));
    yline(ax,0,":","Color",[.25 .85 .30],"DisplayName","Desired");
    shadeActive(ax,S,routeIds,roles,false); drawSwitchLines(ax,switchTimes,false); ylim(ax,[-180 180]);
    ylabel(ax,"Heading Error (deg)"); legend(ax,"Location","northwest");
    text(ax,.99,.86,roleWord(role)+" Path","Units","normalized","HorizontalAlignment","right","Color",roleColor(role),"FontWeight","bold");
end
xlabel(ax,"Time (s)"); outputFiles(end+1)=saveFigure(fig,outputFolder,"04_heading_error_all_paths.png");

%% Remaining figures
[moreFiles] = remainingFigures(S,R,M,W,routeIds,routeNames,roles,outputFolder);
outputFiles = [outputFiles(:); moreFiles(:)];
writeGuide(S,R,W,routeIds,routeNames,outputFiles,outputFolder);
fprintf("Created MATLAB Week-7 analysis in:\n%s\n%s\n",outputFolder,strjoin(outputFiles,newline));
end

function files = remainingFigures(S,R,M,W,routeIds,routeNames,roles,folder)
t=S.elapsed_time_s; switchTimes=W.elapsed_time_s; files=strings(0,1);

% 5. Rudder, steering PWM, one motor throttle PWM and speed.
fig=figure("Position",[70 30 1650 1050]); L=tiledlayout(fig,4,1,"TileSpacing","compact","Padding","compact");
title(L,"Navigation Output Response","FontSize",18,"FontWeight","bold","Color","black");
ax=nexttile(L); hold(ax,"on"); grid(ax,"on");
plot(ax,t,S.final_rudder_angle_deg,"Color",[.55 .15 .75],"DisplayName","Final Rudder Command");
yline(ax,0,":","Color",[.25 .85 .30],"DisplayName","Neutral");
ylabel(ax,"Angle (deg)"); title(ax,"Rudder Steering Command"); legend(ax,"Location","northeast","Orientation","horizontal");
shadeActive(ax,S,routeIds,roles,false); drawSwitchLines(ax,switchTimes,false);
ax=nexttile(L); hold(ax,"on"); grid(ax,"on");
plot(ax,t,S.final_steering_pwm,"Color",[.05 .35 .95],"DisplayName","Steering Command");
yline(ax,6000,"--","Color",[.35 .35 .35],"DisplayName","Steering Neutral");
ylabel(ax,"PWM"); title(ax,"Rudder Servo PWM"); legend(ax,"Location","northeast","Orientation","horizontal");
shadeActive(ax,S,routeIds,roles,false); drawSwitchLines(ax,switchTimes,false);
ax=nexttile(L); hold(ax,"on"); grid(ax,"on");
plot(ax,t,S.final_throttle_pwm,"Color",[.9 .3 0],"DisplayName","Throttle Command");
yline(ax,6450,"--","Color",[.35 .35 .35],"DisplayName","Throttle Stop");
ylabel(ax,"PWM"); title(ax,"Single Motor Throttle PWM"); legend(ax,"Location","northeast","Orientation","horizontal");
shadeActive(ax,S,routeIds,roles,false); drawSwitchLines(ax,switchTimes,false);
ax=nexttile(L); hold(ax,"on"); grid(ax,"on");
plot(ax,t,S.speed_mps,"Color",[.1 .65 .9],"DisplayName","Actual");
plot(ax,t,S.target_speed_mps,"--","Color",[.25 .85 .3],"DisplayName","Desired");
xlabel(ax,"Time (s)"); ylabel(ax,"Speed (m/s)"); title(ax,"Actual and Desired Speed");
legend(ax,"Location","northeast","Orientation","horizontal"); shadeActive(ax,S,routeIds,roles,false); drawSwitchLines(ax,switchTimes,false);
files(end+1)=saveFigure(fig,folder,"05_rudder_throttle_speed_response.png");

% 6. GPS and RTK quality.
fig=figure("Position",[80 30 1650 1050]); L=tiledlayout(fig,4,1,"TileSpacing","compact","Padding","compact");
title(L,"GPS and RTK Measurement Quality","FontSize",18,"FontWeight","bold","Color","black");
ax=nexttile(L); hold(ax,"on"); grid(ax,"on");
plot(ax,t,S.hdop,"Color",[.05 .35 .95],"DisplayName","HDOP");
plot(ax,t,S.hacc_m,"Color",[.9 .3 0],"DisplayName","Horizontal Accuracy (m)");
yline(ax,3,"--","Color",[.95 .1 .2],"DisplayName","Configured HDOP Limit");
ylabel(ax,"HDOP / m"); title(ax,"GPS Position Quality"); legend(ax,"Location","northeast","Orientation","horizontal"); drawSwitchLines(ax,switchTimes,false);
ax=nexttile(L); hold(ax,"on"); grid(ax,"on");
state=zeros(height(S),1); state(string(S.rtk_state)=="DGPS")=1;
state(contains(string(S.rtk_state),"FLOAT"))=2; state(contains(string(S.rtk_state),"FIXED"))=3;
stairs(ax,t,state,"Color",[0 .55 .32],"DisplayName","RTK State");
yticks(ax,0:3); yticklabels(ax,["No Fix","DGPS","RTK Float","RTK Fix"]); ylim(ax,[-.2 3.4]);
title(ax,"RTK State"); legend(ax,"Location","northeast"); drawSwitchLines(ax,switchTimes,false);
ax=nexttile(L); hold(ax,"on"); grid(ax,"on");
plot(ax,t,S.gps_data_age_s,"Color",[.05 .35 .95],"DisplayName","GPS Data Age");
plot(ax,t,S.correction_age_s,"Color",[.9 .05 .08],"DisplayName","Correction Age");
yline(ax,5,"--","Color",[1 .55 0],"DisplayName","Correction Good <= 5 s");
yline(ax,10,":","Color",[.55 0 0],"DisplayName","Correction Stale > 10 s");
ylabel(ax,"Age (s)"); title(ax,"GPS and NTRIP Correction Delay");
legend(ax,"Location","northwest","Orientation","horizontal"); drawSwitchLines(ax,switchTimes,false);
ax=nexttile(L); hold(ax,"on"); grid(ax,"on"); yyaxis(ax,"left");
plot(ax,t,S.satellites,"Color",[.4 .25 .6],"DisplayName","Satellites"); ylabel(ax,"Satellites");
yyaxis(ax,"right"); plot(ax,t,S.cno_dbhz,"Color",[.95 .45 0],"DisplayName","C/N0");
ylabel(ax,"C/N0 (dB-Hz)"); xlabel(ax,"Time (s)"); title(ax,"Satellite Reception");
legend(ax,"Location","northeast","Orientation","horizontal"); drawSwitchLines(ax,switchTimes,false);
files(end+1)=saveFigure(fig,folder,"06_gps_rtk_quality.png");

% 7. Non-disturbance and 8. first path-switch case.
[a,b]=longestStable(t,switchTimes);
files(end+1)=caseFigure(S,R,M,routeIds,roles,a,b,NaN,folder,"07_non_disturbance_case.png","Non-Disturbance Case: Target Path Maintained");
if height(W)>0
    c=W.elapsed_time_s(1);
    files(end+1)=caseFigure(S,R,M,routeIds,roles,max(t(1),c-5),min(t(end),c+7),c,folder,"08_disturbance_case.png","Disturbance Case: Target Path Change");
end
end

function path = caseFigure(S,R,M,routeIds,roles,a,b,c,folder,name,figureTitle)
t=S.elapsed_time_s; mask=t>=a & t<=b;
fig=figure("Position",[90 50 1650 930]); L=tiledlayout(fig,3,2,"TileSpacing","compact","Padding","compact");
title(L,figureTitle,"FontSize",20,"FontWeight","bold","Color","black");
ax=nexttile(L,[3 1]); hold(ax,"on"); grid(ax,"on"); plotRoutes(ax,R,routeIds,roles);
plot(ax,S.utm_easting_m(mask),S.utm_northing_m(mask),"-o","Color",[.95 .85 .05],"LineWidth",2.5,"MarkerSize",2,"DisplayName","Actual Path");
indices=find(mask); step=max(1,floor(numel(indices)/8));
for i=indices(1:step:end)'
    text(ax,S.utm_easting_m(i),S.utm_northing_m(i),sprintf(" %.1fs",t(i)),"FontSize",7,"Color",[.45 .4 0]);
end
if isfinite(c)
    [~,i]=min(abs(t-c)); scatter(ax,S.utm_easting_m(i),S.utm_northing_m(i),75,[.9 .05 .08],"filled","DisplayName","Target Path Switch");
end
axis(ax,"equal"); xlabel(ax,"UTM Easting (m)"); ylabel(ax,"UTM Northing (m)");
title(ax,"Reference Paths and Actual Path"); legend(ax,"Location","best");

ax=nexttile(L); hold(ax,"on"); grid(ax,"on"); angle=S.final_rudder_angle_deg;
right=angle; right(right>=0)=NaN; left=angle; left(left<0)=NaN;
plot(ax,t(mask),zeros(sum(mask),1),":","Color",[.25 .85 .3],"DisplayName","Neutral");
plot(ax,t(mask),right(mask),":","Color",[1 .2 .15],"DisplayName","Right Turn");
plot(ax,t(mask),left(mask),":","Color",[.05 .45 1],"DisplayName","Left Turn");
if isfinite(c),xline(ax,c,"k-","DisplayName","Target Path Switch");end
ylabel(ax,"Steering Angle (deg)"); title(ax,"Rudder Steering Command"); legend(ax,"Location","best");

ax=nexttile(L); hold(ax,"on"); grid(ax,"on");
plot(ax,t(mask),S.target_path_distance_m(mask),"Color",[.05 .35 .95],"DisplayName","Target Path Distance");
plot(ax,t(mask),S.multipath_switch_threshold_m(mask),"--","Color",[.95 .1 .2],"DisplayName","Switch Threshold");
if isfinite(c),xline(ax,c,"k-","DisplayName","Target Path Switch");end
ylabel(ax,"Distance (m)"); title(ax,"Target Path Decision"); legend(ax,"Location","best");

ax=nexttile(L); hold(ax,"on"); grid(ax,"on");
for k=1:numel(routeIds)
    rows=string(M.route_id)==routeIds(k) & M.elapsed_time_s>=a & M.elapsed_time_s<=b;
    plot(ax,M.elapsed_time_s(rows),M.heading_error_deg(rows),":","Color",roleColor(roles(k)),"DisplayName","Heading Error - "+roleWord(roles(k)));
end
yline(ax,0,":","Color",[.25 .85 .3],"DisplayName","Desired");
if isfinite(c),xline(ax,c,"k-","HandleVisibility","off");end
ylim(ax,[-180 180]); xlabel(ax,"Time (s)"); ylabel(ax,"Heading Error (deg)");
title(ax,"Heading Angular Error"); legend(ax,"Location","best");
path=saveFigure(fig,folder,name);
end

function path=saveFigure(fig,folder,name)
% MATLAB desktop dark theme can otherwise leak into the exported canvas.
% Force a presentation-ready white canvas while preserving deliberately
% coloured route, switch and steering annotations.
fig.Color="white";
axesList=findall(fig,"Type","axes");
set(axesList,"Color","white","XColor","black","YColor","black");
textList=findall(fig,"Type","text");
for textIndex=1:numel(textList)
    colour=textList(textIndex).Color;
    if isnumeric(colour) && numel(colour)==3 && all(colour>0.65)
        textList(textIndex).Color="black";
    end
end
path=string(fullfile(folder,name));
exportgraphics(fig,path,"Resolution",220,"BackgroundColor","white");
close(fig);
end

function plotRoutes(ax,R,ids,roles)
for k=1:numel(ids)
    rows=string(R.route_id)==ids(k);
    plot(ax,R.utm_easting_m(rows),R.utm_northing_m(rows),"--.","Color",roleColor(roles(k)),...
        "LineWidth",1.8,"DisplayName",roleWord(roles(k))+" Path");
end
end

function shadeActive(ax,S,ids,roles,labels)
active=string(S.active_route_id); t=S.elapsed_time_s;
changes=[1;find(active(2:end)~=active(1:end-1))+1;numel(active)+1]; yl=ylim(ax);
for j=1:numel(changes)-1
    a=changes(j); b=changes(j+1)-1; idx=find(ids==active(a),1); if isempty(idx),continue;end
    x0=t(a); x1=t(b);
    q=patch(ax,[x0 x1 x1 x0],[yl(1) yl(1) yl(2) yl(2)],roleFill(roles(idx)),...
        "FaceAlpha",.10,"EdgeColor","none","HandleVisibility","off");
    try,uistack(q,"bottom");catch,end
    if labels && x1-x0>=4
        text(ax,(x0+x1)/2,yl(2)-.08*(yl(2)-yl(1)),roleWord(roles(idx))+" Path",...
            "HorizontalAlignment","center","Color",roleColor(roles(idx)),"FontWeight","bold");
    end
end
ylim(ax,yl);
end

function drawSwitchLines(ax,times,showLegend)
for k=1:numel(times)
    vis="off"; if showLegend && k==1,vis="on";end
    xline(ax,times(k),"k-","LineWidth",.8,"Alpha",.55,"DisplayName","Target Path Switch","HandleVisibility",vis);
end
end

function [a,b]=longestStable(t,switchTimes)
p=[t(1);switchTimes(:);t(end)]; [~,i]=max(diff(p)); a=p(i); b=p(i+1);
if b-a>18,m=min(4,(b-a-12)/2);a=a+m;b=b-m;end
end

function writeGuide(S,R,W,ids,names,outputs,folder)
fid=fopen(fullfile(folder,"PPT_작성_및_그래프_해석_MATLAB.txt"),"w","n","UTF-8");
cleaner=onCleanup(@()fclose(fid));
fprintf(fid,"RC-BOAT 도보검증 PPT 작성 및 그래프 해석 가이드 (MATLAB 생성)\n");
fprintf(fid,"====================================================================\n\n");
fprintf(fid,"참고자료\n- 7주차 강의자료 PDF 20~23쪽\n- 7주차 강의자료(도보검증) PPTX 3~6쪽\n\n");
fprintf(fid,"시험 개요\n- 기록 시간 %.1f s, 샘플 %d개, 기준항로 좌표 %d개, 자동 전환 %d회\n",...
    S.elapsed_time_s(end)-S.elapsed_time_s(1),height(S),height(R),height(W));
fprintf(fid,"- Actual Speed 평균 %.3f m/s, 범위 %.3f~%.3f m/s\n",mean(S.speed_mps,"omitnan"),min(S.speed_mps),max(S.speed_mps));
fprintf(fid,"- HDOP 평균 %.3f, 범위 %.3f~%.3f\n\n",mean(S.hdop,"omitnan"),min(S.hdop),max(S.hdop));
fprintf(fid,"PPT 구성\n1쪽 시험 목적과 검증 방법\n2쪽 01 전체 조향각/항로별 Heading Error/속도\n");
fprintf(fid,"3쪽 02 실제 경로와 03 상대거리 2m 판정\n4쪽 07 Non-Disturbance Case\n");
fprintf(fid,"5쪽 08 Disturbance Case\n6쪽 05 단일모터/러더 출력\n7쪽 06 GPS/RTK 품질\n\n");
fprintf(fid,"전환 기록\n번호 | 시간(s) | 전환 전 | 전환 후 | 기존 거리(m) | 새 거리(m)\n");
for k=1:height(W)
    fprintf(fid,"S%d | %.3f | %s | %s | %.4f | %.4f\n",k,W.elapsed_time_s(k),...
        routeName(string(W.previous_route_id(k)),ids,names),routeName(string(W.new_route_id(k)),ids,names),...
        W.previous_target_path_distance_m(k),W.candidate_route_distance_m(k));
end
fprintf(fid,"\n발표 해석\n- Target Path와 보트 위치의 상대거리가 2m 이하이면 현재 항로를 유지했다.\n");
fprintf(fid,"- 2m를 초과하면 가장 가까운 소항로로 Target Path를 변경했다.\n");
fprintf(fid,"- 전환 전후 Heading Error와 러더 명령을 함께 비교해 복귀 방향을 확인한다.\n");
fprintf(fid,"- 단일 추진 모터 구조이므로 L/R Thrust 대신 스로틀 PWM과 러더 PWM/각도를 제시한다.\n\n");
fprintf(fid,"주의\n- final/actual PWM은 전송 명령 확인값이며 실제 추력 또는 러더 위치 센서값이 아니다.\n");
fprintf(fid,"- GPS 속도는 사람이 들고 이동한 속도를 포함한다.\n");
fprintf(fid,"- 외란 시작 버튼이 없으므로 2m 초과와 자동 전환 시각을 기준으로 해석한다.\n");
fprintf(fid,"- 보정 지연 10s 초과 구간은 DGPS/GNSS 결과로 표시한다.\n");
fprintf(fid,"- LOW_SPEED 샘플은 정밀 Heading Error 통계에서 제외한다.\n\n생성 파일\n");
for k=1:numel(outputs),fprintf(fid,"%d. %s\n",k,outputs(k));end
end

function n=routeName(id,ids,names)
i=find(ids==id,1); if isempty(i),n=id;else,n=names(i);end
end
function r=routeRole(name)
u=upper(strtrim(string(name)));
if endsWith(u," L")||u=="L"||contains(u,"LEFT"),r="L";
elseif endsWith(u," R")||u=="R"||contains(u,"RIGHT"),r="R";
else,r="C";end
end
function w=roleWord(r)
if r=="L",w="Left";elseif r=="R",w="Right";else,w="Center";end
end
function i=roleIndex(r)
if r=="L",i=1;elseif r=="R",i=3;else,i=2;end
end
function c=roleColor(r)
if r=="L",c=[1 .2 .15];elseif r=="R",c=[.91 .2 .68];else,c=[.4 .4 .4];end
end
function c=roleFill(r)
if r=="L",c=[1 .83 .83];elseif r=="R",c=[.96 .84 .94];else,c=[.87 .87 .87];end
end
