from setuptools import find_packages, setup

package_name = "rcboat_ros2_bridge"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=("test",)),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        ("share/" + package_name + "/launch", ["launch/bridge.launch.py"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="smini131-maker",
    maintainer_email="smini131-maker@users.noreply.github.com",
    description="Non-invasive ROS 2 bridge for the RC Boat daemon",
    license="MIT",
    entry_points={
        "console_scripts": [
            "bridge_node = rcboat_ros2_bridge.bridge_node:main",
        ],
    },
)
