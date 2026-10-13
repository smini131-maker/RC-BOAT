% RC Boat GPS Ground Path Tracking (actual log: path_tracking.csv)
clear;
clc;
close all;

% If the CSV is not beside this script, choose it in the dialog.
root = fileparts(mfilename('fullpath'));
csvFile = fullfile(root,'..','raw','path_tracking.csv');
if ~isfile(csvFile)
    [name, folder] = uigetfile('*.csv','Select RC Boat path_tracking.csv');
    if isequal(name,0), error('No CSV selected'); end
    csvFile = fullfile(folder,name);
end
T = readtable(csvFile,'TextType','string');
required = {'elapsed_time_s','desired_rudder_angle_deg','heading_error_deg','speed_mps'};
for i = 1:numel(required)
    if ~ismember(required{i}, T.Properties.VariableNames)
        error('CSV missing column: %s',required{i});
    end
end
t = double(T.elapsed_time_s);
angle = double(T.desired_rudder_angle_deg);
err = double(T.heading_error_deg);
speed = double(T.speed_mps); % Already SI (m/s); do not divide by 3.6.
changes = false(height(T),1);
if ismember('multipath_switch',T.Properties.VariableNames)
    v = T.multipath_switch;
    if islogical(v), changes = v;
    elseif isnumeric(v), changes = v~=0;
    else, changes = strcmpi(string(v),'True') | strcmpi(string(v),'1');end
end
switchTimes = t(changes);

if ~isfolder(fullfile(root,'..','plots')), mkdir(fullfile(root,'..','plots')); end
outDir = fullfile(root,'..','plots');

f1 = figure('Color','w','Name','Time vs Rudder Angle');
hfull=plot(t,angle,'-','Color',[.65 .65 .65],'LineWidth',0.8);hold on;
hneutral=yline(0,'k--','Neutral');
left=angle;left(left>0)=NaN;
right=angle;right(right<0)=NaN;
hleft=plot(t,left,'b-','LineWidth',1.8);
hright=plot(t,right,'r-','LineWidth',1.8);
for k=1:numel(switchTimes), xline(switchTimes(k),'m:','Switch');end
xlabel('Time [s]');ylabel('Rudder Angle [deg]');title('Time vs Rudder Angle');
legend([hfull,hneutral,hleft,hright],{'Desired rudder','Neutral','Left','Right'},'Location','best');grid on;
exportgraphics(f1,fullfile(outDir,'steering_angle.png'),'Resolution',150);

f2 = figure('Color','w','Name','Time vs Heading Error');
plot(t,err,'b-','LineWidth',1.5);hold on;yline(0,'k--');
for k=1:numel(switchTimes), xline(switchTimes(k),'m:','Route switch');end
ylim([-180,180]);xlabel('Time [s]');ylabel('Heading Error [deg]');title('Time vs Heading Error');grid on;
exportgraphics(f2,fullfile(outDir,'heading_error.png'),'Resolution',150);

f3 = figure('Color','w','Name','Time vs Speed');
plot(t,speed,'b-','LineWidth',1.5);xlabel('Time [s]');ylabel('Speed [m/s]');
title('Time vs Speed (GNSS)');grid on;
exportgraphics(f3,fullfile(outDir,'speed.png'),'Resolution',150);

if ismember('cross_track_error_m',T.Properties.VariableNames)
    f4=figure('Color','w','Name','Cross Track Error');
    plot(t,double(T.cross_track_error_m),'LineWidth',1.3);hold on;
    for k=1:numel(switchTimes),xline(switchTimes(k),'m:','Route switch');end
    xlabel('Time [s]');ylabel('Signed cross track [m]');title('Cross Track Error');grid on;
    exportgraphics(f4,fullfile(outDir,'cross_track_error.png'),'Resolution',150);
end
fprintf('Samples: %d, switches: %d, duration: %.2f s\n',height(T),numel(switchTimes),max(t)-min(t));
