# MuJoCo 物理引擎：源码调用链与最小验证

核实日期：2026-10-16。研究版本：[MuJoCo 3.16.0](https://github.com/google-deepmind/mujoco/releases/tag/3.16.0)，固定提交 `a892750516336d8358949f4518fcc4fbbd85beae`。已克隆官方完整工作文件的浅历史副本到 `refs/mujoco`，未修改上游源码。

本文的实现判断来自该提交的源码及随仓库提供的计算文档；实验使用相同版本的 PyPI wheel，未自行编译引擎。实验代码、运行方法和完整数值报告见 [mujoco_physics](../experiments/mujoco_physics/README.md)。本轮研究标准刚体、多关节和软接触的常规路径；`discrete`、柔性体及 IPC 另行研究。

## 1. 输入、状态与输出

MuJoCo 根据模型参数、当前状态和控制输入计算下一个状态。模型编译和仿真步进具有不同职责。

| 部分 | 主要内容 | 对应结构 |
| --- | --- | --- |
| 模型参数 | 刚体树、关节轴、质量、质心、惯量、几何、执行器、摩擦和求解选项 | `mjModel`；Python 为 `MjModel` |
| 当前状态 | 广义位置 `qpos`、速度 `qvel`、执行器内部状态 `act`、时间等 | `mjData`；Python 为 `MjData` |
| 外部输入 | `ctrl`、广义外力 `qfrc_applied`、刚体外力/力矩 `xfrc_applied` | `mjData` 中的输入数组 |
| 计算结果 | 质量矩阵、偏置力、执行器力、接触信息、约束力、加速度；积分后更新位置和速度 | `mjData` 中的结果数组 |

`nq` 是位置表示的维度，`nv` 是速度/自由度维度，`nu` 是标量控制输入数。这些值可以不同：自由刚体需要 3 个位置分量和 4 个四元数分量，即 `nq=7`；线速度与角速度各 3 维，即 `nv=6`。执行器激活动力学、延迟等还会引入额外状态，不能一律把完整系统状态写成只有 $2n$ 个数。

来源：[状态数组定义](https://github.com/google-deepmind/mujoco/blob/a892750516336d8358949f4518fcc4fbbd85beae/include/mujoco/mjdata.h#L176-L199)、[维度定义](https://github.com/google-deepmind/mujoco/blob/a892750516336d8358949f4518fcc4fbbd85beae/include/mujoco/mjmodel.h#L244-L247)、[浮动刚体说明](https://github.com/google-deepmind/mujoco/blob/a892750516336d8358949f4518fcc4fbbd85beae/doc/overview.rst)。

## 2. Python 如何进入物理引擎

### 模型编译

`MjModel.from_xml_path(...)` 经 Python C++ wrapper 调用 `mj_loadXML`。该函数先解析 XML，得到可编辑模型描述 `mjSpec`，再调用 `mj_compile` 生成运行时 `mjModel`。MJCF 中的几何、惯量和关节关系被转换成预分配数组及索引，步进阶段反复使用这些编译结果。

来源：[Python 加载 wrapper](https://github.com/google-deepmind/mujoco/blob/a892750516336d8358949f4518fcc4fbbd85beae/python/mujoco/structs_wrappers.cc#L366-L389)、[XML 解析和编译入口](https://github.com/google-deepmind/mujoco/blob/a892750516336d8358949f4518fcc4fbbd85beae/src/xml/xml_api.cc#L37-L51)。

### 仿真步进

Python `mujoco.mj_step(model, data)` 的绑定直接调用 `::mj_step(m_ptr, d_ptr)`；可通过 `nstep` 在 C++ wrapper 内重复调用，调用期间释放 GIL。常规 CPU 仿真的动力学运算由 C 引擎执行。

来源：[Python 步进绑定](https://github.com/google-deepmind/mujoco/blob/a892750516336d8358949f4518fcc4fbbd85beae/python/mujoco/functions.cc#L112-L129)。MJX 和 MJWarp 具有另外的计算后端；这里没有运行它们。

## 3. 一次 `mj_step` 的实际顺序

固定版本的主要函数位于 `src/engine/engine_forward.c`：

| 顺序 | 函数 | 主要操作 |
| --- | --- | --- |
| 1 | `mj_step` | 检查位置和速度，调用 `mj_forward`，检查加速度，再选择积分器 |
| 2 | `mj_fwdPosition` | 正运动学；构造并分解质量矩阵；碰撞检测；约束、约束岛与雅可比相关计算；执行器传动计算 |
| 3 | `mj_fwdVelocity` | 刚体、肌腱和执行器速度；被动力；约束参考量；偏置力 |
| 4 | `mjcb_control` | 若注册官方控制回调，则在状态相关量计算后生成控制输入 |
| 5 | `mj_fwdActuation` | 将输入和执行器状态转换为广义驱动力；处理增益、偏置、传动和限幅等 |
| 6 | `mj_fwdAcceleration` | 汇总非约束力并求无约束加速度 `qacc_smooth` |
| 7 | 约束阶段 | 根据接触、限位、等式等约束计算约束力及最终 `qacc` |
| 8 | 积分器 | 更新执行器状态、速度、位置和时间 |

传感器计算穿插在位置、速度和加速度阶段。这里列出的是主路径，未把缓存、休眠、插件和特殊模型的分支展开成通用步骤。

RK4 在积分器内部还会用中间状态重复计算动力学，并可再次调用控制回调；不能假定每次 `mj_step` 只执行一次控制求值。[RK4 子阶段实现](https://github.com/google-deepmind/mujoco/blob/a892750516336d8358949f4518fcc4fbbd85beae/src/engine/engine_forward.c#L1673-L1689)。

来源：[位置与速度阶段](https://github.com/google-deepmind/mujoco/blob/a892750516336d8358949f4518fcc4fbbd85beae/src/engine/engine_forward.c#L119-L236)、[前向计算与步进入口](https://github.com/google-deepmind/mujoco/blob/a892750516336d8358949f4518fcc4fbbd85beae/src/engine/engine_forward.c#L1956-L2067)。

**`mj_forward` 计算当前状态下的动力学，不推进仿真时间；`mj_step` 还会执行积分。** 实验通过独立测试核对这一区别。`mj_step1`/`mj_step2` 可用于两阶段控制，但该版本在这种拆分下会把 RK4 回退为 Euler，不能把它当作所有积分器的等价拆法。[两阶段实现](https://github.com/google-deepmind/mujoco/blob/a892750516336d8358949f4518fcc4fbbd85beae/src/engine/engine_forward.c#L2070-L2134)。

## 4. 关节力矩如何变成加速度

### 4.1 广义坐标与关节耦合

刚体按照父子关系组成运动学树，用广义坐标表示允许的运动。普通树形关节的运动关系由坐标结构直接表达；闭环机构可通过额外等式约束实现。正运动学沿刚体树递归计算世界坐标中的位姿。[运动学实现](https://github.com/google-deepmind/mujoco/blob/a892750516336d8358949f4518fcc4fbbd85beae/src/engine/engine_core_smooth.c#L41-L249)。

常规连续时间刚体路径可以写成：

$$
M(q)\dot v+c(q,v)
=\tau_{\mathrm{passive}}+\tau_{\mathrm{actuator}}+\tau_{\mathrm{applied}}+J(q)^\mathsf{T}f
$$

其中 $v$ 是广义速度；对于单自由度铰链，$v=\dot q$。$M$ 是广义质量矩阵，$c$ 包含重力和速度相关偏置，$f$ 是约束空间的力。刚体外力还需要投影到广义坐标中，此处并入 $\tau_{\mathrm{applied}}$。

**质量矩阵通常包含非零非对角项，因此各关节的加速度相互耦合。** “有 $n$ 个独立构型自由度”仍然需要求解整个耦合动力学系统。

### 4.2 质量矩阵和偏置力的实际算法

- `mj_makeM` 调用复合刚体惯量算法 `mj_crb`，从子刚体向父刚体累加复合惯量，再结合自由度的运动子空间计算 $M$，并加入相关转子/肌腱惯量。
- `mj_factorM` 对对称正定质量矩阵进行稀疏 $L^\mathsf{T}DL$ 分解。
- `mj_rne(..., flg_acc=0, ...)` 使用递归 Newton–Euler 计算不含加速度项的偏置力。
- 在本轮未启用有效质量度量的模型中，非约束加速度由线性系统求解得到。数学上可以记为 $M^{-1}\tau$；实现利用已分解矩阵求解，避免每步显式构造完整逆矩阵。

来源：[CRB 与分解实现](https://github.com/google-deepmind/mujoco/blob/a892750516336d8358949f4518fcc4fbbd85beae/src/engine/engine_core_smooth.c#L1900-L2005)、[RNE 实现](https://github.com/google-deepmind/mujoco/blob/a892750516336d8358949f4518fcc4fbbd85beae/src/engine/engine_core_smooth.c#L2362-L2490)。

### 4.3 对应的运行时数组

引擎先计算：

$$
\texttt{qfrc\_smooth}
=\texttt{qfrc\_passive}-\texttt{qfrc\_bias}
+\texttt{qfrc\_actuator}+\texttt{qfrc\_applied}
+\operatorname{project}(\texttt{xfrc\_applied})
$$

随后常规路径求解：

$$
M\,\texttt{qacc\_smooth}=\texttt{qfrc\_smooth},
\qquad
M\,\texttt{qacc}=\texttt{qfrc\_smooth}+\texttt{qfrc\_constraint}
$$

实验用后一等式计算残差；它检查给定模型内的动力学一致性，不证明惯量、摩擦等模型参数与某台实物相符。

来源：[非约束力与加速度计算](https://github.com/google-deepmind/mujoco/blob/a892750516336d8358949f4518fcc4fbbd85beae/src/engine/engine_forward.c#L1004-L1075)。该版本还包含 `efm_active` 的有效质量矩阵分支；不能把上式未经适配用于全部新积分模式。

## 5. 碰撞、接触和摩擦如何参与计算

### 5.1 先计算几何接触，再建立力学约束

`mj_collision` 先筛选可能碰撞的刚体/几何对，再进行更细的几何检测。输出接触位置、接触坐标系、距离及参与几何等信息。`mj_makeConstraint` 把接触与等式约束、关节限位、关节摩擦损失等一起实例化，形成约束雅可比和相关数组。

来源：[碰撞检测入口](https://github.com/google-deepmind/mujoco/blob/a892750516336d8358949f4518fcc4fbbd85beae/src/engine/engine_collision_driver.c#L625-L690)、[约束构建](https://github.com/google-deepmind/mujoco/blob/a892750516336d8358949f4518fcc4fbbd85beae/src/engine/engine_core_constraint.c#L2656-L2690)。接触记录的存在也需要结合是否实际激活力学约束判断，不能单凭 `ncon` 推断支撑力大小。

### 5.2 软约束与凸优化

常规接触模型通过软约束及正则化描述接触，法向力和摩擦力受可行域约束。概念上，约束空间的逆惯量及对偶问题可以写为：

$$
A=JM^{-1}J^\mathsf{T},
\qquad
f=\underset{\lambda\in\Omega}{\operatorname{argmin}}
\left[\frac12\lambda^\mathsf{T}(A+R)\lambda+b^\mathsf{T}\lambda\right]
$$

$R$ 是软约束正则化；$b$ 包含自由运动的约束空间加速度与参考加速度之差；$\Omega$ 包含等式、摩擦损失及接触力的可行条件。椭圆摩擦锥对应锥约束，多面体摩擦锥对应线性不等式。具体参考项随约束类型处理；应以固定版本文档的定义及实现为准。

引擎提供三类主要求解器：**Newton 和 CG 求解约化原问题，PGS 求解对偶问题**。上式用于说明约束力的数学结构，不表示所有求解器都显式构造 $A$ 或直接迭代力变量。本轮落球模型显式选择 Newton；无约束时引擎直接采用 `qacc_smooth`。

来源：[固定版本计算文档的 Constraint solver / Algorithms](https://github.com/google-deepmind/mujoco/blob/a892750516336d8358949f4518fcc4fbbd85beae/doc/computation/index.rst)、[求解器选择和无约束分支](https://github.com/google-deepmind/mujoco/blob/a892750516336d8358949f4518fcc4fbbd85beae/src/engine/engine_forward.c#L1210-L1320)。

### 5.3 接触参数与可观测结果

- `friction` 配置滑动、扭转和滚动相关摩擦系数；启用哪些方向还取决于 `condim`。
- `condim=3` 表示一个法向和两个切向接触力方向；本轮使用椭圆摩擦锥。
- `solref` 和 `solimp` 调节约束参考响应与阻抗等，影响接触柔顺性、穿透量和数值行为。
- 有限步长和软接触允许出现一定几何穿透；穿透量、接触冲击与稳定支撑应分别观察。

本轮球体落地后平均支撑力达到 9.81 N，同时仍有约 0.367 mm 稳态穿透；冲击期间最大穿透约 28.6 mm。该结果对应给定参数的软接触，没有测量真实材料，也没有验证切向摩擦。改变 `solref`、步长或速度后需要重新验证。[本地模型](../experiments/mujoco_physics/models/drop_ball.xml)、[实测报告](../experiments/mujoco_physics/results/baseline.json)。

## 6. 数值积分如何得到下一时刻

本轮恒力矩模型选择 `Euler`，无阻尼条件下使用半隐式更新：

$$
v_{k+1}=v_k+h\dot v_k,
\qquad
q_{k+1}=q_k+h v_{k+1}
$$

这个位置更新式适用于普通标量关节。涉及四元数时，`mj_integratePosInd` 根据关节类型更新姿态，不能直接逐元素使用 $q+h v$。

来源：[速度和位置推进](https://github.com/google-deepmind/mujoco/blob/a892750516336d8358949f4518fcc4fbbd85beae/src/engine/engine_forward.c#L1463-L1487)、[按关节类型积分位置](https://github.com/google-deepmind/mujoco/blob/a892750516336d8358949f4518fcc4fbbd85beae/src/engine/engine_support.c#L695-L736)。

对于恒角加速度 $a$、从静止开始、总时间 $T=Nh$ 的单关节：

$$
q_{\mathrm{continuous}}=q_0+\frac12aT^2,
\qquad
q_{\mathrm{Euler}}=q_0+\frac12a(T^2+Th)
$$

因此位置误差是 $\frac12aTh$。本轮 $a=2.5$ rad/s²、$T=0.1$ s、$h=0.001$ s，误差为 0.000125 rad，与实测一致；步长减半，误差也减半。这说明可以在力矩和加速度计算正确时，仍然观察到有限步长的积分误差。

`Euler` 对关节阻尼另有隐式处理；`implicit`、`implicitfast` 和 RK4 的更新方式也不同。3.16.0 还包含较新的 `discrete` 及 IPC 分支，本轮未验证，实验主动拒绝 `discrete`，避免把不同的有效度量和步进语义混用。[积分器分派](https://github.com/google-deepmind/mujoco/blob/a892750516336d8358949f4518fcc4fbbd85beae/src/engine/engine_forward.c#L2039-L2064)。

## 7. 控制策略和物理引擎如何衔接

传统控制器或学习策略产生控制输入，执行器模型把输入转换成力，物理引擎求解运动及接触。**具体动作语义由执行器配置决定**：本轮 `motor` 配合 `gear=1`，标量输入对应关节力矩；配置位置伺服时，输入可表示位置目标，再由执行器模型根据跟踪误差生成力。不能把任意 `ctrl` 数组都解释成关节角度或力矩。

这一层的计算已在 `mj_fwdActuation` 中实现，包括传动映射到 `qfrc_actuator`；生成输入的控制器可以在外部 Python 循环运行，也可以注册官方 `mjcb_control` 回调。本轮仅给定恒定输入，没有训练或加载神经网络。[执行器力和传动映射](https://github.com/google-deepmind/mujoco/blob/a892750516336d8358949f4518fcc4fbbd85beae/src/engine/engine_forward.c#L363-L411)、[广义力映射及限幅](https://github.com/google-deepmind/mujoco/blob/a892750516336d8358949f4518fcc4fbbd85beae/src/engine/engine_forward.c#L974-L997)。

与实际学习系统对应的公开例子是 **MuJoCo Playground 2025 年报告中的足式运动任务**：策略接收关节状态、IMU 相关量、速度指令等观测，输出缩放后的关节位置动作；目标位置通过 PD 控制器转换成力矩，再由仿真器计算物理状态。策略负责动作生成，PD 负责反馈力矩计算，物理引擎负责动力学与接触。该事实只对应报告的相关任务，不能推广成所有 VLA 系统的控制接口。[报告附录 B.2](https://arxiv.org/html/2502.08844v1#A2.SS2)。

## 8. 验证状态与后续研究

### 已完成

1. 官方源码 tag 和提交固定，工作树保持干净；独立 Python 环境及依赖锁定。
2. 沿源码核对模型加载、Python/C 调用、分阶段前向动力学和积分入口。
3. 四个最小物理算例运行通过；10 项测试涵盖解析比较、矩阵一致性、积分误差随步长变化、时间语义和错误输入。
4. 报告保存版本、配置快照、模型哈希和验收阈值。测量时每步额外执行 `mj_forward`，刷新到当前状态；不作为性能基准。

### 尚未验证

- 从源码构建 C/C++ 引擎、在调试器中断点跟踪并核对 wheel 的构建来源。
- 碰撞检测的具体形状算法、摩擦锥求解器内部迭代和接触参数敏感性扫描。
- 真实电机、电流环、柔顺结构、传动间隙及材料接触的辨识与校准。
- MJX/MJWarp 并行仿真、柔性体、IPC、`discrete`、学习策略训练和真实机器人迁移。

建议下一轮先用现有落球模型扫描步长及 `solref`，观察冲击穿透和稳定支撑，再从原生调试器跟踪 `mj_fwdConstraint`。这属于后续研究计划，本轮未执行。
