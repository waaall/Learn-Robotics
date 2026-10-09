from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    share = Path(get_package_share_directory('lab_demo'))
    description = (share / 'urdf' / 'one_joint.urdf').read_text()
    return LaunchDescription([
        DeclareLaunchArgument('rviz', default_value='true'),
        DeclareLaunchArgument('gallium_driver', default_value='',
                             description='Set d3d12 for WSL GPU acceleration; empty uses default.'),
        Node(package='lab_demo', executable='joint_demo', output='screen'),
        Node(package='robot_state_publisher', executable='robot_state_publisher',
             parameters=[{'robot_description': description}], output='screen'),
        Node(package='rviz2', executable='rviz2',
             arguments=['-d', str(share / 'config' / 'demo.rviz')],
             additional_env={'GALLIUM_DRIVER': LaunchConfiguration('gallium_driver')},
             condition=IfCondition(LaunchConfiguration('rviz')), output='screen'),
    ])
