"""Best-effort operator notices. Never raises, never blocks a request, never carries message bodies."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

log = logging.getLogger("bma.notify")
Sink = Callable[[str, str, str], None]


class Notifier:
    def __init__(self, sinks: list[Sink] | None = None, live: bool = False, background: bool = True) -> None:
        self.sinks = sinks or []
        self.live = live
        self.background = background

    def _deliver(self, key: str, title: str, body: str) -> None:
        for sink in self.sinks:
            try:
                sink(key, title, body)
            except Exception:  # noqa: BLE001 - a broken notification channel must not affect the action it reports on
                log.exception("notification sink failed")

    def notify(self, key: str, title: str, body: str) -> None:
        if not self.live or not self.sinks:
            log.info("notice (not sent): %s", title)
            return
        if self.background:
            threading.Thread(target=self._deliver, args=(key, title, body), daemon=True).start()
        else:
            self._deliver(key, title, body)

    def approval_pending(self, approval: Any) -> None:
        self.notify(
            f"notice-{approval.id}",
            f"Approval needed: {approval.action_type} ({approval.risk} risk)",
            f"Target: {approval.target}\nRequested by: {approval.requested_by}\nReview it in the approval queue (request {approval.id[:8]}).",
        )
