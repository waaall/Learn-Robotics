"""仅给开发测试组织源码路径；生产部署通过各项目的独立锁文件安装共享包。"""

from pathlib import Path
import sys
import unittest


def main():
    repo = Path(__file__).resolve().parent.parent
    folders = [repo / "packages/smolvla_common/tests", repo / "experiments/training",
               repo / "experiments/inference", repo / "tools/remote", repo / "tests"]
    sys.path[:0] = [str(repo / "packages/smolvla_common/src"), *(str(path) for path in folders)]
    suite = unittest.TestSuite()
    for folder in folders:
        if folder.exists():
            suite.addTests(unittest.defaultTestLoader.discover(str(folder), pattern="test_*.py"))
    # 不发现 lerobot 的测试，避免无意打开串口或要求未安装的硬件 SDK。
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
