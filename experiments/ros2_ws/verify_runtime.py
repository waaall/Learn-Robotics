"""Bounded integration check; stops only the subprocess groups it starts."""
import argparse
import os
import signal
import subprocess
import tempfile
import time

import rclpy
from sensor_msgs.msg import JointState
from std_msgs.msg import String
from tf2_ros import Buffer, TransformListener, TransformException


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--driver', default='llvmpipe')
    parser.add_argument('--domain', type=int, default=87)
    args = parser.parse_args()
    os.environ['ROS_DOMAIN_ID'] = str(args.domain)
    processes = []
    rclpy.init()
    node = rclpy.create_node('lab_runtime_check')
    states, greetings, transforms = [], [], []
    subscriptions = [
        node.create_subscription(JointState, '/joint_states', states.append, 10),
        node.create_subscription(String, '/chatter', greetings.append, 10),
    ]
    buffer = Buffer()
    listener = TransformListener(buffer, node)
    with tempfile.TemporaryFile(mode='w+t') as log:
        try:
            for command in [
                ['ros2', 'launch', 'lab_demo', 'demo.launch.py', f'gallium_driver:={args.driver}'],
                ['ros2', 'run', 'demo_nodes_cpp', 'talker'],
            ]:
                processes.append(subprocess.Popen(command, stdout=log, stderr=log, start_new_session=True))
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                rclpy.spin_once(node, timeout_sec=0.1)
                try:
                    transforms.append(buffer.lookup_transform('base_link', 'arm_link', rclpy.time.Time()))
                except TransformException:
                    pass
            log.flush()
            log.seek(0)
            output = log.read()
            print(output[-7000:])
            print('Domain:', node.context.get_domain_id(), 'Graph:', node.get_node_names(), 'counts:', len(states), len(greetings), len(transforms))
            assert all(p.poll() is None for p in processes), 'A launched process exited early'
            assert len(states) >= 20, f'Only {len(states)} joint states received'
            assert all(s.name == ['shoulder_joint'] and len(s.position) == 1 for s in states)
            assert all(abs(s.position[0]) <= 0.500001 for s in states)
            assert max(s.position[0] for s in states) - min(s.position[0] for s in states) > 0.1
            assert len({(s.header.stamp.sec, s.header.stamp.nanosec) for s in states}) > 10
            assert greetings and any('Hello World' in s.data for s in greetings), 'C++ -> Python communication failed'
            assert transforms, 'No base_link -> arm_link transform'
            assert max(t.transform.rotation.y for t in transforms) - min(t.transform.rotation.y for t in transforms) > 0.01
            assert '[rviz2-' in output and 'OpenGl version' in output, 'RViz OpenGL initialization not observed'
            assert '[ERROR]' not in output and 'process has died' not in output, 'Runtime error in launch log'
            print(f'PASS: {len(states)} joint states, {len(greetings)} C++ messages, {len(transforms)} TF samples; RViz initialized.')
            print('This checks runtime and OpenGL initialization, not a visual screenshot or dynamics.')
        finally:
            for process in processes:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGINT)
            for process in processes:
                try:
                    process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
            node.destroy_node()
            rclpy.shutdown()


if __name__ == '__main__':
    main()
