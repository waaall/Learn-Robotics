"""Windows 只读盘点与手动会话变量；不安装包、不更新代码、不加载模型。"""

from pathlib import PureWindowsPath
import uuid

from .config import RemoteConfig
from .transport import ps_literal, run_readonly


def session_script(cfg: RemoteConfig):
    windows = cfg.windows
    return "\n".join([
        "# 在服务器 PowerShell 粘贴此块；仅声明路径和切换目录，不调用未安装的模型环境。",
        f"$Repo = {ps_literal(windows.repo_dir)}",
        f"$Python = {ps_literal(windows.python_executable)}",
        f"$Lab = {ps_literal(cfg.lab_dir)}",
        f"$Runner = {ps_literal(cfg.lab_dir / 'run.ps1')}",
        f"$Config = {ps_literal(cfg.config_path)}",
        f"$EntryModule = {ps_literal(cfg.project.module)}",
        "$ErrorActionPreference = 'Stop'",
        "Set-Location -LiteralPath $Lab",
    ]) + "\n"


def inspection_script(cfg: RemoteConfig, marker):
    windows = cfg.windows
    required = [windows.repo_dir / path for path in cfg.project.required_files]
    required.extend([cfg.lab_dir / name for name in ("setup.ps1", "run.ps1", "uv.lock", "pyproject.toml")])
    required.append(cfg.config_path)
    paths = ", ".join(ps_literal(PureWindowsPath(path)) for path in required)
    # 探测 Python 只用标准库读取元数据，避免导入 torch 或分配 GPU。
    python_probe = (
        "import json,sys,platform,struct,importlib.metadata as m; "
        "names=('torch','torchvision','torchcodec','lerobot','transformers','accelerate'); "
        "installed={d.metadata['Name'].lower():d.version for d in m.distributions()}; "
        "print(json.dumps({'executable':sys.executable,'version':sys.version,"
        "'version_info':list(sys.version_info[:3]),"
        "'machine':platform.machine(),'bits':struct.calcsize('P')*8,"
        "'packages':{n:installed.get(n) for n in names}}))"
    )
    return f"""# 仅盘点部署前置条件；不安装、不下载、不写入服务器仓库。
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$env:GIT_OPTIONAL_LOCKS = '0'
$Repo = {ps_literal(windows.repo_dir)}
$Python = {ps_literal(windows.python_executable)}
$Lab = {ps_literal(cfg.lab_dir)}
$Probe = {ps_literal(python_probe)}
function Read-Python([string]$Executable) {{
    if (!(Test-Path -LiteralPath $Executable -PathType Leaf)) {{ return $null }}
    $raw = & $Executable -c $Probe 2>$null
    if ($LASTEXITCODE -ne 0) {{ throw "Python probe failed: $Executable" }}
    return (($raw -join "`n") | ConvertFrom-Json)
}}
function Read-Version([string]$Name) {{
    $cmd = Get-Command $Name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if (!$cmd) {{ return $null }}
    $value = & $cmd.Source --version 2>$null
    if ($LASTEXITCODE -ne 0) {{ throw "Version probe failed: $Name" }}
    return [ordered]@{{ path = $cmd.Source; version = ($value -join "`n") }}
}}
try {{
    $os = Get-CimInstance Win32_OperatingSystem
    $pythonInfo = Read-Python $Python
    $venvInfo = Read-Python (Join-Path $Lab '.venv\\Scripts\\python.exe')
    $uvInfo = Read-Version 'uv'
    $gitInfo = Read-Version 'git'
    $gpuCommand = Get-Command 'nvidia-smi' -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    $gpuLines = @()
    if ($gpuCommand) {{
        $gpuLines = @(& $gpuCommand.Source '--query-gpu=name,memory.total,memory.used,driver_version' '--format=csv,noheader,nounits' 2>$null)
        if ($LASTEXITCODE -ne 0) {{ throw 'nvidia-smi probe failed' }}
    }}
    $files = @({paths})
    $missing = @($files | Where-Object {{ !(Test-Path -LiteralPath $_ -PathType Leaf) }})
    $head = $null
    $dirty = @()
    if ($gitInfo -and (Test-Path -LiteralPath $Repo -PathType Container)) {{
        $headRaw = & $gitInfo.path -C $Repo rev-parse HEAD 2>$null
        if ($LASTEXITCODE -eq 0) {{
            $head = ($headRaw -join '').Trim()
            $dirty = @(& $gitInfo.path -C $Repo status --short 2>$null)
            if ($LASTEXITCODE -ne 0) {{ throw 'Git status probe failed' }}
        }}
    }}
    $pythonOK = $false
    if ($pythonInfo) {{
        $pythonOK = $pythonInfo.version_info[0] -eq 3 -and $pythonInfo.version_info[1] -ge 12 -and $pythonInfo.version_info[1] -lt 14 -and $pythonInfo.bits -eq 64 -and $pythonInfo.machine -in @('AMD64', 'x86_64')
    }}
    $checks = [ordered]@{{
        repo_exists = [bool](Test-Path -LiteralPath $Repo -PathType Container)
        required_files_present = [bool]($missing.Count -eq 0)
        python_supported = [bool]$pythonOK
        uv_on_path = [bool]($null -ne $uvInfo)
        git_checkout_detected = [bool]($null -ne $head)
        nvidia_gpu_detected = [bool]($gpuLines.Count -gt 0)
    }}
    $report = [ordered]@{{
        schema_version = 1; status = 'collected'; checked_at_utc = [DateTime]::UtcNow.ToString('o')
        os = [ordered]@{{ name = $os.Caption; build = $os.BuildNumber; ram_gib = [math]::Round($os.TotalVisibleMemorySize / 1MB, 1) }}
        disks = @(Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3' | ForEach-Object {{
            [ordered]@{{ drive = $_.DeviceID; size_gib = [math]::Round($_.Size / 1GB, 1); free_gib = [math]::Round($_.FreeSpace / 1GB, 1) }}
        }})
        python = $pythonInfo; venv_python = $venvInfo; uv = $uvInfo; git = $gitInfo
        gpu_csv_columns = @('name', 'memory_total_mib', 'memory_used_mib', 'driver_version')
        gpu_csv = $gpuLines
        repo = [ordered]@{{ path = $Repo; head = $head; dirty_files = $dirty; missing_files = $missing }}
        checks = $checks; ready_for_setup = [bool](@($checks.Values | Where-Object {{ !$_ }}).Count -eq 0)
    }}
}} catch {{
    $report = [ordered]@{{ schema_version = 1; status = 'failed'; error = $_.Exception.Message }}
}}
# 编码为独立协议行；即使 SSH 启动提示或 profile 有输出，也不能冒充成功报告。
$json = $report | ConvertTo-Json -Depth 12 -Compress
$payload = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($json))
[Console]::WriteLine('')
[Console]::WriteLine({ps_literal(marker + ':')} + $payload + ':END')
if ($report.status -ne 'collected') {{ exit 1 }}
"""


def check_server(cfg: RemoteConfig):
    marker = "__REMOTE_LAB_" + uuid.uuid4().hex + "__"
    return run_readonly(cfg, inspection_script(cfg, marker), marker)
