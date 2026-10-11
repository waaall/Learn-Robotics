# 幻尔 SO-ARM101 配套源码检查

检查日期：2026-10-11。范围：本地压缩包内 `src/**/*.py` 与 `pyproject.toml`，对比它记录的上游 HEAD；不是固件审计或真机验收。

## 结论

配套包声明 LeRobot 0.3.4、Python >=3.10。主从单臂类、Feetech 驱动和寄存器表与基线相同；没有在这些文件中发现专用 HX 型号驱动。可以先使用独立的上游 0.6.1 环境，暂不移植厂商修改。该结论不证明 HX 舵机在新版本上已经通过实机测试。

- 本地包：`E:\Videos\TV\新建文件夹\SO-ARM101开源6轴机械臂\2.软件工具&源码程序\源码程序\lerobot.zip`
- SHA-256：`9e881f28fce5a9f20f80c69bbffa19202fd6db695bb4ad71fb3a6fdd33c13d2b`
- 包内 HEAD：[`882c80d446a63a44868c67ae535467af32ce0e80`](https://github.com/huggingface/lerobot/tree/882c80d446a63a44868c67ae535467af32ce0e80)。HEAD 只标识基线，不包括打包者的未提交修改。
- 将 CRLF 统一为 LF 后计算 Git blob SHA-1，与官方提交的文件树比较：195 个文件相同、9 个修改、6 个新增（仅上述范围，未统计基线中缺失文件）。随后逐项读取了 9 个修改文件的差异。

## 已核实的修改

| 位置 | 厂商修改 | 对本实验的影响 |
| --- | --- | --- |
| `cameras/utils.py` | Windows 提前返回 DirectShow，原 MSMF 返回语句变得不可达 | 到货后可按需选择 DSHOW，不能认定所有相机都必须用它 |
| `configs/policies.py` | 临时 JSON 关闭后再读取并清理；增加梯度累积配置字段；调整状态/动作特征查找 | 0.6.1 已采用关闭临时文件后读取的模式；仅增加配置字段不能证明训练实现了梯度累积 |
| `motors/motors_bus.py` | 同步读写及内部方法的默认 `num_retry` 从 0 改为 1，失败日志从 debug 改为 info | 增加一次重试可能减少偶发通信失败，也会增加故障时延；待真机测量后决定 |
| 校准、遥操作、采集、回放及工厂函数 | 注册双臂 SO101 类型 | 一主一从的标准版不是两只执行臂，无需该扩展 |
| 6 个新增 Python 文件 | 双主臂/双从臂类型及配置 | 暂不纳入本实验 |

单臂代码把六个电机配置为 `sts3215`，读取 `Present_Position`、写入 `Goal_Position`。从臂配置写入位置模式及 P=16、I=0、D=32 寄存器值。这是已看到的主机指令，**不能据此还原舵机固件内部算法或实际闭环频率**。

## 与新版本的关系

- [0.6.1 相机配置](https://github.com/huggingface/lerobot/blob/v0.6.1/src/lerobot/cameras/opencv/configuration_opencv.py)提供 `backend` 字段，不需要为选择相机后端直接修改安装包。
- [0.6.1 策略配置](https://github.com/huggingface/lerobot/blob/v0.6.1/src/lerobot/configs/policies.py)已有 Windows 临时文件相关处理；本实验将实际检查模型保存和重新加载。
- 配套手册的命令、训练依赖和旧数据格式不应直接混入 0.6.1。后续命令以锁定环境的 `--help` 与对应版本源码为准。
- **动作单位变化：** 厂商 0.3.4 主从臂配置 `use_degrees=False`，0.6.1 主从臂默认 `True`；身体关节的位置表示不同，夹爪仍需单独核对其范围。新实验明确统一选择，不直接加载旧模型/旧数据驱动新配置。
- 0.6.1 的单臂 Python 导入路径已统一为 `robots.so_follower` / `teleoperators.so_leader`，CLI 类型仍支持 `so101_follower` / `so101_leader`。它也提供默认值为 2 的 `num_read_retries`，无需照抄旧版总线修改；写入重试不由此自动推定。

下一步：到货后先读端口与设备信息、核对型号和校准，再小范围遥操作；单摄像头只配置一个稳定的特征名称。源码检查不会执行设备连接、舵机 ID 写入或校准。
