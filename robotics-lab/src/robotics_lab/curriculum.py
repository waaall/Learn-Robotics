"""课程内容与实验引用独立组织；不依赖 experiments/。"""

from copy import deepcopy

MODEL_SOURCE = "https://github.com/google-deepmind/mujoco_menagerie/tree/62ab00f2bc44f6f20c1c9b7a13f3fb1dd41a4e35/franka_emika_panda"
FUNCTION_SOURCE = "https://mujoco.readthedocs.io/en/stable/APIreference/APIfunctions.html"


def _lesson(identifier, title, mode, question, summary, concepts, steps, observations, exercise, prerequisites, duration=3.0):
    return {"id": identifier, "experiment_id": identifier, "title": title, "mode": mode,
            "question": question, "summary": summary, "concepts": concepts, "steps": steps,
            "observations": observations, "exercise": exercise, "prerequisites": prerequisites,
            "duration": duration, "adapter": "panda", "status": "available", "sources": [
                {"title": "Panda 模型、参数与执行器来源", "url": MODEL_SOURCE},
                {"title": "MuJoCo 正向计算与雅可比接口", "url": FUNCTION_SOURCE}]}


PANDA_LESSONS = [
    _lesson("panda-structure", "结构、关节与坐标系", "structure",
            "七个转动关节如何连接基座与夹爪？", "识别连杆、关节轴、关节限位与末端参考点。",
            [{"title": "构型与自由度", "text": "本课使用固定基座 Panda。机械臂有七个转动关节；夹爪有两个受耦合约束的滑动关节。模型的广义位置还包含场景中方块的自由位姿。蓝色末端参考点定义在手部局部 z 轴 0.1034 m 处，红、绿、蓝短轴分别表示末端 x、y、z 方向。悬停关节标签可查看限位。",
              "formula": r"\boldsymbol q_a=(q_1,\ldots,q_7)^\mathsf T"},
             {"title": "夹爪开口", "text": "开口是左右手指滑动量之和，范围为 0 至 0.08 m。本课直接设置构型，研究结构关系，不执行动力学积分。",
              "formula": r"w=q_{f1}+q_{f2}"}],
            ["打开实验，旋转相机观察基座、七个关节和夹爪。", "每次只调整一个关节，再点击应用参数。", "改变夹爪开口，对照末端位置和旋转矩阵。"],
            ["各关节允许范围，单位 rad", "世界坐标系中的末端位置与旋转矩阵", "夹爪实际开口，单位 m"],
            "寻找两个不同的关节，比较它们对夹爪位置和朝向的影响。", "无需前置课程"),
    _lesson("panda-fk", "正运动学", "fk", "给定关节角度，如何计算末端位姿？",
            "调整关节构型，观察关节空间到末端位姿的映射。",
            [{"title": "逐级坐标变换", "text": "各关节变换按运动链顺序相乘。平移向量 p 表示末端参考点的世界坐标，R 表示末端坐标轴在世界坐标系中的方向。计算使用模型定义和 MuJoCo 的 mj_forward。",
              "formula": r"{}^WT_E(\boldsymbol q)=\prod_i {}^{i-1}T_i(q_i)=\begin{bmatrix}R&p\\0&1\end{bmatrix}"},
             {"title": "几何实验的执行方式", "text": "应用参数直接更新关节位置并重新计算派生量。屏幕中出现构型变化时，没有经过执行器跟踪过程；本课用于研究几何映射。",
              "formula": r"\boldsymbol p=f_p(\boldsymbol q)"}],
            ["记录初始末端位置。", "将关节 2 增加 0.1 rad 并应用参数。", "再改变关节 4，比较位置和姿态的变化。"],
            ["七个关节的当前构型", "末端世界位置，单位 m", "末端旋转矩阵的列向量"],
            "改变关节后再恢复原值，检查末端位姿是否恢复。", "结构、关节与坐标系"),
    _lesson("panda-joint-control", "关节位置控制", "joint-control", "关节目标如何转化为实际运动？",
            "设置关节位置目标与伺服增益，比较目标、响应和控制力矩。",
            [{"title": "位置伺服", "text": "本课沿用上游 general 执行器中的位置与速度反馈形式。七路 ctrl 为目标角度，MuJoCo 计算执行器作用并积分运动。实际力矩还受模型执行器限幅约束。",
              "formula": r"\tau_i=K_{p,i}(q_{d,i}-q_i)-K_{d,i}\dot q_i"},
             {"title": "增益与重力补偿", "text": "增益倍率 a 将原始 Kp 乘 a、Kd 乘平方根 a。可切换额外重力补偿；它由当前构型、零速度条件下的偏置力计算。目标改变后，实际关节需要时间跟踪。",
              "formula": r"K_p'=aK_p,\qquad K_d'=\sqrt{a}K_d"}],
            ["选择一个关节，设置小幅目标变化并应用参数。", "观察目标与实际角度曲线以及实际执行器力矩。", "恢复初态，改变增益倍率，重复相同目标。"],
            ["目标角度与实际角度，单位 rad", "关节跟踪误差与实际执行器力矩", "开关重力补偿后稳态误差的变化"],
            "使用 0.1 与 0.5 两个增益倍率，比较同一目标的响应。", "正运动学"),
    _lesson("panda-gravity", "重力与重力补偿", "gravity", "机械臂保持一个构型需要什么输入？",
            "关闭关节位置伺服，对照有无重力补偿时的运动。",
            [{"title": "重力项", "text": "本课将机械臂七路位置伺服增益设为零，保留模型关节阻尼。补偿开启时，由相同构型、零速度的辅助状态求得重力项，并作为关节外加广义力输入。",
              "formula": r"M(q)\ddot q+h(q,\dot q)=\tau+\tau_{\mathrm{ext}}"},
             {"title": "补偿条件", "text": "补偿重力不会消除已有速度、外部扰动、碰撞和模型误差。每次对照应恢复同一初态。本课中的伺服力矩为零，表中重力项给出补偿所需的广义力。",
              "formula": r"g(q)=h(q,0),\qquad \tau_{\mathrm{ext}}=g(q)"}],
            ["保持补偿开启，观察各关节与初始构型的偏差。", "恢复初态，关闭补偿并应用参数。", "观察重力导致的运动，再恢复初态重新开启补偿。"],
            ["补偿输入的七个重力力矩，单位 N·m", "关节位置和速度的变化", "发生桌面接触后的运动变化"],
            "解释为什么在运动过程中开启重力补偿，机械臂仍可能继续运动。", "关节位置控制"),
    _lesson("panda-jacobian", "雅可比与奇异构型", "jacobian", "关节速度如何映射为末端速度？",
            "设置单关节速度，观察平移雅可比、末端速度和奇异值。",
            [{"title": "瞬时速度映射", "text": "使用 mj_jacSite 计算末端参考点的世界坐标平移雅可比，显示其中对应机械臂的 3×7 子矩阵。关节速度单位为 rad/s，输出平移速度单位为 m/s。",
              "formula": r"\dot{\boldsymbol p}=J_p(\boldsymbol q)\dot{\boldsymbol q}"},
             {"title": "构型与奇异值", "text": "本课按设定速度更新几何构型，不经过动力学。平移雅可比最小奇异值减小时，某些平移方向的速度生成能力下降。该指标只描述平移任务；不能用于判定完整六维位姿任务的全部奇异性。",
              "formula": r"J_p=U\Sigma V^\mathsf T"}],
            ["先设置一个构型并应用参数。", "选择运动关节和小幅速度，例如 0.05 rad/s。", "比较 J 的对应列、关节速度和末端速度，暂停后更换构型。"],
            ["平移雅可比 3×7 矩阵", "末端平移速度，单位 m/s", "三个平移雅可比奇异值"],
            "固定同一关节速度，在两个构型下比较末端速度方向。", "正运动学"),
    _lesson("panda-ik", "逆运动学与冗余", "ik", "给定末端位置，怎样求关节构型？",
            "设置三维位置目标，观察阻尼最小二乘求解、误差与关节限位。",
            [{"title": "局部迭代求解", "text": "从当前构型出发，根据位置误差和雅可比计算关节增量，再施加步长与关节限位约束。阻尼系数为 0.02，每次最多 160 次迭代，位置收敛阈值为 0.1 mm。",
              "formula": r"\Delta q=J_p^\mathsf T(J_pJ_p^\mathsf T+\lambda^2I)^{-1}(p_d-p)"},
             {"title": "冗余与未收敛", "text": "本课仅约束末端位置，朝向自由。七个关节可以产生不同解，解与初始构型有关。目标可能不可达或迭代未收敛；界面报告实际残差。求解未包含碰撞避障，结果以几何方式显示。",
              "formula": r"e_p=\|p_d-f_p(q)\|_2"}],
            ["将目标设置在机械臂附近，例如 (0.45, 0.12, 0.42) m。", "应用参数，对照绿色目标点、末端位置与残差。", "设置较远目标，观察未收敛信息，再恢复初态。"],
            ["位置目标与实际末端位置", "迭代次数、收敛状态和位置残差", "最终关节构型及限位"],
            "从两个不同初态求同一位置目标，比较最终构型。", "雅可比与奇异构型"),
    _lesson("panda-trajectory", "轨迹生成与跟踪", "trajectory", "相同终点，不同时间曲线会产生什么响应？",
            "比较三秒关节轨迹的线性和五次插值，以及实际伺服跟踪。",
            [{"title": "关节空间轨迹", "text": "从实际当前角度出发，以三秒时长到达设置的目标。五次插值在起止时刻的参考速度和加速度为零；线性插值在开始和停止处存在参考速度跳变。",
              "formula": r"q_d(t)=q_0+s(u)(q_1-q_0),\quad s(u)=10u^3-15u^4+6u^5,\quad u=t/3"},
             {"title": "参考与跟踪", "text": "每个物理步更新轨迹参考，再由位置伺服执行。曲线中的最终关节目标与轨迹中间参考有不同含义；记录同时保存实际状态与跟踪过程。本课不进行碰撞规划。",
              "formula": r"e(t)=q_d(t)-q(t)"}],
            ["修改终点关节角度，选择五次插值。", "点击执行轨迹，观察三秒运动和关节曲线。", "恢复初态，使用线性插值和相同终点重复实验。"],
            ["实际关节角度与参考角度", "运动期间的轨迹跟踪误差", "改变增益后实际响应的变化"],
            "比较两种插值在运动开始和结束附近的响应。", "关节位置控制、逆运动学与冗余", 4.0),
    _lesson("panda-grasp", "夹爪接触与抓取", "grasp", "夹爪怎样通过接触抬起并放置方块？",
            "运行分阶段抓取，观察真实接触、方块高度和最终放置位置。",
            [{"title": "任务阶段与控制", "text": "顺序执行预抓取、下降、闭合、抬升、移动、下降、松开和撤离。各阶段通过固定朝向的逆运动学生成关节目标，再由位置伺服执行。任务使用显式规则与传统控制，未接入 AI 策略。",
              "formula": r"p_d\ \longrightarrow\ q_d\ \longrightarrow\ \tau\ \longrightarrow\ (q,\dot q)"},
             {"title": "接触与成功判定", "text": "方块质量 0.08 kg、边长 0.05 m。它与手指通过 MuJoCo 接触和摩擦作用，没有绑定或吸附。实际高度曾超过 0.32 m 记为抬升；任务结束后方块距放置中心小于 0.06 m、且高度接近桌面支撑高度，才报告放置成功。静态对称抓取可用下式作近似分析。",
              "formula": r"2\mu N\ge mg"}],
            ["恢复初态，观察桌面方块和绿色放置区域。", "点击执行抓取，观察约 16 秒的任务过程。", "检查方块实际高度、阶段状态和放置判定；改变摩擦后重复。"],
            ["实际接触数量和方块位置", "方块高度随时间的变化", "实际抬升和最终放置判定"],
            "降低手指与方块的滑动摩擦系数，比较抓取结果并解释失败阶段。", "逆运动学、轨迹跟踪、基础接触实验", 18.0),
]


def courses():
    from .catalog import catalog
    experiments = catalog()
    physics_lessons = []
    for identifier in ("pendulum", "drop-ball"):
        exp = experiments[identifier]
        formula = (r"I\ddot\theta=-mg\ell_c\sin\theta" if identifier == "pendulum"
                   else r"m\ddot z=F_n-mg")
        physics_lessons.append({"id": identifier, "experiment_id": identifier, "title": exp.title,
            "mode": "physics", "adapter": "basic", "question": "给定初态和物理条件，会产生怎样的运动？",
            "summary": exp.summary, "prerequisites": "基础力学", "status": "available",
            "concepts": [{"title": "物理模型", "text": exp.explanation, "formula": formula}],
            "steps": ["打开交互实验，使用窗口中的暂停与步进观察运动。", "运行独立验证，观察曲线并下载记录。", "恢复初态，重复观察并对照计算结果。"],
            "observations": list(exp.observations), "exercise": "对照运动过程与曲线，解释主要变化发生的时刻。",
            "sources": [{"title": "MuJoCo 计算接口", "url": FUNCTION_SOURCE}]})
    return [{"id": "panda-basics", "title": "Panda 机械臂基础", "subtitle": "从关节构型到接触抓取",
             "robot": "Franka Emika Panda", "level": "基础 → 进阶", "description": "原理讲解与交互实验并行，逐节研究机械臂的几何、动力学和控制。",
             "lessons": deepcopy(PANDA_LESSONS)},
            {"id": "physics-basics", "title": "基础物理实验", "subtitle": "动力学与接触的基本现象",
             "robot": "基础机构", "level": "基础", "description": "通过单摆与落球建立运动、能量和接触的观察方法。",
             "lessons": physics_lessons}]


def get_lesson(identifier):
    for course in courses():
        for index, lesson in enumerate(course["lessons"]):
            if lesson["id"] == identifier:
                return {**lesson, "course_id": course["id"], "course_title": course["title"], "number": index + 1}
    raise ValueError(f"未知课时：{identifier}")
