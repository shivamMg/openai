"""Fixed CNN/DailyMail data preparation, Azure evaluation, and local result plotting."""

import argparse
import csv
import hashlib
import json
import os
import re
import statistics
import time
import uuid
from datetime import datetime, timezone
from itertools import islice
from pathlib import Path

from datasets import load_dataset
from dotenv import load_dotenv
from openai import OpenAI
from rouge_score import rouge_scorer

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
RESULT = ROOT / "result"
RUNS = RESULT / "runs"
TRAIN_FILE = DATA / "train.jsonl"
VALID_FILE = DATA / "validation.jsonl"
EVAL_FILE = DATA / "eval.jsonl"
RESULTS_FILE = RESULT / "results.tsv"
RESULTS_PLOT_FILE = RESULT / "results.png"
RESULTS_REPORT_FILE = RESULT / "results.md"
MODEL = "gpt-4.1-nano"
FT_MODEL = "gpt-4.1-nano-2025-04-14"
SEED = 42
N_TRAIN, N_VALID, N_EVAL = 1000, 100, 100
MAX_TOKENS = 256
SYSTEM_PROMPT = "Summarize the following news article in concise, factual bullet points, preserving the key information."
RESULT_COLUMNS = [
    "run_id", "kind", "commit", "deployment_name", "model_id", "job_id",
    "n_epochs", "learning_rate_multiplier", "batch_size", "rouge_l", "delta_vs_base",
    "eval_count", "total_seconds", "status", "decision", "description", "fingerprint", "baseline_run_id",
]
SCORER = rouge_scorer.RougeScorer(["rougeL"], use_stemmer=True)


def prepare_data():
    """Create deterministic train, validation, and held-out evaluation JSONL files."""
    DATA.mkdir(parents=True, exist_ok=True)
    dataset = load_dataset("abisee/cnn_dailymail", "3.0.0", streaming=True)
    train = dataset["train"].filter(lambda row: bool(row["article"].strip() and row["highlights"].strip()))
    valid = dataset["validation"].filter(lambda row: bool(row["article"].strip() and row["highlights"].strip()))
    train = list(islice(train.shuffle(seed=SEED, buffer_size=10_000), N_TRAIN))
    valid = list(islice(valid.shuffle(seed=SEED, buffer_size=1_000), N_VALID + N_EVAL))
    validation, evaluation = valid[:N_VALID], valid[N_VALID:]

    def write_ft(path, rows):
        with path.open("w", encoding="utf-8-sig") as out:
            for row in rows:
                item = {"messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": row["article"]},
                    {"role": "assistant", "content": row["highlights"]},
                ]}
                out.write(json.dumps(item, ensure_ascii=False) + "\n")

    if len(train) != N_TRAIN or len(valid) != N_VALID + N_EVAL:
        raise ValueError("The streaming dataset ended before the requested pilot sample sizes were available")
    write_ft(TRAIN_FILE, train)
    write_ft(VALID_FILE, validation)
    with EVAL_FILE.open("w", encoding="utf-8") as out:
        for row in evaluation:
            out.write(json.dumps({"id": row["id"], "article": row["article"], "reference": row["highlights"]}, ensure_ascii=False) + "\n")

    ids = [row["id"] for row in train] + [row["id"] for row in validation] + [row["id"] for row in evaluation]
    if len(ids) != len(set(ids)):
        raise ValueError("Dataset split selection produced overlapping sample IDs")
    provenance = {
        "dataset": "abisee/cnn_dailymail", "config": "3.0.0", "seed": SEED,
        "train": len(train), "validation": len(validation), "evaluation": len(evaluation),
        "sample_ids_sha256": hashlib.sha256("\n".join(ids).encode()).hexdigest(),
    }
    (DATA / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    print(f"Prepared {len(train)} train, {len(validation)} validation, {len(evaluation)} eval examples.")


def read_jsonl(path):
    with path.open(encoding="utf-8-sig") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def evaluation_fingerprint():
    evaluation = read_jsonl(EVAL_FILE)
    source = {
        "ids": [row["id"] for row in evaluation], "model": MODEL,
        "eval_data_sha256": hashlib.sha256(EVAL_FILE.read_bytes()).hexdigest(),
        "system_prompt": SYSTEM_PROMPT, "temperature": 0, "max_tokens": MAX_TOKENS,
        "scorer": "rougeL-fmeasure-stemmer",
    }
    return hashlib.sha256(json.dumps(source, sort_keys=True).encode()).hexdigest()


def client():
    load_dotenv(ROOT / ".env")
    endpoint = os.environ["AZURE_OPENAI_ENDPOINT"].rstrip("/")
    return OpenAI(api_key=os.environ["AZURE_OPENAI_API_KEY"], base_url=endpoint + "/openai/v1/")


def score_deployment(deployment, kind, *, job_id="", model_id="", epochs="", lr="", batch_size="", description="", experiment_seconds=None):
    """Evaluate all fixed examples; persist per-item outputs and aggregate metrics."""
    RUNS.mkdir(parents=True, exist_ok=True)
    run_id = f"{kind}-{datetime.now(timezone.utc):%Y%m%dT%H%M%S%fZ}-{uuid.uuid4().hex[:6]}"
    run_dir = RUNS / run_id
    run_dir.mkdir()
    started = time.monotonic()
    started_at = datetime.now(timezone.utc).isoformat()
    eval_rows = read_jsonl(EVAL_FILE)
    fingerprint = evaluation_fingerprint()
    predictions_path = run_dir / "predictions.jsonl"
    scores = []
    base = latest_base(fingerprint) if kind == "sft" else None
    try:
        aoai = client()
        with predictions_path.open("w", encoding="utf-8") as output:
            for row in eval_rows:
                response = aoai.chat.completions.create(
                    model=deployment,
                    messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": row["article"]}],
                    temperature=0,
                    max_tokens=MAX_TOKENS,
                )
                choice = response.choices[0]
                prediction = choice.message.content or ""
                score = SCORER.score(row["reference"], prediction)["rougeL"].fmeasure
                scores.append(score)
                output.write(json.dumps({
                    "id": row["id"], "reference": row["reference"], "prediction": prediction,
                    "rouge_l": score, "finish_reason": choice.finish_reason,
                }, ensure_ascii=False) + "\n")
                output.flush()
        mean_score = statistics.fmean(scores)
        status = "completed"
        error = ""
    except Exception as exc:
        mean_score, status, error = None, "failed", str(exc)
        raise
    finally:
        elapsed = time.monotonic() - started
        meta = {
            "run_id": run_id, "kind": kind, "deployment_name": deployment, "model_id": model_id or deployment,
            "job_id": job_id, "evaluation_fingerprint": fingerprint, "eval_count": len(scores),
            "rouge_l": mean_score, "status": status if "status" in locals() else "failed",
            "error": error if "error" in locals() else "interrupted",
            "started_at": started_at, "finished_at": datetime.now(timezone.utc).isoformat(),
            "total_seconds": experiment_seconds if experiment_seconds is not None else elapsed,
            "config": {"model": MODEL, "system_prompt": SYSTEM_PROMPT, "temperature": 0, "max_tokens": MAX_TOKENS},
        }
        (run_dir / "metrics.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        if meta["status"] == "completed" and kind == "sft" and base is None:
            meta["status"] = "failed"
            meta["rouge_l"] = None
            meta["error"] = "No matching base evaluation found; run prepare.py --eval-base first"
        if meta["status"] in {"completed", "failed"}:
            append_result({
                "run_id": run_id, "kind": kind, "commit": current_commit(), "deployment_name": deployment,
                "model_id": model_id or deployment, "job_id": job_id, "n_epochs": epochs,
                "learning_rate_multiplier": lr, "batch_size": batch_size,
                "rouge_l": repr(mean_score) if meta["status"] == "completed" else "",
                "delta_vs_base": repr(mean_score - base["rouge_l"]) if base and meta["status"] == "completed" else ("0" if kind == "base" and meta["status"] == "completed" else ""),
                "eval_count": len(scores), "total_seconds": repr(meta["total_seconds"]), "status": meta["status"],
                "decision": "baseline" if kind == "base" else ("pending" if meta["status"] == "completed" else "crash"),
                "description": description or error, "fingerprint": fingerprint,
                "baseline_run_id": base["run_id"] if base else (run_id if kind == "base" else ""),
            })
            if meta["status"] == "completed":
                meta["baseline_run_id"] = base["run_id"] if base else run_id
            (run_dir / "metrics.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
            if meta["status"] == "completed":
                print(f"rouge_l: {mean_score:.6f}  eval_count: {len(scores)}  run_id: {run_id}")
            plot_results()
    return run_id


def current_commit():
    import subprocess
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return "unknown"


def append_result(row):
    RESULT.mkdir(parents=True, exist_ok=True)
    new_file = not RESULTS_FILE.exists()
    with RESULTS_FILE.open("a", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=RESULT_COLUMNS, delimiter="\t", extrasaction="ignore")
        if new_file:
            writer.writeheader()
        writer.writerow({key: row.get(key, "") for key in RESULT_COLUMNS})


def read_results():
    if not RESULTS_FILE.exists():
        return []
    with RESULTS_FILE.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream, delimiter="\t"))


def latest_base(fingerprint=None):
    rows = [r for r in read_results() if r["kind"] == "base" and r["status"] == "completed" and r["eval_count"] == str(N_EVAL)]
    if fingerprint:
        rows = [r for r in rows if r["fingerprint"] == fingerprint]
    if not rows:
        return None
    latest = max(rows, key=lambda r: r["run_id"])
    return {**latest, "rouge_l": float(latest["rouge_l"])}


def write_results_report(rows):
    lines = ["# Autoresearch results", "", "![ROUGE-L results](results.png)", ""]
    if not rows:
        lines.append("No completed runs.")
    else:
        best = max(rows, key=lambda row: float(row["rouge_l"]))
        columns = [
            ("run_id", "run_id"), ("model_id", "model_id"), ("kind", "kind"),
            ("epochs", "n_epochs"), ("lrm", "learning_rate_multiplier"),
            ("batch size", "batch_size"), ("rouge_l", "rouge_l"),
            ("delta_vs_base", "delta_vs_base"), ("eval_count", "eval_count"),
            ("description", "description"),
        ]
        float_columns = {"learning_rate_multiplier", "rouge_l", "delta_vs_base"}
        lines.extend([
            "| " + " | ".join(label for label, _ in columns) + " |",
            "| " + " | ".join("---" for _ in columns) + " |",
        ])
        for row in rows:
            values = []
            for _, key in columns:
                raw_value = row.get(key, "")
                value = f"{float(raw_value):.4f}" if key in float_columns and raw_value else str(raw_value or "—")
                if key == "description":
                    value = re.sub(r"(?<![\w.-])\d+\.\d+(?![\w.-])", lambda match: f"{float(match.group()):.4f}", value)
                value = value.replace("|", "\\|").replace("\n", "<br>")
                values.append(f"**{value}**" if row is best else value)
            lines.append("| " + " | ".join(values) + " |")
    RESULT.mkdir(parents=True, exist_ok=True)
    RESULTS_REPORT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Updated {RESULTS_REPORT_FILE}")


def plot_results():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    rows = read_results()
    valid = [r for r in rows if r["status"] == "completed" and r["eval_count"] == str(N_EVAL) and r["rouge_l"]]
    if not valid:
        return
    # Plot the most recent evaluation protocol only; do not mix incompatible runs.
    fingerprint = valid[-1]["fingerprint"]
    valid = [r for r in valid if r["fingerprint"] == fingerprint]
    bases = [r for r in valid if r["kind"] == "base"]
    sfts = [r for r in valid if r["kind"] == "sft"]
    if not bases:
        return
    base = bases[-1]
    sfts = [row for row in sfts if row.get("baseline_run_id") == base["run_id"]]
    write_results_report([base, *sfts])
    figure, axis = plt.subplots(figsize=(8, 4.5))
    axis.axhline(float(base["rouge_l"]), color="black", linestyle="--", label=f"Base ({float(base['rouge_l']):.4f})")
    markers = {"keep": "o", "discard": "x", "pending": "^", "crash": "s"}
    positions = {row["run_id"]: i for i, row in enumerate(sfts, start=1)}
    for decision, marker in markers.items():
        group = [row for row in sfts if row["decision"] == decision]
        if group:
            axis.scatter([positions[row["run_id"]] for row in group], [float(row["rouge_l"]) for row in group], marker=marker, label=decision)
    axis.set(xlabel="SFT experiment", ylabel="Mean ROUGE-L F1", title="CNN/DailyMail summarization")
    axis.grid(alpha=0.25)
    axis.legend()
    figure.tight_layout()
    RESULT.mkdir(parents=True, exist_ok=True)
    figure.savefig(RESULTS_PLOT_FILE, dpi=150)
    plt.close(figure)
    print(f"Updated {RESULTS_PLOT_FILE}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--eval-base", action="store_true", help="Evaluate the existing Azure deployment named gpt-4.1-nano")
    parser.add_argument("--plot", action="store_true", help="Regenerate the local ROUGE-L plot from results.tsv")
    args = parser.parse_args()
    if args.plot:
        plot_results()
    elif args.eval_base:
        if not EVAL_FILE.exists():
            raise SystemExit("Run prepare.py first to create the fixed eval set")
        score_deployment(MODEL, "base", description="Base GPT-4.1-nano")
    else:
        prepare_data()


if __name__ == "__main__":
    main()
