#!/usr/bin/env python3
"""Generate every figure in the main report from committed result files (law 3).

Companion to ``make_report_tables.py``, with the same rule: nothing is drawn
from a number that is not in a committed file under ``experiments/results/`` or
``models/``. The output is PDF, written to ``report/figures/``, and committed,
so a reader arriving from a clone needs neither a plotting library nor a LaTeX
toolchain to see the pictures.

Four of the figures are the ones the P6 handoff argued the numbers actually
support, and the reasoning is worth keeping beside the code:

1. Both averages, side by side, because they disagree about which classical
   engine leads and a chart carrying one of them would pick a winner by picking
   a denominator.
2. The tier profile, because the two classical engines have strong opposite
   slopes across it and the language model is nearly flat, which is the single
   most informative shape in the benchmark.
3. The finding level precision against recall, which is a picture of three
   threshold policies rather than of three classifiers, and whose caption says
   so.
4. Latency on a log axis, because a linear axis is unreadable across a factor
   of several thousand.

There is deliberately **no** calibration curve for the language model. Its
confidence is self-reported, ``metrics.json`` carries ``calibration: null`` for
it, and putting a self-reported number on the same axis as a calibrated
probability would draw two different quantities as though they were one.

Usage:
    make_report_figures.py [--root DIR] [--out DIR]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt

BENCH = "experiments/results/bench/2026-08-26T20-32-48Z_bench_6457ac7/benchmark.json"
DEV_METRICS = "models/dev_metrics.json"

ENGINES: tuple[str, ...] = ("rules", "ngram", "llm")
TIERS: tuple[str, ...] = ("clean", "partial", "mixed", "hostile")
HELD_OUT_LOCALE = "fr-FR"

# Greyscale first, marker second. The reports are read on paper as often as on a
# screen, and a figure that only works in colour is a figure that stops working
# at the printer.
STYLE: dict[str, dict[str, Any]] = {
    "rules": {"color": "#1b1b1b", "marker": "o", "hatch": "", "linestyle": "-"},
    "ngram": {"color": "#5a5a5a", "marker": "s", "hatch": "//", "linestyle": "--"},
    "llm": {"color": "#9a9a9a", "marker": "^", "hatch": "xx", "linestyle": ":"},
}


def load(root: Path, relative: str) -> Any:
    """Read one committed JSON input, failing loudly when it is not there."""
    path = root / relative
    if not path.is_file():
        raise SystemExit(f"make_report_figures: missing input {relative}")
    return json.loads(path.read_text(encoding="utf-8"))


def prepare() -> None:
    """Set the one plotting style the whole report uses."""
    plt.rcParams.update(
        {
            "figure.dpi": 150,
            "savefig.bbox": "tight",
            "font.size": 9,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "grid.alpha": 0.25,
            "grid.linewidth": 0.5,
            "legend.frameon": False,
        }
    )


def figure_engine_f1(bench: Mapping[str, Any], out: Path) -> Path:
    """Both averages for all three engines, side by side and never alone."""
    engines = bench["grid"]["engines"]
    figure, axes = plt.subplots(figsize=(5.2, 3.0))
    width = 0.36
    positions = range(len(ENGINES))
    macro = [engines[engine]["headline"]["macro_f1"] for engine in ENGINES]
    micro = [engines[engine]["headline"]["micro_f1"] for engine in ENGINES]
    axes.bar(
        [position - width / 2 for position in positions],
        macro,
        width,
        label="macro-F1",
        color="#2b2b2b",
        edgecolor="black",
        linewidth=0.6,
    )
    axes.bar(
        [position + width / 2 for position in positions],
        micro,
        width,
        label="micro-F1",
        color="#c8c8c8",
        edgecolor="black",
        linewidth=0.6,
        hatch="//",
    )
    for position, (left, right) in enumerate(zip(macro, micro, strict=True)):
        axes.text(position - width / 2, left + 0.012, f"{left:.4f}", ha="center", fontsize=7)
        axes.text(position + width / 2, right + 0.012, f"{right:.4f}", ha="center", fontsize=7)
    axes.set_xticks(list(positions))
    axes.set_xticklabels(list(ENGINES))
    axes.set_ylabel("F1 on the test split")
    axes.set_ylim(0.0, 1.0)
    axes.legend(loc="upper right", ncol=2)
    target = out / "engine_f1.pdf"
    figure.savefig(target)
    plt.close(figure)
    return target


def figure_tier_profile(bench: Mapping[str, Any], out: Path) -> Path:
    """The slope of each engine across the four markup quality tiers."""
    engines = bench["grid"]["engines"]
    figure, axes = plt.subplots(figsize=(5.2, 3.0))
    positions = list(range(len(TIERS)))
    for engine in ENGINES:
        values = [engines[engine]["by_tier"][tier]["macro_f1"] for tier in TIERS]
        axes.plot(
            positions,
            values,
            label=engine,
            color=STYLE[engine]["color"],
            marker=STYLE[engine]["marker"],
            linestyle=STYLE[engine]["linestyle"],
            linewidth=1.4,
            markersize=5,
        )
    axes.set_xticks(positions)
    axes.set_xticklabels(list(TIERS))
    axes.set_xlabel("markup quality tier")
    axes.set_ylabel("macro-F1")
    axes.set_ylim(0.4, 1.0)
    axes.legend(loc="lower left", ncol=3)
    target = out / "tier_profile.pdf"
    figure.savefig(target)
    plt.close(figure)
    return target


def figure_locale_profile(bench: Mapping[str, Any], out: Path) -> Path:
    """Macro-F1 by locale, with the held out locale marked as what it is."""
    engines = bench["grid"]["engines"]
    locales = sorted(engines["rules"]["by_locale"])
    figure, axes = plt.subplots(figsize=(5.6, 3.0))
    width = 0.26
    positions = range(len(locales))
    for index, engine in enumerate(ENGINES):
        offset = (index - 1) * width
        values = [engines[engine]["by_locale"][locale]["macro_f1"] for locale in locales]
        axes.bar(
            [position + offset for position in positions],
            values,
            width,
            label=engine,
            color=STYLE[engine]["color"],
            edgecolor="black",
            linewidth=0.5,
            hatch=STYLE[engine]["hatch"],
        )
    held_out = locales.index(HELD_OUT_LOCALE)
    axes.axvspan(held_out - 0.5, held_out + 0.5, color="#000000", alpha=0.06, zorder=0)
    axes.annotate(
        "held out locale",
        xy=(held_out, 0.97),
        ha="center",
        fontsize=7,
        annotation_clip=False,
    )
    axes.set_xticks(list(positions))
    axes.set_xticklabels(locales)
    axes.set_ylabel("macro-F1")
    axes.set_ylim(0.0, 1.05)
    axes.legend(loc="lower right", ncol=3)
    target = out / "locale_profile.pdf"
    figure.savefig(target)
    plt.close(figure)
    return target


def figure_finding_pr(bench: Mapping[str, Any], out: Path) -> Path:
    """Three threshold policies, plotted where they land on precision and recall."""
    engines = bench["grid"]["engines"]
    figure, axes = plt.subplots(figsize=(4.6, 3.4))
    for engine in ENGINES:
        block = engines[engine]["findings"]["MISSING_AUTOCOMPLETE"]
        axes.scatter(
            block["recall"],
            block["precision"],
            s=70,
            label=engine,
            color=STYLE[engine]["color"],
            marker=STYLE[engine]["marker"],
            edgecolor="black",
            linewidth=0.5,
            zorder=3,
        )
        axes.annotate(
            f"{engine}\n{block['accusations']} accusations",
            xy=(block["recall"], block["precision"]),
            xytext=(6, -14),
            textcoords="offset points",
            fontsize=7,
        )
    axes.set_xlabel("recall")
    axes.set_ylabel("precision")
    axes.set_xlim(0.0, 1.0)
    axes.set_ylim(0.0, 1.08)
    target = out / "finding_pr.pdf"
    figure.savefig(target)
    plt.close(figure)
    return target


def figure_latency(bench: Mapping[str, Any], out: Path) -> Path:
    """Latency on a log axis beside the share of wall time the browser takes."""
    engines = bench["grid"]["engines"]
    figure, (left, right) = plt.subplots(1, 2, figsize=(6.6, 3.0))
    positions = range(len(ENGINES))
    for index, percentile in enumerate(("p50", "p95", "p99")):
        values = [engines[engine]["latency_us_per_field"][percentile] for engine in ENGINES]
        shade = ["#1b1b1b", "#6b6b6b", "#b4b4b4"][index]
        left.bar(
            [position + (index - 1) * 0.26 for position in positions],
            values,
            0.26,
            label=percentile,
            color=shade,
            edgecolor="black",
            linewidth=0.5,
        )
    left.set_yscale("log")
    left.set_xticks(list(positions))
    left.set_xticklabels(list(ENGINES))
    left.set_ylabel("microseconds per field, log scale")
    left.legend(loc="upper left", ncol=3, fontsize=7)

    shares = [engines[engine]["wall_time"]["load_and_extract_share"] for engine in ENGINES]
    right.bar(
        list(positions),
        shares,
        0.5,
        color=[STYLE[engine]["color"] for engine in ENGINES],
        edgecolor="black",
        linewidth=0.5,
    )
    for position, share in enumerate(shares):
        right.text(position, share + 0.02, f"{share:.4f}", ha="center", fontsize=7)
    right.set_xticks(list(positions))
    right.set_xticklabels(list(ENGINES))
    right.set_ylim(0.0, 1.1)
    right.set_ylabel("share of wall time spent loading and extracting")
    target = out / "latency.pdf"
    figure.savefig(target)
    plt.close(figure)
    return target


def figure_calibration(dev: Mapping[str, Any], out: Path) -> Path:
    """The n-gram model's reliability on the development split, before and after.

    Only the n-gram engine appears. The rule baseline has no probability at all
    and the language model's confidence is self-reported, so neither belongs on
    an axis of calibrated probability.
    """
    block = dev["calibration"]
    figure, axes = plt.subplots(figsize=(4.4, 3.6))
    axes.plot([0, 1], [0, 1], color="#999999", linewidth=0.8, linestyle=":", label="perfect")
    for name, style, colour in (
        ("before", "--", "#8a8a8a"),
        ("after", "-", "#1b1b1b"),
    ):
        bins = [entry for entry in block[name]["bins"] if entry["count"]]
        axes.plot(
            [entry["mean_predicted"] for entry in bins],
            [entry["mean_observed"] for entry in bins],
            linestyle=style,
            color=colour,
            marker="o",
            markersize=4,
            linewidth=1.3,
            label=f"{name} calibration",
        )
    axes.set_xlabel("mean predicted probability")
    axes.set_ylabel("observed frequency")
    axes.set_xlim(0.0, 1.0)
    axes.set_ylim(0.0, 1.0)
    axes.legend(loc="upper left")
    target = out / "calibration_ngram.pdf"
    figure.savefig(target)
    plt.close(figure)
    return target


def build(root: Path, out: Path) -> list[Path]:
    """Generate every figure and return the files written."""
    bench = load(root, BENCH)
    dev = load(root, DEV_METRICS)
    out.mkdir(parents=True, exist_ok=True)
    prepare()
    return [
        figure_engine_f1(bench, out),
        figure_tier_profile(bench, out),
        figure_locale_profile(bench, out),
        figure_finding_pr(bench, out),
        figure_latency(bench, out),
        figure_calibration(dev, out),
    ]


def main(argv: Sequence[str] | None = None) -> int:
    """Generate the figures and report what was written."""
    parser = argparse.ArgumentParser(description="Generate report figures from result files.")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="repository root")
    parser.add_argument("--out", type=Path, default=None, help="output directory")
    args = parser.parse_args(argv)
    out = args.out if args.out is not None else args.root / "report" / "figures"
    written = build(args.root, out)
    for path in sorted(written):
        print(f"wrote {path.relative_to(args.root)}")
    print(f"make_report_figures: {len(written)} figures generated from committed result files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
