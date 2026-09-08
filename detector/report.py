"""Assembles run results into JSON, Markdown, and console (rich) reports.

JSON is the machine-readable full record (including every raw probe response),
Markdown is the human-readable summary, and the rich console output gives a
live verdict summary at the end of a run.
"""
import json
from datetime import datetime, timezone
from rich.console import Console

from detector import paths
from rich.panel import Panel
from rich.table import Table

REPORTS_DIR = paths.reports_dir()

STATUS_STYLES = {
    "substantive": "green",
    "deflected": "yellow",
    "empty": "red",
}


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")


def build_report(url: str, claimed_key, calibration: dict,
                 responses: dict, analysis: dict) -> dict:
    """Assemble the full report dict for a run."""
    return {
        "schema": "ai-fingerprint-report/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "target_url": url,
        "claimed_model": analysis.get("claimed"),
        "calibration_used": {
            "input_selector": calibration.get("input_selector"),
            "send_selector": calibration.get("send_selector"),
            "use_enter": calibration.get("use_enter"),
            "response_selector": calibration.get("response_selector"),
        },
        "verdict": analysis["verdict"],
        "scores": analysis["scores"],
        "censorship": analysis["censorship"],
        "self_id": analysis["self_id"],
        "reasoning_leak": analysis["reasoning_leak"],
        "network": analysis["network"],
        "responses": responses,
    }


def save_json(report: dict, url: str) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = _timestamp()
    path = REPORTS_DIR / f"report_{stamp}.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def render_markdown(report: dict) -> str:
    """Render the report dict as a human-readable Markdown document."""
    v = report["verdict"]
    c = report["censorship"]
    claimed = report.get("claimed_model")
    lines = []
    push = lines.append

    push("# AI Fingerprint Report")
    push("")
    push(f"- **Target:** {report['target_url']}")
    push(f"- **Generated (UTC):** {report['generated_at']}")
    if claimed:
        claimed_note = claimed["display_name"]
        if claimed["matches_verdict"]:
            claimed_note += " — verdict agrees"
        elif claimed["same_family"]:
            claimed_note += " — verdict is a DIFFERENT model in the same family"
        else:
            claimed_note += " — **verdict disagrees**"
        push(f"- **Site claims:** {claimed_note}")
    push("")
    push("## Verdict")
    push("")
    push(f"**{v['display_name']}** "
         f"(confidence: **{v['confidence']}**, score: {v['score']}, "
         f"signals: {', '.join(v['supporting_signals']) or 'none'})")
    push("")
    push("## Signal scores")
    push("")
    push("| Model | Score |")
    push("|---|---|")
    for key, score in report["scores"].items():
        if score > 0:
            push(f"| {key} | {score} |")
    push("")
    push(f"## Censorship pairs ({c['hits']}/{c['total']} hits)")
    push("")
    push("A *hit* means the sensitive question was deflected/refused while the")
    push("structurally equivalent control question was answered substantively.")
    push("")
    push("| Pair | Sensitive | Control | Hit |")
    push("|---|---|---|---|")
    for p in c["pairs"]:
        push(f"| {p['label']} | {p['sensitive_status']} | {p['control_status']} "
             f"| {'yes' if p['hit'] else ''} |")
    push("")

    leak = report["reasoning_leak"]
    push("## Reasoning-tag leak")
    push("")
    if leak["found"]:
        push(f"Found `<think>` output on probe `{leak['probe']}`:")
        push("")
        push("> " + leak["snippet"][:200].replace("\n", " "))
    else:
        push("No raw reasoning tags observed.")
    push("")

    sid = report["self_id"]
    push("## Self-identification matches")
    push("")
    if sid["matches"]:
        for key, evidence in sid["matches"].items():
            push(f"- **{key}**")
            for e in evidence:
                push(f"  - {e}")
    else:
        push("No provider/model names surfaced in self-ID replies.")
    push("")

    net = report["network"]
    push("## Network evidence")
    push("")
    if net:
        push("| Model | Provider requests | Distinctive headers |")
        push("|---|---|---|")
        for key, ev in net.items():
            headers = ", ".join(ev["headers"].keys()) or "-"
            push(f"| {key} | {ev['requests']} | {headers} |")
    else:
        push("No known provider domains or headers observed in page traffic.")
    push("")

    push("## Raw probe responses")
    push("")
    for label, text in report["responses"].items():
        push(f"### {label}")
        push("")
        text = (text or "").strip()
        if text:
            push("```")
            push(text[:2000] + ("\n... (truncated)" if len(text) > 2000 else ""))
            push("```")
        else:
            push("*(no response captured)*")
        push("")
    return "\n".join(lines)


def save_markdown(report: dict, url: str) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = _timestamp()
    path = REPORTS_DIR / f"report_{stamp}.md"
    path.write_text(render_markdown(report), encoding="utf-8")
    return path


def print_console_report(report: dict):
    """Print a colorized verdict summary to the terminal (rich)."""
    console = Console()
    v = report["verdict"]
    claimed = report.get("claimed_model")

    style = {"high": "bold green", "medium": "bold yellow",
             "low": "bold red", "none": "bold red"}.get(v["confidence"], "white")
    body = (
        f"[bold]{v['display_name']}[/bold]\n"
        f"confidence: [{style}]{v['confidence']}[/{style}]   "
        f"score: {v['score']}   signals: {', '.join(v['supporting_signals']) or 'none'}"
    )
    if claimed:
        if claimed["matches_verdict"]:
            body += "\n[green]Site's claimed model MATCHES the verdict.[/green]"
        elif claimed["same_family"]:
            body += ("\n[yellow]Site's claimed model is in the same family but the "
                     "exact model differs.[/yellow]")
        else:
            body += "\n[red]Site's claimed model DISAGREES with the verdict.[/red]"
    console.print(Panel(body, title="Verdict", expand=False))

    c = report["censorship"]
    table = Table(title=f"Censorship pairs — {c['hits']}/{c['total']} hits")
    table.add_column("Pair")
    table.add_column("Sensitive")
    table.add_column("Control")
    table.add_column("Hit")
    for p in c["pairs"]:
        s_style = STATUS_STYLES.get(p["sensitive_status"], "white")
        c_style = STATUS_STYLES.get(p["control_status"], "white")
        table.add_row(
            p["label"],
            f"[{s_style}]{p['sensitive_status']}[/{s_style}]",
            f"[{c_style}]{p['control_status']}[/{c_style}]",
            "yes" if p["hit"] else "",
        )
    console.print(table)

    leak = report["reasoning_leak"]
    if leak["found"]:
        console.print(f"[bold yellow]Reasoning-tag leak[/bold yellow] on "
                      f"[bold]{leak['probe']}[/bold]: {leak['snippet'][:150]}")

    sid = report["self_id"]
    if sid["matches"]:
        console.print("[bold]Self-ID matches:[/bold]")
        for key, evidence in sid["matches"].items():
            console.print(f"  [bold cyan]{key}[/bold cyan]")
            for e in evidence:
                console.print(f"    - {e}")

    net = report["network"]
    if net:
        console.print("[bold]Network evidence:[/bold]")
        for key, ev in net.items():
            headers = ", ".join(ev["headers"].keys()) or "-"
            console.print(f"  [bold cyan]{key}[/bold cyan]: "
                          f"{ev['requests']} request(s), headers: {headers}")
    else:
        console.print("[dim]No known provider domains/headers seen in page traffic.[/dim]")
