# Microduck 课程资源

来源及固定提交见 `upstream.json`。`robot_groundcontact.xml` 与 `assets/*.stl` 从 Pollen Robotics 官方仓库原样导入。父目录 `microduck_course.xml` 是 Robotics Lab 课程场景。

- `walking.npz`：官方 `alpha_walking.onnx` 的归一化与 MLP 权重。
- `sitstand.npz`：官方 `alpha_sitstand.onnx` 的归一化与 MLP 权重。
- `*_reference.npz`：固定输入与 ONNX Runtime 输出，用于核对 NumPy 推理。
- `velstand.npz`：同版本官方综合策略的参考导出，当前课程未选用。
- `xl330_m6.json`：官方训练固定依赖版本的 BAM M6 参数。
- `policy_manifest.json`：官方策略集合及输入输出契约。

XML 和软件使用 Apache-2.0；STL 使用 CC BY-NC-SA 4.0，版权归 Pollen Robotics。许可范围和署名要求见 `LICENSE-MODELS.md`；BAM 许可见 `LICENSE-BAM`。网格未修改。运行时无需下载额外资源。
