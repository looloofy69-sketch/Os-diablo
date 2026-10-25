"""Executive briefing: structured facts first, prose rendering second."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from sqlmodel import Session, col, func, select

from app.domain.models import ApprovalRequest, ApprovalStatus, Goal, Integration, Project, Status, Task, now
from app.services.priorities import TaskView, as_utc, goal_at_risk, goal_progress, rank_tasks

STALE_PENDING_HOURS = 24
STUCK_EXECUTING_MINUTES = 10


def build_briefing(session: Session, mode: str, moment: datetime | None = None) -> dict[str, Any]:
    moment = moment or now()
    goals = session.exec(select(Goal)).all()
    projects = session.exec(select(Project)).all()
    # Fetch only the fields needed by ranking and attention summaries; loading every
    # ORM column for every open task scales poorly as the task table grows.
    open_task_rows = session.exec(
        select(Task.id, Task.title, Task.status, Task.priority, Task.due_at, Task.project_id)
        .where(col(Task.status) != Status.done.value)
    ).all()
    open_tasks = [TaskView(id=row[0], title=row[1], status=row[2], priority=row[3], due_at=row[4], project_id=row[5]) for row in open_task_rows]
    integrations = session.exec(select(Integration).order_by(col(Integration.name))).all()
    approvals = session.exec(select(ApprovalRequest).where(col(ApprovalRequest.status).in_([ApprovalStatus.pending.value, ApprovalStatus.approved.value, ApprovalStatus.executing.value]))).all()

    # Task counts per project and status, then rolled up to goals through the project's goal_id.
    per_project: dict[str | None, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for project_id, status, count in session.exec(select(Task.project_id, Task.status, func.count()).group_by(Task.project_id, Task.status)).all():
        per_project[project_id][status] += count
    per_goal: dict[str, list[int]] = defaultdict(lambda: [0, 0])  # done, total
    for project in projects:
        if project.goal_id:
            counts = per_project.get(project.id, {})
            per_goal[project.goal_id][0] += counts.get(Status.done.value, 0)
            per_goal[project.goal_id][1] += sum(counts.values())

    overdue = [t for t in open_tasks if (due := as_utc(t.due_at)) is not None and due < moment]
    blocked = [t for t in open_tasks if t.status == Status.blocked.value]
    ranked = rank_tasks(open_tasks, moment, limit=5)

    goal_rows = []
    for goal in goals:
        done, total = per_goal.get(goal.id, (0, 0))
        progress = goal_progress(done, total)
        goal_rows.append(
            {
                "id": goal.id,
                "title": goal.title,
                "status": goal.status,
                "progress": None if progress is None else round(progress, 3),
                "target_date": goal.target_date.isoformat() if goal.target_date else None,
                "at_risk": goal_at_risk(goal.target_date, progress, goal.status, moment),
            }
        )

    attention: list[dict[str, Any]] = []
    for task in sorted(overdue, key=lambda t: as_utc(t.due_at))[:5]:
        attention.append({"severity": "critical", "kind": "task.overdue", "message": f"Overdue: {task.title}", "ref": {"type": "task", "id": task.id}})
    for task in blocked[:5]:
        attention.append({"severity": "warning", "kind": "task.blocked", "message": f"Blocked: {task.title}", "ref": {"type": "task", "id": task.id}})
    for row in goal_rows:
        if row["at_risk"]:
            attention.append({"severity": "warning", "kind": "goal.at_risk", "message": f"Goal at risk: {row['title']}", "ref": {"type": "goal", "id": row["id"]}})
    stale_before = moment - timedelta(hours=STALE_PENDING_HOURS)
    stuck_before = moment - timedelta(minutes=STUCK_EXECUTING_MINUTES)
    for item in approvals:
        created = as_utc(item.created_at)
        if item.status == ApprovalStatus.pending.value and created < stale_before:
            attention.append({"severity": "warning", "kind": "approval.stale", "message": f"Approval waiting over {STALE_PENDING_HOURS}h: {item.action_type} to {item.target}", "ref": {"type": "approval", "id": item.id}})
        elif item.status == ApprovalStatus.executing.value and (as_utc(item.executed_at) or created) < stuck_before:
            attention.append({"severity": "critical", "kind": "approval.stuck", "message": f"Execution may be stuck: {item.action_type} to {item.target}", "ref": {"type": "approval", "id": item.id}})
    for project in projects:
        if project.status != Status.done.value and not per_project.get(project.id):
            attention.append({"severity": "info", "kind": "project.no_tasks", "message": f"No tasks yet: {project.name}", "ref": {"type": "project", "id": project.id}})

    pending = [a for a in approvals if a.status == ApprovalStatus.pending.value]
    return {
        "mode": mode,
        "generated_at": moment.isoformat(),
        "goals": len(goals),
        "projects": len(projects),
        "open_tasks": len(open_tasks),
        "overdue_tasks": len(overdue),
        "blocked_tasks": len(blocked),
        "pending_approvals": len(pending),
        "attention": attention[:15],
        "next_actions": [
            {"id": t.id, "title": t.title, "priority": t.priority, "due_at": t.due_at.isoformat() if t.due_at else None, "reason": reason}
            for t, reason in ranked
        ],
        "goal_progress": goal_rows,
        "integrations": [{"name": i.name, "health": i.health, "enabled": i.enabled} for i in integrations],
    }


def render_briefing_text(b: dict[str, Any]) -> str:
    lines = [
        f"{b['goals']} goals, {b['projects']} projects, {b['open_tasks']} open tasks "
        f"({b['overdue_tasks']} overdue, {b['blocked_tasks']} blocked), {b['pending_approvals']} approvals waiting.",
    ]
    if b["attention"]:
        lines.append("Needs attention:")
        lines += [f"- {item['message']}" for item in b["attention"][:5]]
    if b["next_actions"]:
        lines.append("Next actions:")
        lines += [f"- {a['title']} ({a['reason']})" for a in b["next_actions"][:3]]
    elif not b["open_tasks"]:
        lines.append("No open tasks. Create one with 'create task: ...'.")
    lines.append(f"Mode: {b['mode']}. External actions need approval.")
    return "\n".join(lines)
