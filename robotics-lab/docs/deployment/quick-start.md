# Robotics Lab Docker 离线交付与迁移

本页适用于单应用镜像的交付包。完整源码的原生与 Docker 安装见项目 README。Windows/macOS 使用 Docker Desktop 的 Linux 容器，Linux 可使用 Docker Engine 与 Compose v2+；宿主机不需要 Python 或 Node。

## 选择架构与启动

包名中的 `linux-arm64` 对应 Apple Silicon 或 ARM64 Linux 容器，`linux-amd64` 对应 Intel/AMD Linux 容器。`manifest.json` 记录目标架构、镜像标签和逐文件 SHA-256。构建配置支持这两个目标，实际验收及已生成交付包以 [验证记录](../validation/deployment.md) 为准。

先安装并启动 Docker，完整解压 ZIP，在包含 `compose.yaml` 的目录执行；PowerShell 与 shell 使用同一组命令：

```shell
docker image load --input images.tar
docker compose up -d --wait --remove-orphans
```

打开 <http://localhost:18320>。包内镜像已包含 Python 依赖、前端、模型、网格和策略，导入后无需联网。浏览器需支持 WebAssembly、WebGL2 和 SharedArrayBuffer，保持硬件加速可用。

```shell
docker compose ps
docker compose logs --tail 100 -f
docker compose exec lab python -m robotics_lab doctor
docker compose exec lab python -m robotics_lab smoke
docker compose down
```

`smoke` 会创建数值记录并占用临时交互会话；运行前先结束已有实验。停止不删除数据卷。若同时运行原生服务或另一份容器，请在 `.env` 设置不同的 `ROBOTICS_LAB_PORT`，并为并行部署指定不同的 Compose 项目名。

## 配置与数据保存

`.env` 中的 `ROBOTICS_LAB_HOST`、`ROBOTICS_LAB_PORT` 调整宿主机监听地址和端口，`ROBOTICS_LAB_TAG` 冻结镜像标签。默认只向本机开放。远程访问需自行配置 HTTPS、认证，并保留应用的 COOP/COEP 响应头；远程安全部署尚未验收。

Docker 使用 `robotics-lab-data` 命名卷，数据路径固定为 `/var/lib/robotics-lab`。`.env.example` 中的 `ROBOTICS_LAB_DATA_DIR` 只用于原生部署，不改变 Docker 的卷位置。镜像和 ZIP 不包含用户数据；课时完成状态位于当前浏览器 localStorage。

不要使用 `docker compose down --volumes` 删除需要保留的卷。需要自定义宿主机挂载时，通过单独的 Compose 覆盖文件替换数据卷，并确保容器 UID/GID `10001:10001` 可写；常规部署不需要挂载宿主机目录。

## 备份与恢复

备份前结束交互实验并停止服务写入：

```shell
docker compose stop lab
docker compose cp lab:/var/lib/robotics-lab ./robotics-data-backup
docker compose up -d --wait
```

新机器先导入镜像并创建卷，在停止服务期间恢复完整目录，再修正目录所有者并启动。以下命令中的路径按实际备份位置调整：

```shell
docker compose create
docker compose cp ./robotics-data-backup/. lab:/var/lib/robotics-lab/
docker compose run --rm --no-deps --user 0 --cap-add CHOWN --entrypoint chown lab -R 10001:10001 /var/lib/robotics-lab
docker compose up -d --wait
```

使用相同软件版本确认数值记录可读后再升级。原生与 Docker 之间迁移时，也复制同一数据目录并执行相同读取验证，不复制虚拟环境或浏览器 localStorage。
