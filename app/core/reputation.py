"""Source reputation: what each Soulseek user has actually done for us (roadmap #6).

Worked out from the job history we already keep (no extra bookkeeping to drift out of sync):
- delivered: the file arrived and was staged
- failed:    the download errored or the source never sent it (cancelled by the user doesn't count)
- broken:    it arrived but the check said Broken (fake bitrate, cut short, not audio...)
- speed:     bytes / (staged - requested), so queue waits count; it's how fast a track really reaches you

Shown as a narrow, last "Source" column on search results and used as a tie-breaker when ranking.
A source that has never delivered and failed twice sinks to the bottom, like an ad bot.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class Rep:
    delivered: int = 0
    failed: int = 0
    broken: int = 0
    bytes: int = 0
    seconds: float = 0.0

    @property
    def speed(self) -> float | None:
        """Average bytes/s from request to arrival, or None without a timed delivery."""
        return self.bytes / self.seconds if self.seconds > 0 and self.bytes > 0 else None

    @property
    def never_delivers(self) -> bool:
        return self.delivered == 0 and self.failed >= 2

    @property
    def score(self) -> int:
        """Higher is better. A broken file costs more than a failed download (it wasted a check too)."""
        return self.delivered - self.failed - 2 * self.broken

    def label(self) -> str:
        if not (self.delivered or self.failed):
            return ""
        bits = []
        if self.delivered:
            bits.append(f"✓{self.delivered}")
        if self.failed or self.broken:
            bits.append(f"✗{self.failed + self.broken}")
        return " ".join(bits)

    def tone(self) -> str:
        if self.never_delivers or (self.broken and self.broken >= self.delivered - self.broken):
            return "fail"
        if self.failed + self.broken > self.delivered:
            return "warn"
        return "pass_" if self.delivered else ""

    def sentence(self) -> str:
        if not (self.delivered or self.failed):
            return "You haven't downloaded from this source before."
        parts = [f"{self.delivered} delivered" if self.delivered else "never delivered"]
        if self.failed:
            parts.append(f"{self.failed} failed")
        if self.broken:
            parts.append(f"{self.broken} came out Broken")
        s = "From this source: " + ", ".join(parts)
        if self.speed:
            sp = self.speed
            s += f" · about {sp / 1e6:.1f} MB/s" if sp >= 1e6 else f" · about {sp / 1e3:.0f} kB/s"
            s += " from request to arrival"
        return s + "."


def _ts(s: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(s) if s else None
    except ValueError:
        return None


def from_rows(rows: list[dict]) -> dict[str, Rep]:
    """rows: remote_user, state, staged_path, remote_size, overall_status, requested_at, staged_at."""
    reps: dict[str, Rep] = {}
    for r in rows:
        user = r.get("remote_user")
        if not user:
            continue
        rep = reps.setdefault(user, Rep())
        if r.get("staged_path"):
            rep.delivered += 1
            if r.get("overall_status") == "FAIL":
                rep.broken += 1
            a, b = _ts(r.get("requested_at")), _ts(r.get("staged_at"))
            if a and b and b > a and r.get("remote_size"):
                rep.bytes += int(r["remote_size"])
                rep.seconds += (b - a).total_seconds()
        elif r.get("state") == "ERROR":
            rep.failed += 1
    return reps
