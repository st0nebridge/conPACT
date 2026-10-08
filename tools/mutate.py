"""
Minimal AST mutation tester (no install needed). This is the tool behind every
mutation score quoted in README.md, kept here so they can be reproduced.

Operators (one mutant per site):
  cmp   comparison swap      == <-> !=, < <-> >=, > <-> <=, in <-> not in, is <-> is not
  bool  boolean op swap      and <-> or
  not   negation removal     not x -> x
  const constant change      True <-> False, int n -> n+1, str s -> "XX"+s+"XX"
  binop arithmetic swap      + <-> -, * <-> /, // <-> *
  ret   return value drop    return x -> return
  del   statement deletion   call-expression statements and raise -> pass
Skipped: docstrings, string parts of f-strings, __version__, and string values of
"description"/"title" keys in dict literals (model/human-facing prose, no behaviour),
and type annotations (never evaluated under `from __future__ import annotations`).

Test selection: one coverage run with per-test contexts maps every source line to
the tests that execute it; each mutant runs only the tests covering its line
(pytest -x). A line executed only at import time (module constants) runs the
whole suite. A mutant on a line never executed is "uncovered" (survives).
Coverage chooses which tests a mutant meets first; it never decides a survivor.
A mutant its covering tests let through is run again against the tests written
for its module - its own test file, whole, and every tests/regression/ file that
imports the module or names it in a string - before it is recorded as survived
(its row then carries "recheck": that run's own verdict). The map is wrong in
exactly that place: a module is imported once per process, so a line that runs
at import is credited to collection or to a test that ran the module again
(runpy), not to the tests that use it - `WIDTH = 460 -> 461` met one runpy test
and "survived" although the module's own tests assert the value - and a test
that reads the module's source executes none of it.
Mutant runs disable pytest plugin autoload (startup cost; the suite needs none).
A line only a subprocess executes is "uncovered" (coverage of subprocesses is
not collected), so the score is a slight under-estimate; a subprocess test can
still kill a mutant on a line something else covers, through the recheck. Also
do not edit tools/mutate.py while it runs: each worker imports it afresh.

Results are appended to <out>.jsonl as they finish; a rerun resumes.
Usage: python tools/mutate.py <project_root> <out_prefix> [workers] [module_glob]
  <project_root> is the repo root (the folder holding src/ and tests/), not src/.
  <module_glob> is one or more fnmatch patterns separated by COMMAS - there is no
  brace expansion: 'idle_watch*,toast_*' works, '{idle_watch,toast}*' matches nothing.
  Run it from a scratch directory: it writes <out_prefix>.jsonl / .json and copies
  the repo into <out_prefix>-work/w<N> once per worker.
  Do not edit anything under src/ while it runs - it scans the working tree for
  mutation sites but runs them against the copies, so an edit between the two
  desynchronises them (the run then dies with an AttributeError on a mismatched node).
  Keep the machine otherwise idle: a mutant whose tests exceed the 120-second limit
  is re-run against its own module's tests (limit 300s) and only recorded as
  "timeout" if that does not settle it either. A timeout is NOT counted as detected
  and is listed with the survivors, because it is a measurement that did not finish,
  not a test that failed. Such a mutant is killed with its whole process tree, so a
  test's own child process cannot outlive the run.
"""
import ast
import concurrent.futures as cf
import fnmatch
import json
import multiprocessing
import os
import pathlib
import shutil
import subprocess
import sys
import time

CMP_SWAP = {ast.Eq: ast.NotEq, ast.NotEq: ast.Eq, ast.Lt: ast.GtE, ast.GtE: ast.Lt,
            ast.Gt: ast.LtE, ast.LtE: ast.Gt, ast.In: ast.NotIn, ast.NotIn: ast.In,
            ast.Is: ast.IsNot, ast.IsNot: ast.Is}
BIN_SWAP = {ast.Add: ast.Sub, ast.Sub: ast.Add, ast.Mult: ast.Div, ast.Div: ast.Mult,
            ast.FloorDiv: ast.Mult}


def _skip_ids(tree):
    skip = set()
    for node in ast.walk(tree):
        annotations = []
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.returns is not None:
            annotations.append(node.returns)
        if isinstance(node, ast.arg) and node.annotation is not None:
            annotations.append(node.annotation)
        if isinstance(node, ast.AnnAssign):
            annotations.append(node.annotation)
        for annotation in annotations:
            for sub in ast.walk(annotation):
                skip.add(id(sub))
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                skip.add(id(body[0].value))
        if isinstance(node, ast.JoinedStr):
            for v in node.values:
                skip.add(id(v))
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__version__" for t in node.targets):
            skip.add(id(node.value))
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and k.value in ("description", "title"):
                    for sub in ast.walk(v):
                        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                            skip.add(id(sub))
    return skip


def _parents(tree):
    parents = {}
    for node in ast.walk(tree):
        for field, value in ast.iter_fields(node):
            if isinstance(value, list):
                for i, child in enumerate(value):
                    if isinstance(child, ast.AST):
                        parents[id(child)] = (node, field, i)
            elif isinstance(value, ast.AST):
                parents[id(value)] = (node, field, None)
    return parents


def _statement_lines(tree):
    """id(node) -> first line of the innermost statement containing it."""
    lines = {}

    def visit(node, stmt_line):
        if isinstance(node, ast.stmt):
            stmt_line = node.lineno
        lines[id(node)] = stmt_line
        for child in ast.iter_child_nodes(node):
            visit(child, stmt_line)

    visit(tree, 0)
    return lines


def sites(tree):
    """Yield (walk_index, op, sub, line, description) for every mutation site.
    `line` is "<node line>/<statement line>" so coverage can fall back to the
    statement's first line for constants inside multi-line literals."""
    skip = _skip_ids(tree)
    stmt_lines = _statement_lines(tree)
    for idx, node in enumerate(ast.walk(tree)):
        line = f"{getattr(node, 'lineno', 0)}/{stmt_lines.get(id(node), 0)}"
        if isinstance(node, ast.Compare):
            for k, op in enumerate(node.ops):
                if type(op) in CMP_SWAP:
                    yield idx, "cmp", k, line, f"{type(op).__name__}->{CMP_SWAP[type(op)].__name__}"
        elif isinstance(node, ast.BoolOp):
            yield idx, "bool", None, line, f"{type(node.op).__name__} swap"
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            yield idx, "not", None, line, "drop not"
        elif isinstance(node, ast.Constant) and id(node) not in skip:
            v = node.value
            if isinstance(v, bool):
                yield idx, "const", None, line, f"{v}->{not v}"
            elif isinstance(v, int):
                yield idx, "const", None, line, f"{v}->{v + 1}"
            elif isinstance(v, str):
                yield idx, "const", None, line, f"str {v[:40]!r}"
        elif isinstance(node, ast.BinOp) and type(node.op) in BIN_SWAP:
            yield idx, "binop", None, line, f"{type(node.op).__name__}->{BIN_SWAP[type(node.op)].__name__}"
        elif isinstance(node, ast.Return) and node.value is not None and not (
                isinstance(node.value, ast.Constant) and node.value.value is None):
            yield idx, "ret", None, line, "return value dropped"
        elif isinstance(node, ast.Raise) or (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)):
            yield idx, "del", None, line, f"delete {type(node).__name__}"


def apply(source, walk_index, op, sub):
    tree = ast.parse(source)
    parents = _parents(tree)
    node = list(ast.walk(tree))[walk_index]
    expected = {"cmp": ast.Compare, "bool": ast.BoolOp, "binop": ast.BinOp, "const": ast.Constant,
                "ret": ast.Return, "not": ast.UnaryOp}.get(op)
    if expected is not None and not isinstance(node, expected):
        raise RuntimeError(f"site {walk_index} is {type(node).__name__}, not {expected.__name__}: "
                           "the source changed after the scan - start the run again")
    if op == "cmp":
        node.ops[sub] = CMP_SWAP[type(node.ops[sub])]()
    elif op == "bool":
        node.op = ast.Or() if isinstance(node.op, ast.And) else ast.And()
    elif op == "binop":
        node.op = BIN_SWAP[type(node.op)]()
    elif op == "const":
        v = node.value
        node.value = (not v) if isinstance(v, bool) else (v + 1 if isinstance(v, int) else "XX" + v + "XX")
    elif op == "ret":
        node.value = None
    elif op in ("not", "del"):
        parent, field, i = parents[id(node)]
        new = node.operand if op == "not" else ast.Pass()
        if i is None:
            setattr(parent, field, new)
        else:
            getattr(parent, field)[i] = new
    ast.fix_missing_locations(tree)
    return ast.unparse(tree)


def line_to_tests(workdir):
    """Run the suite once with per-test coverage contexts; map (relpath, line) -> test ids."""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    env["COVERAGE_FILE"] = str(pathlib.Path(workdir).resolve() / ".coverage")
    done = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--cov=src/conpact",
                           "--cov-context=test", "--cov-report=", "tests"], cwd=workdir, env=env,
                          capture_output=True, text=True)
    if done.returncode != 0:
        # Every verdict assumes the unmutated suite passes, so stop - and say which
        # test did not, which a bare CalledProcessError threw away.
        out = done.stdout.splitlines()
        raise SystemExit("the unmutated suite failed under coverage; no mutant can be measured:\n"
                         + "\n".join([line for line in out if line.startswith(("FAILED", "ERROR"))] or out[-20:]))
    import coverage
    data = coverage.CoverageData(basename=str(pathlib.Path(workdir) / ".coverage"))
    data.read()
    mapping = {}
    for filename in data.measured_files():
        rel = pathlib.Path(filename).resolve().relative_to(pathlib.Path(workdir).resolve()).as_posix()
        for line, contexts in data.contexts_by_lineno(filename).items():
            tests = sorted({c.split("|")[0] for c in contexts if c})
            # Executed only at import (empty context): any test may depend on it.
            mapping[f"{rel}:{line}"] = tests or ["tests"]
    return mapping


_WORKDIR = None


def _init(queue):
    global _WORKDIR
    _WORKDIR = queue.get()


def _kill_tree(proc):
    """Kill the timed-out test process *and anything it started*. A test that spawns
    a real child (tests/test_detach.py does) can leave one behind when its parent is
    killed mid-spawn; such a child outlives the run and would otherwise be a stray."""
    if os.name == "nt":
        try:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], timeout=60,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired):
            proc.kill()   # no taskkill: the child still goes, its children are on their own
    else:
        proc.kill()
    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        pass


def _pytest(tests, env, limit=120):
    """Run one mutant's tests; "survived" if they all pass. Output goes to the void:
    with no pipes to drain there is nothing a leaked grandchild can hold open, which
    is what once wedged a worker for good at the 120-second kill."""
    proc = subprocess.Popen([sys.executable, "-m", "pytest", "-x", "-q", "-p", "no:cacheprovider", *tests],
                            cwd=_WORKDIR, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        return "survived" if proc.wait(timeout=limit) == 0 else "killed"
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        return "timeout"


def score(counts):
    """The share of mutants the tests actually failed on. Only "killed" counts: a
    "timeout" is a measurement that did not finish, an "uncovered" mutant is one no
    test ran at all, and neither is evidence that a change would be noticed."""
    total = sum(v for k, v in counts.items() if k != "score")
    return round(100 * counts["killed"] / total, 1) if total else None


def _own_tests(rel, tests):
    """Out of every test that covers the mutated line, the mutated module's own test
    file. A module-level constant is covered by the whole suite, which is what pushes
    those mutants past the limit in the first place.

    A line executed only at import has no per-test context at all, so line_to_tests
    maps it to the whole directory (["tests"]) - and that names no test file, which
    used to leave this returning nothing and the retry never running. That is the
    very case the retry exists for: measured, 92 of 93 timeouts in one run stopped
    dead at the first limit. The module's own test file is on disk whether or not a
    coverage context named it, so ask for it by name."""
    own_file = f"test_{pathlib.Path(rel).stem}.py"
    found = [t for t in tests if pathlib.Path(t.split("::")[0]).name == own_file]
    if found:
        return found
    own_path = f"tests/{own_file}"
    root = pathlib.Path(_WORKDIR) if _WORKDIR else None
    return [own_path] if root is not None and (root / own_path).exists() else []


def _names_module(path, rel):
    """Does this test file import the module at `rel`, or name it in a string - the
    dotted name (runpy), the bare name (a list of modules whose source a test
    reads) or its file? Read from the syntax tree, and a string must be the name,
    not contain it, so prose that mentions the module does not count and neither
    does a module whose name merely starts the same way."""
    dotted = ".".join(pathlib.PurePosixPath(rel).with_suffix("").parts[1:])   # past src/
    package, _, stem = dotted.rpartition(".")
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(a.name == dotted or a.name.startswith(dotted + ".") for a in node.names):
                return True
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            if node.module == dotted or node.module.startswith(dotted + "."):
                return True
            if node.module == package and any(a.name == stem for a in node.names):
                return True
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            text = node.value.replace("\\", "/")
            if text in (dotted, stem, f"{stem}.py") or text.endswith(f"/{stem}.py"):
                return True
    return False


def _module_tests(rel):
    """The tests written for the module at `rel`: its own test file, whole, then
    every regression test that imports it or names it. These are what a
    survivor is asked of before it is recorded; see the docstring above."""
    if not _WORKDIR:
        return []
    root = pathlib.Path(_WORKDIR)
    own = f"tests/test_{pathlib.PurePosixPath(rel).stem}.py"
    found = [own] if (root / own).exists() else []
    for path in sorted((root / "tests" / "regression").glob("test_*.py")):
        if _names_module(path, rel):
            found.append(path.relative_to(root).as_posix())
    return found


def _run(job):
    key, rel, walk_index, op, sub, line, desc, tests = job
    base = {"key": key, "module": rel, "line": line, "op": op, "desc": desc}
    if not tests:
        return dict(base, outcome="uncovered", secs=0)
    target = pathlib.Path(_WORKDIR) / rel
    original = target.read_text(encoding="utf-8")
    try:
        target.write_text(apply(original, walk_index, op, sub), encoding="utf-8")
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
        start = time.time()
        outcome, ran, recheck = _pytest(tests, env), tests, None
        if outcome == "timeout":
            # A timeout is not evidence of detection: it says the run hit the limit,
            # and a mutant whose tests are the whole suite hits it whether or not
            # anything would have failed. Ask its own module's tests, which are few
            # enough to finish. Measured: 8 of 39 such mutants were really survivors.
            own = _own_tests(rel, tests)
            if own:
                outcome, ran = _pytest(own, env, limit=300), own
        if outcome == "survived" and "tests" not in ran:
            # Coverage picked the tests; it does not get to say none would fail.
            # Measured: 10 of settings_window's 20 survivors were import-time lines
            # the map gave to one runpy test, and an 11th fell to a test that reads
            # the source. A recheck that times out is still not a kill.
            more = [t for t in _module_tests(rel) if t not in ran]
            if more:
                recheck = _pytest(more, env, limit=300)
                if recheck == "killed":
                    outcome = "killed"
        result = dict(base, outcome=outcome, secs=round(time.time() - start, 1))
        return result if recheck is None else dict(result, recheck=recheck)
    finally:
        target.write_text(original, encoding="utf-8")


def main():
    root = pathlib.Path(sys.argv[1]).resolve()
    prefix = pathlib.Path(sys.argv[2])
    workers = int(sys.argv[3]) if len(sys.argv) > 3 else (os.cpu_count() or 4)
    module_glob = sys.argv[4] if len(sys.argv) > 4 else "*"
    results_path = prefix.with_suffix(".jsonl")
    done = {}
    if results_path.exists():
        for raw in results_path.read_text(encoding="utf-8").splitlines():
            r = json.loads(raw)
            done[r["key"]] = r

    base = prefix.parent / f"{prefix.name}-work"
    shutil.rmtree(base, ignore_errors=True)
    ignore = shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", ".coverage")
    dirs = []
    for i in range(workers):
        d = base / f"w{i}"
        shutil.copytree(root, d, ignore=ignore)
        dirs.append(str(d))
    print("mapping lines to tests ...", flush=True)
    mapping = line_to_tests(dirs[0])

    jobs = []
    for path in sorted((root / "src").rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        if not any(fnmatch.fnmatch(path.name, g) for g in module_glob.split(",")):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for walk_index, op, sub, line, desc in sites(tree):
            key = f"{rel}#{walk_index}:{op}:{sub}"
            if key not in done:
                own, stmt = line.split("/")
                tests = mapping.get(f"{rel}:{own}") or mapping.get(f"{rel}:{stmt}", [])
                jobs.append((key, rel, walk_index, op, sub, int(own), desc, tests))
    print(f"{len(jobs)} mutants to run ({len(done)} already done), {workers} workers", flush=True)

    manager = multiprocessing.Manager()
    queue = manager.Queue()
    for d in dirs:
        queue.put(d)
    with cf.ProcessPoolExecutor(max_workers=workers, initializer=_init, initargs=(queue,)) as pool, \
            results_path.open("a", encoding="utf-8") as sink:
        for n, result in enumerate(pool.map(_run, jobs), 1):
            sink.write(json.dumps(result) + "\n")
            sink.flush()
            done[result["key"]] = result
            if n % 50 == 0:
                print(f"  {n}/{len(jobs)}", flush=True)

    summary = {}
    for r in done.values():
        s = summary.setdefault(r["module"], {"killed": 0, "survived": 0, "uncovered": 0, "timeout": 0})
        s[r["outcome"]] += 1
    for s in summary.values():
        s["score"] = score(s)
    total = len(done)
    killed = sum(s["killed"] for s in summary.values())
    report = {"total": total, "killed": killed, "score": round(100 * killed / total, 1) if total else None,
              "modules": summary,
              "survivors": sorted([r for r in done.values()
                                   if r["outcome"] in ("survived", "uncovered", "timeout")],
                                  key=lambda r: (r["module"], r["line"]))}
    prefix.with_suffix(".json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    shutil.rmtree(base, ignore_errors=True)
    print(json.dumps({k: v for k, v in report.items() if k != "survivors"}, indent=2))
    print(f"survivors: {len(report['survivors'])}")


if __name__ == "__main__":
    main()
