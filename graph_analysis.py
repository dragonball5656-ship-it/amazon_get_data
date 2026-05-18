import csv
from collections import defaultdict
import matplotlib.pyplot as plt
import matplotlib

matplotlib.rcParams["font.family"] = "MS Gothic"

def load_data(filepath):
    data = []
    with open(filepath, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            data.append({"名前": row["名前"], "所属": row["所属"], "スコア": int(row["スコア"])})
    return data

def main():
    data = load_data("課題3.csv")

    dept_scores = defaultdict(list)
    for row in data:
        dept_scores[row["所属"]].append(row["スコア"])

    departments = list(dept_scores.keys())
    avg_scores = [sum(v) / len(v) for v in dept_scores.values()]
    counts = [len(v) for v in dept_scores.values()]
    all_scores = [row["スコア"] for row in data]
    colors = ["steelblue", "tomato", "mediumseagreen", "gold"]

    # 円グラフ（所属ごとの参加者数）
    fig1, ax1 = plt.subplots(figsize=(7, 7))
    wedges, texts, autotexts = ax1.pie(
        counts,
        labels=departments,
        autopct="%1.1f%%",
        startangle=90,
        colors=colors,
        pctdistance=0.75,
    )
    for text in texts:
        text.set_fontsize(12)
    for autotext in autotexts:
        autotext.set_fontsize(11)
    ax1.set_title("所属ごとの参加者数", fontsize=14, pad=20)
    ax1.legend(
        wedges,
        [f"{d}（{c}人）" for d, c in zip(departments, counts)],
        title="所属",
        loc="lower right",
    )
    fig1.savefig("pie_chart.png", dpi=150, bbox_inches="tight")
    plt.close(fig1)
    print("pie_chart.png を保存しました")

    # 棒グラフ（所属ごとの平均スコア）
    fig2, ax2 = plt.subplots(figsize=(8, 5))
    bars = ax2.bar(departments, avg_scores, color=colors, label="平均スコア", width=0.5)
    ax2.set_title("所属ごとの平均スコア", fontsize=14)
    ax2.set_xlabel("所属", fontsize=12)
    ax2.set_ylabel("スコア", fontsize=12)
    ax2.set_ylim(0, 105)
    ax2.legend(fontsize=11)
    for bar, val in zip(bars, avg_scores):
        ax2.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.8,
            f"{val:.1f}",
            ha="center", va="bottom", fontsize=11,
        )
    fig2.tight_layout()
    fig2.savefig("bar_chart.png", dpi=150, bbox_inches="tight")
    plt.close(fig2)
    print("bar_chart.png を保存しました")

    # ヒストグラム（全参加者のスコア分布）
    fig3, ax3 = plt.subplots(figsize=(8, 5))
    ax3.hist(all_scores, bins=8, range=(65, 100), color="steelblue", edgecolor="white", linewidth=0.8)
    ax3.set_title("全参加者のスコア分布", fontsize=14)
    ax3.set_xlabel("スコア", fontsize=12)
    ax3.set_ylabel("人数", fontsize=12)
    ax3.yaxis.set_major_locator(plt.MaxNLocator(integer=True))
    fig3.tight_layout()
    fig3.savefig("histogram.png", dpi=150, bbox_inches="tight")
    plt.close(fig3)
    print("histogram.png を保存しました")

if __name__ == "__main__":
    main()
