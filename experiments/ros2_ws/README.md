# WSL ROS 2 最小实验

日期：2026-10-09。目标环境：Ubuntu 24.04 / ROS 2 Jazzy。

第一阶段只验证 ROS 通信、关节命名、URDF 和 TF。`joint_demo` 发布合成状态，**没有物理仿真、真实反馈或 PD 控制器**，不能据此计算真实跟踪性能。URDF 尺寸、限位、50 Hz 发布周期、0.5 rad 振幅、0.1 Hz 运动频率均为实验设定。模型没有惯量与碰撞参数，不用于动力学实验。

## 安装

在 Ubuntu 终端执行（脚本自行使用 Bash，兼容当前默认 Zsh）：

```bash
bash /mnt/d/zx-code/ML/Learn-Robotics/experiments/ros2_ws/install_jazzy.sh
```

需要交互输入 sudo 密码。脚本会启用 Universe、安装官方 ros2-apt-source 软件源配置包、ROS Desktop、开发工具与 mesa-utils，并初始化 rosdep。软件源配置包版本从官方 GitHub release 获取并打印。不会自动修改 shell 启动文件、重启 WSL、安装 Gazebo 或全面升级系统。任何下载、APT 或 rosdep 错误都会停止；修复后可重跑。

依据：[ROS 2 Jazzy 官方安装文档源码](https://github.com/ros2/ros2_documentation/blob/jazzy/source/Installation/Ubuntu-Install-Debs.rst)、[官方软件源配置步骤](https://github.com/ros2/ros2_documentation/blob/jazzy/source/Installation/_Apt-Repositories.rst)。核实日期同上。

## 构建

以下命令先进入 Bash。为保持当前仓库只有一个源码副本，暂时通过软链接引用 D 盘源码，构建产物留在 Linux 文件系统；后续若迁移整个仓库至 Linux，再调整链接，不同时维护两份代码。

```bash
bash
source /opt/ros/jazzy/setup.bash
mkdir -p ~/ros2_ws/src
ln -s /mnt/d/zx-code/ML/Learn-Robotics/experiments/ros2_ws/src/lab_demo ~/ros2_ws/src/lab_demo
cd ~/ros2_ws
rosdep install --from-paths src --ignore-src --rosdistro jazzy -y
colcon build --symlink-install --parallel-workers 2
source install/setup.bash
ros2 launch lab_demo demo.launch.py gallium_driver:=llvmpipe
```

如果链接已经存在，先核对 `readlink -f ~/ros2_ws/src/lab_demo`，不要覆盖其他项目。工作区已创建并构建，可直接 source 后启动。RViz 配置已包含 RobotModel 和 Grid，模型话题为 `/robot_description`，Fixed Frame 为 `base_link`。通信正常时应看到橙色连杆绕 Y 轴摆动。关闭时在启动终端 Ctrl+C。`gallium_driver` 仅影响 RViz 进程，不修改系统设置。

## 验证

先运行 `glxinfo -B` 查看渲染器；若为 llvmpipe，记录为软件渲染，不能声称 GPU 加速验收通过。

无图形时可先启动：

```bash
ros2 launch lab_demo demo.launch.py rviz:=false
```

另开 Ubuntu 终端进入 Bash 后：

```bash
bash
source /opt/ros/jazzy/setup.bash
source ~/ros2_ws/install/setup.bash
ros2 topic echo /joint_states --once
ros2 run tf2_ros tf2_echo base_link arm_link
```

验收：状态关节名为 shoulder_joint，位置在 ±0.5 rad 内；TF 随时间变化；RViz 无模型或变换错误。这里只验收同一 WSL 内通信。可另外用 `ros2 run demo_nodes_cpp talker` 与 `ros2 run demo_nodes_py listener` 在两个已 source 的终端验证 C++/Python 通信。

复现时保存 `dpkg-query -W 'ros-jazzy-*'`、`uname -r`、`glxinfo -B` 和构建输出。当前机器检查：Ubuntu 24.04.4、Python 3.12.3、WSL 2.5.10.0、WSLg 1.0.66、12 个逻辑处理器、约 12 GiB 内存、无 swap。

## 安装后检查记录（2026-10-09）

- 用户完成安装；`rosdep check` 通过，`colcon build` 成功构建 lab_demo。
- 组件版本：rclpy 7.1.12、RViz2 14.1.24、rmw_fastrtps_cpp 8.4.4、Fast DDS 2.14.7。
- 默认 OpenGL 使用 llvmpipe 软件渲染。临时指定 d3d12 后 glxinfo 报告 Intel Arc 加速，但实际 RViz 随后出现 `D3D12: Removing Device` 并以 -11 退出，因此 **GPU 渲染验收失败**。软件渲染在多次 12–20 秒短测中成功初始化且未观察到崩溃；未作长期性能测试或截图验收。
- 首轮集成检查收到关节状态、C++ 消息与变化的 TF，但因 RViz 崩溃整体验收失败。TUN 开启期间的后续测试出现订阅端只发现自身、收不到消息；默认域、隔离域、UDPv4、本机发现与回环网卡配置均未解决。
- 普通 UDP 回环收发通过；网卡 eth3 为 198.18.0.1，优先默认路由指向 198.18.0.2。代理/VPN TUN 影响是待验证假设，并未确定根因。没有修改代理、防火墙或 WSL 全局设置。
- Qt 提示 `/run/user/1000` 权限为 0755 而期望 0700；尚未修改，该提示没有阻止软件渲染初始化。

**关闭 TUN 后复测通过：** 用户关闭 TUN 后，使用同一验证脚本、ROS 域 87、默认 Fast DDS 通信设置及 llvmpipe 软件渲染，20 秒采样收到 925 条关节状态、19 条 C++ talker 消息、1244 次 TF 查询结果（查询次数不是独立发布消息数）；关节范围、状态变化、时间戳及 TF 变化断言均通过，节点图包含发布节点、订阅节点和 RViz。RViz OpenGL 4.5 初始化成功，短测内未崩溃，脚本退出码为 0。测试进程已清理。

工程判断：这次开关前后的对照支持 TUN 与此前 DDS 通信异常有关，但未定位到具体代理规则或底层机制；不推广为所有 TUN 实现都会影响 ROS。当前可用条件是 **TUN 关闭 + 软件渲染 + 同一 WSL 实例**；尚未验证跨机通信、长期运行、GPU 稳定性或真实控制性能。

可在自己的 Ubuntu 终端复测，脚本会启动测试节点与 RViz，20 秒采样后关闭本次启动的进程，失败返回非零退出码：

```bash
bash
source /opt/ros/jazzy/setup.bash
source ~/ros2_ws/install/setup.bash
python3 /mnt/d/zx-code/ML/Learn-Robotics/experiments/ros2_ws/verify_runtime.py
```

脚本默认使用 ROS 域 87 和软件渲染；可用 `--domain 0` 做对照。当前机器已验证关闭 TUN 后恢复节点发现，开展本地实验时先保持 TUN 关闭。若以后需要同时使用 TUN，另行验证路由和代理绕行规则，不直接修改全局防火墙。下一步可推进单关节动力学与 PD 跟踪实验。

## 下一步

通信与显示通过后，增加单关节动力学对象和独立 PD 控制器，明确区分目标与测量；记录误差、限幅和扰动响应。需要接触、重力等场景时再引入 Gazebo Harmonic 与 ros2_control。学习策略沿用明确的动作接口，避免先创建空的算法模块。
