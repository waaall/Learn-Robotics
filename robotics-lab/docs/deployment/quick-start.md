# Robotics Lab Docker 离线交付包

当前交付包为 `linux-amd64`，用于 Intel/AMD 电脑。解压包中的 `manifest.json` 记录适用 CPU 架构和文件 SHA-256。Apple Silicon 所需 ARM64 包的构建与验收后续在 macOS 完成，当前未交付。镜像运行环境为 Linux；Windows 和 macOS 使用 Docker Desktop 的 Linux 容器，Linux 可使用 Docker Engine 与 Compose 插件。宿主机无需 Python、Node.js 或手动安装 WSL Ubuntu。当前已在 Windows 的 Linux 容器中实测，macOS 宿主机尚未实测。

## 启动

先安装并启动 Docker，完整解压 ZIP，再在包含 `compose.yaml` 的目录打开终端。

Windows PowerShell：

```powershell
./run-docker.ps1 load
./run-docker.ps1
```

Linux / macOS：

```bash
bash run-docker.sh load
bash run-docker.sh
```

打开 <http://localhost:18320>。加载的是包内镜像，首次运行也无需联网下载 Python 依赖和模型。浏览器需支持 WebAssembly、WebGL 和 SharedArrayBuffer；保持桌面浏览器硬件加速可用。

## 停止、日志与配置

Windows 使用 `./run-docker.ps1 stop`、`./run-docker.ps1 logs`、`./run-docker.ps1 status`；Linux/macOS 将相同操作传给 `bash run-docker.sh`。

编辑 `.env` 可修改 `ROBOTICS_LAB_PORT`。默认只绑定本机回环地址，供单用户学习；远程部署需要配置 HTTPS 和访问认证。WASM 多线程要求安全上下文，本机 localhost 可使用 HTTP，远程访问使用 HTTPS，并保留代理的 COOP/COEP 响应头。

## 数据保存与迁移

默认使用 Compose 的 `robotics-lab-data` 命名卷，停止和重建容器会保留数值记录和日志。不要执行 `docker compose down --volumes`，该选项会删除数据卷。镜像和 ZIP 不包含用户运行数据。课时完成状态保存在当前浏览器，数据卷不包含浏览器的 localStorage。

如需直接保存到宿主机目录，在 `.env` 配置 `ROBOTICS_LAB_DATA_DIR=./data`，先创建该目录；Linux 目录需允许容器 UID/GID `10001:10001` 写入。切换目录会切换数据存储位置，旧卷不会自动复制到新目录。

备份默认卷：先结束仿真、停止写入，再复制完整数据目录，最后恢复服务。以下命令在 PowerShell 和 shell 中相同：

```bash
docker compose stop api
docker compose cp api:/var/lib/robotics-lab ./robotics-data-backup
docker compose up -d --wait
```

迁移时先将备份解压到新机器专用 `data/` 目录，再配置该目录挂载并恢复服务。使用相同软件版本完成恢复验证后再升级。
