# 机器人学习资料入口

按技术主题组织资料；书籍、视频、文章、代码、研究笔记和实验记录作为条目类型标注，不与技术主题并列。仅建立已有内容的分类。

## 机器人学基础与综合参考

跨模块的教材、手册与背景资料集中在此；具体笔记和实验归入下方对应主题。

- **教材：** [《机器人学导论》](https://book.douban.com/subject/30325317/)：中文版 PDF 在 `reference/` 文件夹。
- **综合手册：** [《机器人手册》](https://book.douban.com/subject/21334808/)：英文第二版 PDF 在 `reference/` 文件夹，中文第一版三卷在 Apple Books。
- **教材与配套资源：** [《现代机器人学》网站](https://hades.mech.northwestern.edu/index.php/Modern_Robotics)。
  - **书籍：** 英文版 PDF 在 `reference/` 文件夹，中文版在 Apple Books。
  - **视频：** [配套课程](https://modernrobotics.northwestern.edu/nu-gm-book-resource/introduction-autoplay/#department)。
  - **代码：** [教材配套代码仓库](https://github.com/NxRLab/ModernRobotics)。
- **背景文章／线索：** [机器人项目都涉及哪些技术，怎么组织起来](https://zhuanlan.zhihu.com/p/634848960)。
- **背景讨论／线索：** [机器人研究热点](https://www.zhihu.com/question/328583927)。

以上两项知乎资料保留为跨模块背景线索，本轮仅调整分类，未核实其中的技术判断。

## 运动学与动作

- **研究笔记：** [机械臂运动学基础：理解动作，定位失败](research/robotics-kinematics-foundations.md)：按《现代机器人学》组织必要理论，用于核对动作接口与排查实验失败。

## 传统控制与机器人算法

这组资料以传统的显式建模、优化控制与模块化机器人算法为主，用于模型预测控制（Model Predictive Control，MPC）入门及小规模对照实验，不作为学习现代机器人前必须完成的课程。其中交互指南也涉及学习模型与 MPC 的结合。

- [MathWorks：Understanding Model Predictive Control](https://www.mathworks.com/videos/series/understanding-model-predictive-control.html)
  - **来源与用途：** MathWorks 官方教学视频，优先用于理解预测、在线优化、约束、预测与控制时域，以及参数选择。
  - **局限与日期：** 后续实现偏 MATLAB/Simulink，不能代替系统性的控制理论教材；[首集](https://www.mathworks.com/videos/understanding-model-predictive-control-part-1-why-use-mpc--1526484715269.html)发表于 2018-05-16，系列各集日期不同。
- [MPC Finally Explained：交互式指南](https://psemnani.github.io/mpc-finally-explained/)
  - **来源与用途：** Parastoo Semnani 的个人教学指南，通过四水箱等交互示例解释“预测多步、执行一步、重新规划”，并介绍学习模型与 MPC 的结合。
  - **局限与日期：** 适合建立直觉，不作为稳定性、安全性或通用性能结论的唯一依据；页面中的算法耗时比较不是普遍工程保证。页面标注最近修订为 2026 年 5 月。
- [PythonRobotics：文档](https://atsushisakai.github.io/PythonRobotics/)／[代码仓库](https://github.com/AtsushiSakai/PythonRobotics)
  - **来源与用途：** 项目官方文档与教学代码，覆盖定位、规划、路径跟踪、机械臂等算法，可用于阅读实现和建立小规模实验基线。
  - **局限与版本：** 不是仅讲控制的课程；教学仿真成功不代表可直接部署真机。项目持续更新，本次未锁定代码提交或验证运行环境，实验时需记录所用版本与配置。

**按需使用：** 研究主线是现代学习策略与实际机器人系统；需要理解 MPC 的预测、约束与在线优化时，先看 MathWorks，再用交互指南辅助理解；需要算法基线时查 PythonRobotics。若要做控制对照，可选其[倒立摆 LQR/MPC 示例](https://atsushisakai.github.io/PythonRobotics/modules/10_inverted_pendulum/inverted_pendulum.html)，统一模型、初始状态、输入约束与扰动条件，不直接把默认示例结果当作公平比较。倒立摆对照用于理解控制取舍，不是 VLA 替代实验。VLA 已接管的具体环节与仍保留的算法见下一节。

## 学习策略与 VLA

视觉语言动作模型（Vision-Language-Action，VLA）不只是输出文字建议。以下系统已经由模型直接生成操作动作或关节运动目标，不应把这些公开事实写成“将来可能替代”：

- **公开披露 — DeepMind RT-2（CoRL 2023）：** 相机图像与任务指令直接映射到末端位置/旋转增量、夹爪指令和任务终止标志。对象选择与逐步末端动作生成由同一个 VLA 承担，而不只是让语言模型挑选技能名称、再交给另一个动作策略生成末端动作。[论文发表记录](https://proceedings.mlr.press/v229/zitkovich23a.html)；[论文正文 §1、§3.2，arXiv v1](https://arxiv.org/html/2307.15818v1)。
- **公开披露与代码 — π₀/openpi 的 ALOHA 实现（π₀ 发表于 RSS 2025）：** 图像、语言与关节状态输入策略，模型生成动作序列；ALOHA 执行接口中的动作是双臂绝对关节位置与夹爪目标，`RealEnv.step()` 将关节目标直接传给 `set_joint_positions()`。任务动作路径绕过了独立的“末端轨迹规划 → 逆运动学（Inverse Kinematics，IK）求解 → 关节目标”链，关节运动目标生成已由 VLA 接管。这不表示模型在显式求解 IK，也不表示关节驱动被替换。[论文发表记录](https://www.roboticsproceedings.org/rss21/p010.html)；[π₀ 论文 §III、附录 A-D，arXiv v1](https://arxiv.org/html/2410.24164v1)；[ALOHA 执行代码](https://github.com/Physical-Intelligence/openpi/blob/main/examples/aloha_real/real_env.py#L16-L34)及[目标下发](https://github.com/Physical-Intelligence/openpi/blob/main/examples/aloha_real/real_env.py#L134-L140)。[Interbotix SDK](https://github.com/Interbotix/interbotix_ros_toolboxes/blob/main/interbotix_xs_toolbox/interbotix_xs_modules/src/interbotix_xs_modules/arm.py#L125-L136)在该关节接口中检查限位并发布目标，区别于另一个调用 IK 的末端接口。
- **公开代码 — OpenVLA 的 LIBERO 执行链：** 模型生成动作，经夹爪约定转换后传给 `env.step()`；环境仍默认采用操作空间控制（Operational Space Control，OSC）的 `OSC_POSE` 控制器。因此这里模型承担的是操作动作生成，OSC 并未被替代。[策略执行代码](https://github.com/openvla/openvla/blob/main/experiments/robot/libero/run_libero_eval.py#L179-L203)；[环境初始化](https://github.com/openvla/openvla/blob/main/experiments/robot/libero/libero_utils.py#L17-L23)；[控制器配置](https://github.com/Lifelong-Robot-Learning/LIBERO/blob/master/libero/libero/envs/env_wrapper.py#L10-L55)。

**趋势归纳（工程判断）：** 在这些操纵系统中，原先需要手工编排或独立动作生成模块承担的职责，已被端到端学习策略接管；这是传统模块化动作生成流程被 VLA 替代的具体趋势依据，不是对未来能力的猜测。但“某职能由模型承担”和“某个算法被实测击败”是两种判断：上述证据不能写成 MPC、LQR、PID 或 PythonRobotics 中全部算法已被 VLA 淘汰，也不能移植为 Tesla 的部署事实。

## 运行系统：ROS 2、通信与可视化

- **实验记录：** [WSL ROS 2 最小实验](experiments/ros2_ws/README.md)
