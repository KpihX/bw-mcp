#!/usr/bin/env python3
import statistics
import subprocess
import time

from rich.console import Console
from rich.table import Table


console = Console()


def measure(cmd: str, iterations: int = 3) -> tuple[float, float]:
    times = []
    for _ in range(iterations):
        start = time.perf_counter()
        subprocess.run(cmd, shell=True, capture_output=True, check=False)
        end = time.perf_counter()
        times.append(end - start)
    return statistics.mean(times), statistics.stdev(times) if len(times) > 1 else 0.0


def main() -> None:
    console.print("[bold cyan]BW-Proxy Performance Audit[/bold cyan]\n")

    console.print("Measuring pure host overhead (--help)...")
    help_avg, help_std = measure("bw-proxy --help")

    console.print("Measuring low-cost admin status...")
    status_avg, status_std = measure("bw-proxy admin status")

    console.print("Measuring explicit logged-out fast-path (do sync)...")
    sync_avg, sync_std = measure("bw-proxy do sync")

    console.print("Measuring local Python overhead (native reference)...")
    local_avg, local_std = measure("python3 -m bw_proxy.main --help")

    table = Table(title="Performance Benchmarks")
    table.add_column("Command Type", style="cyan")
    table.add_column("Avg Latency (s)", justify="right")
    table.add_column("Jitter (±s)", justify="right")
    table.add_column("Notes", style="dim")

    table.add_row("Agnostic Shim (Docker)", f"{help_avg:.3f}", f"{help_std:.3f}", "Host shim -> Docker exec overhead")
    table.add_row("Admin Status (Docker)", f"{status_avg:.3f}", f"{status_std:.3f}", "Full Docker lifecycle + status probe")
    table.add_row("Do Sync Fast-Fail", f"{sync_avg:.3f}", f"{sync_std:.3f}", "Expected fast failure when unauthenticated")
    table.add_row("Native Python (Ref)", f"{local_avg:.3f}", f"{local_std:.3f}", "Base Python interpreter cost")

    console.print(table)

    docker_overhead = status_avg - local_avg
    console.print(
        f"\n[bold yellow]Analysis:[/bold yellow] Docker overhead is approximately "
        f"[bold]{docker_overhead:.3f}s[/bold] per invocation."
    )
    console.print(
        "Interactive scenarios such as `admin unlock` and lease-backed repeated `do` commands "
        "should be measured separately in a live authenticated shell because they require human approval."
    )


if __name__ == "__main__":
    main()
