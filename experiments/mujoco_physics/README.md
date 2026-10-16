# MuJoCo 3.16.0 物理计算实验

核实日期：2026-10-16。目标是沿实际源码调用链研究关节动力学、接触求解和数值积分；不连接硬件，不训练策略。

## 1. 源码与运行库

- 官方仓库：<https://github.com/google-deepmind/mujoco>。
- 固定 tag：`3.16.0`；提交：`a892750516336d8358949f4518fcc4fbbd85beae`。
- 源码保存在本仓库的 `refs/mujoco`，保留独立 Git 元数据，主仓库已忽略 `refs/`。浅克隆包含该提交的工作文件，不含完整历史。
- **实际运行使用 PyPI 的 `mujoco==3.16.0` 预编译 wheel。没有从克隆的 C/C++ 源码构建。** Python 包版本和本地动态库版本均检查为 `3.16.0`；这不构成对 wheel 与源码的逐字节构建一致性证明。
- 来源记录在 [upstream.json](upstream.json)，依赖由 [pyproject.toml](pyproject.toml) 和 [uv.lock](uv.lock) 固定。

从仓库根目录恢复参考源码：

```shell
git clone --depth 1 --branch 3.16.0 https://github.com/google-deepmind/mujoco.git refs/mujoco
git -C refs/mujoco rev-parse HEAD
```

目标目录已存在时先核对版本，不覆盖或自动重置。报告会检查现有源码提交与工作树是否改变。源码目录不存在时，wheel 实验仍可运行，报告明确记录 `source_checkout.available=false`。

## 2. 安装和运行

在本实验目录执行，使用独立 `.venv`，不复用机器人硬件、推理或训练环境：

```shell
uv sync --locked --python 3.12
uv run --locked python -m physics_lab --output results/baseline.json
uv run --locked python -m unittest discover -s tests -v
```

完成首次安装后，可给 `uv run` 增加 `--offline` 禁止联网。未提供 `--output` 时，入口只向标准输出打印 JSON。任一物理验收项不通过时返回退出码 `1`；配置错误会抛出异常并返回非零状态。

不需要显卡、显示窗口或 OpenGL 上下文即可执行这里的计算。MuJoCo wheel 自带的 GUI 依赖仍会安装，但上述数值验收命令不打开查看器。**已验证环境仅为 macOS arm64、Python 3.12.11；Windows/Linux 和其他 Python 版本尚未实测。**

### 使用原生 UI 查看实验

保持现有依赖，不安装 MuJoCo Playground。在本实验目录运行：

```shell
# 按配置顺序查看四项；关闭当前窗口后进入下一项。
uv run --locked --offline python -m physics_lab.view

# 也可以只打开一项：torque、coupling、pendulum、contact。
uv run --locked --offline python -m physics_lab.view --case pendulum
```

入口使用官方 `mujoco.viewer.launch` 的 managed 模式，由原生查看器管理物理线程和交互。**此入口使用 `python`，不使用 `mjpython`。** 官方文档中 macOS 的 `mjpython` 要求针对 `launch_passive` 模式；这两种启动方式不能直接混用。[固定版本查看器说明](https://github.com/google-deepmind/mujoco/blob/a892750516336d8358949f4518fcc4fbbd85beae/doc/python.rst#L48-L97)

| 操作 | 用途 |
| --- | --- |
| `Space` | 暂停/继续 |
| `Simulation > Load key` | 载入增加的 `experiment_initial` 关键帧，恢复配置中的初态和输入 |
| `Rendering > Frame > Body` | 显示刚体坐标轴，便于观察均匀球形转子的转动 |
| 原生控制面板 | 检查或调整关节、执行器和仿真设置 |
| 关闭窗口 | 结束当前项；未指定 `--case` 时自动进入下一项 |

`Reset` 恢复模型默认状态，可能清除配置中的力矩或初始角；恢复原实验请使用 `Load key`。关键帧只加在内存中的模型副本里，源 MJCF、配置、依赖锁和基线报告保持不变。

UI 会连续积分直到窗口关闭，不按数值实验的 0.1 s / 2 s 自动结束。`coupling` 的原始数值验收只计算初始状态；UI 另外展示了后续运动，不能把这段轨迹当作已增加的定量验收。交互中修改力矩、关节或物理选项后，也不能直接与基线数值比较。

新增 4 项无窗口测试核对 UI 模型的动力学一致性、初态恢复及单项/顺序启动选择；当前共 14 项测试通过。这些测试使用查看器替身，不代表逐项视觉验收。

## 3. 文件职责

| 文件或目录 | 职责 |
| --- | --- |
| [configs/default.toml](configs/default.toml) | 控制输入、初始关节状态、时长和验收阈值 |
| [models](models) | 四个独立 MJCF：几何、质量、关节、执行器和仿真选项 |
| [physics_lab/common.py](physics_lab/common.py) | 加载配置、初始化状态、质量矩阵及同一时刻的动力学采样 |
| [physics_lab/experiments.py](physics_lab/experiments.py) | 四个算例各自的理论比较与指标 |
| [physics_lab/__main__.py](physics_lab/__main__.py) | 版本检查、来源核对、执行和报告输出 |
| [physics_lab/view.py](physics_lab/view.py) | 将配置和初态关键帧交给官方 managed viewer，逐项或单项查看 |
| [tests/test_physics.py](tests/test_physics.py) | 数值验收、步长收敛、接口语义和配置错误检查 |
| [tests/test_view.py](tests/test_view.py) | 无窗口检查 UI 模型、关键帧恢复及查看器调用 |
| [results/baseline.json](results/baseline.json) | 本次实测报告：运行时、配置快照、MJCF 哈希、指标和验收结果 |

模型值与实验参数放在 XML/TOML 中；解析公式中的 `2/5` 等系数来自实心球惯量关系。实验函数只支持各自说明的简化结构，含结构前提检查，不作为任意机器人模型的通用验收器。`coupling` 只做初始状态下的动力学求值，不推进时间。

## 4. 实测结果

2026-10-16，macOS arm64，MuJoCo Python 包和 C 运行库均为 3.16.0，**四个算例通过，10 项自动测试通过**。数值来自本目录的 [baseline.json](results/baseline.json)。

| 算例 | 配置与观测 | 结果及含义 |
| --- | --- | --- |
| 恒力矩 | 实心球质量 2 kg、半径 0.1 m；力矩 0.02 N·m | 惯量 0.008 kg·m²，理论和实测角加速度均为 2.5 rad/s² |
| 欧拉积分 | 步长 0.001 s，仿真 0.1 s | 连续解角度 0.0125 rad，实测 0.012625 rad；与半隐式离散解误差约 $1.21\times10^{-17}$ rad。步长减半时连续解位置误差也减半 |
| 双关节耦合 | 初态 `[0, 0.5]` rad，力矩 `[0.1, 0]` N·m | 第二关节没有驱动力矩，角加速度仍为 −1.136364805 rad/s²；质量矩阵存在非零非对角项 |
| 无阻尼摆 | 初角 0.4 rad，RK4，运行 2 s | 初始角加速度理论和实测均为 −5.611223972 rad/s²；最大能量绝对变化约 $5.68\times10^{-14}$ J |
| 球与平面 | 1 kg 球从中心高度 1 m 下落，半径 0.1 m，Newton + implicitfast | 最后 0.25 s 平均支撑力 9.81 N，与重力平衡；平均有符号间隙 −0.000367182 m |

接触过程的**最大几何穿透量约 0.0286076 m**，发生在下落冲击期间；稳定后的穿透量约 0.367 mm。这里使用时间常数 `solref="0.02 1"` 的软接触，不保证零穿透。该算例只验证法向接触与支撑，**没有验证切向摩擦、滚动摩擦或抓取**。最大动力学残差约 $2.93\times10^{-10}$，低于配置阈值 $10^{-8}$。

能量误差很小只针对这个无阻尼单摆、步长和时长，不能推广为任意机器人都严格守恒。双关节的矩阵求解比较属于内部方程一致性检查；球惯量、重力矩和支撑力的比较另外引入了简化结构的解析关系。

每次 `mj_step` 后会额外调用 `mj_forward`，把派生位置、力和加速度刷新到当前状态，避免混合不同时刻的数据。因此这里的计算时间不能用作 MuJoCo 原生步进吞吐基准。

## 5. 源码研究入口

完整说明见 [MuJoCo 物理引擎：源码调用链与最小验证](../../research/mujoco-physics-engine.md)。建议按以下顺序阅读固定版本源码：

1. `python/mujoco/functions.cc`：Python `mj_step` 调用 C API。
2. `src/engine/engine_forward.c`：`mj_step`、`mj_forwardSkip` 和分阶段计算。
3. `src/engine/engine_core_smooth.c`：质量矩阵、稀疏分解和偏置力。
4. `src/engine/engine_collision_driver.c`：碰撞检测入口。
5. `src/engine/engine_core_constraint.c`、`engine_solver.c`：约束构建及数值求解。
6. 回到 `engine_forward.c`：积分器和状态推进。

初轮数值验收没有打开 GUI；后续已增加原生查看器入口，并在本机启动顺序查看进程。用户已确认球形转子的原生窗口正常显示；桌面自动化工具未能识别此 Python 原生窗口，尚未逐项截图验收。未验证 C/C++ 编译、原生调试器单步、真实机器人、学习策略训练、MJX/MJWarp、柔性体、IPC 和 `discrete` 积分器。本实验主动拒绝 `discrete`，因为其有效质量度量和 `qacc` 语义需要单独适配。
