# WSL ROS 2 最小实验

目标环境：Ubuntu 24.04 / ROS 2 Jazzy。

第一阶段只验证 ROS 通信、关节命名、URDF 和 TF。`joint_demo` 发布合成状态，**没有物理仿真、真实反馈或 PD 控制器**，不能据此计算真实跟踪性能。URDF 尺寸、限位、50 Hz 发布周期、0.5 rad 振幅、0.1 Hz 运动频率均为实验设定。模型没有惯量与碰撞参数，不用于动力学实验。

## 安装

先在 Ubuntu 终端进入本仓库根目录，以下安装、构建和复测命令均从仓库根目录开始执行（脚本自行使用 Bash，兼容当前默认 Zsh）：

```bash
bash experiments/ros2_ws/install_jazzy.sh --minimal
```

`--minimal` 安装当前实验所需的 ROS Base、RViz2、robot_state_publisher、C++/Python demo 节点、colcon 扩展、rosdep 与 mesa-utils，使用 `--no-install-recommends`。需要完整桌面开发套件时使用 `--desktop`；不带选项仍保留原来的 Desktop + ros-dev-tools 安装行为。后续新增实验按其 `package.xml` 补充依赖。

普通用户需要交互输入 sudo 密码，root 用户通常无需密码。脚本会启用 Universe、安装官方 ros2-apt-source 软件源配置包与所选组件，并初始化 rosdep。软件源配置包版本从官方 GitHub release 获取并打印。不会自动修改 shell 启动文件、重启 WSL、安装 Gazebo 或全面升级系统。任何下载、APT 或 rosdep 错误都会停止；修复后可重跑。

如果第一步 `apt-get update` 返回 HTTP 403，先检查 Ubuntu 软件源的访问，而不是修改 ROS 包。备份源配置后，可切换到可达的 Ubuntu 官方源，保留发行版、组件与签名验证，再重跑脚本。[Ubuntu 官方包管理文档](https://ubuntu.com/server/docs/how-to/software/package-management/)说明了软件源配置与索引更新。

依据：[ROS 2 Jazzy 官方安装文档源码](https://github.com/ros2/ros2_documentation/blob/jazzy/source/Installation/Ubuntu-Install-Debs.rst)、[官方软件源配置步骤](https://github.com/ros2/ros2_documentation/blob/jazzy/source/Installation/_Apt-Repositories.rst)。

## 构建

以下命令先进入 Bash。通过软链接引用当前仓库源码，构建产物留在 Linux 文件系统的 `~/ros2_ws`；链接目标从仓库相对路径解析，不依赖仓库所在的盘符或目录。

```bash
bash
source /opt/ros/jazzy/setup.bash
mkdir -p ~/ros2_ws/src
ln -s "$(realpath experiments/ros2_ws/src/lab_demo)" ~/ros2_ws/src/lab_demo
cd ~/ros2_ws
rosdep install --from-paths src --ignore-src --rosdistro jazzy -y
colcon build --symlink-install --parallel-workers 2
source install/setup.bash
ros2 launch lab_demo demo.launch.py gallium_driver:=llvmpipe
```

如果链接已经存在，先核对 `readlink -f ~/ros2_ws/src/lab_demo`，不要覆盖其他项目。后续启动时，加载 ROS 和工作区环境后直接运行 launch 命令。RViz 配置已包含 RobotModel 和 Grid，模型话题为 `/robot_description`，Fixed Frame 为 `base_link`。通信正常时应看到橙色连杆绕 Y 轴摆动。关闭时在启动终端 Ctrl+C。`gallium_driver` 仅影响 RViz 进程，不修改系统设置。

## 验证

可运行 `glxinfo -B` 查看渲染器；llvmpipe 表示软件渲染。

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

回到仓库根目录后，可在自己的 Ubuntu 终端复测，脚本会启动测试节点与 RViz，20 秒采样后关闭本次启动的进程，失败返回非零退出码：

```bash
bash
source /opt/ros/jazzy/setup.bash
source ~/ros2_ws/install/setup.bash
python3 experiments/ros2_ws/verify_runtime.py
```

脚本默认使用 ROS 域 87 和软件渲染；可用 `--domain 0` 切换域。若节点无法发现或收不到消息，可尝试关闭代理/VPN 的 TUN 模式后重试。
