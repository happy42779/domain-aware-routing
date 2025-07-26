import re
import numpy as np
import matplotlib.pyplot as plt
import argparse
import pandas as pd


def parse_file(filename):
    # Will store: {size: {colname: [values,...]}}
    data = {}
    with open(filename) as f:
        content = f.read()
    # Split by [size]
    sections = re.split(r"\[(\d+)\],", content)
    # sections: ['', '10', 'run_index,...\n10,test13-167.com,...', '100', ...]
    for i in range(1, len(sections), 2):
        size = int(sections[i])
        block = sections[i + 1].strip()
        lines = block.split("\n")
        if not lines:
            continue
        header = lines[0].split(",")
        # Find columns
        try:
            idx_overall = header.index("overall_delay")
            idx_api = header.index("api_delay")
            idx_policy = header.index("policy_delay")
        except ValueError:
            continue  # skip if bad header
        # Collect values
        ovals, apvals, pvals = [], [], []
        for line in lines[1:]:
            parts = line.split(",")
            try:
                overall = (
                    float(parts[idx_overall].replace(".", "0.", 1))
                    if parts[idx_overall].startswith(".")
                    else float(parts[idx_overall])
                )
                api = float(parts[idx_api])
                policy = float(parts[idx_policy])
            except Exception:
                continue
            ovals.append(overall * 1000)
            apvals.append(api * 1000)
            pvals.append(policy * 1000)
        data[size] = {
            "overall_delay": np.array(ovals),
            "api_delay": np.array(apvals),
            "policy_delay": np.array(pvals),
        }
    return data


def remove_outliers(arr):
    arr = np.array(arr)
    q1 = np.percentile(arr, 25)
    q3 = np.percentile(arr, 75)
    iqr = q3 - q1
    lower = q1 - 1.5 * iqr
    upper = q3 + 1.5 * iqr
    filtered = arr[(arr >= lower) & (arr <= upper)]
    return filtered


def summary_stats(data):
    # data: {size: {'overall_delay': arr, ...}}
    means, stds = {}, {}
    for size in sorted(data.keys()):
        means[size] = {}
        stds[size] = {}
        for key in ["overall_delay", "api_delay", "policy_delay"]:
            filtered = remove_outliers(data[size][key])
            means[size][key] = np.round(filtered.mean(), 1)
            stds[size][key] = np.round(filtered.std(), 1)
        # Calculate residuals per run
        filtered_overall = remove_outliers(data[size]["overall_delay"])
        filtered_api = remove_outliers(data[size]["api_delay"])
        filtered_policy = remove_outliers(data[size]["policy_delay"])
        # To ensure matching lengths (after outlier removal), take intersection
        n = min(len(filtered_overall), len(filtered_api), len(filtered_policy))
        residuals = filtered_overall[:n] - (filtered_api[:n] + filtered_policy[:n])
        means[size]["residual_delay"] = np.round(residuals.mean(), 1)
        stds[size]["residual_delay"] = np.round(residuals.std(), 1)
    return means, stds


def plot_delays(data, means, stds):
    sizes = sorted(data.keys())
    delay_names = ["overall_delay", "api_delay", "policy_delay"]
    titles = ["Overall Delay", "API Delay", "Policy Delay"]

    fig, axs = plt.subplots(
        1, len(delay_names), figsize=(6 * len(delay_names), 6), sharex=True
    )
    if len(delay_names) == 1:
        axs = [axs]

    for idx, (col, ax, title) in enumerate(zip(delay_names, axs, titles)):
        mean_values = [means[size][col] for size in sizes]
        std_values = [stds[size][col] for size in sizes]
        ax.errorbar(
            sizes,
            mean_values,
            yerr=std_values,
            fmt="o-",
            capsize=5,
            label=col.replace("_", " ").title(),
        )
        ax.set_title(title)
        ax.set_xlabel("Rule Size")
        ax.set_ylabel("Delay (ms)")
        ax.grid(True)
        ax.legend()
    plt.tight_layout()
    plt.savefig("plots/responsiveness.png", dpi=200)


def plot_table_figure(means, stds, output="plots/resp_table"):
    sizes = sorted(means.keys())
    rows = []
    for size in sizes:
        row = [size]
        for col in ["overall_delay", "api_delay", "policy_delay", "residual_delay"]:
            row.append(f"{means[size][col]} ± {stds[size][col]}")
        rows.append(row)

    header = ["Rule Size", "Overall (ms)", "API (ms)", "Policy (ms)", "Residual (ms)"]

    fig, ax = plt.subplots(figsize=(8, len(rows) * 0.6 + 1))
    ax.axis("off")
    table = ax.table(cellText=rows, colLabels=header, loc="center", cellLoc="center")
    table.auto_set_font_size(False)
    table.set_fontsize(12)
    table.scale(1.2, 1.4)
    plt.title("Responsiveness Table (mean ± std, outliers removed)", pad=14)
    plt.tight_layout()
    plt.savefig(output, dpi=200)
    # plt.show()


def print_table(means, stds):
    # Build a DataFrame for pretty printing
    sizes = sorted(means.keys())
    rows = []
    for size in sizes:
        row = [size]
        for col in ["overall_delay", "api_delay", "policy_delay", "residual_delay"]:
            row.append(f"{means[size][col]} ± {stds[size][col]}")
        rows.append(row)
    df = pd.DataFrame(
        rows,
        columns=[
            "Rule Size",
            "Overall (ms)",
            "API (ms)",
            "Policy (ms)",
            "Residual (ms)",
        ],
    )
    print("\nSummary Table (mean ± std, outliers removed):\n")
    print(df.to_string(index=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Plot responsiveness from multi-section file."
    )
    parser.add_argument("file", help="Input file")
    args = parser.parse_args()
    data = parse_file(args.file)
    # print(data[2000])
    means, stds = summary_stats(data)
    plot_delays(data, means, stds)
    # print_table(means, stds)
    plot_table_figure(means, stds)
