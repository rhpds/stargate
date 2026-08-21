"""Shared oc command runner — single implementation for all non-security-gated callers."""

import logging
import os
import subprocess
import time
from typing import Any, Dict, List, Tuple

logger = logging.getLogger("stargate.oc_runner")


def run_oc(args: List[str], kubeconfig: str = "", timeout: int = 30) -> str:
    cmd = ["oc"] + args
    env = {**os.environ}
    if kubeconfig:
        env["KUBECONFIG"] = kubeconfig
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
    if result.returncode != 0 and "not found" not in result.stderr.lower() and "no resources" not in result.stderr.lower():
        if "cannot" in result.stderr.lower() or "forbidden" in result.stderr.lower():
            return result.stderr.strip()
        if result.stderr.strip():
            logger.warning(f"oc {' '.join(args)}: {result.stderr.strip()}")
    return result.stdout.strip() or result.stderr.strip()


def run_oc_traced(args: List[str], kubeconfig: str = "", timeout: int = 30) -> Tuple[str, Dict[str, Any]]:
    cmd = ["oc"] + args
    cmd_str = " ".join(cmd)
    env = {**os.environ}
    if kubeconfig:
        env["KUBECONFIG"] = kubeconfig
    t0 = time.time()
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
    duration_ms = int((time.time() - t0) * 1000)

    if result.returncode != 0 and "not found" not in result.stderr.lower() and "no resources" not in result.stderr.lower():
        if "cannot" in result.stderr.lower() or "forbidden" in result.stderr.lower():
            output = result.stderr.strip()
        else:
            if result.stderr.strip():
                logger.warning(f"oc {' '.join(args)}: {result.stderr.strip()}")
            output = result.stdout.strip() or result.stderr.strip()
    else:
        output = result.stdout.strip() or result.stderr.strip()

    trace = {
        "command": cmd_str,
        "output": output[:2000],
        "exit_code": result.returncode,
        "duration_ms": duration_ms,
    }
    return output, trace


def run_oc_stdin(args: List[str], input_data: str, kubeconfig: str = "", timeout: int = 30) -> str:
    cmd = ["oc"] + args
    env = {**os.environ}
    if kubeconfig:
        env["KUBECONFIG"] = kubeconfig
    result = subprocess.run(cmd, input=input_data, capture_output=True, text=True, timeout=timeout, env=env)
    if result.returncode != 0:
        logger.warning(f"oc {' '.join(args)}: {result.stderr.strip()}")
    return result.stdout.strip() or result.stderr.strip()
