from glob import glob
from setuptools import setup

setup(
    name='lab_demo', version='0.1.0', packages=['lab_demo'],
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/lab_demo']),
        ('share/lab_demo', ['package.xml']),
        ('share/lab_demo/launch', glob('launch/*.launch.py')),
        ('share/lab_demo/urdf', glob('urdf/*.urdf')),
        ('share/lab_demo/config', glob('config/*.rviz')),
    ],
    install_requires=['setuptools'], zip_safe=True,
    maintainer='Learn Robotics', maintainer_email='maintainer@example.com',
    description='One-joint kinematic integration demo', license='Apache-2.0',
    entry_points={'console_scripts': ['joint_demo = lab_demo.joint_demo:main']},
)
