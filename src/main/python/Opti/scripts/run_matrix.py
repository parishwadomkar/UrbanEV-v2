from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from input_scenarios import VIPV_SCENARIOS


def main():
    p = argparse.ArgumentParser(description="Run ten annual four-season demand cases sequentially.")
    p.add_argument("--method", choices=["monolithic", "lbbd", "benders"], default="lbbd")
    p.add_argument("--dataset", choices=["small", "full"], default="full")
    p.add_argument("--scenario", choices=["no_redirection", "with_redirection"], default="no_redirection")
    p.add_argument("--vipv-scenarios", nargs="+", choices=VIPV_SCENARIOS, default=list(VIPV_SCENARIOS))
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("solver_args", nargs=argparse.REMAINDER)
    args = p.parse_args()
    entry = {"monolithic": "src/run_optimization.py", "lbbd": "src_lbbd/run_lbbd.py", "benders": "src_benders/run_benders.py"}[args.method]
    extra = args.solver_args[1:] if args.solver_args[:1] == ["--"] else args.solver_args
    reserved = {"--dataset", "--small", "--full", "--vipv-scenario", "--scenario", "--run-name", "--resume-certified-run", "--bootstrap-checkpoint"}
    reserved.update("--" + scenario for scenario in VIPV_SCENARIOS)
    if any(value.split("=", 1)[0] in reserved for value in extra):
        p.error("Dataset, treatment, scenario, run names and restart inputs must not be overridden in matrix solver arguments.")
    for scenario in args.vipv_scenarios:
        command = [sys.executable, str(ROOT / entry), "--dataset", args.dataset, "--vipv-scenario", scenario, "--scenario", args.scenario, *extra]
        print(subprocess.list2cmdline(command) if sys.platform == "win32" else shlex.join(command), flush=True)
        if not args.dry_run:
            subprocess.run(command, cwd=ROOT, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
