#!/usr/bin/env python3
"""Check consistency between the canonical backlog, issue map and live GitHub issues.

Local mode validates repository documents without dependencies or network access.
When GITHUB_TOKEN is set, it also verifies that each mapped issue exists, its
title contains the corresponding task ID, and its body links back to the backlog.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKLOG_PATH = ROOT / "docs" / "roadmap" / "implementation-backlog.md"
ISSUE_MAP_PATH = ROOT / "docs" / "roadmap" / "issue-map.md"
TASK_RE = re.compile(r"^###\s+([A-Z]{2,6}-\d{2})\s+—", re.MULTILINE)
MAP_ROW_RE = re.compile(
    r"^\|\s*([A-Z]{2,6}-\d{2})\s*\|\s*P[0-3]\s*\|[^|]*"
    r"\|\s*\[#(\d+)\]\((https://github\.com/([^/]+/[^/]+)/issues/(\d+))\)\s*\|",
    re.MULTILINE,
)
FINDING_ROW_RE = re.compile(
    r"^\|\s*(F-\d{2})\s*—[^|]*\|\s*([^|]+)\|",
    re.MULTILINE,
)


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def unique_ids(values: list[str], label: str) -> set[str]:
    if len(values) != len(set(values)):
        fail(f"{label} contains duplicate IDs")
    return set(values)


def check_live_issue(repo: str, number: int, task_id: str, token: str) -> None:
    url = f"https://api.github.com/repos/{repo}/issues/{number}"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "os-diablo-backlog-sync-check",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            issue = json.load(response)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        fail(f"cannot verify {task_id} at {url}: {exc}")

    if "pull_request" in issue:
        fail(f"{task_id} maps to a pull request, not an Issue: #{number}")
    title = issue.get("title", "")
    if task_id not in title:
        fail(f"issue #{number} title does not contain task ID {task_id!r}: {title!r}")
    body = issue.get("body") or ""
    if "docs/roadmap/implementation-backlog.md" not in body:
        fail(f"issue #{number} does not link back to the canonical backlog")
    if issue.get("state") not in {"open", "closed"}:
        fail(f"issue #{number} has an unexpected state")


def main() -> None:
    if not BACKLOG_PATH.is_file() or not ISSUE_MAP_PATH.is_file():
        fail("canonical backlog or issue map is missing")

    backlog = BACKLOG_PATH.read_text(encoding="utf-8")
    issue_map = ISSUE_MAP_PATH.read_text(encoding="utf-8")

    backlog_list = TASK_RE.findall(backlog)
    backlog_ids = unique_ids(backlog_list, "backlog")
    rows = MAP_ROW_RE.findall(issue_map)
    map_ids = [row[0] for row in rows]
    map_id_set = unique_ids(map_ids, "issue map")
    if backlog_ids != map_id_set:
        fail(
            "task IDs differ between backlog and issue map; "
            f"only in backlog={sorted(backlog_ids - map_id_set)}, "
            f"only in map={sorted(map_id_set - backlog_ids)}"
        )

    issue_numbers = [int(row[1]) for row in rows]
    if len(issue_numbers) != len(set(issue_numbers)):
        fail("an Issue number is mapped to more than one task")

    repo = os.environ.get("GITHUB_REPOSITORY", "looloofy69-sketch/Os-diablo")
    for task_id, number_text, url, url_repo, url_number in rows:
        number = int(number_text)
        if url_repo.lower() != repo.lower():
            fail(f"{task_id} points to {url_repo}, expected {repo}")
        if int(url_number) != number:
            fail(f"{task_id} Issue link number disagrees with table number")
        heading_link = re.search(
            rf"^\*\*GitHub issue:\*\*\s+\[{re.escape(task_id)}\]\({re.escape(url)}\)\s*$",
            backlog,
            re.MULTILINE,
        )
        if not heading_link:
            fail(f"{task_id} is not linked to its Issue from the backlog")

    finding_rows = FINDING_ROW_RE.findall(issue_map)
    finding_ids = [row[0] for row in finding_rows]
    unique_ids(finding_ids, "finding map")
    mapped_finding_ids: set[str] = set()
    for finding_id, task_text in finding_rows:
        linked_tasks = set(re.findall(r"\b[A-Z]{2,6}-\d{2}\b", task_text))
        if not linked_tasks:
            fail(f"{finding_id} has no mapped backlog task")
        unknown = linked_tasks - backlog_ids
        if unknown:
            fail(f"{finding_id} maps to unknown task IDs: {sorted(unknown)}")
        mapped_finding_ids.add(finding_id)
    if len(mapped_finding_ids) != 22:
        fail(f"expected 22 findings in baseline map, found {len(mapped_finding_ids)}")

    token = os.environ.get("GITHUB_TOKEN")
    if token:
        for task_id, number_text, _url, _url_repo, _url_number in rows:
            check_live_issue(repo, int(number_text), task_id, token)
        print(f"PASS: documents match; {len(rows)} live GitHub Issues verified.")
    else:
        print(
            f"PASS: documents match ({len(backlog_ids)} tasks, "
            f"{len(mapped_finding_ids)} findings, {len(issue_numbers)} unique Issue links). "
            "Set GITHUB_TOKEN to include live Issue verification."
        )


if __name__ == "__main__":
    main()
