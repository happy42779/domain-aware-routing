import sys
import os
import matplotlib.pyplot as plt
import numpy as np
import argparse
import seaborn as sns


def parse_file(filename: str):
    times = []
    cpus = []
    memories = []
    with open(filename, "r") as f:
        for line in f:
            line = line.strip()
            # Skip header or empty lines
            if not line or line.startswith("Elapsed") or line.startswith("-"):
                continue
            # Split on whitespace and only take first three columns
            cols = line.split()
            if len(cols) < 3:
                continue
            try:
                times.append(float(cols[0]))
                cpus.append(float(cols[1]))
                memories.append(float(cols[2]))
            except ValueError:
                continue
    return np.array(times), np.array(cpus), np.array(memories)


# Use command line or hardcode your files here
if len(sys.argv) < 2:
    print("Usage: python plot_psrecord_multi.py file1.txt file2.txt ...")
    sys.exit(1)

parser = argparse.ArgumentParser(description="plot psrecord logs")
parser.add_argument("files", nargs="+", help="Input data files (space-separated)")
parser.add_argument(
    "-o",
    "--output",
    type=str,
    default="output.png",
    help="Output image filename for the plog",
)

args = parser.parse_args()
files = args.files
output_file = args.output

# colors = plt.get_cmap("tab10").colors
colors = sns.color_palette("colorblind", 6)


# global min/max
cpus_all = []
mems_all = []

fig, ax1 = plt.subplots(figsize=(14, 7))
ax2 = ax1.twinx()

lines = []
labels = []

for i, fname in enumerate(files):
    times, cpus, mems = parse_file(fname)
    color = colors[i % len(colors)]

    cpus_all.extend(cpus)
    mems_all.extend(mems)

    # Plot CPU (%), dashed line
    (l1,) = ax1.plot(
        times,
        cpus,
        linestyle="--",
        color=color,
        label=f"CPU {os.path.basename(fname)}",
        linewidth=2,
    )
    # Plot Real (MB), solid line
    (l2,) = ax2.plot(
        times,
        mems,
        linestyle="-",
        color=color,
        label=f"Mem {os.path.basename(fname)}",
        linewidth=2,
    )
    lines.extend([l1, l2])
    labels.extend([f"CPU {os.path.basename(fname)}", f"Mem {os.path.basename(fname)}"])

ax1.set_xlabel("Elapsed Time (s)")
ax1.set_ylabel("CPU (%)", color="tab:blue")
ax2.set_ylabel("Real Memory (MB)", color="tab:red")
ax1.tick_params(axis="y", labelcolor="tab:blue")
ax2.tick_params(axis="y", labelcolor="tab:red")

# # reset y axis
# margin = 0.1
# cpu_min, cpu_max = min(cpus_all), max(cpus_all)
# mem_min, mem_max = min(mems_all), max(mems_all)
# cpu_range = cpu_max - cpu_min
# mem_range = mem_max - mem_min
# if cpu_range == 0:
#     cpu_range = 1  # prevent zero division
# if mem_range == 0:
#     mem_range = 1
# ax1.set_ylim(cpu_min - cpu_range * margin, cpu_max + cpu_range * margin)
# ax2.set_ylim(mem_min - mem_range * margin, mem_max + mem_range * margin)

title = files[0].split("/")[1].split("_")[0]
# print(f"title is {title}")
plt.title(f"CPU and Memory Usage Over Time ({title})")

# Combine legends from both axes
ax1.legend(lines, labels, loc="upper left", fontsize="small")
plt.tight_layout()

plt.savefig(output_file, dpi=200)

# plt.show()
