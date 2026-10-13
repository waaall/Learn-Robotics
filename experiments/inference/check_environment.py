"""只验收离线推理软件环境，不执行训练更新或机器人动作。"""

from pathlib import Path
from smolvla_common.environment import main


if __name__ == "__main__":
    main(Path(__file__).resolve().parent, training=False)
