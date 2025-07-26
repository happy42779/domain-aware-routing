import re
import numpy as np
import matplotlib.pyplot as plt
import argparse


def parse_file(filename):
    data = {}
    with open(filename) as f:
        rule_size = None
        for line in f:
            line = line.strip()
            match = re.match(r"\[(\d+)\]", line)
            if match:
                rule_size = int(match.group(1))
                data[rule_size] = []
            elif (
                "," in line
                and rule_size is not None
                and not line.startswith("run_index")
            ):
                parts = line.split(",")
                try:
                    value = float(parts[-1])
                    data[rule_size].append(value)
                except ValueError:
                    pass
    return data


def remove_outliers(arr, thresh=2):
    arr = np.array(arr)
    mean = np.mean(arr)
    std = np.std(arr)
    if std == 0:
        return arr
    filtered = arr[np.abs(arr - mean) <= thresh * std]
    return filtered


def mean_std(arr):
    return np.mean(arr), np.std(arr)


def plot(data1, data2, output):
    # For plotting, get sorted rule sizes that appear in both files
    rule_sizes = sorted(set(data1.keys()) & set(data2.keys()))
    means1, stds1 = [], []
    means2, stds2 = [], []
    label1 = "Latency (SND)"
    label2 = "Latency (PBR)"
    table_data = []

    for rs in rule_sizes:
        # arr1, arr2 = np.array(data1[rs]), np.array(data2[rs])
        arr1, arr2 = remove_outliers(data1[rs]), remove_outliers(data2[rs])
        m1, s1 = mean_std(arr1)
        m2, s2 = mean_std(arr2)
        # convert to ms
        means1.append(m1 * 1000)
        stds1.append(s1 * 1000)
        means2.append(m2 * 1000)
        stds2.append(s2 * 1000)
        table_data.append(
            [
                rs,
                f"{m1 * 1000:.2f} ± {s1 * 1000:.2f}",
                f"{m2 * 1000:.2f} ± {s2 * 1000:.2f}",
            ]
        )

    plt.figure(figsize=(10, 6))
    plt.errorbar(rule_sizes, means1, yerr=stds1, fmt="o-", capsize=4, label=label1)
    plt.errorbar(rule_sizes, means2, yerr=stds2, fmt="s--", capsize=4, label=label2)
    plt.xlabel("Rule Size")
    plt.ylabel("Latency (ms)")
    plt.title("Latency vs. Rule Size")
    plt.legend()
    plt.grid(True)
    plt.tight_layout()
    # plt.show()
    plt.savefig(output, dpi=200)

    # print table
    print("\nSummary Table (mean ± std, ms, outliers removed):\n")
    header = f"{'Rule Size':>10} {label1:>18} {label2:>18}"
    print(header)
    print("-" * len(header))
    for row in table_data:
        print(f"{row[0]:>10} {row[1]:>18} {row[2]:>18}")

    # plot summary table
    fig, ax = plt.subplots(figsize=(6, 0.6 + 0.3 * len(table_data)))
    ax.axis("off")

    col_labels = ["Rule Size", f"{label1} (ms)", f"{label2} (ms)"]
    cell_text = [[f"{row[0]}", row[1], row[2]] for row in table_data]
    table = ax.table(
        cellText=cell_text, colLabels=col_labels, loc="center", cellLoc="center"
    )
    table.auto_set_font_size(False)
    table.set_fontsize(12)
    table.scale(1, 1.4)
    plt.title("Latency Table (mean ± std, ms, outliers removed)", pad=14)
    plt.tight_layout()
    plt.savefig("plots/latency_table.png", dpi=200)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Plot delays from multi-section file.")
    parser.add_argument("file", nargs="+", help="Input file")
    parser.add_argument("-o", "--output", help="File path for the plotted image")
    args = parser.parse_args()
    # file[0] is SDN latency, and file[1] is PBR lAtency
    data1, data2 = parse_file(args.file[0]), parse_file(args.file[1])
    plot(data1, data2, args.output)
