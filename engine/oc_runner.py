"""Shared oc command runner — single implementation for all non-security-gated callers."""

import logging
import os
import subprocess
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("stargate.oc_runner")


# Characters that mean something to a shell. No caller of this module runs a
# shell, but a caller that *validates* a command string and then executes it as
# argv must still refuse these: `oc get pods; curl …` is a single argv list
# whose last three words are harmless, and refusing to notice that is how a
# read-only console stops being read-only. Rejecting them also keeps a
# rejection honest — the string was never going to be what the caller meant.
SHELL_METACHARACTERS = (";", "&", "`", "$", "<", ">", "\\", "\n", "\r")

# Filters that a read-only pipeline may be piped into. Deliberately no `sed`
# and no `awk`: they are the two filters that can write a file or call
# `system()`, and `sort -o FILE` is excluded below for the same reason.
READ_ONLY_PIPE_COMMANDS = frozenset(
    {"grep", "head", "tail", "wc", "sort", "uniq", "cut", "tr", "column"}
)

# Per-command flags that turn a filter into a writer. `sort -o FILE` would let
# a path described as read-only overwrite a file — including the kubeconfig the
# same command is authenticating with.
FILTER_BLOCKED_FLAGS = {"sort": frozenset({"-o", "--output"})}


def has_shell_metacharacters(text: str) -> bool:
    """True when `text` contains anything a shell would interpret."""
    return any(character in text for character in SHELL_METACHARACTERS)


def split_pipeline(command: str) -> List[List[str]]:
    """Split `oc get pods | grep nginx` into argv stages.

    An empty stage (a leading, trailing or doubled `|`) makes the whole thing
    invalid and returns `[]`, so callers reject rather than guess.
    """
    stages: List[List[str]] = []
    for raw in command.split("|"):
        argv = raw.split()
        if not argv:
            return []
        stages.append(argv)
    return stages


def run_pipeline(
    stages: List[List[str]],
    kubeconfig: str = "",
    timeout: int = 30,
) -> Tuple[str, str, int]:
    """Run argv stages with no shell, feeding each stdout into the next stdin.

    Returns `(stdout, stderr, returncode)`: the failing stage's if one fails,
    otherwise the last stage's. `timeout` applies per stage — a five-stage
    pipeline can take five times as long as one command, and the alternative
    (one budget for the chain) kills a `grep` that is waiting for `oc logs`
    rather than the `oc logs` itself.

    A pipe used to mean `subprocess.run(cmd, shell=True)`. That made every
    allowlist check advisory: the shell re-parsed the same string, so a `;` or
    `$(…)` that survived validation became a second command.
    """
    env = {**os.environ}
    if kubeconfig:
        env["KUBECONFIG"] = kubeconfig

    data: Optional[str] = None
    stderr = ""
    for argv in stages:
        result = subprocess.run(
            argv,
            input=data,
            stdin=None if data is not None else subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        if result.returncode != 0:
            return result.stdout, result.stderr, result.returncode
        data = result.stdout
        stderr = result.stderr
    return data or "", stderr, 0



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
