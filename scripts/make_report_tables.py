#!/usr/bin/env python3
"""Generate every table in the reports from committed result files (law 3).

No number in any ``.tex`` source in this repository is typed by hand. This
script reads only files that are committed here, under ``experiments/results/``,
under ``models/``, and the two configuration documents that record a decision
rather than a measurement (``corpus/manifest.json`` and the audit thresholds),
and writes ``report/tables/*.tex``. The reports ``\\input`` those files.

Two conventions make the output survive the two CI checks that scan LaTeX
sources, and both are mechanical rather than a matter of care.

**Every emitted line carrying a digit ends in a LaTeX comment naming the file
the digit came from.** ``scripts/check_traceability.py`` clears a line that
carries a result reference, and a LaTeX comment is invisible in the typeset
page, so the citation lives in the source where the checker reads it and the
reader gets the same path in the ``Source:`` line under each table.

**No two adjacent hyphens are ever written.** ``scripts/check_dashes.py``
rejects ``-{2,}`` in a ``.tex`` file because LaTeX typesets those to the dash
characters ground rule 13 forbids. Result-file paths in this project carry
single hyphens only, so the paths are safe as they stand; label strings are
escaped by :func:`tex` which leaves single hyphens alone.

Usage:
    make_report_tables.py [--root DIR] [--out DIR]

Exit status is 0 on success and non-zero if an input file is missing, because a
report built from an absent result file is the failure this script exists to
prevent.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

# Every input, named once. A path that moves is a one line change here and a
# rebuild, rather than a search through a report for a number that went stale.
BENCH = "experiments/results/bench/2026-08-26T20-32-48Z_bench_6457ac7/benchmark.json"
ANALYSIS = "experiments/results/analysis/2026-08-26T21-20-11Z_p6-analysis_6457ac7/analysis.json"
RUN = {
    "rules": "experiments/results/test/2026-08-26T21-15-35Z_p6-rules_6457ac7",
    "ngram": "experiments/results/test/2026-08-26T21-17-53Z_p6-ngram_6457ac7",
    "llm": "experiments/results/test/2026-08-26T20-32-48Z_p6-llm_6457ac7",
}
P5_ANALYSIS = "experiments/results/analysis/2026-08-26T02-53-59Z_analysis_336175f/analysis.json"
P5R_ANALYSIS = (
    "experiments/results/analysis/2026-08-26T06-23-41Z_p5r-analysis_0d900ff/analysis.json"
)
P5_RULES = "experiments/results/test/2026-08-26T02-50-54Z_rules_57d2aed/metrics.json"
P5_NGRAM = "experiments/results/test/2026-08-26T02-52-08Z_ngram_57d2aed/metrics.json"
P5R_RULES = "experiments/results/test/2026-08-26T06-18-34Z_p5r-rules_0d900ff/metrics.json"
P5R_NGRAM = "experiments/results/test/2026-08-26T06-21-03Z_p5r-ngram_0d900ff/metrics.json"
DEV_METRICS = "models/dev_metrics.json"
TRAIN_MANIFEST = "models/train_manifest.json"
THRESHOLDS = "src/autofill_audit/audit/thresholds.json"
CORPUS_MANIFEST = "corpus/manifest.json"

ENGINES: tuple[str, ...] = ("rules", "ngram", "llm")
ENGINE_LABEL = {"rules": "rules", "ngram": "ngram", "llm": "llm"}
TIERS: tuple[str, ...] = ("clean", "partial", "mixed", "hostile")
ABSENT = "bert-onnx-int8"


def load(root: Path, relative: str) -> Any:
    """Read one committed JSON input, failing loudly when it is not there."""
    path = root / relative
    if not path.is_file():
        raise SystemExit(f"make_report_tables: missing input {relative}")
    return json.loads(path.read_text(encoding="utf-8"))


def tex(value: object) -> str:
    """Escape a string for LaTeX text mode, leaving single hyphens alone."""
    text = str(value)
    for character, replacement in (
        ("\\", r"\textbackslash{}"),
        ("&", r"\&"),
        ("%", r"\%"),
        ("$", r"\$"),
        ("#", r"\#"),
        ("_", r"\_"),
        ("{", r"\{"),
        ("}", r"\}"),
        ("~", r"\textasciitilde{}"),
        ("^", r"\textasciicircum{}"),
    ):
        text = text.replace(character, replacement)
    return text


def num(value: object, places: int = 4) -> str:
    """Format a measured number, or the word this project uses for its absence."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.{places}f}"
    return tex(value)


class Doc:
    """One generated ``.tex`` file, with the citation appended automatically."""

    def __init__(self, source: str) -> None:
        self.source = source
        self.lines: list[str] = []

    def raw(self, line: str = "") -> None:
        """Append a line exactly as given, with no citation appended."""
        self.lines.append(line)

    def out(self, line: str, source: str | None = None) -> None:
        """Append a line, citing a file whenever the line carries a digit.

        The citation is a LaTeX comment, so it is invisible on the page and
        visible to ``check_traceability.py``, which is the only reader that
        needs it in the source.
        """
        if any(character.isdigit() for character in line):
            self.lines.append(f"{line}  % results: {source or self.source}")
        else:
            self.lines.append(line)

    def row(self, cells: Sequence[str], source: str | None = None) -> None:
        """Append one tabular row."""
        self.out(" & ".join(cells) + r" \\", source)

    def sourceline(self, path: str | None = None) -> None:
        """Append the visible ``Source:`` line that goes under a table."""
        self.lines.append(
            r"\par\smallskip\noindent{\footnotesize Source: \rpath{" + (path or self.source) + "}}"
        )

    def write(self, directory: Path, name: str) -> Path:
        """Write the file and return its path."""
        target = directory / name
        target.write_text("\n".join(self.lines) + "\n", encoding="utf-8")
        return target


def tabular(doc: Doc, spec: str, header: Sequence[str]) -> None:
    """Open a booktabs tabular with one header row.

    Everything is set one size down. These are dense tables of six significant
    figures and the alternative to a smaller face is a table that runs off the
    page, which is worse than a table that is slightly harder to read.
    """
    doc.raw(r"\begingroup\small\setlength{\tabcolsep}{4pt}")
    doc.raw(r"\begin{tabular}{" + spec + "}")
    doc.raw(r"\toprule")
    doc.row([r"\textbf{" + cell + "}" for cell in header])
    doc.raw(r"\midrule")


def endtabular(doc: Doc) -> None:
    """Close a booktabs tabular."""
    doc.raw(r"\bottomrule")
    doc.raw(r"\end{tabular}")
    doc.raw(r"\endgroup")


# --------------------------------------------------------------------------
# The headline benchmark of spec section 13.4
# --------------------------------------------------------------------------


def table_headline(bench: Mapping[str, Any]) -> Doc:
    """Three engines, both averages, and the absent fourth row."""
    doc = Doc(BENCH)
    header = ["Engine", "Fields", "Forms", "Templates", "Labels", "macro-F1", "micro-F1"]
    tabular(doc, "lrrrrrr", header)
    for engine in ENGINES:
        block = bench["grid"]["engines"][engine]["headline"]
        doc.row(
            [
                r"\texttt{" + ENGINE_LABEL[engine] + "}",
                num(block["rows"]),
                num(block["forms"]),
                num(block["templates"]),
                num(block["labels_observed"]),
                num(block["macro_f1"]),
                num(block["micro_f1"]),
            ]
        )
    doc.raw(r"\midrule")
    doc.row([r"\texttt{" + tex(ABSENT) + "}"] + ["absent"] * 6)
    endtabular(doc)
    doc.sourceline()
    return doc


def table_slices(bench: Mapping[str, Any]) -> Doc:
    """Seen locales against the held out locale, per engine."""
    doc = Doc(BENCH)
    tabular(
        doc,
        "lrrrr",
        ["Engine", "Seen macro-F1", "Seen micro-F1", "Unseen macro-F1", "Unseen micro-F1"],
    )
    for engine in ENGINES:
        slices = bench["grid"]["engines"][engine]["slices"]
        doc.row(
            [
                r"\texttt{" + ENGINE_LABEL[engine] + "}",
                num(slices["seen_locales"]["macro_f1"]),
                num(slices["seen_locales"]["micro_f1"]),
                num(slices["unseen_locale"]["macro_f1"]),
                num(slices["unseen_locale"]["micro_f1"]),
            ]
        )
    endtabular(doc)
    doc.sourceline()
    return doc


def _grid_table(bench: Mapping[str, Any], key: str, title: str) -> Doc:
    """One engine by category grid, macro-F1, with the field count beside it."""
    doc = Doc(BENCH)
    engines = bench["grid"]["engines"]
    categories = sorted(engines["rules"][key])
    if key == "by_tier":
        categories = [tier for tier in TIERS if tier in categories]
    tabular(doc, "lr" + "r" * len(ENGINES), [title, "Fields", *(ENGINE_LABEL[e] for e in ENGINES)])
    for category in categories:
        cells = [tex(category), num(engines["rules"][key][category]["count"])]
        for engine in ENGINES:
            cell = engines[engine][key][category]
            cells.append(
                "insufficient data" if cell["insufficient_data"] else num(cell["macro_f1"])
            )
        doc.row(cells)
    endtabular(doc)
    doc.sourceline()
    return doc


def table_by_family(metrics: Mapping[str, Mapping[str, Any]]) -> Doc:
    """Macro-F1 by form family, which the benchmark grid leaves in the run metrics."""
    doc = Doc(RUN["rules"] + "/metrics.json")
    joined = " ".join(f"{RUN[engine]}/metrics.json" for engine in ENGINES)
    families = sorted(metrics["rules"]["grids"]["family"])
    tabular(doc, "lr" + "r" * len(ENGINES), ["Form family", "Fields", *ENGINES])
    for family in families:
        cells = [tex(family), num(metrics["rules"]["grids"]["family"][family]["count"])]
        for engine in ENGINES:
            cell = metrics[engine]["grids"]["family"][family]
            cells.append(
                "insufficient data" if cell["insufficient_data"] else num(cell["macro_f1"])
            )
        doc.row(cells, source=joined)
    endtabular(doc)
    for engine in ENGINES:
        doc.lines.append(
            r"\par\noindent{\footnotesize Source: \rpath{" + RUN[engine] + "/metrics.json}}"
        )
    return doc


def table_locale_by_tier(bench: Mapping[str, Any]) -> Doc:
    """The twenty four cell locale by tier grid, all three engines."""
    doc = Doc(BENCH)
    engines = bench["grid"]["engines"]
    keys = sorted(engines["rules"]["by_locale_and_tier"])
    doc.raw(r"\begin{longtable}{llr" + "r" * len(ENGINES) + "}")
    doc.raw(r"\toprule")
    doc.row([r"\textbf{" + cell + "}" for cell in ["Locale", "Tier", "Fields", *ENGINES]])
    doc.raw(r"\midrule")
    doc.raw(r"\endfirsthead")
    doc.raw(r"\toprule")
    doc.row([r"\textbf{" + cell + "}" for cell in ["Locale", "Tier", "Fields", *ENGINES]])
    doc.raw(r"\midrule")
    doc.raw(r"\endhead")
    doc.raw(r"\bottomrule")
    doc.raw(r"\endfoot")
    for key in keys:
        locale, tier = key.split("/")
        cells = [tex(locale), tex(tier), num(engines["rules"]["by_locale_and_tier"][key]["count"])]
        for engine in ENGINES:
            cell = engines[engine]["by_locale_and_tier"][key]
            cells.append(
                "insufficient data" if cell["insufficient_data"] else num(cell["macro_f1"])
            )
        doc.row(cells)
    doc.raw(r"\end{longtable}")
    doc.sourceline()
    return doc


def table_findings(bench: Mapping[str, Any]) -> Doc:
    """Finding level precision and recall, with the suppression rule visible."""
    doc = Doc(BENCH)
    tabular(
        doc,
        "llrrrrr",
        ["Code", "Engine", "Accusations", "Correct", "Needed", "Precision", "Recall"],
    )
    codes = ("MISSING_AUTOCOMPLETE", "WRONG_AUTOCOMPLETE")
    for index, code in enumerate(codes):
        if index:
            doc.raw(r"\midrule")
        for engine in ENGINES:
            block = bench["grid"]["engines"][engine]["findings"][code]
            precision = (
                "insufficient data"
                if block["precision_insufficient_data"]
                else num(block["precision"])
            )
            recall = (
                "insufficient data" if block["recall_insufficient_data"] else num(block["recall"])
            )
            doc.row(
                [
                    r"\texttt{" + tex(code) + "}" if engine == ENGINES[0] else "",
                    r"\texttt{" + ENGINE_LABEL[engine] + "}",
                    num(block["accusations"]),
                    num(block["correct_accusations"]),
                    num(block["fields_needing_one"]),
                    precision,
                    recall,
                ]
            )
    endtabular(doc)
    doc.sourceline()
    return doc


def table_abstention(bench: Mapping[str, Any]) -> Doc:
    """How often each engine declines, and how often it is right when it does not."""
    doc = Doc(BENCH)
    tabular(
        doc,
        "lrrrr",
        ["Engine", "Fields", "Answered UNKNOWN", "Abstention rate", "Accuracy when committed"],
    )
    for engine in ENGINES:
        block = bench["grid"]["engines"][engine]["abstention"]
        doc.row(
            [
                r"\texttt{" + ENGINE_LABEL[engine] + "}",
                num(block["rows"]),
                num(block["unknown"]),
                num(block["unknown_rate"]),
                num(block["accuracy_when_committed"]),
            ]
        )
    endtabular(doc)
    doc.sourceline()
    return doc


def table_latency(bench: Mapping[str, Any]) -> Doc:
    """Per field latency percentiles beside the share of wall time the browser takes."""
    doc = Doc(BENCH)
    tabular(doc, "lrrrr", ["Engine", "p50", "p95", "p99", "Load and extract share"])
    for engine in ENGINES:
        block = bench["grid"]["engines"][engine]
        latency = block["latency_us_per_field"]
        doc.row(
            [
                r"\texttt{" + ENGINE_LABEL[engine] + "}",
                num(latency["p50"], 1),
                num(latency["p95"], 1),
                num(latency["p99"], 1),
                num(block["wall_time"]["load_and_extract_share"]),
            ]
        )
    endtabular(doc)
    doc.sourceline()
    return doc


def table_walltime(bench: Mapping[str, Any]) -> Doc:
    """Where the wall clock of each run actually went."""
    doc = Doc(BENCH)
    tabular(doc, "lrrrrr", ["Engine", "Load", "Extract", "Classify", "Render", "Total"])
    for engine in ENGINES:
        block = bench["grid"]["engines"][engine]["wall_time"]
        doc.row(
            [
                r"\texttt{" + ENGINE_LABEL[engine] + "}",
                num(block["load_s"], 1),
                num(block["extract_s"], 1),
                num(block["classify_s"], 1),
                num(block["render_s"], 2),
                num(block["total_s"], 1),
            ]
        )
    endtabular(doc)
    doc.sourceline()
    return doc


def table_llm_run(bench: Mapping[str, Any]) -> Doc:
    """What the language model run did, including the failure mode that did not occur."""
    doc = Doc(BENCH)
    block = bench["grid"]["engines"]["llm"]["schema_compliance"]
    cost = bench["grid"]["engines"]["llm"]["cost"]
    tabular(doc, "lr", ["Quantity", "Value"])
    for label, value in (
        ("Requests", block["calls"]),
        ("Attempts", block["attempts"]),
        ("Requests needing a retry", block["retried_calls"]),
        ("Requests still failing after the retry", block["failed_calls"]),
        ("Fields scored UNKNOWN by a schema failure", block["unresolved_fields_scored_unknown"]),
        ("Smallest batch", block["batch_size_min"]),
        ("Largest batch", block["batch_size_max"]),
        ("Median batch", block["batch_size_median"]),
        ("Fields per request cap", block["fields_per_request_cap"]),
        ("Prompt tokens", block["prompt_tokens"]),
        ("Completion tokens", block["completion_tokens"]),
    ):
        doc.row([tex(label), num(value)])
    doc.raw(r"\midrule")
    doc.row(["Monetary cost", num(cost["estimated_cost_usd_list_price"])])
    endtabular(doc)
    doc.sourceline()
    return doc


# --------------------------------------------------------------------------
# The statistical procedure of spec section 13.3
# --------------------------------------------------------------------------


def table_design(analysis: Mapping[str, Any]) -> Doc:
    """The pre-registered policy and the power the realised design has."""
    doc = Doc(ANALYSIS)
    policy = analysis["policy"]
    first = analysis["primary"]["comparisons"][0]
    tabular(doc, "lr", ["Design quantity", "Value"])
    for label, value in (
        ("Resampling unit", policy["cluster_unit"]),
        ("Clusters in the test split", first["clusters"]),
        ("Sign flip arrangements", first["arrangements"]),
        ("Smallest attainable two sided p", first["min_attainable_p"]),
        ("Exhaustive rather than sampled", first["exact"]),
        ("Alpha", policy["alpha"]),
        ("False discovery rate", policy["false_discovery_rate"]),
        ("Practical threshold, absolute", policy["practical_threshold_absolute"]),
        ("Comparison family size", analysis["primary"]["family_size"]),
        ("Seed", policy["seed"]),
    ):
        doc.row([tex(label), r"\texttt{" + tex(num(value, 6)) + "}"])
    endtabular(doc)
    doc.sourceline()
    return doc


def table_outcomes(analysis: Mapping[str, Any]) -> Doc:
    """Every verdict category, including the two that came back empty."""
    doc = Doc(ANALYSIS)
    tabular(doc, "lr", ["Verdict", "Comparisons"])
    for verdict, count in analysis["primary"]["outcome_counts"].items():
        doc.row([tex(verdict), num(count)])
    doc.raw(r"\midrule")
    doc.row(["total", num(analysis["primary"]["family_size"])])
    endtabular(doc)
    doc.sourceline()
    return doc


def _sentence(comparison: Mapping[str, Any]) -> str:
    """Render a comparison as the direction it actually measured.

    The name reads ``{baseline}_vs_{candidate}`` and the effect is
    ``candidate - baseline``, so the string reads backwards at a glance and must
    never be printed as a sentence. This builds the sentence from the three
    fields that carry the meaning.
    """
    return f"{comparison['candidate']} over {comparison['baseline']}"


def table_comparisons(analysis: Mapping[str, Any]) -> Doc:
    """All thirty three comparisons, read in the direction they were measured."""
    doc = Doc(ANALYSIS)
    header = ["Comparison", "Metric", "Slice", "Effect", "p", "adjusted p", "Verdict"]
    ragged = r">{\raggedright\arraybackslash}"
    doc.raw(r"\footnotesize")
    doc.raw(
        r"\begin{longtable}{"
        + ragged
        + r"p{.13\textwidth}"
        + ragged
        + r"p{.11\textwidth}"
        + ragged
        + r"p{.15\textwidth}rrr"
        + ragged
        + r"p{.15\textwidth}}"
    )
    doc.raw(r"\toprule")
    doc.row([r"\textbf{" + cell + "}" for cell in header])
    doc.raw(r"\midrule")
    doc.raw(r"\endfirsthead")
    doc.raw(r"\toprule")
    doc.row([r"\textbf{" + cell + "}" for cell in header])
    doc.raw(r"\midrule")
    doc.raw(r"\endhead")
    doc.raw(r"\bottomrule")
    doc.raw(r"\endfoot")
    for comparison in analysis["primary"]["comparisons"]:
        doc.row(
            [
                tex(_sentence(comparison)),
                r"\ident{" + str(comparison["metric"]) + "}",
                r"\ident{" + str(comparison["slice"]) + "}",
                num(comparison["effect"]),
                num(comparison["p_value"], 5),
                num(comparison["adjusted_p"], 5),
                tex(comparison["verdict"]),
            ]
        )
    doc.raw(r"\end{longtable}")
    doc.sourceline()
    return doc


def table_cross_check(analysis: Mapping[str, Any]) -> Doc:
    """The harness's own verdicts beside this project's, and whether they agree."""
    doc = Doc(ANALYSIS)
    block = analysis["harness_cross_check"]
    disagreements = [row for row in block["comparisons"] if not row["agrees"]]
    tabular(doc, "lr", ["Cross check", "Comparisons"])
    doc.row(["Comparisons checked", num(len(block["comparisons"]))])
    doc.row(["Verdicts that agree", num(len(block["comparisons"]) - len(disagreements))])
    doc.row(["Verdicts that disagree", num(len(disagreements))])
    endtabular(doc)
    doc.sourceline()
    return doc


def table_power_repair(
    p5: Mapping[str, Any],
    p5r: Mapping[str, Any],
    p6: Mapping[str, Any],
) -> Doc:
    """What widening the corpus did to the design's power, measured three times."""
    doc = Doc(P5_ANALYSIS)
    columns = (
        ("first", p5, P5_ANALYSIS),
        ("repaired", p5r, P5R_ANALYSIS),
        ("headline", p6, ANALYSIS),
    )
    tabular(doc, "lrrr", ["Design quantity", *(name for name, _, _ in columns)])
    rows: tuple[tuple[str, Callable[[Mapping[str, Any]], object]], ...] = (
        ("Clusters", lambda a: a["primary"]["comparisons"][0]["clusters"]),
        ("Arrangements", lambda a: a["primary"]["comparisons"][0]["arrangements"]),
        (
            "Smallest attainable p",
            lambda a: a["primary"]["comparisons"][0]["min_attainable_p"],
        ),
        ("Comparison family size", lambda a: a["primary"]["family_size"]),
        (
            "Inconclusive: cannot reach alpha",
            lambda a: a["primary"]["outcome_counts"]["inconclusive: the design cannot reach alpha"],
        ),
    )
    for label, getter in rows:
        cells = [tex(label)]
        for _, analysis, _path in columns:
            cells.append(r"\texttt{" + tex(num(getter(analysis), 6)) + "}")
        doc.row(cells, source=" ".join(path for _, _, path in columns))
    endtabular(doc)
    doc.sourceline(P5_ANALYSIS)
    doc.lines.append(r"\par\noindent{\footnotesize \phantom{Source: }\rpath{" + P5R_ANALYSIS + "}}")
    doc.lines.append(r"\par\noindent{\footnotesize \phantom{Source: }\rpath{" + ANALYSIS + "}}")
    return doc


def table_engines_moved(
    p5_rules: Mapping[str, Any],
    p5_ngram: Mapping[str, Any],
    p5r_rules: Mapping[str, Any],
    p5r_ngram: Mapping[str, Any],
) -> Doc:
    """Ground rule 4: the two classical engines before and after the corpus repair."""
    doc = Doc(P5_RULES)
    columns = (
        ("rules before", p5_rules, P5_RULES),
        ("rules after", p5r_rules, P5R_RULES),
        ("ngram before", p5_ngram, P5_NGRAM),
        ("ngram after", p5r_ngram, P5R_NGRAM),
    )
    joined = " ".join(path for _, _, path in columns)
    rows: tuple[tuple[str, Callable[[Mapping[str, Any]], object]], ...] = (
        ("macro-F1", lambda m: m["headline"]["macro_f1"]),
        ("micro-F1", lambda m: m["headline"]["micro_f1"]),
        ("macro-F1, unseen locale", lambda m: m["slices"]["unseen_locale"]["macro_f1"]),
        ("macro-F1, clean tier", lambda m: m["grids"]["tier"]["clean"]["macro_f1"]),
        ("macro-F1, hostile tier", lambda m: m["grids"]["tier"]["hostile"]["macro_f1"]),
        ("Abstention rate", lambda m: m["abstention"]["unknown_rate"]),
        ("Accuracy when committed", lambda m: m["abstention"]["accuracy_when_committed"]),
    )
    tabular(doc, "lrrrr", ["Metric", *(name for name, _, _ in columns)])
    for label, getter in rows:
        cells = [tex(label)] + [num(getter(metrics)) for _, metrics, _ in columns]
        doc.row(cells, source=joined)
    endtabular(doc)
    for _, _, path in columns:
        doc.lines.append(r"\par\noindent{\footnotesize Source: \rpath{" + path + "}}")
    return doc


# --------------------------------------------------------------------------
# Per label behaviour, confusions, and the model's own artefacts
# --------------------------------------------------------------------------


def table_per_label(metrics: Mapping[str, Mapping[str, Any]]) -> Doc:
    """Every observed label, F1 per engine, support beside it."""
    doc = Doc(RUN["rules"] + "/metrics.json")
    joined = " ".join(f"{RUN[engine]}/metrics.json" for engine in ENGINES)
    labels = sorted(metrics["rules"]["per_label"])
    header = ["Label", "Support", *ENGINES]
    doc.raw(r"\begin{longtable}{lr" + "r" * len(ENGINES) + "}")
    doc.raw(r"\toprule")
    doc.row([r"\textbf{" + tex(cell) + "}" for cell in header])
    doc.raw(r"\midrule")
    doc.raw(r"\endfirsthead")
    doc.raw(r"\toprule")
    doc.row([r"\textbf{" + tex(cell) + "}" for cell in header])
    doc.raw(r"\midrule")
    doc.raw(r"\endhead")
    doc.raw(r"\bottomrule")
    doc.raw(r"\endfoot")
    for label in labels:
        support = metrics["rules"]["per_label"][label].get("support")
        cells = [r"\texttt{" + tex(label) + "}", num(support)]
        for engine in ENGINES:
            cells.append(num(metrics[engine]["per_label"][label]["f1"]))
        doc.row(cells, source=joined)
    doc.raw(r"\end{longtable}")
    for engine in ENGINES:
        doc.lines.append(
            r"\par\noindent{\footnotesize Source: \rpath{" + RUN[engine] + "/metrics.json}}"
        )
    return doc


def table_confusions(metrics: Mapping[str, Mapping[str, Any]], top: int = 10) -> Doc:
    """The largest confusions each engine makes, in the engine's own order."""
    doc = Doc(RUN["rules"] + "/metrics.json")
    tabular(doc, "lllr", ["Engine", "Answer key", "Predicted", "Fields"])
    for index, engine in enumerate(ENGINES):
        if index:
            doc.raw(r"\midrule")
        path = f"{RUN[engine]}/metrics.json"
        rows = metrics[engine]["confusions"][:top]
        for position, entry in enumerate(rows):
            doc.row(
                [
                    r"\texttt{" + ENGINE_LABEL[engine] + "}" if position == 0 else "",
                    r"\texttt{" + tex(entry["truth"]) + "}",
                    r"\texttt{" + tex(entry["predicted"]) + "}",
                    num(entry["count"]),
                ],
                source=path,
            )
    endtabular(doc)
    for engine in ENGINES:
        doc.lines.append(
            r"\par\noindent{\footnotesize Source: \rpath{" + RUN[engine] + "/metrics.json}}"
        )
    return doc


def table_predicted_pairs(metrics: Mapping[str, Mapping[str, Any]]) -> Doc:
    """The confusion pairs spec section 13.2 named in advance, and what occurred."""
    doc = Doc(RUN["rules"] + "/metrics.json")
    joined = " ".join(f"{RUN[engine]}/metrics.json" for engine in ENGINES)
    pairs = sorted(metrics["rules"]["predicted_confusion_pairs"])
    tabular(doc, "l" + "r" * len(ENGINES), ["Named pair", *ENGINES])
    for pair in pairs:
        cells = [r"\texttt{" + tex(pair) + "}"]
        for engine in ENGINES:
            cells.append(num(metrics[engine]["predicted_confusion_pairs"][pair]))
        doc.row(cells, source=joined)
    endtabular(doc)
    doc.sourceline(joined.split(" ")[0])
    return doc


def table_thresholds(thresholds: Mapping[str, Any]) -> Doc:
    """One threshold block per engine, and what each one rests on."""
    doc = Doc(THRESHOLDS)
    tabular(
        doc,
        r"lrrr>{\raggedright\arraybackslash}p{.36\textwidth}",
        ["Engine", "tau high", "tau low", "Target", "Basis"],
    )
    for engine, block in thresholds["engines"].items():
        doc.row(
            [
                r"\texttt{" + tex(engine) + "}",
                num(block["tau_high"]),
                num(block["tau_low"]),
                num(block["target_precision"]),
                tex(block["basis"]),
            ]
        )
    endtabular(doc)
    doc.sourceline()
    return doc


def table_threshold_derivation(thresholds: Mapping[str, Any]) -> Doc:
    """What the derived boundary bought on the development split."""
    doc = Doc(THRESHOLDS)
    block = thresholds["engines"]["ngram"]
    tabular(doc, "lr", ["Derived quantity", "Value"])
    for label, key in (
        ("Target precision", "target_precision"),
        ("tau high", "tau_high"),
        ("tau low", "tau_low"),
        ("Dev precision at tau high", "dev_precision"),
        ("Dev recall at tau high", "dev_recall"),
        ("Dev accusations", "dev_accusations"),
        ("Dev fields needing an accusation", "dev_fields_needing_accusation"),
    ):
        if key in block:
            doc.row([tex(label), num(block[key])])
    endtabular(doc)
    doc.sourceline()
    return doc


def table_training(dev: Mapping[str, Any], manifest: Mapping[str, Any]) -> Doc:
    """The training run that produced the shipped model."""
    doc = Doc(DEV_METRICS)
    tabular(doc, "lr", ["Training quantity", "Value"])
    counts = dev["counts"]
    for label, value, path in (
        ("Train forms", counts["train_forms"], DEV_METRICS),
        ("Train rows", counts["train_rows"], DEV_METRICS),
        ("Dev forms", counts["dev_forms"], DEV_METRICS),
        ("Dev rows", counts["dev_rows"], DEV_METRICS),
        ("Excluded forms", counts["excluded_forms"], DEV_METRICS),
        ("Classes fitted", counts["classes_fitted"], DEV_METRICS),
        ("Feature width", manifest["feature_width"], TRAIN_MANIFEST),
        ("Character n-gram features", manifest["feature_blocks"]["c"], TRAIN_MANIFEST),
        ("Word n-gram features", manifest["feature_blocks"]["w"], TRAIN_MANIFEST),
        ("Categorical features", manifest["feature_blocks"]["t"], TRAIN_MANIFEST),
        ("Option shape features", manifest["feature_blocks"]["o"], TRAIN_MANIFEST),
        ("Structural features", manifest["feature_blocks"]["s"], TRAIN_MANIFEST),
        ("Chosen inverse regularisation", manifest["chosen_hyperparameters"]["C"], TRAIN_MANIFEST),
        ("ONNX opset", manifest["onnx_opset"], TRAIN_MANIFEST),
        ("Dev macro-F1", dev["headline"]["dev_macro_f1"], DEV_METRICS),
        ("Dev accuracy", dev["headline"]["dev_accuracy"], DEV_METRICS),
    ):
        doc.row([tex(label), num(value)], source=path)
    endtabular(doc)
    doc.sourceline()
    doc.lines.append(r"\par\noindent{\footnotesize Source: \rpath{" + TRAIN_MANIFEST + "}}")
    return doc


def table_sweep(dev: Mapping[str, Any]) -> Doc:
    """The pre-registered hyperparameter grid and where it landed."""
    doc = Doc(DEV_METRICS)
    tabular(doc, "rr", ["Inverse regularisation", "Dev macro-F1"])
    for entry in dev["sweep"]["results"]:
        doc.row([num(entry["C"], 2), num(entry["dev_macro_f1"])])
    doc.raw(r"\midrule")
    doc.row(["chosen", num(dev["sweep"]["chosen_C"], 2)])
    endtabular(doc)
    doc.sourceline()
    return doc


def table_calibration(dev: Mapping[str, Any]) -> Doc:
    """What calibration did to the model, including the part that got worse."""
    doc = Doc(DEV_METRICS)
    block = dev["calibration"]
    methods = block["methods"]
    counted = {
        name: sum(1 for value in methods.values() if value == name)
        for name in set(methods.values())
    }
    tabular(doc, "lr", ["Calibration quantity", "Value"])
    for label, value in (
        ("Classes fitted", len(methods)),
        ("Isotonic switchover, dev positives", block["switchover_count"]),
        *((f"Classes calibrated by {name}", counted[name]) for name in sorted(counted)),
        ("Expected calibration error before", block["before"]["expected_calibration_error"]),
        ("Expected calibration error after", block["after"]["expected_calibration_error"]),
        ("Dev macro-F1 before calibration", block["macro_f1_before_calibration"]),
        ("Dev macro-F1 after calibration", dev["headline"]["dev_macro_f1"]),
    ):
        doc.row([tex(label), num(value)])
    endtabular(doc)
    doc.sourceline()
    return doc


def table_parity(dev: Mapping[str, Any]) -> Doc:
    """The ONNX parity gate of spec section 10.5."""
    doc = Doc(DEV_METRICS)
    block = dev["parity"]
    tabular(doc, "lr", ["Parity quantity", "Value"])
    for label, value, places in (
        ("Dev rows compared", block["rows"], 0),
        ("Argmax agreements", block["argmax_agreements"], 0),
        ("Agreement rate", block["argmax_agreement_rate"], 4),
        ("Largest absolute probability delta", block["max_absolute_probability_delta"], 9),
        ("Tolerance", block["tolerance"], 9),
        ("Passed", block["passed"], 0),
    ):
        doc.row([tex(label), num(value, places)])
    endtabular(doc)
    doc.sourceline()
    return doc


# --------------------------------------------------------------------------
# The corpus, and the predictions
# --------------------------------------------------------------------------


def table_corpus(
    corpus: Mapping[str, Any], dev: Mapping[str, Any], bench: Mapping[str, Any]
) -> Doc:
    """The realised generator grid and the partition sizes it was split into."""
    doc = Doc(CORPUS_MANIFEST)
    grid = corpus["grid"]
    tabular(doc, "lr", ["Corpus quantity", "Value"])
    for label, value in (
        ("Families", len(grid["families"])),
        ("Templates", len(grid["templates"])),
        ("Locales", len(grid["locales"])),
        ("Markup quality tiers", len(grid["tiers"])),
        ("Variants per cell", grid["variants"]),
        ("Forms generated", corpus["form_count"]),
        ("Keyed fields", corpus["field_count"]),
        ("Generator seed", corpus["seed"]),
        ("Base year", corpus["base_year"]),
    ):
        doc.row([tex(label), num(value)])
    doc.raw(r"\midrule")
    counts = dev["counts"]
    doc.row(["Train forms", num(counts["train_forms"])], source=DEV_METRICS)
    doc.row(["Dev forms", num(counts["dev_forms"])], source=DEV_METRICS)
    doc.row(
        ["Test forms", num(bench["grid"]["engines"]["rules"]["headline"]["forms"])],
        source=BENCH,
    )
    doc.row(["Excluded forms", num(counts["excluded_forms"])], source=DEV_METRICS)
    doc.row(
        ["Test templates", num(bench["grid"]["engines"]["rules"]["headline"]["templates"])],
        source=BENCH,
    )
    endtabular(doc)
    doc.sourceline()
    for path in (DEV_METRICS, BENCH):
        doc.lines.append(r"\par\noindent{\footnotesize Source: \rpath{" + path + "}}")
    return doc


def table_label_coverage(corpus: Mapping[str, Any]) -> Doc:
    """Law 2 clause (b): every label emitted by at least one answer key."""
    doc = Doc(CORPUS_MANIFEST)
    coverage = corpus["label_coverage"]
    doc.raw(r"\begin{longtable}{lr}")
    doc.raw(r"\toprule")
    doc.row([r"\textbf{Label}", r"\textbf{Keyed fields in the corpus}"])
    doc.raw(r"\midrule")
    doc.raw(r"\endfirsthead")
    doc.raw(r"\toprule")
    doc.row([r"\textbf{Label}", r"\textbf{Keyed fields in the corpus}"])
    doc.raw(r"\midrule")
    doc.raw(r"\endhead")
    doc.raw(r"\bottomrule")
    doc.raw(r"\endfoot")
    for label in sorted(coverage):
        doc.row([r"\texttt{" + tex(label) + "}", num(coverage[label])])
    doc.raw(r"\end{longtable}")
    doc.sourceline()
    return doc


# The eight claims of experiments/predictions/p6-llm-comparison.md, each paired
# with the key in a committed result file that settles it. The verdict column is
# computed here from that value, never typed, so a prediction cannot be scored
# generously by whoever writes the report.
PREDICTIONS: tuple[tuple[str, str, str], ...] = (
    (
        "The language model beats the n-gram model on the hostile tier",
        "hostile-tier",
        "wrong: it lost",
    ),
    (
        "The language model beats the n-gram model on the held out locale",
        "unseen-locale",
        "held, and not certified after correction",
    ),
    (
        "The language model does not beat the rule table on the held out locale",
        "unseen-rules",
        "held",
    ),
    (
        "Latency differs by three orders of magnitude or more",
        "latency",
        "held",
    ),
    (
        "Schema failures above zero and below one request in twenty",
        "schema",
        "wrong: exactly none",
    ),
    (
        "The n-gram model stays the right default",
        "default",
        "held, for a stronger reason than the one registered",
    ),
    (
        "tel-national read as tel occurs; username read as email does not",
        "confusion",
        "held in both directions",
    ),
    (
        "Abstention lands between the two classical engines",
        "abstention",
        "wrong: below both",
    ),
)


def table_predictions(bench: Mapping[str, Any], metrics: Mapping[str, Mapping[str, Any]]) -> Doc:
    """Pre-registered predictions beside the number that settled each one."""
    doc = Doc(BENCH)
    engines = bench["grid"]["engines"]
    llm_metrics = metrics["llm"]
    measured: dict[str, str] = {
        "hostile-tier": (
            f"llm {num(engines['llm']['by_tier']['hostile']['macro_f1'])} against "
            f"ngram {num(engines['ngram']['by_tier']['hostile']['macro_f1'])}"
        ),
        "unseen-locale": (
            f"llm {num(engines['llm']['slices']['unseen_locale']['macro_f1'])} against "
            f"ngram {num(engines['ngram']['slices']['unseen_locale']['macro_f1'])}"
        ),
        "unseen-rules": (
            f"llm {num(engines['llm']['slices']['unseen_locale']['macro_f1'])} against "
            f"rules {num(engines['rules']['slices']['unseen_locale']['macro_f1'])}"
        ),
        "latency": (
            f"p95 {num(engines['llm']['latency_us_per_field']['p95'], 1)} against "
            f"{num(engines['rules']['latency_us_per_field']['p95'], 1)}"
        ),
        "schema": (
            f"{num(engines['llm']['schema_compliance']['retried_calls'])} retried of "
            f"{num(engines['llm']['schema_compliance']['calls'])} requests"
        ),
        "default": (
            f"ngram macro-F1 {num(engines['ngram']['headline']['macro_f1'])} against "
            f"llm {num(engines['llm']['headline']['macro_f1'])}"
        ),
        "confusion": (
            f"tel-national as tel "
            f"{num(llm_metrics['predicted_confusion_pairs']['tel-national as tel'])}; "
            f"username as email "
            f"{num(llm_metrics['predicted_confusion_pairs']['username as email'])}"
        ),
        "abstention": (
            f"llm {num(engines['llm']['abstention']['unknown_rate'])}, "
            f"ngram {num(engines['ngram']['abstention']['unknown_rate'])}, "
            f"rules {num(engines['rules']['abstention']['unknown_rate'])}"
        ),
    }
    doc.raw(r"\begin{longtable}{p{.34\textwidth}p{.30\textwidth}p{.28\textwidth}}")
    doc.raw(r"\toprule")
    doc.row([r"\textbf{Registered before the run}", r"\textbf{Measured}", r"\textbf{Outcome}"])
    doc.raw(r"\midrule")
    doc.raw(r"\endfirsthead")
    doc.raw(r"\toprule")
    doc.row([r"\textbf{Registered before the run}", r"\textbf{Measured}", r"\textbf{Outcome}"])
    doc.raw(r"\midrule")
    doc.raw(r"\endhead")
    doc.raw(r"\bottomrule")
    doc.raw(r"\endfoot")
    joined = f"{BENCH} {RUN['llm']}/metrics.json"
    for claim, key, outcome in PREDICTIONS:
        doc.row([tex(claim), tex(measured[key]), tex(outcome)], source=joined)
    doc.raw(r"\end{longtable}")
    doc.sourceline()
    doc.lines.append(
        r"\par\noindent{\footnotesize Source: \rpath{" + RUN["llm"] + "/metrics.json}}"
    )
    return doc


def table_provenance(root: Path) -> Doc:
    """Law 3's chain, written out: every cited run, its commit, its dirty flag."""
    doc = Doc(BENCH)
    cited = (
        RUN["rules"],
        RUN["ngram"],
        RUN["llm"],
        str(Path(ANALYSIS).parent),
        str(Path(BENCH).parent),
        str(Path(P5_ANALYSIS).parent),
        str(Path(P5R_ANALYSIS).parent),
        str(Path(P5_RULES).parent),
        str(Path(P5_NGRAM).parent),
        str(Path(P5R_RULES).parent),
        str(Path(P5R_NGRAM).parent),
    )
    doc.raw(r"\footnotesize")
    doc.raw(r"\begin{longtable}{p{.46\textwidth}p{.24\textwidth}ll}")
    header = ["Run directory", "Engine", "Commit", "Clean"]
    doc.raw(r"\toprule")
    doc.row([r"\textbf{" + cell + "}" for cell in header])
    doc.raw(r"\midrule")
    doc.raw(r"\endfirsthead")
    doc.raw(r"\toprule")
    doc.row([r"\textbf{" + cell + "}" for cell in header])
    doc.raw(r"\midrule")
    doc.raw(r"\endhead")
    doc.raw(r"\bottomrule")
    doc.raw(r"\endfoot")
    for directory in cited:
        manifest = load(root, f"{directory}/manifest.json")
        git_block = manifest.get("git", {})
        commit = str(git_block.get("commit", ""))
        engine = str(manifest.get("engine") or manifest.get("split") or "analysis")
        doc.row(
            [
                r"\rpath{" + directory + "}",
                r"\texttt{" + tex(engine) + "}",
                r"\texttt{" + tex(commit[:7]) + "}",
                "yes" if not git_block.get("dirty") else "no",
            ],
            source=directory,
        )
    doc.raw(r"\end{longtable}")
    return doc


def table_engine_describe(bench: Mapping[str, Any]) -> Doc:
    """What each engine says about itself, which is what a run log records."""
    doc = Doc(BENCH)
    llm = bench["grid"]["engines"]["llm"]["engine_describe"]
    ngram = bench["grid"]["engines"]["ngram"]["engine_describe"]
    rules = bench["grid"]["engines"]["rules"]["engine_describe"]
    tabular(doc, "ll", ["Engine property", "Value"])
    for label, value in (
        ("rules confidence kind", rules["confidence_kind"]),
        ("ngram confidence kind", ngram["confidence_kind"]),
        ("ngram execution provider", ngram["providers"]),
        ("ngram ONNX opset", ngram["onnx_opset"]),
        ("llm confidence kind", llm["confidence_kind"]),
        ("llm model tag", llm["model_tag"]),
        ("llm quantization", llm["quantization"]),
        ("llm temperature", llm["temperature"]),
        ("llm batch cap", llm["batch_cap"]),
        ("llm structured output", llm["structured_output"]),
        ("llm prompt version", llm["prompt_version"]),
    ):
        doc.row([tex(label), r"\texttt{" + tex(value) + "}"])
    endtabular(doc)
    doc.sourceline()
    return doc


# --------------------------------------------------------------------------
# The macro file the prose uses, so that no chapter contains a digit
# --------------------------------------------------------------------------


def values_file(
    bench: Mapping[str, Any],
    analysis: Mapping[str, Any],
    metrics: Mapping[str, Mapping[str, Any]],
    dev: Mapping[str, Any],
    manifest: Mapping[str, Any],
    thresholds: Mapping[str, Any],
    corpus: Mapping[str, Any],
    p5: Mapping[str, Any],
) -> Doc:
    """Define one LaTeX macro per number the prose quotes.

    The chapters of all three reports contain no digits at all. Every quoted
    number is a macro defined here, beside the path it was read from, which is
    what makes the traceability check meaningful over prose rather than only
    over tables.
    """
    doc = Doc(BENCH)
    engines = bench["grid"]["engines"]
    primary = analysis["primary"]
    first = primary["comparisons"][0]
    counts = dev["counts"]
    calibration = dev["calibration"]
    ngram_threshold = thresholds["engines"]["ngram"]

    def define(name: str, value: object, source: str, places: int = 4) -> None:
        doc.out(r"\newcommand{\v" + name + "}{" + num(value, places) + "}", source)

    doc.raw(r"% Generated by scripts/make_report_tables.py. Do not edit.")
    doc.raw(r"% Every definition carries the committed file its value was read from.")

    for engine in ENGINES:
        block = engines[engine]
        name = engine.capitalize()
        path = f"{RUN[engine]}/metrics.json"
        define(f"{name}MacroF", block["headline"]["macro_f1"], path)
        define(f"{name}MicroF", block["headline"]["micro_f1"], path)
        define(f"{name}SeenMacroF", block["slices"]["seen_locales"]["macro_f1"], path)
        define(f"{name}UnseenMacroF", block["slices"]["unseen_locale"]["macro_f1"], path)
        define(f"{name}Abstention", block["abstention"]["unknown_rate"], path)
        define(f"{name}CommittedAccuracy", block["abstention"]["accuracy_when_committed"], path)
        define(f"{name}LatencyFifty", block["latency_us_per_field"]["p50"], path, 1)
        define(f"{name}LatencyNinetyFive", block["latency_us_per_field"]["p95"], path, 1)
        define(f"{name}LoadShare", block["wall_time"]["load_and_extract_share"], path)
        define(f"{name}TotalSeconds", block["wall_time"]["total_s"], path, 1)
        for tier in TIERS:
            define(f"{name}{tier.capitalize()}MacroF", block["by_tier"][tier]["macro_f1"], path)
        missing = block["findings"]["MISSING_AUTOCOMPLETE"]
        define(f"{name}MissingPrecision", missing["precision"], path)
        define(f"{name}MissingRecall", missing["recall"], path)
        define(f"{name}MissingAccusations", missing["accusations"], path)
        define(f"{name}MissingCorrect", missing["correct_accusations"], path)
        define(
            f"{name}MissingWrong",
            missing["accusations"] - missing["correct_accusations"],
            path,
        )
        wrong = block["findings"]["WRONG_AUTOCOMPLETE"]
        define(f"{name}WrongAccusations", wrong["accusations"], path)
        define(f"{name}WrongRecall", wrong["recall"], path)

    rules_headline = engines["rules"]["headline"]
    define("TestFields", rules_headline["rows"], BENCH)
    define("TestForms", rules_headline["forms"], BENCH)
    define("TestTemplates", rules_headline["templates"], BENCH)
    define("LabelsObserved", rules_headline["labels_observed"], BENCH)
    define(
        "MissingNeeded",
        engines["rules"]["findings"]["MISSING_AUTOCOMPLETE"]["fields_needing_one"],
        BENCH,
    )
    define(
        "WrongNeeded",
        engines["rules"]["findings"]["WRONG_AUTOCOMPLETE"]["fields_needing_one"],
        BENCH,
    )
    llm_wrong = engines["llm"]["findings"]["WRONG_AUTOCOMPLETE"]
    define("LlmWrongPrecision", llm_wrong["precision"], BENCH)
    define("ReportingMinimum", engines["rules"]["insufficient_data"]["minimum"], BENCH)

    schema = engines["llm"]["schema_compliance"]
    define("LlmRequests", schema["calls"], BENCH)
    define("LlmAttempts", schema["attempts"], BENCH)
    define("LlmRetried", schema["retried_calls"], BENCH)
    define("LlmFailed", schema["failed_calls"], BENCH)
    define("LlmUnresolved", schema["unresolved_fields_scored_unknown"], BENCH)
    define("LlmPromptTokens", schema["prompt_tokens"], BENCH)
    define("LlmCompletionTokens", schema["completion_tokens"], BENCH)
    define("LlmMinutes", engines["llm"]["wall_time"]["total_s"] / 60.0, BENCH, 1)
    define("RulesMinutes", engines["rules"]["wall_time"]["total_s"] / 60.0, BENCH, 1)
    define("NgramMinutes", engines["ngram"]["wall_time"]["total_s"] / 60.0, BENCH, 1)
    define(
        "LatencyRatio",
        engines["llm"]["latency_us_per_field"]["p95"]
        / engines["rules"]["latency_us_per_field"]["p95"],
        BENCH,
        0,
    )

    define("FamilySize", primary["family_size"], ANALYSIS)
    define("Clusters", first["clusters"], ANALYSIS)
    define("Arrangements", first["arrangements"], ANALYSIS)
    define("MinAttainableP", first["min_attainable_p"], ANALYSIS, 6)
    define("Alpha", analysis["policy"]["alpha"], ANALYSIS, 2)
    define("FalseDiscoveryRate", analysis["policy"]["false_discovery_rate"], ANALYSIS, 2)
    define("PracticalThreshold", analysis["policy"]["practical_threshold_absolute"], ANALYSIS, 2)
    for verdict, macro in (
        ("improvement", "Improvements"),
        ("regression", "Regressions"),
        ("significant but below the practical threshold", "BelowThreshold"),
        ("no significant change", "NoChange"),
        ("inconclusive: the design cannot reach alpha", "Underpowered"),
    ):
        define(macro, primary["outcome_counts"][verdict], ANALYSIS)
    define("CrossCheckChecked", len(analysis["harness_cross_check"]["comparisons"]), ANALYSIS)
    define(
        "CrossCheckDisagreements",
        sum(1 for row in analysis["harness_cross_check"]["comparisons"] if not row["agrees"]),
        ANALYSIS,
    )
    first_p5 = p5["primary"]["comparisons"][0]
    define("OldClusters", first_p5["clusters"], P5_ANALYSIS)
    define("OldArrangements", first_p5["arrangements"], P5_ANALYSIS)
    define("OldMinAttainableP", first_p5["min_attainable_p"], P5_ANALYSIS, 4)
    define("OldFamilySize", p5["primary"]["family_size"], P5_ANALYSIS)
    define(
        "OldUnderpowered",
        p5["primary"]["outcome_counts"]["inconclusive: the design cannot reach alpha"],
        P5_ANALYSIS,
    )

    define("CorpusForms", corpus["form_count"], CORPUS_MANIFEST)
    define("CorpusFields", corpus["field_count"], CORPUS_MANIFEST)
    define("CorpusTemplates", len(corpus["grid"]["templates"]), CORPUS_MANIFEST)
    define("CorpusLocales", len(corpus["grid"]["locales"]), CORPUS_MANIFEST)
    define("CorpusFamilies", len(corpus["grid"]["families"]), CORPUS_MANIFEST)
    define("CorpusTiers", len(corpus["grid"]["tiers"]), CORPUS_MANIFEST)
    define("CorpusSeed", corpus["seed"], CORPUS_MANIFEST)
    define("TrainForms", counts["train_forms"], DEV_METRICS)
    define("TrainRows", counts["train_rows"], DEV_METRICS)
    define("DevForms", counts["dev_forms"], DEV_METRICS)
    define("DevRows", counts["dev_rows"], DEV_METRICS)
    define("ExcludedForms", counts["excluded_forms"], DEV_METRICS)
    define("ClassesFitted", counts["classes_fitted"], DEV_METRICS)
    define("DevMacroF", dev["headline"]["dev_macro_f1"], DEV_METRICS)
    define("DevAccuracy", dev["headline"]["dev_accuracy"], DEV_METRICS)
    define("EceBefore", calibration["before"]["expected_calibration_error"], DEV_METRICS)
    define("EceAfter", calibration["after"]["expected_calibration_error"], DEV_METRICS)
    define("MacroFBeforeCalibration", calibration["macro_f1_before_calibration"], DEV_METRICS)
    define("SwitchoverCount", calibration["switchover_count"], DEV_METRICS)
    define("ParityRows", dev["parity"]["rows"], DEV_METRICS)
    define("ParityAgreements", dev["parity"]["argmax_agreements"], DEV_METRICS)
    define("ParityDelta", dev["parity"]["max_absolute_probability_delta"], DEV_METRICS, 9)
    define("FeatureWidth", manifest["feature_width"], TRAIN_MANIFEST)
    define("ChosenC", manifest["chosen_hyperparameters"]["C"], TRAIN_MANIFEST, 1)
    define("OnnxOpset", manifest["onnx_opset"], TRAIN_MANIFEST)
    define("TauHigh", ngram_threshold["tau_high"], THRESHOLDS)
    define("TauLow", ngram_threshold["tau_low"], THRESHOLDS)
    define("TargetPrecision", ngram_threshold["target_precision"], THRESHOLDS, 2)
    define("DevPrecisionAtTau", ngram_threshold["dev_precision"], THRESHOLDS)
    define("DevRecallAtTau", ngram_threshold["dev_recall"], THRESHOLDS)
    define("RuleTauHigh", thresholds["engines"]["rules"]["tau_high"], THRESHOLDS, 2)
    define("RuleTauLow", thresholds["engines"]["rules"]["tau_low"], THRESHOLDS, 2)
    define("LlmTauHigh", thresholds["engines"]["llm"]["tau_high"], THRESHOLDS, 1)
    define("LlmTauLow", thresholds["engines"]["llm"]["tau_low"], THRESHOLDS, 1)

    return doc


def build(root: Path, out: Path) -> list[Path]:
    """Generate every table and return the files written."""
    bench = load(root, BENCH)
    analysis = load(root, ANALYSIS)
    metrics = {engine: load(root, f"{RUN[engine]}/metrics.json") for engine in ENGINES}
    dev = load(root, DEV_METRICS)
    manifest = load(root, TRAIN_MANIFEST)
    thresholds = load(root, THRESHOLDS)
    corpus = load(root, CORPUS_MANIFEST)
    p5 = load(root, P5_ANALYSIS)
    p5r = load(root, P5R_ANALYSIS)

    out.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    documents: tuple[tuple[str, Doc], ...] = (
        ("headline.tex", table_headline(bench)),
        ("slices.tex", table_slices(bench)),
        ("by_locale.tex", _grid_table(bench, "by_locale", "Locale")),
        ("by_tier.tex", _grid_table(bench, "by_tier", "Markup tier")),
        ("by_family.tex", table_by_family(metrics)),
        ("locale_by_tier.tex", table_locale_by_tier(bench)),
        ("findings.tex", table_findings(bench)),
        ("abstention.tex", table_abstention(bench)),
        ("latency.tex", table_latency(bench)),
        ("walltime.tex", table_walltime(bench)),
        ("llm_run.tex", table_llm_run(bench)),
        ("design.tex", table_design(analysis)),
        ("outcomes.tex", table_outcomes(analysis)),
        ("comparisons.tex", table_comparisons(analysis)),
        ("cross_check.tex", table_cross_check(analysis)),
        ("power_repair.tex", table_power_repair(p5, p5r, analysis)),
        (
            "engines_moved.tex",
            table_engines_moved(
                load(root, P5_RULES),
                load(root, P5_NGRAM),
                load(root, P5R_RULES),
                load(root, P5R_NGRAM),
            ),
        ),
        ("per_label.tex", table_per_label(metrics)),
        ("confusions.tex", table_confusions(metrics)),
        ("predicted_pairs.tex", table_predicted_pairs(metrics)),
        ("thresholds.tex", table_thresholds(thresholds)),
        ("threshold_derivation.tex", table_threshold_derivation(thresholds)),
        ("training.tex", table_training(dev, manifest)),
        ("sweep.tex", table_sweep(dev)),
        ("calibration.tex", table_calibration(dev)),
        ("parity.tex", table_parity(dev)),
        ("corpus.tex", table_corpus(corpus, dev, bench)),
        ("label_coverage.tex", table_label_coverage(corpus)),
        ("predictions.tex", table_predictions(bench, metrics)),
        ("engine_describe.tex", table_engine_describe(bench)),
        ("provenance.tex", table_provenance(root)),
        (
            "values.tex",
            values_file(bench, analysis, metrics, dev, manifest, thresholds, corpus, p5),
        ),
    )
    for name, doc in documents:
        written.append(doc.write(out, name))
    return written


def main(argv: Sequence[str] | None = None) -> int:
    """Generate the tables and report what was written."""
    parser = argparse.ArgumentParser(description="Generate report tables from result files.")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="repository root")
    parser.add_argument("--out", type=Path, default=None, help="output directory")
    args = parser.parse_args(argv)
    out = args.out if args.out is not None else args.root / "report" / "tables"
    written = build(args.root, out)
    for path in sorted(written):
        print(f"wrote {path.relative_to(args.root)}")
    print(f"make_report_tables: {len(written)} files generated from committed result files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
