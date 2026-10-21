function outputFiles = plot_ground_test_week7(testFolder, outputFolder)
%PLOT_GROUND_TEST_WEEK7 Week-7 walking-validation figures made by MATLAB.
% Reference layouts: lecture PDF pp.20-23 and walking-test PPTX slides 3-6.

testFolder = string(testFolder);
if nargin < 2 || strlength(string(outputFolder)) == 0
    outputFolder = fullfile(testFolder, "RCBOAT_ground_test_results");
else
    outputFolder = string(outputFolder);
end
if ~isfolder(outputFolder), mkdir(outputFolder); end
graphFolder=fullfile(outputFolder,"graphs");
dataFolder=fullfile(outputFolder,"data");
qgisFolder=fullfile(outputFolder,"qgis");
docsFolder=fullfile(outputFolder,"docs");
matlabFolder=fullfile(outputFolder,"matlab");
folders=[graphFolder,dataFolder,qgisFolder,docsFolder,matlabFolder];
for folderIndex=1:numel(folders)
    if ~isfolder(folders(folderIndex)), mkdir(folders(folderIndex)); end
end

S = readtable(fullfile(testFolder,"ground_test.csv"),"Delimiter",",","VariableNamingRule","preserve");
R = readtable(fullfile(testFolder,"reference_routes.csv"),"Delimiter",",","VariableNamingRule","preserve");
M = readtable(fullfile(testFolder,"route_metrics.csv"),"Delimiter",",","VariableNamingRule","preserve");
W = readtable(fullfile(testFolder,"route_switches.csv"),"Delimiter",",","VariableNamingRule","preserve");
assert(height(S)>=2 && height(R)>=2,"Ground-test CSV files are empty");

% Backward-compatible input mapping for logs recorded before v2.1.7.
sampleVariables=string(S.Properties.VariableNames);
if ~ismember("previous_target_path_distance_m",sampleVariables)
    S.previous_target_path_distance_m=S.target_path_distance_m;
end
if ~ismember("route_distance_improvement_m",sampleVariables)
    S.route_distance_improvement_m=max(0,S.previous_target_path_distance_m-S.candidate_route_distance_m);
end
switchVariables=string(W.Properties.VariableNames);
if ~ismember("route_distance_improvement_m",switchVariables)
    W.route_distance_improvement_m=max(0,W.previous_target_path_distance_m-W.candidate_route_distance_m);
end

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
legend(ax,"Location","northoutside","Orientation","horizontal","NumColumns",3); xlim(ax,[t(1) t(end)]);
for p=1:3
    ax=nexttile(L); hold(ax,"on"); grid(ax,"on");
    idx=find(roles==ordered(p),1); if isempty(idx),idx=min(p,numel(routeIds));end
    rows=string(M.route_id)==routeIds(idx); role=roles(idx);
    plot(ax,M.elapsed_time_s(rows),M.heading_error_deg(rows),":","Color",roleColor(role),"DisplayName","Heading Error - "+roleWord(role));
    yline(ax,0,":","Color",[.25 .85 .30],"DisplayName","Desired");
    shadeActive(ax,S,routeIds,roles,false); drawSwitchLines(ax,switchTimes,false); ylim(ax,[-180 180]);
    ylabel(ax,role+newline+"Error (deg)"); legend(ax,"Location","northoutside","Orientation","horizontal","NumColumns",2);
end
ax=nexttile(L); hold(ax,"on"); grid(ax,"on");
plot(ax,t,S.target_speed_mps,"Color",[.25 .85 .30],"DisplayName","Desired");
plot(ax,t,S.speed_mps,"Color",[.10 .65 .90],"DisplayName","Actual");
shadeActive(ax,S,routeIds,roles,false); drawSwitchLines(ax,switchTimes,false);
xlabel(ax,"Time (s)"); ylabel(ax,"Speed (m/s)"); title(ax,"Speed"); legend(ax,"Location","northoutside","Orientation","horizontal");
outputFiles(end+1)=saveFigure(fig,graphFolder,"01_week7_full_summary.png");

%% 2. Reference paths and actual path
fig=figure("Position",[40 40 1650 930]); ax=axes(fig); hold(ax,"on"); grid(ax,"on"); plotRoutes(ax,R,routeIds,roles);
plot(ax,S.utm_easting_m,S.utm_northing_m,"-","Color",[.95 .85 .05],"LineWidth",2.5,"DisplayName","Actual Path");
scatter(ax,S.utm_easting_m(1),S.utm_northing_m(1),80,[.15 .65 .2],"filled","MarkerEdgeColor","k","DisplayName","Start");
scatter(ax,S.utm_easting_m(end),S.utm_northing_m(end),90,"k","s","filled","DisplayName","End");
for k=1:height(W)
    idx=max(1,min(height(S),round(W.sample_index(k)))); name="Target Path Switch"; vis="off"; if k==1,vis="on";end
    scatter(ax,S.utm_easting_m(idx),S.utm_northing_m(idx),65,[.9 .08 .08],"filled","MarkerEdgeColor","w","DisplayName",name,"HandleVisibility",vis);
end
axis(ax,"equal"); xlabel(ax,"UTM Easting (m)"); ylabel(ax,"UTM Northing (m)");
title(ax,"Reference Paths and Actual Path with Target Path Switches","FontSize",18,"FontWeight","bold"); legend(ax,"Location","eastoutside");
axis(ax,"padded");
outputFiles(end+1)=saveFigure(fig,graphFolder,"02_reference_and_actual_path.png");

%% 3. Nearest-route Target Path decision
fig=figure("Position",[50 50 1650 930]); L=tiledlayout(fig,2,1,"TileSpacing","compact","Padding","compact");
ax=nexttile(L); hold(ax,"on"); grid(ax,"on");
plot(ax,t,S.previous_target_path_distance_m,"Color",[.05 .35 .95],"DisplayName","Previous Active Path Distance");
plot(ax,t,S.candidate_route_distance_m,"Color",[0 .65 .65],"DisplayName","Nearest Path Distance");
plot(ax,t,S.route_distance_improvement_m,"--","Color",[.95 .35 .05],"DisplayName","Distance Improvement");
for k=1:height(W)
    name="Target Path Switch"; vis="off"; if k==1,vis="on";end
    scatter(ax,W.elapsed_time_s(k),W.previous_target_path_distance_m(k),55,[.85 .05 .08],"filled","MarkerEdgeColor","w","DisplayName",name,"HandleVisibility",vis);
    text(ax,W.elapsed_time_s(k),W.previous_target_path_distance_m(k),"  S"+k);
end
shadeActive(ax,S,routeIds,roles,true); ylabel(ax,"Distance (m)");
title(ax,"Target Path Decision: Select Minimum Route Distance (No Threshold)","FontSize",18,"FontWeight","bold");
legend(ax,"Location","northoutside","Orientation","horizontal","NumColumns",4);
ax=nexttile(L); hold(ax,"on"); grid(ax,"on"); active=string(S.active_route_id); y=zeros(height(S),1);
for k=1:numel(routeIds), y(active==routeIds(k))=roleIndex(roles(k)); end
stairs(ax,t,y,"k","LineWidth",1.8,"DisplayName","Active Target Path"); drawSwitchLines(ax,switchTimes,true);
yticks(ax,[1 2 3]); yticklabels(ax,["Left Path","Center Path","Right Path"]); ylim(ax,[.5 3.5]);
xlabel(ax,"Time (s)"); ylabel(ax,"Target Path"); legend(ax,"Location","northoutside","Orientation","horizontal");
outputFiles(end+1)=saveFigure(fig,graphFolder,"03_nearest_route_decision.png");

%% 4. Heading error for all paths
fig=figure("Position",[60 60 1650 930]); L=tiledlayout(fig,3,1,"TileSpacing","compact","Padding","compact");
title(L,"Heading Angular Error for Every Reference Path","FontSize",18,"FontWeight","bold","Color","black");
for p=1:3
    ax=nexttile(L); hold(ax,"on"); grid(ax,"on"); idx=find(roles==ordered(p),1); if isempty(idx),idx=min(p,numel(routeIds));end
    role=roles(idx); rows=string(M.route_id)==routeIds(idx);
    plot(ax,M.elapsed_time_s(rows),M.heading_error_deg(rows),":","Color",roleColor(role),"DisplayName","Heading Error - "+roleWord(role));
    yline(ax,0,":","Color",[.25 .85 .30],"DisplayName","Desired");
    shadeActive(ax,S,routeIds,roles,false); drawSwitchLines(ax,switchTimes,false); ylim(ax,[-180 180]);
    ylabel(ax,"Heading Error (deg)"); legend(ax,"Location","northoutside","Orientation","horizontal","NumColumns",2);
end
xlabel(ax,"Time (s)"); outputFiles(end+1)=saveFigure(fig,graphFolder,"04_heading_error_all_paths.png");

%% Remaining figures
[moreFiles] = remainingFigures(S,R,M,W,routeIds,routeNames,roles,graphFolder);
outputFiles = [outputFiles(:); moreFiles(:)];
[extraFiles] = extraFigures(S,R,M,W,routeIds,routeNames,roles,graphFolder);
outputFiles = [outputFiles(:); extraFiles(:)];
exportAnalysisData(S,R,M,W,routeIds,routeNames,roles,testFolder,dataFolder,qgisFolder);
writeGuide(S,R,M,W,routeIds,routeNames,outputFiles,docsFolder,qgisFolder);
scriptPath=string(mfilename("fullpath"))+".m";
copyfile(scriptPath,fullfile(matlabFolder,"plot_ground_test_week7.m"),"f");
writeResultReadme(outputFolder,outputFiles);
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
ylabel(ax,"Angle (deg)"); title(ax,"Rudder Steering Command"); legend(ax,"Location","northoutside","Orientation","horizontal");
shadeActive(ax,S,routeIds,roles,false); drawSwitchLines(ax,switchTimes,false);
ax=nexttile(L); hold(ax,"on"); grid(ax,"on");
plot(ax,t,S.final_steering_pwm,"Color",[.05 .35 .95],"DisplayName","Steering Command");
yline(ax,6000,"--","Color",[.35 .35 .35],"DisplayName","Steering Neutral");
ylabel(ax,"PWM"); title(ax,"Rudder Servo PWM"); legend(ax,"Location","northoutside","Orientation","horizontal");
shadeActive(ax,S,routeIds,roles,false); drawSwitchLines(ax,switchTimes,false);
ax=nexttile(L); hold(ax,"on"); grid(ax,"on");
plot(ax,t,S.final_throttle_pwm,"Color",[.9 .3 0],"DisplayName","Throttle Command");
yline(ax,6450,"--","Color",[.35 .35 .35],"DisplayName","Throttle Stop");
ylabel(ax,"PWM"); title(ax,"Single Motor Throttle PWM"); legend(ax,"Location","northoutside","Orientation","horizontal");
shadeActive(ax,S,routeIds,roles,false); drawSwitchLines(ax,switchTimes,false);
ax=nexttile(L); hold(ax,"on"); grid(ax,"on");
plot(ax,t,S.speed_mps,"Color",[.1 .65 .9],"DisplayName","Actual");
plot(ax,t,S.target_speed_mps,"--","Color",[.25 .85 .3],"DisplayName","Desired");
xlabel(ax,"Time (s)"); ylabel(ax,"Speed (m/s)"); title(ax,"Actual and Desired Speed");
legend(ax,"Location","northoutside","Orientation","horizontal"); shadeActive(ax,S,routeIds,roles,false); drawSwitchLines(ax,switchTimes,false);
files(end+1)=saveFigure(fig,folder,"05_rudder_throttle_speed_response.png");

% 6. GPS and RTK quality.
fig=figure("Position",[80 30 1650 1050]); L=tiledlayout(fig,4,1,"TileSpacing","compact","Padding","compact");
title(L,"GPS and RTK Measurement Quality","FontSize",18,"FontWeight","bold","Color","black");
ax=nexttile(L); hold(ax,"on"); grid(ax,"on");
plot(ax,t,S.hdop,"Color",[.05 .35 .95],"DisplayName","HDOP");
plot(ax,t,S.hacc_m,"Color",[.9 .3 0],"DisplayName","Horizontal Accuracy (m)");
yline(ax,3,"--","Color",[.95 .1 .2],"DisplayName","Configured HDOP Limit");
ylabel(ax,"HDOP / m"); title(ax,"GPS Position Quality"); legend(ax,"Location","northoutside","Orientation","horizontal","NumColumns",3); drawSwitchLines(ax,switchTimes,false);
ax=nexttile(L); hold(ax,"on"); grid(ax,"on");
state=zeros(height(S),1); state(string(S.rtk_state)=="DGPS")=1;
state(contains(string(S.rtk_state),"FLOAT"))=2; state(contains(string(S.rtk_state),"FIXED"))=3;
stairs(ax,t,state,"Color",[0 .55 .32],"DisplayName","RTK State");
yticks(ax,0:3); yticklabels(ax,["No Fix","DGPS","RTK Float","RTK Fix"]); ylim(ax,[-.2 3.4]);
title(ax,"RTK State"); legend(ax,"Location","northoutside","Orientation","horizontal"); drawSwitchLines(ax,switchTimes,false);
ax=nexttile(L); hold(ax,"on"); grid(ax,"on"); yyaxis(ax,"left");
plot(ax,t,S.gps_data_age_s,"Color",[.05 .35 .95],"DisplayName","GPS Data Age");
ylabel(ax,"GPS Age (s)"); yyaxis(ax,"right");
plot(ax,t,S.correction_age_s,"Color",[.9 .05 .08],"DisplayName","Correction Age");
yline(ax,5,"--","Color",[1 .55 0],"DisplayName","Correction Good <= 5 s");
yline(ax,10,":","Color",[.55 0 0],"DisplayName","Correction Stale > 10 s");
ylabel(ax,"Correction Age (s)"); title(ax,"GPS and NTRIP Correction Delay");
legend(ax,"Location","northoutside","Orientation","horizontal","NumColumns",4); drawSwitchLines(ax,switchTimes,false);
ax=nexttile(L); hold(ax,"on"); grid(ax,"on"); yyaxis(ax,"left");
plot(ax,t,S.satellites,"Color",[.4 .25 .6],"DisplayName","Satellites"); ylabel(ax,"Satellites");
yyaxis(ax,"right"); plot(ax,t,S.cno_dbhz,"Color",[.95 .45 0],"DisplayName","C/N0");
ylabel(ax,"C/N0 (dB-Hz)"); xlabel(ax,"Time (s)"); title(ax,"Satellite Reception");
legend(ax,"Location","northoutside","Orientation","horizontal"); drawSwitchLines(ax,switchTimes,false);
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
indices=find(mask);
if ~isempty(indices)
    scatter(ax,S.utm_easting_m(indices(1)),S.utm_northing_m(indices(1)),55,[.15 .65 .2],"filled","MarkerEdgeColor","k","DisplayName","Window Start");
    scatter(ax,S.utm_easting_m(indices(end)),S.utm_northing_m(indices(end)),55,"k","s","filled","DisplayName","Window End");
end
if isfinite(c)
    [~,i]=min(abs(t-c)); scatter(ax,S.utm_easting_m(i),S.utm_northing_m(i),75,[.9 .05 .08],"filled","DisplayName","Target Path Switch");
end
axis(ax,"equal"); xlabel(ax,"UTM Easting (m)"); ylabel(ax,"UTM Northing (m)");
title(ax,"Reference Paths and Actual Path"); legend(ax,"Location","southoutside","Orientation","horizontal","NumColumns",3); axis(ax,"padded");

ax=nexttile(L); hold(ax,"on"); grid(ax,"on"); angle=S.final_rudder_angle_deg;
right=angle; right(right>=0)=NaN; left=angle; left(left<0)=NaN;
plot(ax,t(mask),zeros(sum(mask),1),":","Color",[.25 .85 .3],"DisplayName","Neutral");
plot(ax,t(mask),right(mask),":","Color",[1 .2 .15],"DisplayName","Right Turn");
plot(ax,t(mask),left(mask),":","Color",[.05 .45 1],"DisplayName","Left Turn");
if isfinite(c),xline(ax,c,"k-","DisplayName","Target Path Switch");end
ylabel(ax,"Steering Angle (deg)"); title(ax,"Rudder Steering Command"); legend(ax,"Location","northoutside","Orientation","horizontal","NumColumns",4);

ax=nexttile(L); hold(ax,"on"); grid(ax,"on");
plot(ax,t(mask),S.previous_target_path_distance_m(mask),"Color",[.05 .35 .95],"DisplayName","Previous Active Path Distance");
plot(ax,t(mask),S.candidate_route_distance_m(mask),"Color",[0 .65 .65],"DisplayName","Nearest Path Distance");
if isfinite(c),xline(ax,c,"k-","DisplayName","Target Path Switch");end
ylabel(ax,"Distance (m)"); title(ax,"Target Path Decision"); legend(ax,"Location","northoutside","Orientation","horizontal","NumColumns",3);

ax=nexttile(L); hold(ax,"on"); grid(ax,"on");
for k=1:numel(routeIds)
    rows=string(M.route_id)==routeIds(k) & M.elapsed_time_s>=a & M.elapsed_time_s<=b;
    plot(ax,M.elapsed_time_s(rows),M.heading_error_deg(rows),":","Color",roleColor(roles(k)),"DisplayName","Heading Error - "+roleWord(roles(k)));
end
yline(ax,0,":","Color",[.25 .85 .3],"DisplayName","Desired");
if isfinite(c),xline(ax,c,"k-","HandleVisibility","off");end
ylim(ax,[-180 180]); xlabel(ax,"Time (s)"); ylabel(ax,"Heading Error (deg)");
title(ax,"Heading Angular Error"); legend(ax,"Location","northoutside","Orientation","horizontal","NumColumns",4);
path=saveFigure(fig,folder,name);
end

function files=extraFigures(S,R,M,W,routeIds,routeNames,roles,folder)
% Additional figures for quantitative interpretation and repeatable PPT use.
t=S.elapsed_time_s; switchTimes=W.elapsed_time_s; files=strings(0,1);

% 9. Core tracking errors used for quantitative interpretation.
fig=figure("Position",[95 35 1700 1080]); L=tiledlayout(fig,4,1,"TileSpacing","compact","Padding","compact");
title(L,"Tracking Error and Speed Error","FontSize",19,"FontWeight","bold","Color","black");
ax=nexttile(L); hold(ax,"on"); grid(ax,"on");
plot(ax,t,S.previous_target_path_distance_m,"Color",[.05 .35 .95],"DisplayName","Previous Active Path Distance");
plot(ax,t,S.target_path_distance_m,"Color",[0 .65 .65],"DisplayName","Selected Nearest Path Distance");
ylabel(ax,"Distance (m)"); title(ax,"Distance from Active Target Path");
legend(ax,"Location","northoutside","Orientation","horizontal"); drawSwitchLines(ax,switchTimes,false);
ax=nexttile(L); hold(ax,"on"); grid(ax,"on");
plot(ax,t,S.cross_track_error_m,"Color",[.5 .15 .75],"DisplayName","Cross Track Error");
yline(ax,0,":","Color",[.25 .75 .3],"DisplayName","Target Path");
ylabel(ax,"CTE (m)"); title(ax,"Signed Cross Track Error");
legend(ax,"Location","northoutside","Orientation","horizontal"); drawSwitchLines(ax,switchTimes,false);
ax=nexttile(L); hold(ax,"on"); grid(ax,"on");
plot(ax,t,S.heading_error_deg,"Color",[.9 .3 0],"DisplayName","Active Heading Error");
yline(ax,0,":","Color",[.25 .75 .3],"DisplayName","Desired"); ylim(ax,[-180 180]);
ylabel(ax,"Error (deg)"); title(ax,"Heading Error Used by Controller");
legend(ax,"Location","northoutside","Orientation","horizontal"); drawSwitchLines(ax,switchTimes,false);
ax=nexttile(L); hold(ax,"on"); grid(ax,"on"); speedError=S.speed_mps-S.target_speed_mps;
plot(ax,t,speedError,"Color",[.05 .65 .85],"DisplayName","Actual - Desired");
yline(ax,0,":","Color",[.25 .75 .3],"DisplayName","Desired");
xlabel(ax,"Time (s)"); ylabel(ax,"Speed Error (m/s)"); title(ax,"Speed Tracking Error");
legend(ax,"Location","northoutside","Orientation","horizontal"); drawSwitchLines(ax,switchTimes,false);
files(end+1)=saveFigure(fig,folder,"09_tracking_error_and_speed_error.png");

% 10. Desired, safety-filtered and PCA9685-confirmed PWM values.
fig=figure("Position",[100 35 1700 1080]); L=tiledlayout(fig,4,1,"TileSpacing","compact","Padding","compact");
title(L,"Control Command and Output Verification","FontSize",19,"FontWeight","bold","Color","black");
ax=nexttile(L); hold(ax,"on"); grid(ax,"on");
plot(ax,t,S.desired_steering_pwm,"Color",[.55 .15 .75],"DisplayName","Navigation Desired");
plot(ax,t,S.final_steering_pwm,"--","Color",[.05 .35 .95],"DisplayName","Safety Final");
plot(ax,t,S.actual_steering_pwm,":","Color",[0 .65 .45],"DisplayName","PCA9685 Command Confirmation");
ylabel(ax,"PWM"); title(ax,"Rudder Servo Command Chain");
legend(ax,"Location","northoutside","Orientation","horizontal","NumColumns",3); drawSwitchLines(ax,switchTimes,false);
ax=nexttile(L); hold(ax,"on"); grid(ax,"on");
plot(ax,t,S.desired_throttle_pwm,"Color",[.9 .3 0],"DisplayName","Navigation Desired");
plot(ax,t,S.final_throttle_pwm,"--","Color",[.75 .05 .1],"DisplayName","Safety Final");
plot(ax,t,S.actual_throttle_pwm,":","Color",[0 .55 .45],"DisplayName","PCA9685 Command Confirmation");
ylabel(ax,"PWM"); title(ax,"Single Motor Throttle Command Chain");
legend(ax,"Location","northoutside","Orientation","horizontal","NumColumns",3); drawSwitchLines(ax,switchTimes,false);
ax=nexttile(L); hold(ax,"on"); grid(ax,"on");
stairs(ax,t,double(boolVector(S.output_send_success)),"Color",[.05 .55 .25],"DisplayName","Output Send Success");
ylim(ax,[-.1 1.2]); yticks(ax,[0 1]); yticklabels(ax,["Failure","Success"]); title(ax,"Output Transmission Result");
legend(ax,"Location","northoutside","Orientation","horizontal"); drawSwitchLines(ax,switchTimes,false);
ax=nexttile(L); hold(ax,"on"); grid(ax,"on");
stairs(ax,t,double(boolVector(S.ground_test_actuation_enabled)),"Color",[.05 .35 .95],"DisplayName","Ground Test Output Enabled");
stairs(ax,t,double(boolVector(S.output_locked)),"--","Color",[.9 .1 .1],"DisplayName","Output Locked");
stairs(ax,t,double(boolVector(S.throttle_locked)),":","Color",[.5 .2 .65],"DisplayName","Throttle Locked");
ylim(ax,[-.1 1.2]); yticks(ax,[0 1]); yticklabels(ax,["No","Yes"]);
xlabel(ax,"Time (s)"); title(ax,"Safety and Output State");
legend(ax,"Location","northoutside","Orientation","horizontal","NumColumns",3); drawSwitchLines(ax,switchTimes,false);
files(end+1)=saveFigure(fig,folder,"10_control_command_and_output_verification.png");

% 11. Waypoint selection, active route and travelled distance.
fig=figure("Position",[105 45 1700 1020]); L=tiledlayout(fig,4,1,"TileSpacing","compact","Padding","compact");
title(L,"Waypoint and Route Progress","FontSize",19,"FontWeight","bold","Color","black");
ax=nexttile(L); hold(ax,"on"); grid(ax,"on");
stairs(ax,t,S.target_waypoint_number,"Color",[.05 .35 .95],"DisplayName","Target Waypoint Number");
ylabel(ax,"Waypoint"); title(ax,"Selected Target Waypoint"); legend(ax,"Location","northoutside","Orientation","horizontal"); drawSwitchLines(ax,switchTimes,false);
ax=nexttile(L); hold(ax,"on"); grid(ax,"on");
plot(ax,t,S.distance_to_waypoint_m,"Color",[.9 .3 0],"DisplayName","Distance to Waypoint");
ylabel(ax,"Distance (m)"); title(ax,"Distance to Current Target Waypoint"); legend(ax,"Location","northoutside","Orientation","horizontal"); drawSwitchLines(ax,switchTimes,false);
ax=nexttile(L); hold(ax,"on"); grid(ax,"on"); [activeIndex,activeLabels]=activeRouteIndex(S,routeIds,routeNames);
stairs(ax,t,activeIndex,"k","LineWidth",1.8,"DisplayName","Active Target Path");
yticks(ax,1:numel(activeLabels)); yticklabels(ax,activeLabels); ylim(ax,[.5 numel(activeLabels)+.5]);
title(ax,"Active Target Path"); legend(ax,"Location","northoutside","Orientation","horizontal"); drawSwitchLines(ax,switchTimes,false);
ax=nexttile(L); hold(ax,"on"); grid(ax,"on"); travelled=cumsum([0;hypot(diff(S.utm_easting_m),diff(S.utm_northing_m))]);
plot(ax,t,travelled,"Color",[0 .6 .45],"DisplayName","Cumulative GPS Distance");
xlabel(ax,"Time (s)"); ylabel(ax,"Distance (m)"); title(ax,"Cumulative Walking Distance");
legend(ax,"Location","northoutside","Orientation","horizontal"); drawSwitchLines(ax,switchTimes,false);
files(end+1)=saveFigure(fig,folder,"11_waypoint_and_route_progress.png");

% 12. Align every switch to t=0 for direct response comparison.
if height(W)>0
    colours=lines(height(W)); fig=figure("Position",[110 45 1700 1000]);
    L=tiledlayout(fig,3,1,"TileSpacing","compact","Padding","compact");
    title(L,"Target Path Switch Response Comparison","FontSize",19,"FontWeight","bold","Color","black");
    ax1=nexttile(L); hold(ax1,"on"); grid(ax1,"on");
    ax2=nexttile(L); hold(ax2,"on"); grid(ax2,"on");
    ax3=nexttile(L); hold(ax3,"on"); grid(ax3,"on");
    for k=1:height(W)
        relative=t-W.elapsed_time_s(k); mask=relative>=-5 & relative<=8;
        plot(ax1,relative(mask),S.route_distance_improvement_m(mask),"Color",colours(k,:),"DisplayName","S"+k);
        plot(ax2,relative(mask),S.heading_error_deg(mask),"Color",colours(k,:),"HandleVisibility","off");
        plot(ax3,relative(mask),S.final_rudder_angle_deg(mask),"Color",colours(k,:),"HandleVisibility","off");
    end
    yline(ax1,0,":","Color",[.25 .75 .3],"DisplayName","No Distance Gain"); xline(ax1,0,"k-","HandleVisibility","off");
    ylabel(ax1,"Improvement (m)"); title(ax1,"Distance Gain from Nearest-Path Selection");
    legend(ax1,"Location","northoutside","Orientation","horizontal","NumColumns",5);
    yline(ax2,0,":","Color",[.25 .75 .3]); xline(ax2,0,"k-"); ylim(ax2,[-180 180]);
    ylabel(ax2,"Heading Error (deg)"); title(ax2,"Controller Heading Error");
    yline(ax3,0,":","Color",[.25 .75 .3]); xline(ax3,0,"k-");
    xlabel(ax3,"Time from Target Path Switch (s)"); ylabel(ax3,"Rudder Angle (deg)"); title(ax3,"Rudder Command");
    files(end+1)=saveFigure(fig,folder,"12_target_path_switch_response_comparison.png");
end

% 13. Route-level statistics for the result table in the presentation.
[statLabels,distanceStats,headingStats,speedStats,sampleCounts]=routeStatistics(S,routeIds,routeNames);
fig=figure("Position",[115 55 1700 980]); L=tiledlayout(fig,2,2,"TileSpacing","loose","Padding","compact");
title(L,"Route-level Tracking Statistics","FontSize",19,"FontWeight","bold","Color","black");
ax=nexttile(L); bar(ax,distanceStats); grid(ax,"on"); xticks(ax,1:numel(statLabels)); xticklabels(ax,statLabels);
ylabel(ax,"Distance (m)"); title(ax,"Absolute Target Path Distance"); legend(ax,["Mean","95th Percentile"],"Location","northoutside","Orientation","horizontal");
ax=nexttile(L); bar(ax,headingStats); grid(ax,"on"); xticks(ax,1:numel(statLabels)); xticklabels(ax,statLabels);
ylabel(ax,"Absolute Error (deg)"); title(ax,"Heading Error Excluding Low-speed Samples"); legend(ax,["Mean","95th Percentile"],"Location","northoutside","Orientation","horizontal");
ax=nexttile(L); bar(ax,speedStats); grid(ax,"on"); xticks(ax,1:numel(statLabels)); xticklabels(ax,statLabels);
ylabel(ax,"Speed (m/s)"); title(ax,"Actual and Desired Speed"); legend(ax,["Actual Mean","Desired Mean"],"Location","northoutside","Orientation","horizontal");
ax=nexttile(L); bar(ax,sampleCounts,"FaceColor",[.15 .55 .8]); grid(ax,"on"); xticks(ax,1:numel(statLabels)); xticklabels(ax,statLabels);
ylabel(ax,"Samples"); title(ax,"Samples Assigned to Each Target Path");
files(end+1)=saveFigure(fig,folder,"13_route_level_tracking_statistics.png");

% 14. Data availability and quality categories.
fig=figure("Position",[120 60 1700 920]); L=tiledlayout(fig,2,2,"TileSpacing","loose","Padding","compact");
title(L,"Data Quality and Availability Summary","FontSize",19,"FontWeight","bold","Color","black");
ax=nexttile(L); rtk=upper(string(S.rtk_state)); values=100*[mean(contains(rtk,"FIXED"));mean(contains(rtk,"FLOAT"));mean(rtk=="DGPS");mean(~contains(rtk,"FIXED") & ~contains(rtk,"FLOAT") & rtk~="DGPS")];
bar(ax,values,"FaceColor",[0 .55 .35]); grid(ax,"on"); xticks(ax,1:4); xticklabels(ax,["RTK Fix","RTK Float","DGPS","Other"]); ylabel(ax,"Samples (%)"); title(ax,"RTK State Share"); ylim(ax,[0 105]);
ax=nexttile(L); age=S.correction_age_s; age=age(isfinite(age)); values=100*[mean(age<=5);mean(age>5 & age<=10);mean(age>10)];
bar(ax,values,"FaceColor",[.9 .45 .05]); grid(ax,"on"); xticks(ax,1:3); xticklabels(ax,["<= 5 s","5-10 s","> 10 s"]); ylabel(ax,"Samples (%)"); title(ax,"NTRIP Correction Age"); ylim(ax,[0 105]);
ax=nexttile(L); values=100*[mean(string(S.gps_validity)=="valid");mean(boolVector(S.gps_healthy));mean(boolVector(S.output_send_success))];
bar(ax,values,"FaceColor",[.1 .45 .85]); grid(ax,"on"); xticks(ax,1:3); xticklabels(ax,["GPS Valid","GPS Healthy","Output Sent"]); ylabel(ax,"Samples (%)"); title(ax,"Validity and Output Availability"); ylim(ax,[0 105]);
ax=nexttile(L); course=upper(string(S.course_quality)); values=100*[mean(course=="MOVING_COG");mean(course=="LOW_SPEED");mean(course~="MOVING_COG" & course~="LOW_SPEED")];
bar(ax,values,"FaceColor",[.55 .25 .7]); grid(ax,"on"); xticks(ax,1:3); xticklabels(ax,["Moving COG","Low Speed","Other"]); ylabel(ax,"Samples (%)"); title(ax,"GNSS Course Quality"); ylim(ax,[0 105]);
files(end+1)=saveFigure(fig,folder,"14_data_quality_and_availability_summary.png");
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
    if labels && x1-x0>=12
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

function exportAnalysisData(S,R,M,W,ids,names,roles,testFolder,dataFolder,qgisFolder)
% Keep the final result self-contained and provide QGIS-ready subsets.
writetable(S,fullfile(dataFolder,"ground_test_all.csv"));
writetable(R,fullfile(dataFolder,"reference_routes_all.csv"));
writetable(M,fullfile(dataFolder,"route_metrics_all.csv"));
writetable(W,fullfile(dataFolder,"route_switches.csv"));
actualVars=["sample_index","elapsed_time_s","logger_time_utc","measurement_time_utc",...
    "latitude","longitude","utm_easting_m","utm_northing_m","utm_zone",...
    "heading_deg","heading_source","speed_mps","course_deg","gps_fix","rtk_state",...
    "gps_validity","gps_data_age_s","correction_age_s","active_route_id",...
    "target_waypoint_number","target_path_distance_m","cross_track_error_m",...
    "heading_error_deg","final_rudder_angle_deg","final_steering_pwm","final_throttle_pwm"];
actualVars=actualVars(ismember(actualVars,string(S.Properties.VariableNames)));
actualPath=S(:,cellstr(actualVars));
writetable(actualPath,fullfile(dataFolder,"actual_path.csv"));
writetable(actualPath,fullfile(qgisFolder,"qgis_actual_path.csv"));
writetable(R,fullfile(qgisFolder,"qgis_reference_routes.csv"));
for k=1:numel(ids)
    rows=string(R.route_id)==ids(k);
    safeName=regexprep(char(roles(k)+"_"+names(k)),"[^0-9A-Za-z가-힣_-]","_");
    writetable(R(rows,:),fullfile(dataFolder,sprintf("reference_route_%02d_%s.csv",k,safeName)));
end
if height(W)>0
    idx=max(1,min(height(S),round(W.sample_index)));
    switchPoints=W;
    switchPoints.switch_number=(1:height(W))';
    switchPoints.latitude=S.latitude(idx);
    switchPoints.longitude=S.longitude(idx);
    switchPoints.utm_easting_m=S.utm_easting_m(idx);
    switchPoints.utm_northing_m=S.utm_northing_m(idx);
    switchPoints.utm_zone=S.utm_zone(idx);
    writetable(switchPoints,fullfile(qgisFolder,"qgis_route_switch_points.csv"));
end
rawFiles=["ground_test.jsonl","reference_routes.json","route_changes.jsonl","events.jsonl",...
    "test_metadata.json","analysis_manifest.json","export_manifest.json"];
for k=1:numel(rawFiles)
    source=fullfile(testFolder,rawFiles(k));
    if isfile(source), copyfile(source,fullfile(dataFolder,rawFiles(k)),"f"); end
end
end

function writeGuide(S,R,M,W,ids,names,outputs,folder,qgisFolder)
guidePath=fullfile(folder,"PPT_QGIS_그래프_해설_및_캡처_설계도.txt");
fid=fopen(guidePath,"w","n","UTF-8"); cleaner=onCleanup(@()fclose(fid)); %#ok<NASGU>
duration=S.elapsed_time_s(end)-S.elapsed_time_s(1);
fprintf(fid,"RC-BOAT 도보검증 PPT/QGIS 그래프 해설 및 캡처 설계도\n");
fprintf(fid,"===========================================================\n\n");
fprintf(fid,"1. 참고한 자료\n");
fprintf(fid,"- 어드벤처디자인 7주차 강의자료 PDF 20~23쪽\n");
fprintf(fid,"- 어드벤처디자인 7주차 강의자료(도보검증) PPTX 3~6쪽\n");
fprintf(fid,"- 강의자료의 L/R Thrust는 듀얼 추진기 예시다. 현재 보트는 단일 추진모터와 러더 구조이므로 스로틀 PWM과 러더 PWM/각도로 대응했다.\n\n");
fprintf(fid,"2. 시험 요약\n");
fprintf(fid,"- 기록 시간: %.1f s\n- 샘플: %d개\n- 기준항로 좌표: %d개\n- 자동 Target Path 전환: %d회\n",duration,height(S),height(R),height(W));
fprintf(fid,"- 실제 속도 평균/최소/최대: %.3f / %.3f / %.3f m/s\n",mean(S.speed_mps,"omitnan"),min(S.speed_mps),max(S.speed_mps));
fprintf(fid,"- 목표 속도 평균: %.3f m/s\n",mean(S.target_speed_mps,"omitnan"));
fprintf(fid,"- HDOP 평균/최소/최대: %.3f / %.3f / %.3f\n",mean(S.hdop,"omitnan"),min(S.hdop),max(S.hdop));
fprintf(fid,"- 출력 전송 성공률: %.1f %%\n\n",100*mean(boolVector(S.output_send_success)));

fprintf(fid,"3. 권장 PPT 구성\n");
fprintf(fid,"1쪽: 시험 목적, 시험 환경, 대루트와 최근접 소루트 자동 선택 조건\n");
fprintf(fid,"2쪽: 01 전체 요약. 조향각, 항로별 Heading Error, 실제/목표 속도를 강의자료와 같은 흐름으로 설명\n");
fprintf(fid,"3쪽: QGIS 전체 경로 캡처와 02 기준/실제 경로. 실제 이동이 세 기준항로 사이에서 어떻게 변했는지 설명\n");
fprintf(fid,"4쪽: 03 최근접 항로 판단. 기존 활성 항로 거리와 최근접 후보 거리를 비교해 S1~S8 전환을 증명\n");
fprintf(fid,"5쪽: 07 비외란 사례. Target Path 유지 중 거리와 Heading Error가 어떻게 유지되는지 설명\n");
fprintf(fid,"6쪽: 08 외란 사례. 최근접 소루트가 바뀐 전후 Target Path, 러더 명령, Heading Error 변화를 설명\n");
fprintf(fid,"7쪽: 05와 10. 단일모터/러더 명령 및 desired-final-actual 전송 체인을 설명\n");
fprintf(fid,"8쪽: 09와 13. 횡오차, Heading Error, 속도 오차 및 항로별 평균/95%% 통계\n");
fprintf(fid,"9쪽: 11과 12. waypoint 진행과 8회 전환의 상대시간 응답 비교\n");
fprintf(fid,"10쪽: 06과 14. GPS/RTK 품질, 보정 지연과 데이터 가용성, 한계 사항\n\n");

fprintf(fid,"4. 그래프별 발표 해설\n");
fprintf(fid,"01 전체 요약: 위에서부터 러더 조향 명령, Right/Center/Left 기준 Heading Error, 실제/목표 속도다. 회색 세로선은 자동 Target Path 전환 시각이다. 짧은 구간은 이름을 생략해 글자 겹침을 막았다.\n");
fprintf(fid,"02 기준/실제 경로: 점선 3개는 시험 시작 시 고정 저장한 기준항로, 노란 실선은 실제 GPS 경로, 빨간 점은 전환 위치다. 지도 배경은 QGIS 캡처로 보완한다.\n");
fprintf(fid,"03 최근접 판단: 파란선은 전환 직전 활성 항로 거리, 청록선은 모든 후보 중 최소거리다. 후보가 더 가까워지는 즉시 임계값 없이 활성 항로가 변경되고 주황선은 확보한 거리 개선량을 나타낸다.\n");
fprintf(fid,"04 항로별 Heading Error: 각 시점의 위치와 헤딩을 세 기준항로 모두에 대해 계산한 값이다. 현재 선택되지 않은 항로의 오차도 비교할 수 있다.\n");
fprintf(fid,"05 제어응답: 러더 각도, 러더 PWM, 단일 추진모터 PWM, 속도를 시간순으로 비교한다. L/R thrust 대신 이 그래프를 사용한다.\n");
fprintf(fid,"06 GPS/RTK 품질: HDOP/HACC, RTK 상태, GPS 및 보정 데이터 지연, 위성 수/CN0를 표시한다. 보정 지연이 10초를 넘는 구간은 RTK 보정 신뢰에 주의한다.\n");
fprintf(fid,"07 비외란 사례: 가장 긴 Target Path 유지 구간에서 경로, 러더, 거리, 항로별 Heading Error를 묶어 보여준다.\n");
fprintf(fid,"08 외란 사례: 첫 자동 전환 전후 5초/8초 구간이다. 수동 마커 없이 최근접 소루트가 바뀐 자동 결정시각을 외란 판정 기준으로 삼았다.\n");
fprintf(fid,"09 추종 오차: Target Path 거리, 부호 있는 횡오차, 제어용 Heading Error, 속도 오차를 같은 시간축에서 해석한다.\n");
fprintf(fid,"10 출력 검증: navigation desired, safety final, PCA9685 전송 확인값을 비교한다. actual PWM은 물리 센서 피드백이 아니라 전송 명령 확인값이다.\n");
fprintf(fid,"11 waypoint 진행: 목표 waypoint 번호, waypoint까지 거리, 활성 항로, 누적 보행거리를 함께 보여준다.\n");
fprintf(fid,"12 전환 응답 비교: S1~S8 전환을 각각 t=0에 맞춰 최근접 선택 거리 개선량, Heading Error, 러더 명령을 비교한다.\n");
fprintf(fid,"13 항로별 통계: 각 활성 항로 구간의 평균과 95백분위 오차를 제시한다. LOW_SPEED 표본은 Heading Error 통계에서 제외한다.\n");
fprintf(fid,"14 데이터 가용성: RTK 상태, 보정 지연 등급, GPS/출력 성공률, course 품질의 표본 비율이다.\n\n");

fprintf(fid,"5. Target Path 자동 전환 기록\n");
fprintf(fid,"번호 | 시간(s) | 전환 전 | 전환 후 | 기존 거리(m) | 최근접 거리(m) | 개선량(m)\n");
for k=1:height(W)
    fprintf(fid,"S%d | %.3f | %s | %s | %.4f | %.4f | %.4f\n",k,W.elapsed_time_s(k),...
        routeName(string(W.previous_route_id(k)),ids,names),routeName(string(W.new_route_id(k)),ids,names),...
        W.previous_target_path_distance_m(k),W.candidate_route_distance_m(k),W.route_distance_improvement_m(k));
end

allLat=[S.latitude;R.latitude]; allLon=[S.longitude;R.longitude];
latSpan=max(allLat)-min(allLat); lonSpan=max(allLon)-min(allLon);
latMin=min(allLat)-.08*latSpan; latMax=max(allLat)+.08*latSpan;
lonMin=min(allLon)-.08*lonSpan; lonMax=max(allLon)+.08*lonSpan;
fprintf(fid,"\n6. QGIS 캡처 설계\n");
fprintf(fid,"불러올 파일\n- %s\n- %s\n- %s\n",...
    fullfile(qgisFolder,"qgis_reference_routes.csv"),fullfile(qgisFolder,"qgis_actual_path.csv"),fullfile(qgisFolder,"qgis_route_switch_points.csv"));
fprintf(fid,"좌표 설정\n- X=longitude, Y=latitude, CRS=EPSG:4326\n- 또는 UTM X=utm_easting_m, Y=utm_northing_m, CRS=EPSG:32652\n");
fprintf(fid,"전체 경로 캡처 권장 범위(WGS84)\n- longitude %.8f ~ %.8f\n- latitude %.8f ~ %.8f\n",lonMin,lonMax,latMin,latMax);
fprintf(fid,"레이어 순서와 색\n- 배경: 위성 또는 OpenStreetMap. 제출 시 지도 출처 표기\n- 다리 L: 빨강 점선 1.2 mm\n- 다리 C: 짙은 회색 점선 1.2 mm\n- 다리 R: 자홍 점선 1.2 mm\n- actual path: 노랑 실선 1.8 mm\n- route switch points: 빨간 원, switch_number 라벨\n");
fprintf(fid,"반드시 캡처할 화면\n1) 전체 3개 기준항로와 실제 경로가 모두 보이는 화면. 북쪽표시, 축척, 지도 출처를 포함한다.\n");
fprintf(fid,"2) S1 첫 전환 위치 확대 화면. 최근접 후보가 바뀌어 Target Path가 변경된 사례에 사용한다.\n");
fprintf(fid,"3) S4 또는 S5 부근 확대 화면. Center/Left 사이 전환 사례와 실제 경로 복귀 모습을 보여준다.\n");
fprintf(fid,"4) 필요하면 S6~S8 연속 전환 구간을 별도 확대한다. 이 구간은 전환 간격이 짧아 전체 지도에서 라벨이 겹칠 수 있다.\n");
for k=1:height(W)
    idx=max(1,min(height(S),round(W.sample_index(k))));
    fprintf(fid,"- S%d 좌표: lat %.8f, lon %.8f, 시간 %.3f s\n",k,S.latitude(idx),S.longitude(idx),W.elapsed_time_s(k));
end

fprintf(fid,"\n7. 해석 시 주의사항\n");
fprintf(fid,"- final/actual PWM은 실제 추력 또는 러더 위치 센서값이 아니다. PCA9685로 전송한 명령 확인값이다.\n");
fprintf(fid,"- GPS 속도에는 사람이 배를 들고 이동한 속도가 포함된다. 수상 성능으로 직접 일반화하지 않는다.\n");
fprintf(fid,"- 수동 외란 마커는 사용하지 않았다. 모든 소루트 거리 비교로 결정된 자동 Target Path 전환 시각을 외란 사례 기준으로 사용한다.\n");
fprintf(fid,"- LOW_SPEED 구간의 GNSS course는 불안정할 수 있으므로 정밀 Heading Error 통계에서 제외한다.\n");
fprintf(fid,"- 보정 데이터 지연이 10초를 넘으면 RTK FIX 여부와 별도로 보정 신선도를 주의해서 해석한다.\n");
fprintf(fid,"- QGIS 배경지도는 데이터에 포함되지 않는다. 반드시 QGIS에서 동일 좌표계로 불러와 캡처한다.\n\n");

fprintf(fid,"8. 생성 그래프 목록\n");
for k=1:numel(outputs), [~,name,ext]=fileparts(outputs(k)); fprintf(fid,"%02d. %s%s\n",k,name,ext); end
end

function writeResultReadme(folder,outputs)
fid=fopen(fullfile(folder,"README_FIRST.txt"),"w","n","UTF-8"); cleaner=onCleanup(@()fclose(fid)); %#ok<NASGU>
fprintf(fid,"RC-BOAT 도보검증 최종 결과\n============================\n\n");
fprintf(fid,"graphs : MATLAB R2026a로 생성한 PPT용 PNG %d개\n",numel(outputs));
fprintf(fid,"data   : 원본/분석용 CSV와 JSON/JSONL\n");
fprintf(fid,"qgis   : QGIS용 기준항로, 실제경로, 전환점 CSV\n");
fprintf(fid,"docs   : PPT 해설 및 QGIS 캡처 설계도\n");
fprintf(fid,"matlab : 동일 그래프를 다시 생성하는 MATLAB 스크립트\n\n");
fprintf(fid,"먼저 docs/PPT_QGIS_그래프_해설_및_캡처_설계도.txt를 읽으십시오.\n");
end

function [index,labels]=activeRouteIndex(S,ids,names)
labels=names(:)'; index=nan(height(S),1); active=string(S.active_route_id);
for k=1:numel(ids), index(active==ids(k))=k; end
end

function [labels,distanceStats,headingStats,speedStats,sampleCounts]=routeStatistics(S,ids,names)
labels=names(:)'; n=numel(ids); distanceStats=nan(n,2); headingStats=nan(n,2); speedStats=nan(n,2); sampleCounts=zeros(n,1);
for k=1:n
    mask=string(S.active_route_id)==ids(k); sampleCounts(k)=sum(mask);
    d=abs(S.target_path_distance_m(mask)); d=d(isfinite(d));
    hmask=mask & upper(string(S.course_quality))~="LOW_SPEED"; h=abs(S.heading_error_deg(hmask)); h=h(isfinite(h));
    actual=S.speed_mps(mask); desired=S.target_speed_mps(mask);
    distanceStats(k,:)=[meanOrNaN(d),percentileValue(d,95)];
    headingStats(k,:)=[meanOrNaN(h),percentileValue(h,95)];
    speedStats(k,:)=[mean(actual,"omitnan"),mean(desired,"omitnan")];
end
end

function value=percentileValue(values,p)
values=sort(values(isfinite(values))); if isempty(values),value=NaN;return;end
position=1+(numel(values)-1)*p/100; lo=floor(position); hi=ceil(position);
if lo==hi,value=values(lo);else,value=values(lo)+(position-lo)*(values(hi)-values(lo));end
end

function value=meanOrNaN(values)
if isempty(values),value=NaN;else,value=mean(values,"omitnan");end
end

function values=boolVector(raw)
if islogical(raw),values=raw;
elseif isnumeric(raw),values=raw~=0;
else
    text=lower(strtrim(string(raw)));
    values=text=="true" | text=="1" | text=="yes" | text=="on";
end
values=values(:);
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
