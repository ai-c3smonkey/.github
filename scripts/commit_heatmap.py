#!/usr/bin/env python3
"""Commit-Heatmap für eine GitHub-Organisation (SVG, ohne Abhängigkeiten).

Zählt pro Tag die Commits eines Autors in allen nicht archivierten Repos der
Org (Default-Branch) und schreibt eine SVG im Stil des GitHub-Contribution-Graphen.

Umgebung:
  GH_TOKEN   Token mit Lesezugriff auf die Repos der Org (für private Repos nötig)
  ORG        Default: ai-c3smonkey
  AUTHOR     GitHub-Login, dessen Commits gezählt werden. Default: marzelwidmer
  OUT        Zieldatei. Default: profile/heatmap.svg
  SAMPLE=1   Zufallsdaten statt API (Offline-Test)
"""
from __future__ import annotations

import json
import os
import random
import sys
import urllib.error
import urllib.request
from collections import Counter
from datetime import date, datetime, timedelta, timezone

ORG = os.environ.get("ORG", "ai-c3smonkey")
AUTHOR = os.environ.get("AUTHOR", "marzelwidmer")
OUT = os.environ.get("OUT", "profile/heatmap.svg")
TOKEN = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
API = "https://api.github.com"
WEEKS = 53

# Farben wie GitHub (hell / dunkel); Index 0 = keine Commits
LIGHT = ["#ebedf0", "#9be9a8", "#40c463", "#30a14e", "#216e39"]
DARK = ["#161b22", "#0e4429", "#006d32", "#26a641", "#39d353"]


def api_get(path: str) -> tuple[list | dict, str | None]:
    request = urllib.request.Request(
        API + path,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {TOKEN}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "org-commit-heatmap",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        body = json.load(response)
        link = response.headers.get("Link", "")
    next_url = None
    for part in link.split(","):
        if 'rel="next"' in part:
            next_url = part.split(";")[0].strip()[1:-1].removeprefix(API)
    return body, next_url


def paginate(path: str) -> list:
    items: list = []
    next_path: str | None = path
    while next_path:
        page, next_path = api_get(next_path)
        items.extend(page)  # type: ignore[arg-type]
    return items


def fetch_counts(since: date) -> Counter[date]:
    counts: Counter[date] = Counter()
    repos = paginate(f"/orgs/{ORG}/repos?type=all&per_page=100")
    for repo in repos:
        if repo.get("archived"):
            continue
        name = repo["name"]
        try:
            commits = paginate(
                f"/repos/{ORG}/{name}/commits?author={AUTHOR}"
                f"&since={since.isoformat()}T00:00:00Z&per_page=100"
            )
        except urllib.error.HTTPError as error:
            # 409 = leeres Repo, 403/404 = kein Zugriff
            print(f"  übersprungen: {name} (HTTP {error.code})", file=sys.stderr)
            continue
        print(f"  {name}: {len(commits)} Commits", file=sys.stderr)
        for commit in commits:
            stamp = commit["commit"]["author"]["date"]
            counts[datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(timezone.utc).date()] += 1
    return counts


def sample_counts(first_day: date, today: date) -> Counter[date]:
    rng = random.Random(7)
    counts: Counter[date] = Counter()
    day = first_day
    while day <= today:
        if rng.random() < 0.35:
            counts[day] = rng.randint(1, 12)
        day += timedelta(days=1)
    return counts


def level(count: int, maximum: int) -> int:
    if count <= 0:
        return 0
    # Quartile des Maximums, damit einzelne Ausreisser die Skala nicht kaputt machen
    ratio = count / maximum
    return 1 if ratio <= 0.25 else 2 if ratio <= 0.5 else 3 if ratio <= 0.75 else 4


def streaks(counts: Counter[date], today: date) -> tuple[int, int]:
    longest = run = 0
    day = min(counts) if counts else today
    while day <= today:
        run = run + 1 if counts.get(day) else 0
        longest = max(longest, run)
        day += timedelta(days=1)
    current = 0
    day = today if counts.get(today) else today - timedelta(days=1)
    while counts.get(day):
        current += 1
        day -= timedelta(days=1)
    return current, longest


def render(counts: Counter[date], today: date, first_day: date) -> str:
    cell, gap, left, top = 11, 3, 34, 62
    step = cell + gap
    width = left + WEEKS * step + 12
    height = top + 7 * step + 36
    maximum = max(counts.values(), default=1)
    total = sum(counts.values())
    active = sum(1 for value in counts.values() if value)
    current, longest = streaks(counts, today)

    css = ["text{font:12px -apple-system,Segoe UI,Helvetica,Arial,sans-serif;fill:#57606a}"]
    css.append(".t{font-size:14px;font-weight:600;fill:#1f2328}")
    css.append(".bg{fill:#fff}")
    for index, colour in enumerate(LIGHT):
        css.append(f".l{index}{{fill:{colour}}}")
    css.append(
        "@media(prefers-color-scheme:dark){text{fill:#8b949e}.t{fill:#e6edf3}.bg{fill:#0d1117}"
        + "".join(f".l{index}{{fill:{colour}}}" for index, colour in enumerate(DARK))
        + "}"
    )

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="Commits von {AUTHOR} in {ORG}, letzte 12 Monate">',
        f"<style>{''.join(css)}</style>",
        f'<rect class="bg" width="{width}" height="{height}" rx="6"/>',
        f'<text class="t" x="{left}" y="22">{total} Commits in {ORG} (letzte 12 Monate)</text>',
        f'<text x="{left}" y="38" style="font-size:11px">'
        f"{active} aktive Tage · Serie aktuell {current} · längste Serie {longest}</text>",
    ]

    month_names = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"]
    last_month = -1
    cells: list[str] = []
    for week in range(WEEKS):
        for weekday in range(7):
            day = first_day + timedelta(days=week * 7 + weekday)
            if day > today:
                continue
            x, y = left + week * step, top + weekday * step
            count = counts.get(day, 0)
            cells.append(
                f'<rect class="l{level(count, maximum)}" x="{x}" y="{y}" width="{cell}" '
                f'height="{cell}" rx="2"><title>{count} Commits am {day.isoformat()}</title></rect>'
            )
            if weekday == 0 and day.month != last_month and day.day <= 7:
                parts.append(f'<text x="{x}" y="{top - 6}" style="font-size:11px">{month_names[day.month - 1]}</text>')
                last_month = day.month
    parts.extend(cells)

    for weekday, label in ((1, "Mo"), (3, "Mi"), (5, "Fr")):
        parts.append(f'<text x="4" y="{top + weekday * step + 10}" style="font-size:10px">{label}</text>')

    legend_y = top + 7 * step + 18
    legend_x = width - 12 - 5 * step - 60
    parts.append(f'<text x="{legend_x - 30}" y="{legend_y + 9}" style="font-size:10px">Wenig</text>')
    for index in range(5):
        parts.append(f'<rect class="l{index}" x="{legend_x + index * step}" y="{legend_y}" width="{cell}" height="{cell}" rx="2"/>')
    parts.append(f'<text x="{legend_x + 5 * step + 4}" y="{legend_y + 9}" style="font-size:10px">Viel</text>')

    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def main() -> int:
    today = datetime.now(timezone.utc).date()
    # Wochenstart = Sonntag wie bei GitHub
    this_week_start = today - timedelta(days=(today.weekday() + 1) % 7)
    first_day = this_week_start - timedelta(weeks=WEEKS - 1)

    if os.environ.get("SAMPLE"):
        counts = sample_counts(first_day, today)
    else:
        if not TOKEN:
            print("GH_TOKEN fehlt", file=sys.stderr)
            return 1
        counts = fetch_counts(first_day)

    os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as handle:
        handle.write(render(counts, today, first_day))
    print(f"{OUT} geschrieben ({sum(counts.values())} Commits)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
