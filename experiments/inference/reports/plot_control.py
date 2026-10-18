"""Generate a reproducible static tracking plot from an exported trajectory CSV."""

import argparse
import csv
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


parser = argparse.ArgumentParser()
parser.add_argument("csv", type=Path)
args = parser.parse_args()
with args.csv.open(encoding="utf-8") as stream:
    rows = list(csv.DictReader(stream))
t = [float(r["time_s"]) for r in rows]
command = [float(r["command_wrist_deg"]) for r in rows]
measured = [float(r["measured_wrist_deg"]) for r in rows]
fig, ax = plt.subplots(figsize=(8.4, 4.2), layout="constrained")
ax.plot(t, command, label="Command", linewidth=2, color="#2367b0")
ax.step(t, measured, where="post", label="Encoder feedback", linewidth=2, color="#bd5a24")
ax.axhline(0, color="#777777", linewidth=.6)
ax.set(xlabel="Time since tool execution started (s)", ylabel="Wrist pitch relative to start (encoder degrees)",
       title="LLM-selected wrist nod: deterministic controller; VLA disabled")
ax.grid(alpha=.2)
ax.legend(loc="upper right")
fig.savefig(args.csv.with_suffix(".png"), dpi=180)
fig.savefig(args.csv.with_suffix(".svg"))
print(args.csv.with_suffix(".png"))
