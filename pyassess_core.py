
import ast
import csv
import math
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, asdict
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
BENCHMARK = ROOT / "benchmark"
for p in [RESULTS, BENCHMARK]:
    p.mkdir(exist_ok=True)


@dataclass
class TaskSpec:
    task_id: str
    title: str
    category: str
    pattern: str
    visible: list
    hidden: list
    forbidden_names: list
    structural_rule: str
    correct_body: str
    alt_body: str
    constraint_body: str
    wrong_value: object
    boundary_input: object


def make_func(body: str) -> str:
    return "def solve(x):\n" + "\n".join("    " + line for line in body.strip().splitlines()) + "\n"


def literal(v):
    return repr(v)


def make_visible_overfit_code(task: TaskSpec):
    cases = []
    for inp, expected in task.visible:
        cases.append(f"    if x == {literal(inp)}:\n        return {literal(expected)}")
    return "def solve(x):\n" + "\n".join(cases) + f"\n    return {literal(task.wrong_value)}\n"


def make_boundary_error_code(task: TaskSpec):
    return (
        "def solve(x):\n"
        f"    if x == {literal(task.boundary_input)}:\n"
        f"        return {literal(task.wrong_value)}\n"
        + "\n".join("    " + line for line in task.correct_body.strip().splitlines())
        + "\n"
    )


def make_boundary_runtime_code(task: TaskSpec):
    # A small subset of boundary-error variants is designed to fail at
    # execution time on the boundary input. This preserves the constructed
    # label while allowing observed diagnosis to reflect the actual failure mode.
    return (
        "def solve(x):\n"
        f"    if x == {literal(task.boundary_input)}:\n"
        "        return 1 / 0\n"
        + "\n".join("    " + line for line in task.correct_body.strip().splitlines())
        + "\n"
    )


def make_wrong_logic_code(task: TaskSpec):
    return f"def solve(x):\n    return {literal(task.wrong_value)}\n"


def make_syntax_error_code(task: TaskSpec):
    return "def solve(x)\n    return x\n"


def make_runtime_error_code(task: TaskSpec):
    return "def solve(x):\n    return 1 / 0\n"


def make_incomplete_code(task: TaskSpec):
    return "def solve(x):\n    pass\n"


def make_nontermination_code(task: TaskSpec):
    return "def solve(x):\n    while True:\n        pass\n"


def template_library():
    # Each template uses solve(x) and returns an expected Python object.
    return [
        {
            "pattern": "factorial",
            "category": "Loops",
            "title": "factorial value",
            "visible": [(3, 6), (5, 120)],
            "hidden": [(0, 1), (1, 1), (7, 5040)],
            "forbidden": ["prod"],
            "rule": "no_math_prod",
            "correct": """
result = 1
for i in range(2, x + 1):
    result *= i
return result
""",
            "alt": """
result = 1
i = 1
while i <= x:
    result *= i
    i += 1
return result
""",
            "constraint": """
import math
return math.prod(range(1, x + 1))
""",
            "wrong": 0,
            "boundary": 0
        },
        {
            "pattern": "sum_to_n",
            "category": "Loops",
            "title": "summation from 1 to n",
            "visible": [(3, 6), (5, 15)],
            "hidden": [(0, 0), (1, 1), (10, 55)],
            "forbidden": ["sum"],
            "rule": "no_sum_builtin",
            "correct": """
total = 0
for i in range(1, x + 1):
    total += i
return total
""",
            "alt": """
total = 0
i = 1
while i <= x:
    total += i
    i += 1
return total
""",
            "constraint": """
return sum(range(1, x + 1))
""",
            "wrong": -1,
            "boundary": 0
        },
        {
            "pattern": "count_even",
            "category": "Lists",
            "title": "count even values",
            "visible": [([1, 2, 3, 4], 2), ([2, 4, 6], 3)],
            "hidden": [([], 0), ([1, 3, 5], 0), ([-2, -1, 0], 2)],
            "forbidden": ["sum"],
            "rule": "no_sum_builtin",
            "correct": """
count = 0
for value in x:
    if value % 2 == 0:
        count += 1
return count
""",
            "alt": """
count = 0
for value in x:
    count += 1 if value % 2 == 0 else 0
return count
""",
            "constraint": """
return sum(1 for value in x if value % 2 == 0)
""",
            "wrong": 99,
            "boundary": []
        },
        {
            "pattern": "max_list",
            "category": "Lists",
            "title": "maximum list value",
            "visible": [([1, 5, 3], 5), ([2, 2, 1], 2)],
            "hidden": [([-5, -2, -9], -2), ([7], 7), ([3, 9, 1], 9)],
            "forbidden": ["max"],
            "rule": "no_max_builtin",
            "correct": """
best = x[0]
for value in x[1:]:
    if value > best:
        best = value
return best
""",
            "alt": """
best = None
for value in x:
    if best is None or value > best:
        best = value
return best
""",
            "constraint": """
return max(x)
""",
            "wrong": None,
            "boundary": [7]
        },
        {
            "pattern": "unique_count",
            "category": "Lists",
            "title": "number of unique values",
            "visible": [([1, 1, 2, 3], 3), ([2, 2, 2], 1)],
            "hidden": [([], 0), ([-1, -1, 0], 2), ([5, 4, 5, 4], 2)],
            "forbidden": ["set"],
            "rule": "no_set_builtin",
            "correct": """
seen = []
for value in x:
    if value not in seen:
        seen.append(value)
return len(seen)
""",
            "alt": """
seen = {}
for value in x:
    seen[value] = True
return len(seen)
""",
            "constraint": """
return len(set(x))
""",
            "wrong": -1,
            "boundary": []
        },
        {
            "pattern": "word_count",
            "category": "Dictionaries",
            "title": "word frequency dictionary",
            "visible": [("a b a", {"a": 2, "b": 1}), ("cat dog", {"cat": 1, "dog": 1})],
            "hidden": [("", {}), ("a a a", {"a": 3}), ("red blue red", {"red": 2, "blue": 1})],
            "forbidden": ["Counter"],
            "rule": "no_counter_class",
            "correct": """
counts = {}
for word in x.split():
    counts[word] = counts.get(word, 0) + 1
return counts
""",
            "alt": """
counts = {}
for word in x.split():
    if word not in counts:
        counts[word] = 0
    counts[word] += 1
return counts
""",
            "constraint": """
from collections import Counter
return dict(Counter(x.split()))
""",
            "wrong": {"__wrong__": 1},
            "boundary": ""
        },
        {
            "pattern": "count_vowels",
            "category": "Strings",
            "title": "count vowels in a string",
            "visible": [("hello", 2), ("ABC", 1)],
            "hidden": [("", 0), ("sky", 0), ("Education", 5)],
            "forbidden": ["sum"],
            "rule": "no_sum_builtin",
            "correct": """
count = 0
for ch in x.lower():
    if ch in "aeiou":
        count += 1
return count
""",
            "alt": """
vowels = "aeiou"
count = 0
for ch in x:
    if ch.lower() in vowels:
        count += 1
return count
""",
            "constraint": """
return sum(1 for ch in x.lower() if ch in "aeiou")
""",
            "wrong": 42,
            "boundary": ""
        },
        {
            "pattern": "normalized_palindrome",
            "category": "Strings",
            "title": "normalized palindrome check",
            "visible": [("Level", True), ("hello", False)],
            "hidden": [("", True), ("A man, a plan, a canal: Panama", True), ("abc", False)],
            "forbidden": ["reversed"],
            "rule": "no_reversed_builtin",
            "correct": """
cleaned = ""
for ch in x:
    if ch.isalnum():
        cleaned += ch.lower()
left = 0
right = len(cleaned) - 1
while left < right:
    if cleaned[left] != cleaned[right]:
        return False
    left += 1
    right -= 1
return True
""",
            "alt": """
cleaned = ""
for ch in x:
    if ch.isalnum():
        cleaned = cleaned + ch.lower()
for i in range(len(cleaned) // 2):
    if cleaned[i] != cleaned[len(cleaned) - 1 - i]:
        return False
return True
""",
            "constraint": """
cleaned = ''.join(ch.lower() for ch in x if ch.isalnum())
return cleaned == ''.join(reversed(cleaned))
""",
            "wrong": False,
            "boundary": ""
        },
        {
            "pattern": "grade_letter",
            "category": "Conditional logic",
            "title": "numeric score to letter grade",
            "visible": [(95, "A"), (72, "C")],
            "hidden": [(59, "F"), (60, "D"), (89, "B")],
            "forbidden": ["IfExp"],
            "rule": "no_conditional_expression",
            "correct": """
if x >= 90:
    return "A"
elif x >= 80:
    return "B"
elif x >= 70:
    return "C"
elif x >= 60:
    return "D"
else:
    return "F"
""",
            "alt": """
grade = "F"
if x >= 60:
    grade = "D"
if x >= 70:
    grade = "C"
if x >= 80:
    grade = "B"
if x >= 90:
    grade = "A"
return grade
""",
            "constraint": """
return "A" if x >= 90 else "B" if x >= 80 else "C" if x >= 70 else "D" if x >= 60 else "F"
""",
            "wrong": "A",
            "boundary": 60
        },
        {
            "pattern": "csv_average",
            "category": "File/CSV-style data",
            "title": "average score from row dictionaries",
            "visible": [([{"score": 80}, {"score": 100}], 90.0), ([{"score": 70}], 70.0)],
            "hidden": [([], 0.0), ([{"score": 0}, {"score": 100}], 50.0), ([{"score": 88}, {"score": 92}], 90.0)],
            "forbidden": ["sum"],
            "rule": "no_sum_builtin",
            "correct": """
if not x:
    return 0.0
total = 0
for row in x:
    total += row["score"]
return total / len(x)
""",
            "alt": """
if len(x) == 0:
    return 0.0
total = 0
count = 0
for row in x:
    total += row["score"]
    count += 1
return total / count
""",
            "constraint": """
return 0.0 if not x else sum(row["score"] for row in x) / len(x)
""",
            "wrong": -1.0,
            "boundary": []
        },
    ]


def build_tasks():
    templates = template_library()
    titles = [
        "introductory example", "practice variant", "assessment variant"
    ]
    tasks = []
    idx = 1
    # Repeat template library three times with different titles; this produces 30 controlled tasks.
    for round_i in range(3):
        for t in templates:
            task = TaskSpec(
                task_id=f"T{idx:02d}",
                title=f"{t['title']} ({titles[round_i]})",
                category=t["category"],
                pattern=t["pattern"],
                visible=t["visible"],
                hidden=t["hidden"],
                forbidden_names=t["forbidden"],
                structural_rule=t["rule"],
                correct_body=t["correct"],
                alt_body=t["alt"],
                constraint_body=t["constraint"],
                wrong_value=t["wrong"],
                boundary_input=t["boundary"],
            )
            tasks.append(task)
            idx += 1
    return tasks


VARIANT_ORDER = [
    "correct_reference",
    "correct_alternative",
    "visible_overfit",
    "boundary_error",
    "wrong_logic",
    "constraint_violation",
    "syntax_error",
    "runtime_error",
    "incomplete",
    "nontermination",
]

PRIMARY_LABEL = {
    "correct_reference": "accepted",
    "correct_alternative": "accepted",
    "visible_overfit": "visible_overfit",
    "boundary_error": "boundary_error",
    "wrong_logic": "wrong_logic",
    "constraint_violation": "constraint_violation",
    "syntax_error": "syntax_error",
    "runtime_error": "runtime_error",
    "incomplete": "incomplete",
    "nontermination": "nontermination",
}


def code_for_variant(task, variant):
    if variant == "correct_reference":
        return make_func(task.correct_body)
    if variant == "correct_alternative":
        return make_func(task.alt_body)
    if variant == "visible_overfit":
        return make_visible_overfit_code(task)
    if variant == "boundary_error":
        # Four boundary-error submissions are intended to manifest as runtime
        # errors on hidden boundary inputs; the remaining 26 fail as ordinary
        # hidden generalization errors.
        if task.task_id in {"T01", "T02", "T03", "T04"}:
            return make_boundary_runtime_code(task)
        return make_boundary_error_code(task)
    if variant == "wrong_logic":
        return make_wrong_logic_code(task)
    if variant == "constraint_violation":
        return make_func(task.constraint_body)
    if variant == "syntax_error":
        return make_syntax_error_code(task)
    if variant == "runtime_error":
        return make_runtime_error_code(task)
    if variant == "incomplete":
        return make_incomplete_code(task)
    if variant == "nontermination":
        return make_nontermination_code(task)
    raise ValueError(variant)


def build_records(tasks):
    records = []
    for task in tasks:
        split = "holdout" if int(task.task_id[1:]) > 24 else "development"
        for variant in VARIANT_ORDER:
            sid = f"{task.task_id}_{variant}"
            records.append({
                "submission_id": sid,
                "task_id": task.task_id,
                "split": split,
                "task_title": task.title,
                "category": task.category,
                "pattern": task.pattern,
                "variant": variant,
                "primary_label": PRIMARY_LABEL[variant],
                "ground_truth_accept": variant in ("correct_reference", "correct_alternative"),
                "code": code_for_variant(task, variant),
                "visible": task.visible,
                "hidden": task.hidden,
                "forbidden_names": task.forbidden_names,
                "structural_rule": task.structural_rule,
            })
    return records


def is_nontermination_pattern(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.While):
            if isinstance(node.test, ast.Constant) and node.test.value is True:
                return True
    return False


def ast_constraint_pass(tree, forbidden_names, structural_rule):
    for node in ast.walk(tree):
        # Name calls such as sum(...), max(...), set(...), reversed(...)
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in forbidden_names:
                return False
            if isinstance(node.func, ast.Attribute) and node.func.attr in forbidden_names:
                return False
        if "Counter" in forbidden_names:
            if isinstance(node, ast.Name) and node.id == "Counter":
                return False
            if isinstance(node, ast.ImportFrom) and node.module == "collections":
                for alias in node.names:
                    if alias.name == "Counter":
                        return False
        if "IfExp" in forbidden_names and isinstance(node, ast.IfExp):
            return False
    return True


def equal_expected(a, b):
    if isinstance(b, float):
        try:
            return abs(float(a) - b) < 1e-9
        except Exception:
            return False
    return a == b


def run_solve(func, tests):
    for inp, expected in tests:
        try:
            out = func(inp)
        except Exception as e:
            return False, "runtime_error", str(e)
        if not equal_expected(out, expected):
            return False, "output_mismatch", f"expected={expected!r}; got={out!r}; input={inp!r}"
    return True, "pass", ""


def evaluate_record(record):
    code = record["code"]
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return {
            "visible_pass": False, "hidden_pass": False, "ast_pass": False,
            "observed_diagnosis": "syntax_error", "detail": str(e),
            "accepted_visible_only": False, "accepted_visible_hidden": False, "accepted_full": False
        }
    if is_nontermination_pattern(tree):
        # Internal benchmark treats deterministic while-True submissions as nontermination.
        return {
            "visible_pass": False, "hidden_pass": False, "ast_pass": False,
            "observed_diagnosis": "nontermination_pattern", "detail": "while True detected",
            "accepted_visible_only": False, "accepted_visible_hidden": False, "accepted_full": False
        }
    ast_pass = ast_constraint_pass(tree, record["forbidden_names"], record["structural_rule"])

    ns = {}
    try:
        exec(compile(tree, "<submission>", "exec"), {}, ns)
        func = ns.get("solve")
        if not callable(func):
            return {
                "visible_pass": False, "hidden_pass": False, "ast_pass": ast_pass,
                "observed_diagnosis": "incomplete_or_missing_function", "detail": "solve not callable",
                "accepted_visible_only": False, "accepted_visible_hidden": False, "accepted_full": False
            }
    except Exception as e:
        return {
            "visible_pass": False, "hidden_pass": False, "ast_pass": ast_pass,
            "observed_diagnosis": "runtime_error", "detail": str(e),
            "accepted_visible_only": False, "accepted_visible_hidden": False, "accepted_full": False
        }

    visible_pass, v_status, v_detail = run_solve(func, record["visible"])
    if not visible_pass:
        diag = "runtime_error" if v_status == "runtime_error" else "visible_output_mismatch"
        return {
            "visible_pass": False, "hidden_pass": False, "ast_pass": ast_pass,
            "observed_diagnosis": diag, "detail": v_detail,
            "accepted_visible_only": False, "accepted_visible_hidden": False, "accepted_full": False
        }
    hidden_pass, h_status, h_detail = run_solve(func, record["hidden"])
    if not hidden_pass:
        diag = "runtime_error" if h_status == "runtime_error" else "hidden_generalization_failure"
        return {
            "visible_pass": True, "hidden_pass": False, "ast_pass": ast_pass,
            "observed_diagnosis": diag, "detail": h_detail,
            "accepted_visible_only": True, "accepted_visible_hidden": False, "accepted_full": False
        }
    if not ast_pass:
        return {
            "visible_pass": True, "hidden_pass": True, "ast_pass": False,
            "observed_diagnosis": "structural_constraint_violation", "detail": record["structural_rule"],
            "accepted_visible_only": True, "accepted_visible_hidden": True, "accepted_full": False
        }
    return {
        "visible_pass": True, "hidden_pass": True, "ast_pass": True,
        "observed_diagnosis": "accepted", "detail": "",
        "accepted_visible_only": True, "accepted_visible_hidden": True, "accepted_full": True
    }


def acceptable_diagnosis(primary_label, observed):
    mapping = {
        "accepted": {"accepted"},
        "visible_overfit": {"hidden_generalization_failure", "runtime_error"},
        "boundary_error": {"hidden_generalization_failure", "runtime_error"},
        "wrong_logic": {"visible_output_mismatch", "hidden_generalization_failure"},
        "constraint_violation": {"structural_constraint_violation"},
        "syntax_error": {"syntax_error"},
        "runtime_error": {"runtime_error"},
        "incomplete": {"visible_output_mismatch", "incomplete_or_missing_function"},
        "nontermination": {"nontermination_pattern", "timeout"},
    }
    return observed in mapping.get(primary_label, set())


def metrics_for(df, accept_col):
    total = len(df)
    correct = df["ground_truth_accept"]
    accepted = df[accept_col]
    tp = ((accepted == True) & (correct == True)).sum()
    tn = ((accepted == False) & (correct == False)).sum()
    fp = ((accepted == True) & (correct == False)).sum()
    fn = ((accepted == False) & (correct == True)).sum()
    incorrect = (~correct).sum()
    correct_n = correct.sum()
    return {
        "n": total,
        "true_accept": int(tp),
        "true_reject": int(tn),
        "false_accept": int(fp),
        "false_reject": int(fn),
        "accuracy": (tp + tn) / total if total else 0,
        "false_acceptance_rate": fp / incorrect if incorrect else 0,
        "false_rejection_rate": fn / correct_n if correct_n else 0,
    }


def save_csv(path, rows, fieldnames=None):
    if not rows:
        return
    if fieldnames is None:
        fieldnames = list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def run_subprocess_timeout_demo():
    rows = []
    cases = {
        "normal": "def solve(x):\n    return x + 1\nprint(solve(1))\n",
        "runtime_error": "def solve(x):\n    return 1/0\nprint(solve(1))\n",
        "nontermination": "while True:\n    pass\n",
    }
    for name, code in cases.items():
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write(code)
            temp_path = f.name
        t0 = time.perf_counter()
        try:
            cp = subprocess.run(
                [sys.executable, temp_path],
                capture_output=True,
                text=True,
                timeout=1.0,
            )
            elapsed = time.perf_counter() - t0
            if cp.returncode == 0:
                status = "completed"
            else:
                status = "runtime_error"
            rows.append({
                "case": name,
                "timeout_seconds": 1.0,
                "status": status,
                "returncode": cp.returncode,
                "elapsed_seconds": elapsed,
                "stdout": cp.stdout.strip(),
                "stderr_head": cp.stderr.strip().splitlines()[0] if cp.stderr.strip() else ""
            })
        except subprocess.TimeoutExpired:
            elapsed = time.perf_counter() - t0
            rows.append({
                "case": name,
                "timeout_seconds": 1.0,
                "status": "timeout",
                "returncode": "",
                "elapsed_seconds": elapsed,
                "stdout": "",
                "stderr_head": "TimeoutExpired"
            })
        finally:
            try:
                os.remove(temp_path)
            except OSError:
                pass
    pd.DataFrame(rows).to_csv(RESULTS / "subprocess_timeout_demo.csv", index=False)
    return rows


def worker_eval(record):
    res = evaluate_record(record)
    return res["accepted_full"]


def parallel_throughput(records):
    # Keep this modest for Windows/Anaconda execution.
    base_records = records * ((3000 // len(records)) + 1)
    workloads = [300, 1000, 3000]
    worker_counts = [1, 2, 4]
    rows = []
    for n in workloads:
        workload = base_records[:n]
        for workers in worker_counts:
            t0 = time.perf_counter()
            if workers == 1:
                out = [worker_eval(r) for r in workload]
            else:
                with ProcessPoolExecutor(max_workers=workers) as ex:
                    out = list(ex.map(worker_eval, workload, chunksize=50))
            elapsed = time.perf_counter() - t0
            rows.append({
                "workload": n,
                "workers": workers,
                "elapsed_seconds": elapsed,
                "avg_ms_per_submission": elapsed / n * 1000,
                "accepted_count": int(sum(out)),
            })
    pd.DataFrame(rows).to_csv(RESULTS / "parallel_throughput.csv", index=False)
    return rows


def internal_scalability(records):
    base_records = records * ((5000 // len(records)) + 1)
    workloads = [100, 300, 1000, 3000, 5000]
    rows = []
    for n in workloads:
        workload = base_records[:n]
        t0 = time.perf_counter()
        acc_count = 0
        for r in workload:
            acc_count += int(evaluate_record(r)["accepted_full"])
        elapsed = time.perf_counter() - t0
        rows.append({
            "workload": n,
            "elapsed_seconds": elapsed,
            "avg_ms_per_submission": elapsed / n * 1000,
            "accepted_count": acc_count,
            "execution_mode": "single-process internal deterministic loop"
        })
    pd.DataFrame(rows).to_csv(RESULTS / "internal_scalability.csv", index=False)
    return rows



def benchmark_construction_matrix_rows():
    return [
        {"variant": "correct_reference", "intended_role": "canonical acceptable implementation", "visible_expected": "pass", "hidden_expected": "pass", "ast_expected": "pass"},
        {"variant": "correct_alternative", "intended_role": "alternative acceptable implementation", "visible_expected": "pass", "hidden_expected": "pass", "ast_expected": "pass"},
        {"variant": "visible_overfit", "intended_role": "passes only public examples", "visible_expected": "pass", "hidden_expected": "fail", "ast_expected": "pass"},
        {"variant": "boundary_error", "intended_role": "fails edge or boundary input", "visible_expected": "pass", "hidden_expected": "fail or runtime", "ast_expected": "pass"},
        {"variant": "wrong_logic", "intended_role": "incorrect transformation", "visible_expected": "fail", "hidden_expected": "not needed", "ast_expected": "pass"},
        {"variant": "constraint_violation", "intended_role": "behaviorally correct but structurally invalid", "visible_expected": "pass", "hidden_expected": "pass", "ast_expected": "fail"},
        {"variant": "syntax_error", "intended_role": "parser-level failure", "visible_expected": "fail", "hidden_expected": "not run", "ast_expected": "not run"},
        {"variant": "runtime_error", "intended_role": "execution failure", "visible_expected": "runtime error", "hidden_expected": "not run", "ast_expected": "not central"},
        {"variant": "incomplete", "intended_role": "missing or incomplete implementation", "visible_expected": "fail", "hidden_expected": "not run", "ast_expected": "usually pass"},
        {"variant": "nontermination", "intended_role": "nonterminating pattern", "visible_expected": "detected before internal execution", "hidden_expected": "not run", "ast_expected": "not central"},
    ]

def execution_mode_rows():
    return [
        {
            "mode": "internal deterministic loop",
            "implemented_in_package": "yes",
            "timeout": "no",
            "isolation": "same Python process",
            "purpose": "benchmark-level component evaluation and internal runtime scalability",
            "manuscript_interpretation": "framework-level processing efficiency, not a production sandbox result",
        },
        {
            "mode": "subprocess timeout protocol",
            "implemented_in_package": "yes, protocol demo",
            "timeout": "yes, 1 second in demo",
            "isolation": "separate Python process",
            "purpose": "demonstrate how nontermination/runtime failures can be bounded",
            "manuscript_interpretation": "deployment-oriented safety extension; not used to replace all internal benchmark measurements",
        },
        {
            "mode": "container sandbox",
            "implemented_in_package": "no",
            "timeout": "recommended",
            "isolation": "OS/container-level",
            "purpose": "future production deployment for arbitrary untrusted submissions",
            "manuscript_interpretation": "future work and practical deployment requirement",
        },
    ]

def manuscript_environment_row():
    return {
        "operating_system": "Microsoft Windows 10 Pro 10.0.19045, 64-bit",
        "machine": "ASUS System Product Name",
        "cpu": "13th Gen Intel(R) Core(TM) i7-13700KF",
        "cores_threads": "16 cores / 24 logical processors",
        "ram": "34.16 GB installed (31.81 GiB usable)",
        "python_version": "Python 3.11.5 (Anaconda, 64-bit)",
        "execution_mode": "CPU-only; single-process internal evaluation; separate subprocess timeout demo",
        "benchmark_size": "30 tasks; 300 candidate submissions",
        "holdout_split": "24 development tasks and 6 holdout tasks",
    }
