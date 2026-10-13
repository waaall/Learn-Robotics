"""只验收训练项目的软件环境；无串口、相机或推理项目依赖。"""

from pathlib import Path
from smolvla_common.environment import main


if __name__ == "__main__":
    main(Path(__file__).resolve().parent, training=True)
