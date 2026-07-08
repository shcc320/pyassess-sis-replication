"""Step 1: prepare the benchmark metadata.

Input:
    None. The benchmark task definitions are deterministic and stored in
    pyassess_core.py.

Outputs:
    benchmark/benchmark_metadata.csv
    benchmark/submissions/<task_id>/<variant>.py
    results/task_details.csv
    results/task_taxonomy.csv
    results/benchmark_construction_matrix.csv
"""

from pathlib import Path

import pandas as pd

from pyassess_core import (
    BENCHMARK,
    RESULTS,
    build_records,
    build_tasks,
    benchmark_construction_matrix_rows,
)


def main() -> None:
    tasks = build_tasks()
    records = build_records(tasks)

    meta_rows = []
    for record in records:
        meta_rows.append({
            "submission_id": record["submission_id"],
            "task_id": record["task_id"],
            "split": record["split"],
            "task_title": record["task_title"],
            "category": record["category"],
            "pattern": record["pattern"],
            "variant": record["variant"],
            "primary_label": record["primary_label"],
            "ground_truth_accept": record["ground_truth_accept"],
            "structural_rule": record["structural_rule"],
            "forbidden_names": ";".join(record["forbidden_names"]),
        })
        code_dir = BENCHMARK / "submissions" / record["task_id"]
        code_dir.mkdir(parents=True, exist_ok=True)
        (code_dir / f"{record['variant']}.py").write_text(record["code"], encoding="utf-8")

    pd.DataFrame(meta_rows).to_csv(BENCHMARK / "benchmark_metadata.csv", index=False)

    task_rows = [{
        "task_id": task.task_id,
        "title": task.title,
        "category": task.category,
        "pattern": task.pattern,
        "visible_tests": len(task.visible),
        "hidden_tests": len(task.hidden),
        "structural_rule": task.structural_rule,
    } for task in tasks]
    task_df = pd.DataFrame(task_rows)
    task_df.to_csv(RESULTS / "task_details.csv", index=False)

    taxonomy = task_df.groupby("category").agg(
        tasks=("task_id", "count"),
        patterns=("pattern", lambda x: ", ".join(sorted(set(x)))),
        visible_tests_total=("visible_tests", "sum"),
        hidden_tests_total=("hidden_tests", "sum"),
    ).reset_index()
    taxonomy.to_csv(RESULTS / "task_taxonomy.csv", index=False)

    pd.DataFrame(benchmark_construction_matrix_rows()).to_csv(
        RESULTS / "benchmark_construction_matrix.csv", index=False
    )

    print("Step 1 completed: benchmark metadata prepared.")
    print(f"Tasks: {len(tasks)}; candidate submissions: {len(records)}")
    print(f"Benchmark metadata: {BENCHMARK / 'benchmark_metadata.csv'}")


if __name__ == "__main__":
    main()
