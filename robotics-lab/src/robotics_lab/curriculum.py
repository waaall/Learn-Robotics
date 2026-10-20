"""课程内容与实验引用独立组织；不依赖 experiments/。"""

from copy import deepcopy

MODEL_SOURCE = "https://github.com/google-deepmind/mujoco_menagerie/tree/62ab00f2bc44f6f20c1c9b7a13f3fb1dd41a4e35/franka_emika_panda"
FUNCTION_SOURCE = "https://mujoco.readthedocs.io/en/stable/APIreference/APIfunctions.html"
LESSON_ALIASES = {"panda-fk": "panda-structure"}


def _lesson(identifier, title, mode, question, summary, concepts, steps, observations, exercise, prerequisites, duration=3.0):
    return {"id": identifier, "experiment_id": identifier, "title": title, "mode": mode,
            "question": question, "summary": summary, "concepts": concepts, "steps": steps,
            "observations": observations, "exercise": exercise, "prerequisites": prerequisites,
            "duration": duration, "adapter": "panda", "status": "available", "sources": [
                {"title": "Panda 模型、参数与执行器来源", "url": MODEL_SOURCE},
                {"title": "MuJoCo 正向计算与雅可比接口", "url": FUNCTION_SOURCE}]}


PANDA_LESSONS = [
    _lesson("panda-structure", "机械臂结构与正运动学", "structure",
            "关节运动如何改变连杆构型与末端位姿？", "通过位置控制观察连续运动，识别关节、坐标系与关节角到末端位姿的映射。",
            [{"title": "构型与自由度", "text": "本课使用固定基座 Panda。机械臂有七个转动关节；夹爪有两个受耦合约束的滑动关节。模型的广义位置还包含场景中方块的自由位姿。蓝色末端参考点定义在手部局部 z 轴 0.1034 m 处，红、绿、蓝短轴分别表示末端 x、y、z 方向。悬停关节标签可查看限位。",
              "formula": r"\boldsymbol q_a=(q_1,\ldots,q_7)^\mathsf T"},
             {"title": "正运动学", "text": "各关节变换按运动链顺序相乘。平移向量 p 表示末端参考点的世界坐标，R 的三列表示末端坐标轴在世界坐标系中的方向。每一时刻使用实际关节角和模型定义计算位姿。",
              "formula": r"{}^WT_E(\boldsymbol q)=\prod_i {}^{i-1}T_i(q_i)=\begin{bmatrix}R&p\\0&1\end{bmatrix}"},
             {"title": "连续运动与夹爪", "text": "输入角度作为位置伺服目标，沿用关节位置控制课的动力学执行方式；默认控制参数与重力补偿使运动过程可观察。夹爪开口是左右手指滑动量之和，范围为 0 至 0.08 m。",
              "formula": r"\boldsymbol p(t)=f_p(\boldsymbol q(t)),\qquad w=q_{f1}+q_{f2}"}],
            ["打开实验，默认关节 2 从初态增加 0.1 rad；旋转相机识别基座、七个关节、夹爪和末端坐标轴。", "观察末端 X、Y、Z 位置曲线与旋转矩阵，再修改关节 2 目标并点击移动到目标。", "恢复初态会重新应用本课默认目标。改变关节 4，对照末端位置与朝向；最后改变夹爪开口。"],
            ["目标与实际关节角随时间的变化，单位 rad", "世界坐标系中的末端位置与旋转矩阵", "各关节限位与夹爪实际开口"],
            "比较关节 2 与关节 4 的运动对末端位置和朝向的影响；恢复相同构型后核对末端位姿。", "无需前置课程"),
    _lesson("panda-joint-control", "关节位置控制与动态响应", "joint-control", "位置反馈和速度反馈怎样影响跟踪过程？",
            "从相同初态跟踪相同目标，分别调整位置增益与阻尼，比较响应、误差和力矩。",
            [{"title": "位置伺服", "text": "本课沿用上游 general 执行器中的位置与速度反馈形式。七路 ctrl 为目标角度，MuJoCo 计算执行器作用并积分运动。实际力矩还受模型执行器限幅约束。",
              "formula": r"\tau_i=K_{p,i}(q_{d,i}-q_i)-K_{d,i}\dot q_i"},
             {"title": "独立调节反馈参数", "text": "位置增益倍率 a 与阻尼倍率 b 分别乘上游 Kp、Kd。默认 a=0.2、b=√0.2。先保持重力补偿开启，每次只改变一个倍率，并从相同初态重复实验。实际响应也受惯性、关节阻尼和力矩限幅影响。",
              "formula": r"K_p'=aK_p,\qquad K_d'=bK_d"}],
            ["打开实验，默认关节 1 跟踪 0.2 rad 目标；观察实际、参考、终点目标及执行器力矩曲线。", "恢复初态，保持阻尼倍率不变，比较位置增益倍率 0.1 与 0.5；每次调整后移动到目标。", "再次恢复初态，固定位置增益，改变阻尼倍率，比较响应和力矩。"],
            ["目标角度与实际角度，单位 rad", "关节跟踪误差与实际执行器力矩", "分别改变位置增益和阻尼后的响应变化"],
            "保持同一目标和初态，分别改变位置增益、阻尼，说明响应时间和误差的变化。", "机械臂结构与正运动学"),
    _lesson("panda-gravity", "机械臂自重与重力补偿", "gravity", "支撑机械臂当前姿态需要哪些关节力矩？",
            "关闭位置伺服，从同一静止初态对照机械臂下落与补偿保持。",
            [{"title": "重力项", "text": "本课将机械臂七路位置伺服增益设为零，保留模型关节阻尼。补偿开启时，由相同构型、零速度的辅助状态求得重力项，并作为关节外加广义力输入。",
              "formula": r"M(q)\ddot q+h(q,\dot q)=\tau+\tau_{\mathrm{ext}}"},
             {"title": "补偿条件", "text": "补偿重力不会消除已有速度、外部扰动、碰撞和模型误差。每次对照应恢复同一初态。本课中的伺服力矩为零，表中重力项给出补偿所需的广义力。",
              "formula": r"g(q)=h(q,0),\qquad \tau_{\mathrm{ext}}=g(q)"}],
            ["点击关闭补偿并释放，观察连杆绕关节转动、末端高度及构型偏移。", "点击恢复初态并开启补偿，从相同初态观察构型保持与补偿力矩。", "对照两次实验的角度曲线；世界重力在两次实验中均为竖直向下 9.81 m/s²。"],
            ["关节所需重力力矩与实际补偿输入，单位 N·m", "相对初态的构型偏移和末端高度变化", "补偿开启状态与关节角度曲线"],
            "根据重力项分析各关节所需的支撑力矩，并解释重力补偿为什么无法消除已有运动速度。", "关节位置控制与动态响应"),
    _lesson("panda-jacobian", "雅可比与奇异构型", "jacobian", "关节速度如何映射为末端速度？",
            "运行两秒单关节运动，将雅可比预测速度与末端位置差分观测进行对照。",
            [{"title": "瞬时速度映射", "text": "使用 mj_jacSite 计算末端参考点的世界坐标平移雅可比，显示其中对应机械臂的 3×7 子矩阵。关节速度单位为 rad/s，输出平移速度单位为 m/s。",
              "formula": r"\dot{\boldsymbol p}=J_p(\boldsymbol q)\dot{\boldsymbol q},\qquad J_p=\frac{\partial\boldsymbol p}{\partial\boldsymbol q}"},
             {"title": "预测与独立观测", "text": "每个 1 ms 区间在起点计算 J，用区间实际关节速度预测末端速度；另用区间两端的末端位置差分得到观测速度。三维速度投影图用相同缩放绘制两支箭头。矩阵高亮运动关节对应列，完成后保留最后一个运动区间供对照。",
              "formula": r"v_{\mathrm{obs}}=\frac{p(t+\Delta t)-p(t)}{\Delta t},\qquad v_{\mathrm{pred}}=J_p(q(t))\frac{q(t+\Delta t)-q(t)}{\Delta t}"},
             {"title": "构型与奇异值", "text": "本课按设定速度更新几何构型，不经过动力学。平移雅可比最小奇异值减小时，某些平移方向的速度生成能力下降。该指标只描述平移任务；不能用于判定完整六维位姿任务的全部奇异性。",
              "formula": r"J_p=U\Sigma V^\mathsf T"}],
            ["默认选关节 2、速度 0.05 rad/s；点击设置构型并运行 2 秒。", "对照高亮矩阵列、预测与观测速度箭头、三轴速度和误差；运动完成后可继续查看末次采样。", "改变起始构型后重复相同关节速度，比较末端速度方向；切换关节后再运行。"],
            ["平移雅可比 3×7 矩阵及运动关节对应列", "预测速度与位置差分观测速度，单位 m/s", "速度误差、采样区间和三个平移奇异值"],
            "固定相同关节速度，在两个起始构型下比较末端速度方向，解释雅可比随构型变化的含义。", "机械臂结构与正运动学"),
    _lesson("panda-ik", "逆运动学与冗余", "ik", "给定末端位置，怎样求关节构型？",
            "设置三维末端目标，通过逆运动学求关节目标，再观察位置伺服的连续运动与实际误差。",
            [{"title": "局部迭代求解", "text": "从当前构型出发，根据位置误差和雅可比计算关节增量，再施加步长与关节限位约束。阻尼系数为 0.02，每次最多 160 次迭代，位置收敛阈值为 0.1 mm。",
              "formula": r"\Delta q=J_p^\mathsf T(J_pJ_p^\mathsf T+\lambda^2I)^{-1}(p_d-p)"},
             {"title": "求解与运动执行", "text": "求解在辅助状态中进行，实际关节位置与速度保持连续。收敛后将关节解作为位置伺服目标，MuJoCo 通过执行器和动力学推进运动，默认增益与重力补偿与第一节一致。IK 候选解残差描述求解结果；实际末端到目标的距离随运动变化。",
              "formula": r"p_d\longrightarrow q_d\longrightarrow\tau\longrightarrow q(t),\qquad e_{\mathrm{actual}}(t)=\|p_d-f_p(q(t))\|_2"},
             {"title": "冗余与未收敛", "text": "本课仅约束末端位置，朝向自由。七个关节可以产生不同解，解与求解起始构型有关。目标不可达或迭代未收敛时，显示候选解残差并保留上一有效关节目标。求解未包含碰撞避障，实际运动可能受接触或力矩限幅影响。",
              "formula": r"e_{\mathrm{IK}}=\|p_d-f_p(q_{\mathrm{solution}})\|_2"}],
            ["将末端目标设置在机械臂附近，例如 (0.45, 0.12, 0.42) m。", "点击求解并移动到目标，对照绿色目标点、IK 候选解残差与实际末端误差的变化。", "暂停后更改目标并求解，确认构型保持不变；单步或继续后观察运动。再设置较远目标检查未收敛提示。"],
            ["末端位置目标与实际末端位置、实际末端误差", "迭代次数、收敛状态与 IK 候选解残差", "目标与实际关节角曲线、关节跟踪误差及限位"],
            "从两个不同初态求同一位置目标，比较最终构型。", "雅可比与奇异构型"),
    _lesson("panda-trajectory", "轨迹生成与跟踪", "trajectory", "相同终点，不同时间曲线会产生什么响应？",
            "比较三秒关节轨迹的线性和五次插值，以及实际伺服跟踪。",
            [{"title": "关节空间轨迹", "text": "从实际当前角度出发，以三秒时长到达设置的目标。五次插值在起止时刻的参考速度和加速度为零；线性插值在开始和停止处存在参考速度跳变。",
              "formula": r"q_d(t)=q_0+s(u)(q_1-q_0),\quad s(u)=10u^3-15u^4+6u^5,\quad u=t/3"},
             {"title": "参考与跟踪", "text": "每个物理步更新轨迹参考，再由位置伺服执行。曲线中的最终关节目标与轨迹中间参考有不同含义；记录同时保存实际状态与跟踪过程。本课不进行碰撞规划。",
              "formula": r"e(t)=q_d(t)-q(t)"}],
            ["默认终点为关节 1 = 0.3 rad、关节 2 = 0.2 rad，其余保持初态；打开实验后等待执行，编辑终点不会提前移动。", "点击执行轨迹，观察三秒五次插值、实际跟踪和误差曲线；暂停时需单步或继续执行。", "恢复初态，选择线性插值和相同终点重复实验。"],
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
    from .humanoid_curriculum import HUMANOID_LESSONS
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
    from .panda import default_settings as panda_defaults
    from .humanoid import default_settings as humanoid_defaults
    panda_lessons, humanoid_lessons = deepcopy(PANDA_LESSONS), deepcopy(HUMANOID_LESSONS)
    for item in panda_lessons:
        item["default_settings"] = panda_defaults(item["mode"])
    for item in humanoid_lessons:
        item["default_settings"] = {"humanoid": humanoid_defaults(item["mode"])}
    return [{"id": "panda-basics", "title": "Panda 机械臂基础", "subtitle": "从关节构型到接触抓取",
             "robot": "Franka Emika Panda", "level": "基础 → 进阶", "description": "原理讲解与交互实验并行，逐节研究机械臂的几何、动力学和控制。",
             "lessons": panda_lessons},
            {"id": "humanoid-basics", "title": "人形机器人：站立、平衡与学习控制",
             "subtitle": "浮动基座、足底接触与学习策略", "robot": "Unitree G1（12 驱动关节）",
             "level": "基础 → 学习控制", "description": "连续运动、真实接触与可观察的学习策略执行。",
             "lessons": humanoid_lessons},
            {"id": "physics-basics", "title": "基础物理实验", "subtitle": "动力学与接触的基本现象",
             "robot": "基础机构", "level": "基础", "description": "通过单摆与落球建立运动、能量和接触的观察方法。",
             "lessons": physics_lessons}]


def get_lesson(identifier):
    identifier = LESSON_ALIASES.get(identifier, identifier)
    for course in courses():
        for index, lesson in enumerate(course["lessons"]):
            if lesson["id"] == identifier:
                return {**lesson, "course_id": course["id"], "course_title": course["title"], "number": index + 1}
    raise ValueError(f"未知课时：{identifier}")
