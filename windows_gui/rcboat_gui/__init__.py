"""Windows RC Boat controller GUI."""

# Source runs and PyInstaller both use the ROS-free canonical control helpers.
import sys
from pathlib import Path
_shared = Path(__file__).resolve().parents[2] / 'catkin_ws/src/rcboat_ros/src'
if _shared.is_dir():
    sys.path.insert(0,str(_shared))

__version__ = "2.4.1"
