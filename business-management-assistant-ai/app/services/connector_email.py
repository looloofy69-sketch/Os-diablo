"""SMTP email connector (message.send, invoice.send, contract.send, calendar.invite). Stdlib only."""

from __future__ import annotations

import re
import smtplib
import socket
import ssl
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Any

from app.services.connectors import ConnectorResult, HealthResult

ACTION_TYPES = ("message.send", "invoice.send", "contract.send", "calendar.invite")
EMAIL_RE = re.compile(r"^[^@\s,;<>\"']+@[^@\s,;<>\"']+\.[^@\s,;<>\"']+$")


@dataclass(frozen=True)
class SmtpConfig:
    host: str
    port: int
    sender: str
    username: str | None = None
    password: str | None = None
    security: str = "starttls"  # starttls | ssl | none
    allowed_domains: tuple[str, ...] = ()
    timeout: float = 15.0
    max_recipients: int = 25

    def __repr__(self) -> str:
        return f"SmtpConfig(host={self.host!r}, port={self.port}, sender={self.sender!r}, security={self.security!r})"


def parse_recipients(*values: Any) -> list[str]:
    """Split strings or lists on commas, semicolons and whitespace; lower-case; de-duplicate preserving order."""
    seen: dict[str, None] = {}
    for value in values:
        items: Iterable[Any] = value if isinstance(value, (list, tuple)) else [value]
        for item in items:
            for part in re.split(r"[,;\s]+", str(item or "")):
                if part:
                    seen.setdefault(part.lower(), None)
    return list(seen)


def _parse_when(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r\n", "\n").replace("\n", "\\n")


def _fold(line: str) -> str:
    chunks = [line[i : i + 73] for i in range(0, len(line), 73)] or [""]
    return "\r\n ".join(chunks)


def build_ics(uid: str, title: str, start: datetime, end: datetime, organizer: str, attendees: list[str], location: str = "", description: str = "", stamp: datetime | None = None) -> str:
    fmt = "%Y%m%dT%H%M%SZ"
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Business Assistant//EN", "METHOD:REQUEST", "BEGIN:VEVENT",
        f"UID:{uid}", f"DTSTAMP:{(stamp or datetime.now(timezone.utc)).strftime(fmt)}",
        f"DTSTART:{start.strftime(fmt)}", f"DTEND:{end.strftime(fmt)}", f"SUMMARY:{_escape(title)}", f"ORGANIZER:mailto:{organizer}",
        *[f"ATTENDEE;RSVP=TRUE:mailto:{a}" for a in attendees],
    ]
    if location:
        lines.append(f"LOCATION:{_escape(location)}")
    if description:
        lines.append(f"DESCRIPTION:{_escape(description)}")
    lines += ["END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"


def default_smtp_factory(config: SmtpConfig) -> smtplib.SMTP:
    """Connect, secure and authenticate. Anything raised here happened before any mail was submitted."""
    if config.security == "ssl":
        smtp: smtplib.SMTP = smtplib.SMTP_SSL(config.host, config.port, timeout=config.timeout, context=ssl.create_default_context())
    else:
        smtp = smtplib.SMTP(config.host, config.port, timeout=config.timeout)
        if config.security == "starttls":
            smtp.starttls(context=ssl.create_default_context())
    if config.username:
        smtp.login(config.username, config.password or "")
    return smtp


class EmailConnector:
    name = "smtp-email"
    integrations = ("Email", "Calendar")

    def __init__(self, config: SmtpConfig, smtp_factory: Callable[[SmtpConfig], Any] = default_smtp_factory) -> None:
        self.config = config
        self._factory = smtp_factory
        self._domain = config.sender.rsplit("@", 1)[-1]

    def supports(self, action_type: str, target: str) -> bool:
        recipients = parse_recipients(target)
        return action_type in ACTION_TYPES and bool(recipients) and all(EMAIL_RE.match(r) for r in recipients)

    @staticmethod
    def _fail(detail: str, retryable: bool = False, outcome_unknown: bool = False) -> ConnectorResult:
        return ConnectorResult(ok=False, dry_run=False, detail=detail, retryable=retryable, outcome_unknown=outcome_unknown)

    def _build(self, action_type: str, to: list[str], cc: list[str], payload: dict[str, Any], key: str) -> EmailMessage | str:
        """Return the message, or a human-readable reason it cannot be built."""
        msg = EmailMessage()
        safe_key = re.sub(r"[^A-Za-z0-9._-]", "", key) or "message"
        msg["From"], msg["To"] = self.config.sender, ", ".join(to)
        if cc:
            msg["Cc"] = ", ".join(cc)
        msg["Message-ID"] = f"<{safe_key}@{self._domain}>"
        msg["X-BMA-Approval"] = safe_key
        if action_type == "calendar.invite":
            title = str(payload.get("title") or payload.get("subject") or "").strip()
            try:
                start, end = _parse_when(payload["start"]), _parse_when(payload["end"])
            except (KeyError, ValueError):
                return "calendar.invite needs ISO 8601 'start' and 'end' in the payload"
            if not title or end <= start:
                return "calendar.invite needs a 'title' and an end after the start"
            msg["Subject"] = title
            msg.set_content(str(payload.get("body") or f"You are invited: {title}"))
            ics = build_ics(safe_key, title, start, end, self.config.sender, [*to, *cc], str(payload.get("location") or ""), str(payload.get("description") or ""))
            msg.add_alternative(ics, subtype="calendar", params={"method": "REQUEST", "charset": "utf-8"})
            return msg
        subject, body = str(payload.get("subject") or "").strip(), str(payload.get("body") or "").strip()
        if not subject or not body:
            return f"{action_type} needs 'subject' and 'body' in the payload; amend the request before approving"
        msg["Subject"] = subject
        msg.set_content(body)
        return msg

    def execute(self, *, action_type: str, target: str, payload: dict[str, Any], idempotency_key: str) -> ConnectorResult:
        to, cc = parse_recipients(target), parse_recipients(payload.get("cc"))
        everyone = list(dict.fromkeys([*to, *cc]))
        bad = [r for r in everyone if not EMAIL_RE.match(r)]
        if bad:
            return self._fail(f"invalid recipient address: {bad[0]}")
        if len(everyone) > self.config.max_recipients:
            return self._fail(f"{len(everyone)} recipients exceeds the connector limit of {self.config.max_recipients}")
        if self.config.allowed_domains:
            outside = [r for r in everyone if r.rsplit("@", 1)[-1] not in self.config.allowed_domains]
            if outside:
                return self._fail(f"recipient {outside[0]} is outside the allowed domains")
        try:
            built = self._build(action_type, to, cc, payload, idempotency_key)
        except ValueError:
            return self._fail("a header value contains forbidden characters")
        if isinstance(built, str):
            return self._fail(built)

        try:
            smtp = self._factory(self.config)
        except smtplib.SMTPAuthenticationError:
            return self._fail("SMTP authentication failed; nothing was sent")
        except (smtplib.SMTPException, OSError, socket.timeout) as exc:
            return self._fail(f"could not reach the SMTP server ({type(exc).__name__}); nothing was sent", retryable=True)
        try:
            smtp.send_message(built, to_addrs=everyone)
        except smtplib.SMTPResponseException as exc:
            temporary = 400 <= exc.smtp_code < 500
            return self._fail(f"SMTP server rejected the message ({exc.smtp_code}); nothing was sent", retryable=temporary)
        except smtplib.SMTPRecipientsRefused:
            return self._fail("SMTP server refused every recipient; nothing was sent")
        except (smtplib.SMTPException, OSError, socket.timeout) as exc:
            return self._fail(
                f"connection lost while sending ({type(exc).__name__}); outcome unknown, check the mail log before retrying",
                outcome_unknown=True,
            )
        finally:
            try:
                smtp.quit()
            except Exception:  # noqa: BLE001 - closing must never mask the send result
                pass
        return ConnectorResult(ok=True, dry_run=False, detail=f"sent to {len(everyone)} recipient(s)", external_id=built["Message-ID"])

    def health(self) -> HealthResult:
        try:
            smtp = self._factory(self.config)
        except smtplib.SMTPAuthenticationError:
            return HealthResult(False, "SMTP authentication failed")
        except (smtplib.SMTPException, OSError) as exc:
            return HealthResult(False, f"SMTP unreachable ({type(exc).__name__})")
        try:
            code, _ = smtp.noop()
            return HealthResult(code == 250, "SMTP reachable" if code == 250 else f"SMTP replied {code}")
        except (smtplib.SMTPException, OSError) as exc:
            return HealthResult(False, f"SMTP error ({type(exc).__name__})")
        finally:
            try:
                smtp.quit()
            except Exception:  # noqa: BLE001
                pass
