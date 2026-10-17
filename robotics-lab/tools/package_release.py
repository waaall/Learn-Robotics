"""将本地已构建镜像和启动文件打包为按 CPU 架构区分的离线交付 ZIP。"""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arch", choices=("amd64", "arm64"), required=True)
    parser.add_argument("--tag", default="0.1.0")
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    platform = "linux/" + args.arch
    stem = f"robotics-lab-{args.tag}-linux-{args.arch}"
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    archive = output / (stem + ".zip")
    if archive.exists():
        raise FileExistsError(f"交付包已存在，请指定新的输出目录或版本: {archive}")
    images = [f"robotics-lab-{service}:{args.tag}" for service in ("api", "web")]
    with tempfile.TemporaryDirectory(prefix="robotics-release-", dir=output) as temporary:
        bundle = Path(temporary) / stem
        bundle.mkdir()
        subprocess.run(["docker", "image", "save", "--platform", platform,
                        "--output", str(bundle / "images.tar"), *images], check=True)
        for name in ("compose.yaml", ".env.example", "run-docker.sh", "run-docker.ps1"):
            shutil.copy2(ROOT / name, bundle / name)
        shutil.copy2(ROOT / "docs/deployment/quick-start.md", bundle / "README.md")
        # 发布时冻结镜像版本；解压后无需源码目录和构建工具。
        (bundle / ".env").write_text(
            f"ROBOTICS_LAB_TAG={args.tag}\nROBOTICS_LAB_BIND=127.0.0.1\n"
            "ROBOTICS_LAB_PORT=18320\nROBOTICS_LAB_DATA_DIR=\n", encoding="utf-8")
        manifest = {"version": args.tag, "platform": platform, "images": images,
                    "data_included": False, "files": {}}
        for path in sorted(bundle.iterdir()):
            manifest["files"][path.name] = sha256(path)
        (bundle / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED,
                             compresslevel=1, allowZip64=True) as target:
            for path in sorted(bundle.iterdir()):
                target.write(path, arcname=stem + "/" + path.name)
    checksum = sha256(archive)
    archive.with_suffix(".zip.sha256").write_text(f"{checksum}  {archive.name}\n", encoding="utf-8")
    print(json.dumps({"archive": str(archive), "bytes": archive.stat().st_size,
                      "sha256": checksum, "platform": platform}, indent=2))


if __name__ == "__main__":
    main()
