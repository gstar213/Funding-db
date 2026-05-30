"""
main.py — Funding Intelligence Database CLI

Commands:
  python main.py init       - Create funding.db
  python main.py collect    - Run one collection cycle
  python main.py run        - Run forever (every 6 hours)
  python main.py status     - Show DB stats
  python main.py serve      - Launch Datasette browser UI
  python main.py export     - Export to JSON/CSV
"""
import sys
import io
# Force UTF-8 output on Windows so Rich can print Unicode symbols
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import logging
import sqlite3
from pathlib import Path
from datetime import datetime

import click
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table
from rich import box
from rich.panel import Panel

load_dotenv()
ROOT = Path(__file__).parent
DB_PATH = ROOT / "funding.db"

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(ROOT / "funding.log"),
        logging.StreamHandler(sys.stdout),
    ]
)

console = Console()


# ── CLI ───────────────────────────────────────────────────────────────────────

@click.group()
def cli():
    """💰 Funding Intelligence Database — track every startup funding round globally."""
    pass


@cli.command()
def init():
    """Create the database schema."""
    from schema import init_db
    init_db()
    console.print("[bold green]✓ Database ready[/bold green] at funding.db")
    console.print("[dim]Next: python main.py collect[/dim]")


@cli.command()
def collect():
    """Run one full collection cycle across all sources."""
    if not DB_PATH.exists():
        console.print("[red]Database not found. Run: python main.py init[/red]")
        sys.exit(1)

    console.print(Panel.fit(
        "[bold cyan]🔍 Starting collection cycle[/bold cyan]\n"
        f"[dim]{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}[/dim]",
        border_style="cyan"
    ))

    from collector import run_collection
    result = run_collection(verbose=True)

    console.print(f"\n[bold green]✓ Done![/bold green]  "
                  f"Found [bold]{result['total_found']}[/bold] funding articles · "
                  f"[bold]{result['total_new']}[/bold] new rounds saved")
    console.print("[dim]Next: python main.py serve[/dim]")


@cli.command()
@click.option("--interval", default=360, help="Interval in minutes between runs (default: 360 = 6 hours)")
def run(interval: int):
    """Run collection on a schedule (forever). Ctrl+C to stop."""
    import time
    console.print(Panel.fit(
        f"[bold cyan]🔄 Scheduler started[/bold cyan]\n"
        f"[dim]Running every {interval} minutes. Press Ctrl+C to stop.[/dim]",
        border_style="cyan"
    ))

    from collector import run_collection

    run_num = 0
    while True:
        run_num += 1
        console.print(f"\n[bold]Run #{run_num}[/bold] — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        try:
            result = run_collection(verbose=True)
            console.print(f"[green]✓[/green] {result['total_new']} new rounds saved")
        except Exception as e:
            console.print(f"[red]✗ Error:[/red] {e}")

        next_run = datetime.now().strftime("%H:%M")
        console.print(f"[dim]Sleeping {interval} min. Next run at ~{next_run}[/dim]")
        time.sleep(interval * 60)


@cli.command()
def status():
    """Show database statistics."""
    if not DB_PATH.exists():
        console.print("[red]Database not found.[/red]")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # Summary stats
    total = conn.execute("SELECT COUNT(*) FROM funding_rounds").fetchone()[0]
    with_amount = conn.execute("SELECT COUNT(*) FROM funding_rounds WHERE amount_usd IS NOT NULL").fetchone()[0]
    today = conn.execute(
        "SELECT COUNT(*) FROM funding_rounds WHERE announced_date = date('now')"
    ).fetchone()[0]
    this_week = conn.execute(
        "SELECT COUNT(*) FROM funding_rounds WHERE announced_date >= date('now', '-7 days')"
    ).fetchone()[0]

    console.print(Panel.fit(
        f"[bold cyan]📊 Funding DB Status[/bold cyan]\n\n"
        f"Total rounds: [bold]{total:,}[/bold]\n"
        f"With amount:  [bold]{with_amount:,}[/bold] ({with_amount*100//total if total else 0}%)\n"
        f"Today:        [bold]{today:,}[/bold]\n"
        f"This week:    [bold]{this_week:,}[/bold]",
        border_style="green"
    ))

    # By round type
    rt = Table(title="By Round Type", box=box.SIMPLE_HEAD)
    rt.add_column("Round", style="cyan")
    rt.add_column("Count", justify="right")
    rt.add_column("Avg Amount", justify="right", style="green")
    for row in conn.execute("""
        SELECT round_type, COUNT(*) as cnt,
               AVG(amount_usd) as avg_amt
        FROM funding_rounds
        GROUP BY round_type ORDER BY cnt DESC LIMIT 12
    """).fetchall():
        avg = f"${row['avg_amt']/1e6:.1f}M" if row['avg_amt'] else "—"
        rt.add_row(row['round_type'] or "unknown", str(row['cnt']), avg)
    console.print(rt)

    # By country
    cc = Table(title="Top Countries", box=box.SIMPLE_HEAD)
    cc.add_column("Country", style="cyan")
    cc.add_column("Rounds", justify="right")
    for row in conn.execute("""
        SELECT hq_country, COUNT(*) as cnt
        FROM funding_rounds
        WHERE hq_country IS NOT NULL
        GROUP BY hq_country ORDER BY cnt DESC LIMIT 10
    """).fetchall():
        cc.add_row(row["hq_country"], str(row["cnt"]))
    console.print(cc)

    # By sector
    sc = Table(title="Top Sectors", box=box.SIMPLE_HEAD)
    sc.add_column("Sector", style="cyan")
    sc.add_column("Rounds", justify="right")
    for row in conn.execute("""
        SELECT sector, COUNT(*) as cnt
        FROM funding_rounds
        WHERE sector IS NOT NULL
        GROUP BY sector ORDER BY cnt DESC LIMIT 10
    """).fetchall():
        sc.add_row(row["sector"], str(row["cnt"]))
    console.print(sc)

    # Recent runs
    runs = Table(title="Recent Collection Runs", box=box.SIMPLE_HEAD)
    runs.add_column("Source", style="dim")
    runs.add_column("Started", style="dim")
    runs.add_column("Found", justify="right")
    runs.add_column("New", justify="right", style="green")
    runs.add_column("Status")
    for row in conn.execute("""
        SELECT source, started_at, found, new, status
        FROM collection_runs ORDER BY id DESC LIMIT 15
    """).fetchall():
        status_style = "green" if row["status"] == "ok" else "red" if row["status"] == "error" else "yellow"
        runs.add_row(
            (row["source"] or "")[:45],
            (row["started_at"] or "")[:16],
            str(row["found"]),
            str(row["new"]),
            f"[{status_style}]{row['status']}[/{status_style}]"
        )
    console.print(runs)
    conn.close()


@cli.command()
@click.option("--host", default="127.0.0.1")
@click.option("--port", default=8001, help="Port (default: 8001)")
@click.option("--open/--no-open", default=True, help="Open browser automatically")
def serve(host: str, port: int, open: bool):
    """Launch Datasette — the browser UI for exploring funding rounds."""
    import subprocess
    import webbrowser
    import time

    if not DB_PATH.exists():
        console.print("[red]Database not found. Run: python main.py init[/red]")
        sys.exit(1)

    metadata = ROOT / "datasette_metadata.json"
    cmd = [
        sys.executable, "-m", "datasette", "serve",
        str(DB_PATH),
        "--host", host,
        "--port", str(port),
        "--reload",
        "--open",
    ]
    if metadata.exists():
        cmd += ["--metadata", str(metadata)]

    console.print(Panel.fit(
        f"[bold cyan]🌐 Datasette launching[/bold cyan]\n"
        f"[dim]URL: http://{host}:{port}[/dim]\n"
        f"[dim]Ctrl+C to stop[/dim]",
        border_style="cyan"
    ))

    if open:
        # Give Datasette 2 seconds to start
        import threading
        def _open():
            time.sleep(2)
            webbrowser.open(f"http://{host}:{port}/funding/funding_rounds")
        threading.Thread(target=_open, daemon=True).start()

    try:
        subprocess.run(cmd)
    except KeyboardInterrupt:
        console.print("\n[yellow]Datasette stopped.[/yellow]")


@cli.command()
@click.option("--format", "fmt", type=click.Choice(["json", "csv"]), default="json")
@click.option("--country", default=None, help="Filter by country")
@click.option("--sector", default=None, help="Filter by sector")
@click.option("--min-amount", "min_amount", default=None, type=float, help="Minimum USD amount")
@click.option("--days", default=30, help="Last N days (default: 30)")
def export(fmt: str, country: str, sector: str, min_amount: float, days: int):
    """Export funding rounds to JSON or CSV."""
    import json
    import csv
    from io import StringIO

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    query = "SELECT * FROM funding_rounds WHERE 1=1"
    params = []

    if days:
        query += " AND (announced_date >= date('now', ?) OR announced_date IS NULL)"
        params.append(f"-{days} days")
    if country:
        query += " AND hq_country = ?"
        params.append(country)
    if sector:
        query += " AND sector = ?"
        params.append(sector)
    if min_amount:
        query += " AND amount_usd >= ?"
        params.append(min_amount)

    query += " ORDER BY announced_date DESC, amount_usd DESC"
    rows = conn.execute(query, params).fetchall()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = ROOT / "exports"
    out_dir.mkdir(exist_ok=True)

    if fmt == "json":
        out_path = out_dir / f"funding_rounds_{ts}.json"
        data = [dict(r) for r in rows]
        out_path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    else:
        out_path = out_dir / f"funding_rounds_{ts}.csv"
        if rows:
            keys = rows[0].keys()
            buf = StringIO()
            w = csv.DictWriter(buf, fieldnames=keys)
            w.writeheader()
            w.writerows([dict(r) for r in rows])
            out_path.write_text(buf.getvalue(), encoding="utf-8")

    size_kb = out_path.stat().st_size // 1024
    console.print(f"[green]✓[/green] Exported [bold]{len(rows)}[/bold] rows → [bold]{out_path.name}[/bold] ({size_kb} KB)")
    conn.close()


# ── Entry ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    cli()
