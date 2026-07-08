# pyassess-sis-replication

Replication materials for the manuscript:

**A Scalable Information-System Framework for Reproducible Assessment and Diagnostic Analysis of Python Programming Submissions**


## Repository contents

This repository contains the materials needed to repeat the reported runs:

```text
pyassess-sis-replication/
  README.md
  requirements.txt
  pyassess_core.py
  01_prepare_benchmark.py
  02_run_assessment.py
  03_analyze_diagnostics.py
  04_runtime_checks.py
  benchmark/
    benchmark_metadata.csv
  results/
    *.csv
```

`pyassess_core.py` stores the shared deterministic task definitions and helper functions. The four numbered scripts are intended to be run in sequence.

## Environment and included results

The result tables included in this repository are the manuscript result tables. They keep the timing values from the author's CPU-only Windows run used in the paper. If the numbered scripts are rerun on another machine, platform-dependent timing files such as `internal_scalability.csv`, `subprocess_timeout_demo.csv`, `parallel_throughput.csv`, and `run_summary.csv` may change. The non-runtime assessment tables should reproduce the reported benchmark counts, false-acceptance results, boundary-error split, diagnostic alignment, and layer-wise contributions.

Install the dependency first:

```bash
python -m pip install -r requirements.txt
```

## Step-by-step execution

### Step 1. Prepare benchmark metadata

Command:

```bash
python 01_prepare_benchmark.py
```

Input: none. The deterministic benchmark definitions are stored in `pyassess_core.py`.

Outputs:

```text
benchmark/benchmark_metadata.csv
benchmark/submissions/<task_id>/<variant>.py
results/task_details.csv
results/task_taxonomy.csv
results/benchmark_construction_matrix.csv
```

### Step 2. Run layered assessment

Command:

```bash
python 02_run_assessment.py
```

Input:

```text
benchmark/benchmark_metadata.csv
```

Outputs:

```text
results/submission_level_results.csv
results/baseline_results.csv
results/holdout_evaluation.csv
results/layer_contribution.csv
results/hidden_test_gain_by_label.csv
results/ast_contribution_by_category.csv
```

### Step 3. Analyze diagnostic alignment

Command:

```bash
python 03_analyze_diagnostics.py
```

Input:

```text
results/submission_level_results.csv
```

Outputs:

```text
results/diagnostic_cross_table_long.csv
results/diagnostic_alignment_by_label.csv
results/diagnostic_alignment.csv
results/case_studies.csv
```

### Step 4. Run runtime and protocol checks

Command:

```bash
python 04_runtime_checks.py
```

Input:

```text
benchmark/benchmark_metadata.csv
```

Outputs:

```text
results/internal_scalability.csv
results/subprocess_timeout_demo.csv
results/parallel_throughput.csv
results/execution_mode_interpretation.csv
results/manuscript_environment_windows.csv
results/run_summary.csv
```

