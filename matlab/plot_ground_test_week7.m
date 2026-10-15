function outputFiles = plot_ground_test_week7(testFolder)
%PLOT_GROUND_TEST_WEEK7 Rebuild the Week-7 walking-validation charts.
%   outputFiles = plot_ground_test_week7("C:\path\ground_test_YYYYMMDD_HHMMSS")
%
% The lecture's L/R thrust-vectoring plot is represented by this boat's
% actual architecture: throttle PWM plus rudder steering PWM/angle.

testFolder = string(testFolder);
sampleFile = fullfile(testFolder, "ground_test.csv");
referenceFile = fullfile(testFolder, "reference_routes.csv");
metricFile = fullfile(testFolder, "route_metrics.csv");
assert(isfile(sampleFile), "Missing ground_test.csv: %s", sampleFile);
assert(isfile(referenceFile), "Missing reference_routes.csv: %s", referenceFile);
assert(isfile(metricFile), "Missing route_metrics.csv: %s", metricFile);

samples = readtable(sampleFile, "VariableNamingRule", "preserve");
references = readtable(referenceFile, "VariableNamingRule", "preserve");
metrics = readtable(metricFile, "VariableNamingRule", "preserve");
assert(height(samples) > 0, "ground_test.csv contains no samples");

t = samples.elapsed_time_s;
outputFiles = strings(0, 1);

figure("Color", "w", "Position", [80 80 1500 900]);
layout = tiledlayout(2, 2, "TileSpacing", "compact", "Padding", "compact");
title(layout, "Week-7 Ground Validation - Path and Target-Path Decision");

nexttile;
hold on; grid on; axis equal;
routeIds = unique(string(references.route_id), "stable");
colors = lines(max(1, numel(routeIds)));
for index = 1:numel(routeIds)
    rows = string(references.route_id) == routeIds(index);
    routeName = string(references.route_name(find(rows, 1)));
    plot(references.longitude(rows), references.latitude(rows), "--", ...
        "Color", colors(index, :), "LineWidth", 1.8, "DisplayName", routeName);
end
plot(samples.longitude, samples.latitude, "k-", "LineWidth", 2.0, ...
    "DisplayName", "Actual Path");
xlabel("Longitude (deg)"); ylabel("Latitude (deg)");
title("Reference Routes and Actual GPS Path"); legend("Location", "best");

nexttile;
hold on; grid on;
plot(t, samples.target_path_distance_m, "b-", "LineWidth", 1.8, ...
    "DisplayName", "Current Target Path distance");
plot(t, samples.multipath_switch_threshold_m, "r--", "LineWidth", 1.5, ...
    "DisplayName", "Switch threshold");
if islogical(samples.multipath_switch)
    switchRows = samples.multipath_switch;
elseif isnumeric(samples.multipath_switch)
    switchRows = samples.multipath_switch ~= 0;
else
    switchRows = strcmpi(string(samples.multipath_switch), "true") | ...
                 string(samples.multipath_switch) == "1";
end
scatter(t(switchRows), samples.target_path_distance_m(switchRows), 55, "filled", ...
    "MarkerFaceColor", [0.85 0.2 0.1], "DisplayName", "Target Path switch");
xlabel("Time (s)"); ylabel("Distance (m)");
title("Target Path Distance: <=2 m Keep, >2 m Switch"); legend("Location", "best");

nexttile;
hold on; grid on;
metricRouteIds = unique(string(metrics.route_id), "stable");
metricColors = lines(max(1, numel(metricRouteIds)));
for index = 1:numel(metricRouteIds)
    rows = string(metrics.route_id) == metricRouteIds(index);
    routeName = string(metrics.route_name(find(rows, 1)));
    plot(metrics.elapsed_time_s(rows), metrics.heading_error_deg(rows), ...
        "LineWidth", 1.5, "Color", metricColors(index, :), ...
        "DisplayName", routeName + " heading error");
end
yline(0, "r--", "Desired 0 deg", "LineWidth", 1.2, "HandleVisibility", "off");
xlabel("Time (s)"); ylabel("Heading angular error (deg)");
title("Per-Subroute Heading Angular Error"); legend("Location", "best");

nexttile;
hold on; grid on;
activeIds = string(samples.active_route_id);
for index = 1:numel(routeIds)
    rows = activeIds == routeIds(index);
    stairs(t, double(rows) * index, "LineWidth", 1.5, ...
        "Color", colors(index, :), "DisplayName", routeIds(index));
end
xlabel("Time (s)"); ylabel("Active Target Path index");
title("Active Target Path and Switch Instants"); legend("Location", "best");

pathOutput = fullfile(testFolder, "week7_path_and_switch.png");
exportgraphics(gcf, pathOutput, "Resolution", 300);
outputFiles(end + 1) = pathOutput;

figure("Color", "w", "Position", [100 100 1500 900]);
layout = tiledlayout(2, 2, "TileSpacing", "compact", "Padding", "compact");
title(layout, "Week-7 Ground Validation - Navigation Output Response");

nexttile;
hold on; grid on;
plot(t, samples.desired_steering_pwm, "Color", [0.45 0.45 0.45], ...
    "LineStyle", "--", "LineWidth", 1.2, "DisplayName", "Desired steering PWM");
plot(t, samples.final_steering_pwm, "b-", "LineWidth", 1.8, ...
    "DisplayName", "Final steering PWM");
xlabel("Time (s)"); ylabel("Steering PWM");
title("Rudder Servo Command"); legend("Location", "best");

nexttile;
hold on; grid on;
plot(t, samples.desired_throttle_pwm, "Color", [0.45 0.45 0.45], ...
    "LineStyle", "--", "LineWidth", 1.2, "DisplayName", "Desired throttle PWM");
plot(t, samples.final_throttle_pwm, "Color", [0.85 0.25 0.1], ...
    "LineWidth", 1.8, "DisplayName", "Final throttle PWM");
xlabel("Time (s)"); ylabel("Throttle PWM");
title("Propulsion Command (Lecture L/R Thrust Equivalent)");
legend("Location", "best");

nexttile;
hold on; grid on;
plot(t, samples.desired_rudder_angle_deg, "k--", "LineWidth", 1.2, ...
    "DisplayName", "Desired rudder angle");
plot(t, samples.final_rudder_angle_deg, "m-", "LineWidth", 1.8, ...
    "DisplayName", "Final rudder angle");
yline(0, "r:", "HandleVisibility", "off"); xlabel("Time (s)"); ylabel("Rudder angle (deg)");
title("Rudder Direction and Response"); legend("Location", "best");

nexttile;
hold on; grid on;
plot(t, samples.speed_mps, "Color", [0.1 0.65 0.9], "LineWidth", 1.8, ...
    "DisplayName", "GPS speed");
plot(t, samples.target_speed_mps, "Color", [0.7 0.2 0.9], ...
    "LineStyle", "--", "LineWidth", 1.5, "DisplayName", "Desired speed");
xlabel("Time (s)"); ylabel("Speed (m/s)");
title("Actual and Desired Speed"); legend("Location", "best");

controlOutput = fullfile(testFolder, "week7_control_response.png");
exportgraphics(gcf, controlOutput, "Resolution", 300);
outputFiles(end + 1) = controlOutput;

fprintf("Created:\n%s\n", strjoin(outputFiles, newline));
end
