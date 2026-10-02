# Optimus：AI 与传统控制

核实日期：2026-10-02。本文用于建立研究问题与证据边界，后续随技术披露更新。

## 结论

公开材料支持 Tesla Optimus 团队把学习方法用于操作和全身运动，也支持其继续研究物理建模、电机控制及位置/力矩控制。现有材料不足以重建某一代量产机器人的完整控制链。

值得研究的核心问题是：策略的动作输出是什么，哪些反馈回路把它变成物理动作，哪些模型用于离线训练，哪些用于在线运行，以及各处的约束和失败条件。

## 公开证据及其限度

以下招聘正文主要来自检索工具返回的官方页面索引文本。直接打开部分页面时只获得岗位标题与元数据，因此它们作为官方招聘披露线索使用，不能视为当前完整产品技术文档。招聘原文未提供可靠发布日期；核实日期不等于发布日期。

| 来源 | 可以支持的判断 | 不能据此确定的内容 |
| --- | --- | --- |
| [Tesla AI & Robotics](https://www.tesla.com/AI) | 官方将平衡、导航、感知、物理交互列为 Optimus 软件工作范围 | 页面中车辆的网络、算力与传感器数据是否适用于 Optimus |
| [Applied Reinforcement Learning Engineer, Whole Body Controls, Optimus，职位 276000](https://www.tesla.com/sv_SE/careers/search/job/applied-reinforcement-learning-engineer-whole-body-controls-optimus-276000) | 招聘披露全身运动强化学习，以及通过物理建模、域随机化和学习动力学改善仿真迁移的工作 | 实际策略动作空间、推理频率、在线控制器结构与已部署能力 |
| [AI Engineer, Manipulation, Optimus，职位 224501](https://www.tesla.com/en_PR/careers/search/job/ai-engineer-manipulation-optimus-224501) | 招聘披露学习式操作栈及操作过程的建模、仿真、规划和控制 | 网络架构、数据规模、运行时模块边界和泛化成功率 |
| [Robotics Physics Modeling Engineer, Model Based Design, Optimus，职位 270616](https://www.tesla.com/he_IL/careers/search/job/robotics-physics-modeling-engineer-model-based-design-optimus-270616) | 招聘披露运动学与动力学建模、电机控制及位置/力矩控制相关需求 | Optimus 是否实际在线采用 PID、MPC、某种驱动方案或特定求解器 |
| [Internship, Reinforcement Learning Engineer, Optimus (Summer 2026)，职位 253454](https://www.tesla.com/da_DK/careers/search/job/internship-reinforcement-learning-engineer-optimus-summer-2026-253454) | 该岗位资料提及强化/模仿学习和由视觉完成语言条件任务的策略 | 当前部署了某个 VLA 架构；不能由岗位名称推断当前招聘或生产状态 |

“全身控制使用强化学习”和“仍需物理与电机控制工作”可以同时成立。招聘资料不足以确定两者在同一台机器人上的具体组合方式。

## 模块如何结合：待逐步验证的工程分析

下表是通用研究框架，**不是已经确认的 Optimus 内部架构**。所列算法是比较对象，不意味着每个系统都使用它们。

| 模块 | 学习方法可能承担的部分 | 传统方法值得研究的部分 | 对 Optimus 仍需查证的接口 |
| --- | --- | --- | --- |
| 任务与行为 | 视觉/语言条件策略、技能选择 | 状态机、任务约束、完成与失败判断 | 指令怎样变成策略条件或动作？ |
| 感知与状态估计 | 视觉特征、物体理解、学习式状态估计 | 标定、同步、运动学、滤波与传感器融合 | 策略依赖哪些外部和本体传感器？ |
| 全身运动与操作 | 强化学习、模仿学习产生协调动作 | 运动学、动力学、轨迹优化、模型预测控制（MPC）、全身控制（WBC） | 这些方法是在线组件、训练工具、基线，还是已被策略替代？ |
| 关节与接触 | 输出目标位置、速度、力矩或阻抗参数 | PD/PID、重力补偿、动力学前馈、阻抗/力控制 | 策略动作空间与反馈控制器分别是什么？ |
| 电机与驱动 | 可研究学习补偿或参数估计 | 电流反馈、PI、FOC、饱和与电气保护 | 电机类型、驱动器模式和内部反馈回路是什么？ |
| 系统运行 | 学习模型推理、数据闭环 | 实时调度、通信时序、日志、看门狗与故障响应 | 推理延迟、失联/越界响应和验证条件是什么？ |

传统算法的重要性应结合具体接口判断。即使学习策略直接输出力矩，也不能推断驱动器内部电流回路消失；反过来，位置目标加 PD 也不是学习控制唯一可行的结构。

## 一个具体的学习策略与反馈控制组合

以下是通用示例，不能称为 Optimus 的已知控制链：

```text
任务条件 + 传感器/状态
          ↓
      学习策略
          ↓  期望关节位置/速度
  PD 反馈 + 可选动力学前馈
          ↓  期望关节力矩
    执行器传动与电驱
          ↓
       实际运动
          └── 测量状态反馈到策略与控制器
```

在这个示例中，可用如下关节控制律讨论接口：

$$
\tau_{\mathrm{cmd}} = K_p(q_d-q) + K_d(\dot q_d-\dot q) + \tau_{\mathrm{ff}}.
$$

其中策略可以产生目标 $q_d$，反馈项纠正偏差，前馈项可补偿重力或其他动力学效应。最终输出还受到驱动器和机械约束限制。积分项是否需要，应根据偏差来源、补偿方法和饱和条件分析。

[Isaac Lab 的控制文档](https://isaac-sim.github.io/IsaacLab/v2.2.0/source/overview/core-concepts/motion_generators.html)给出了直接力矩、位置 PD 和可变阻抗等不同接口，说明比较学习策略时必须先讲清动作空间。[Modern Robotics 第 11.4 节](https://modernrobotics.northwestern.edu/nu-gm-book-resource/11-4-motion-control-with-torque-or-force-inputs-part-3-of-3/)解释了反馈与动力学前馈的组合及模型误差的限制。这些资料解释一般原理，不证明 Tesla 采用这些实现。

电流回路是另一处需要单独研究的边界。[TI 的电机控制讲解](https://www.ti.com/ko-kr/video/3881562077001)说明了 PI 与 FOC、级联反馈回路的关系。这里不能把 FOC 当成 PID 的别名，也不能推断 Tesla 使用 TI 的芯片或控制实现。

## 研究原则的取舍

- 工程问题约束阅读范围；顶刊与少量顶会奠基论文提供精选方法证据。官方产品材料和教材解决不同类型的问题。
- 高水平发表不能证明生产成熟度；公司展示不能独自证明方法与自主程度。
- 学习策略、模型控制与简单反馈控制按接口与任务比较，避免先决定赢家。
- 缺失的闭源细节保留为未知；可以用开源系统做对照实验，但不能把对照系统改名为 Optimus 复现。

