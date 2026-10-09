"""Publish synthetic joint positions; these are not measured robot states."""
import math

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState


class JointDemo(Node):
    def __init__(self):
        super().__init__('joint_demo')
        self.publisher = self.create_publisher(JointState, 'joint_states', 10)
        self.start = self.get_clock().now()
        # Experiment settings: 50 Hz publication, 0.5 rad amplitude, 0.1 Hz motion.
        self.timer = self.create_timer(0.02, self.publish_state)
        self.get_logger().info('Synthetic kinematics only: no plant or feedback controller.')

    def publish_state(self):
        now = self.get_clock().now()
        t = (now - self.start).nanoseconds * 1e-9
        omega = 2.0 * math.pi * 0.1
        state = JointState()
        state.header.stamp = now.to_msg()
        state.name = ['shoulder_joint']
        state.position = [0.5 * math.sin(omega * t)]
        state.velocity = [0.5 * omega * math.cos(omega * t)]
        self.publisher.publish(state)


def main(args=None):
    rclpy.init(args=args)
    node = JointDemo()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
