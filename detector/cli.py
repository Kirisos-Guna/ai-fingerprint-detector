"""Command-line interface for the AI fingerprint detector."""
import argparse
import sys

from rich.console import Console

from detector.analyzer import analyze
from detector.browser_session import domain_for, launch_session
from detector.calibration import calibrate
from detector.fingerprint_db import load_db, resolve_claim
from detector.network_capture import NetworkCapture
from detector.probes import all_probes
from detector.report import (build_report, print_console_report, save_json,
                             save_markdown)
from detector.runner import run_probes


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="detector",
        description=("Fingerprint the real AI model behind any chat website: "
                     "calibrate its UI, run a probe battery, capture network "
                     "evidence, and produce a verdict report."),
    )
    p.add_argument("url", help="chat site URL, e.g. https://example-chat.com")
    p.add_argument("--claims", default=None,
                   help=("what the site claims to be, e.g. 'gpt-4', 'claude', "
                         "'deepseek'. Enables claim-vs-verdict comparison."))
    p.add_argument("--calibrate", action="store_true",
                   help="force re-calibration even if this domain was calibrated before")
    p.add_argument("--headless", action="store_true",
                   help="run Chromium headless (calibration needs a visible window)")
    p.add_argument("--report-dir", default=None,
                   help="override the default reports/ output directory")
    p.add_argument("--no-network-capture", action="store_true",
                   help="skip passive network fingerprinting")
    p.add_argument("--version", action="version", version="detector 1.0")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    console = Console()

    db = load_db()
    claimed_key = resolve_claim(args.claims, db)
    if args.claims and not claimed_key:
        console.print(f"[yellow]Warning:[/yellow] could not resolve claims string "
                      f"'{args.claims}' to a known model; ignoring it.")

    # -- report dir override ------------------------------------------------
    if args.report_dir:
        from pathlib import Path as _Path
        import detector.report as report_mod
        report_mod.REPORTS_DIR = _Path(args.report_dir)

    # -- browser session ----------------------------------------------------
    console.print(f"[bold]Launching browser session for {args.url} ...[/bold]")
    pw, context, page = launch_session(args.url, headless=args.headless)
    domain = domain_for(args.url)

    capture = None  # bind before try so finally can't raise UnboundLocalError
    try:
        # -- calibration ----------------------------------------------------
        calibration = calibrate(page, domain, force=args.calibrate)

        # -- probe run ------------------------------------------------------
        probes = all_probes()
        console.print(f"\n[bold]Running {len(probes)} probes "
                      f"(censorship pairs, self-ID, formatting)...[/bold]\n")

        if not args.no_network_capture:
            capture = NetworkCapture(db)
            capture.attach(page)

        def on_progress(done, total, label):
            console.print(f"  [cyan][{done}/{total}][/cyan] {label}")

        results = run_probes(page, calibration, probes, on_progress=on_progress)

        network_summary = capture.summary() if capture else {}
        analysis = analyze(results, network_summary, db, claimed_key=claimed_key)

        report = build_report(args.url, claimed_key, calibration, results, analysis)
        json_path = save_json(report, args.url)
        md_path = save_markdown(report, args.url)

        console.print()
        print_console_report(report)
        console.print()
        console.print(f"[green]Reports written:[/green]\n"
                      f"  JSON: {json_path}\n  Markdown: {md_path}")
        return 0
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user.[/yellow]")
        return 130
    finally:
        if capture:
            capture.detach(page)
        try:
            context.close()
        except Exception:
            pass
        try:
            pw.stop()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
