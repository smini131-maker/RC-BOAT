from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription(
        [
            Node(
                package="rcboat_ros2_bridge",
                executable="bridge_node",
                name="rcboat_bridge",
                output="screen",
                parameters=[
                    {
                        "daemon_host": "127.0.0.1",
                        "daemon_port": 8765,
                        "gps_frame_id": "gps_link",
                    }
                ],
            )
        ]
    )
