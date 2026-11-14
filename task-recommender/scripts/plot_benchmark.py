"""Render the multi-round benchmark as light/dark report charts."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import gridspec  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DIM_LABELS = {
    "reputation": "信誉",
    "skill": "技能",
    "expertise": "专长",
    "collaborative": "协同",
    "preference": "偏好",
    "load": "负载",
    "customer_preference": "客户偏好",
}

THEMES = {
    "light": {
        "surface": "#fcfcfb",
        "text": "#0b0b0b",
        "secondary": "#52514e",
        "muted": "#898781",
        "grid": "#e1e0d9",
        "axis": "#c3c2b7",
        "series": ["#2a78d6", "#eb6834", "#1baf7a"],
        "weight": "#2a78d6",
    },
    "dark": {
        "surface": "#1a1a19",
        "text": "#f0efec",
        "secondary": "#c3c2b7",
        "muted": "#898781",
        "grid": "#2c2c2a",
        "axis": "#383835",
        "series": ["#3987e5", "#d95926", "#199e70"],
        "weight": "#3987e5",
    },
}


def load_rows() -> list[dict]:
    path = ROOT / "reports" / "benchmark_rounds.json"
    if not path.exists():
        raise SystemExit(
            "reports/benchmark_rounds.json not found; "
            "run scripts/run_benchmark_rounds.py first"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _style_axis(ax, theme, show_y: bool = True) -> None:
    ax.set_facecolor(theme["surface"])
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(theme["axis"])
        ax.spines[side].set_linewidth(1)
    ax.tick_params(
        colors=theme["muted"],
        labelsize=9,
        length=0,
        labelleft=show_y,
        labelbottom=True,
    )
    ax.grid(axis="y", color=theme["grid"], linewidth=0.8)
    ax.set_axisbelow(True)


def render(theme_name: str, rows: list[dict]) -> Path:
    theme = THEMES[theme_name]
    plt.rcParams["font.sans-serif"] = [
        "Microsoft YaHei",
        "SimHei",
        "Noto Sans CJK SC",
        "DejaVu Sans",
    ]
    plt.rcParams["axes.unicode_minus"] = False

    rounds = [item["round"] for item in rows]
    top1 = [item["metrics"]["top1"] for item in rows]
    top5 = [item["metrics"]["top5"] for item in rows]
    test1 = [item["metrics"]["test_top1"] for item in rows]
    weights = [item["weights_after"] for item in rows]
    initial = rows[0]["weights_before"]

    fig = plt.figure(figsize=(14, 10.5), facecolor=theme["surface"])
    grid = gridspec.GridSpec(
        3,
        4,
        figure=fig,
        height_ratios=[1.55, 1, 1],
        hspace=0.62,
        wspace=0.32,
        left=0.075,
        right=0.955,
        top=0.86,
        bottom=0.07,
    )

    fig.text(
        0.075,
        0.94,
        f"对答案学习：{len(rounds)} 轮命中率与权重漂移",
        color=theme["text"],
        fontsize=18,
        fontweight="bold",
        ha="left",
    )
    fig.text(
        0.075,
        0.905,
        "1,000 条自然语言任务 · 100 份自然语言简历 · 800 训练 / 200 测试",
        color=theme["secondary"],
        fontsize=10,
        ha="left",
    )
    fig.text(
        0.075,
        0.882,
        "每轮：清空推荐缓存 → 推荐 → 对答案 → 只用训练集学习",
        color=theme["muted"],
        fontsize=9,
        ha="left",
    )

    ax = fig.add_subplot(grid[0, :])
    _style_axis(ax, theme)
    ax.set_xlim(0.6, rounds[-1] + 2.1)
    ax.set_ylim(0, 1.04)
    tick_rounds = rounds if len(rounds) <= 12 else rounds[::2]
    ax.set_xticks(tick_rounds)
    ax.set_xticklabels([f"R{value}" for value in tick_rounds])
    ax.set_yticks([0, 0.2, 0.4, 0.6, 0.8, 1.0])
    ax.set_yticklabels(["0.0", "0.2", "0.4", "0.6", "0.8", "1.0"])
    ax.set_xlabel("轮次", color=theme["muted"], fontsize=10, labelpad=8)
    ax.set_ylabel("命中率", color=theme["muted"], fontsize=10, labelpad=8)

    series = [
        ("Top-1", top1, theme["series"][0], 0.70),
        ("Top-5", top5, theme["series"][1], 0.99),
        ("测试集 Top-1", test1, theme["series"][2], 0.78),
    ]
    for label, values, color, label_y in series:
        ax.plot(
            rounds,
            values,
            color=color,
            linewidth=2.0,
            marker="o",
            markersize=6.5,
            markeredgecolor=theme["surface"],
            markeredgewidth=1.4,
            zorder=3,
        )
        ax.text(
            rounds[-1] + 0.35,
            label_y,
            f"{label}  {values[-1]:.3f}",
            color=theme["secondary"],
            fontsize=9,
            va="center",
            ha="left",
        )

    ax.annotate(
        f"Top-1 +{(top1[-1] - top1[0]) * 100:.1f}pp",
        xy=(rounds[-1] - 0.5, top1[-1] + 0.10),
        color=theme["series"][0],
        fontsize=9,
        ha="right",
        fontweight="bold",
    )

    weight_axes = []
    positions = [
        (1, 0),
        (1, 1),
        (1, 2),
        (1, 3),
        (2, 0),
        (2, 1),
        (2, 2),
    ]
    keys = list(DIM_LABELS)
    for index, key in enumerate(keys):
        row, col = positions[index]
        weight_ax = fig.add_subplot(grid[row, col], sharey=weight_axes[0] if weight_axes else None)
        weight_axes.append(weight_ax)
        _style_axis(weight_ax, theme, show_y=(col == 0))
        values = [item[key] for item in weights]
        weight_ax.plot(
            rounds,
            values,
            color=theme["weight"],
            linewidth=2.0,
            marker="o",
            markersize=4.5,
            markeredgecolor=theme["surface"],
            markeredgewidth=1.0,
            zorder=3,
        )
        weight_ax.axhline(
            initial.get(key, values[0]),
            color=theme["muted"],
            linewidth=1,
            linestyle=(0, (4, 4)),
            zorder=1,
        )
        weight_ax.set_title(
            f"{DIM_LABELS[key]}  {initial.get(key, values[0]):.3f} → {values[-1]:.3f}",
            color=theme["secondary"],
            fontsize=10,
            loc="left",
            pad=6,
        )
        weight_ax.set_xticks([rounds[0], rounds[len(rounds) // 2], rounds[-1]])
        weight_ax.set_ylim(0, 0.46)
        weight_ax.set_yticks([0, 0.2, 0.4])
        if index == 0:
            weight_ax.set_ylabel("权重", color=theme["muted"], fontsize=9)

    fig.text(
        0.075,
        0.018,
        "虚线 = 初始权重；实线 = 每轮学习后的权重。标签只在对答案和学习阶段读取。",
        color=theme["muted"],
        fontsize=9,
        ha="left",
    )

    suffix = "" if theme_name == "light" else "_dark"
    png = ROOT / "reports" / f"benchmark_curve{suffix}.png"
    svg = ROOT / "reports" / f"benchmark_curve{suffix}.svg"
    fig.savefig(png, dpi=180, facecolor=theme["surface"], bbox_inches="tight")
    fig.savefig(svg, facecolor=theme["surface"], bbox_inches="tight")
    plt.close(fig)
    return png


def main() -> None:
    rows = load_rows()
    (ROOT / "reports").mkdir(parents=True, exist_ok=True)
    for mode in ("light", "dark"):
        path = render(mode, rows)
        print(path)


if __name__ == "__main__":
    main()
