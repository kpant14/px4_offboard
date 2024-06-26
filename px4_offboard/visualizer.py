#!/usr/bin/env python
############################################################################
#
#   Copyright (C) 2022 PX4 Development Team. All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
#
# 1. Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in
#    the documentation and/or other materials provided with the
#    distribution.
# 3. Neither the name PX4 nor the names of its contributors may be
#    used to endorse or promote products derived from this software
#    without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
# FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
# COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
# INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
# BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS
# OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED
# AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
# LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN
# ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
#
############################################################################

__author__ = "Kartik Anand Pant"
__contact__ = "kpant14@gmail.com"

import navpy
import rclpy
import numpy as np
from rclpy.node import Node
from rclpy.qos import QoSProfile, QoSReliabilityPolicy, QoSHistoryPolicy
from px4_msgs.msg import VehicleAttitude
from px4_msgs.msg import VehicleLocalPosition
from geometry_msgs.msg import PoseStamped, TransformStamped
from tf2_ros import TransformBroadcaster
from nav_msgs.msg import Path


def vector2PoseMsg(frame_id, position, attitude):
    pose_msg = PoseStamped()
    # msg.header.stamp = Clock().now().nanoseconds / 1000
    pose_msg.header.frame_id = frame_id
    pose_msg.pose.orientation.w = attitude[0]
    pose_msg.pose.orientation.x = attitude[1]
    pose_msg.pose.orientation.y = attitude[2]
    pose_msg.pose.orientation.z = attitude[3]
    pose_msg.pose.position.x = position[0]
    pose_msg.pose.position.y = position[1]
    pose_msg.pose.position.z = position[2]
    return pose_msg

class PX4Visualizer(Node):
    def __init__(self):
        super().__init__("visualizer")

        # Configure subscritpions
        qos_profile = QoSProfile(
            reliability=QoSReliabilityPolicy.BEST_EFFORT,
            history=QoSHistoryPolicy.KEEP_LAST,
            depth=1,
        )
        self.declare_parameter('px4_ns', 'px4_1')
        
        self.ns = self.get_parameter('px4_ns').get_parameter_value().string_value
        self.attitude_sub = self.create_subscription(
            VehicleAttitude,
            f'{self.ns}/fmu/out/vehicle_attitude',
            self.vehicle_attitude_callback,
            qos_profile,
        )
        self.local_position_sub = self.create_subscription(
            VehicleLocalPosition,
            f'{self.ns}/fmu/out/vehicle_local_position',
            self.vehicle_local_position_callback,
            qos_profile,
        )
     
        self.vehicle_path_pub = self.create_publisher(
            Path, f'{self.ns}/px4_visualizer/vehicle_path', 10
        )
        self.setpoint_path_pub = self.create_publisher(
            Path, f'{self.ns}/px4_visualizer/setpoint_path', 10
        )

        # Gazebo Model Origin 
        self.lla_ref = np.array([24.484043629238872, 54.36068616768677, 0]) # latlonele -> (deg,deg,m)
        self.waypoint_idx = 0
        self.waypoints_lla = np.array([
           [24.484326113268185, 54.360644616972564, 30],
           [24.48476311664666, 54.3614948536716, 30],
           [24.485097533474377, 54.36197496905472, 30],
           [24.485400216562002, 54.3625570084458, 30], 
           [24.48585179883862, 54.36321951405934, 30], 
           [24.486198417650844, 54.363726451568475, 30], 
           [24.486564563238797, 54.36423338904003, 0], 
        ])
        self.wpt_set_ = navpy.lla2ned(self.waypoints_lla[:,0], self.waypoints_lla[:,1],
                    self.waypoints_lla[:,2],self.lla_ref[0], self.lla_ref[1], self.lla_ref[2],
                    latlon_unit='deg', alt_unit='m', model='wgs84')

        # Initialize the transform broadcaster
        self.tf_broadcaster = TransformBroadcaster(self)
        self.vehicle_attitude = np.array([1.0, 0.0, 0.0, 0.0])
        self.vehicle_local_position = np.array([0.0, 0.0, 0.0])
        self.vehicle_local_velocity = np.array([0.0, 0.0, 0.0])
        self.setpoint_position = np.array([0.0, 0.0, 0.0])
        self.vehicle_path_msg = Path()
        self.setpoint_path_msg = Path()
        # trail size
        self.trail_size = 1000
        timer_period = 0.05  # seconds
        self.timer = self.create_timer(timer_period, self.cmdloop_callback)

    def vehicle_attitude_callback(self, msg):
        # TODO: handle NED->ENU transformation
        self.vehicle_attitude[0] = msg.q[0]
        self.vehicle_attitude[1] = -msg.q[1]
        self.vehicle_attitude[2] = -msg.q[2]
        self.vehicle_attitude[3] = msg.q[3]

    def vehicle_local_position_callback(self, msg):
        # TODO: handle NED->ENU transformation
        self.vehicle_local_position[0] = msg.y
        self.vehicle_local_position[1] = msg.x
        self.vehicle_local_position[2] = -msg.z
        self.vehicle_local_velocity[0] = msg.vy
        self.vehicle_local_velocity[1] = msg.vx
        self.vehicle_local_velocity[2] = -msg.vz

    def append_vehicle_path(self, msg):
        self.vehicle_path_msg.poses.append(msg)
        if len(self.vehicle_path_msg.poses) > self.trail_size:
            del self.vehicle_path_msg.poses[0]

    def cmdloop_callback(self):
        vehicle_pose_msg = vector2PoseMsg(
            "map", self.vehicle_local_position, self.vehicle_attitude
        )
        t = TransformStamped()

        # Read message content and assign it to
        # corresponding tf variables
        t.header.stamp = self.get_clock().now().to_msg()
        t.header.frame_id = 'map'
        t.child_frame_id = 'Estimated_Pose'
        t.transform.translation.x = vehicle_pose_msg.pose.position.x
        t.transform.translation.y = vehicle_pose_msg.pose.position.y
        t.transform.translation.z = vehicle_pose_msg.pose.position.z
        t.transform.rotation.x = vehicle_pose_msg.pose.orientation.x
        t.transform.rotation.y = vehicle_pose_msg.pose.orientation.y
        t.transform.rotation.z = vehicle_pose_msg.pose.orientation.z
        t.transform.rotation.w = vehicle_pose_msg.pose.orientation.w
        # Send the transformation
        self.tf_broadcaster.sendTransform(t)
        
        # Publish set waypoints
        setpoint_path_msg = Path()
        setpoint_pose_msg = vector2PoseMsg("map", [0.0, 0.0, 0.0], [0.0, 0.0, 0.0, 1.0])
        setpoint_path_msg.poses.append(setpoint_pose_msg)
        for i in range(self.wpt_set_.shape[0]):
            enu = np.array([self.wpt_set_[i,1], self.wpt_set_[i,0], -self.wpt_set_[i,2]])
            setpoint_pose_msg = vector2PoseMsg("map", enu, [0.0, 0.0, 0.0, 1.0])
            setpoint_path_msg.poses.append(setpoint_pose_msg)
      
        setpoint_path_msg.header = setpoint_pose_msg.header
        self.setpoint_path_pub.publish(setpoint_path_msg)


        # Publish time history of the vehicle path
        self.vehicle_path_msg.header = vehicle_pose_msg.header
        self.append_vehicle_path(vehicle_pose_msg)
        self.vehicle_path_pub.publish(self.vehicle_path_msg)

def main(args=None):
    rclpy.init(args=args)

    px4_visualizer = PX4Visualizer()

    rclpy.spin(px4_visualizer)

    px4_visualizer.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()