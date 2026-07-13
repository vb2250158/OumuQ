from __future__ import annotations

import os
import queue
import tempfile
import threading
import time
import wave
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from itertools import count
from pathlib import Path
from typing import Any


PlaybackFunction = Callable[[Path], None]
ClockFunction = Callable[[], float]


def _environment_float(name: str, default: float, *, minimum: float = 0.0) -> float:
    try:
        value = float(os.environ.get(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, value)


DEFAULT_STATUS_ERROR_GRACE_SECONDS = _environment_float(
    "OUMUQ_PLAYBACK_STATUS_ERROR_GRACE_SECONDS",
    15.0,
)
DEFAULT_HOST_LOCK_TIMEOUT_SECONDS = _environment_float(
    "OUMUQ_PLAYBACK_LOCK_TIMEOUT_SECONDS",
    900.0,
    minimum=0.1,
)
DEFAULT_HOST_LOCK_POLL_SECONDS = _environment_float(
    "OUMUQ_PLAYBACK_LOCK_POLL_SECONDS",
    0.05,
    minimum=0.01,
)


@dataclass
class PlaybackStatusPollGrace:
    """Track a continuous worker-status polling outage before failing a job."""

    grace_seconds: float = DEFAULT_STATUS_ERROR_GRACE_SECONDS
    clock: ClockFunction = field(default=time.monotonic, repr=False)
    first_failure_at: float | None = None
    failures: int = 0
    last_error: str | None = None

    def note_failure(self, error: BaseException | str) -> bool:
        """Record a failed poll and return True only after the grace expires."""

        now = self.clock()
        if self.first_failure_at is None:
            self.first_failure_at = now
        self.failures += 1
        self.last_error = str(error)
        return now - self.first_failure_at >= max(0.0, self.grace_seconds)

    def note_success(self) -> None:
        """A successful poll ends the current continuous outage window."""

        self.first_failure_at = None
        self.failures = 0
        self.last_error = None

    def snapshot(self) -> dict[str, Any]:
        now = self.clock()
        elapsed = 0.0 if self.first_failure_at is None else max(0.0, now - self.first_failure_at)
        return {
            "grace_seconds": max(0.0, self.grace_seconds),
            "continuous_failure_seconds": elapsed,
            "failures": self.failures,
            "last_error": self.last_error,
            "expired": self.first_failure_at is not None and elapsed >= max(0.0, self.grace_seconds),
        }


def default_host_playback_lock_path() -> Path:
    configured = os.environ.get("OUMUQ_PLAYBACK_LOCK_FILE", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path(tempfile.gettempdir()) / "oumuq-host-playback.lock").resolve()


@contextmanager
def host_playback_lock(
    lock_path: str | Path | None = None,
    *,
    timeout_seconds: float | None = None,
):
    """Hold one OS-backed host lock while a process uses the audio device."""

    path = Path(lock_path).expanduser().resolve() if lock_path is not None else default_host_playback_lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    timeout = DEFAULT_HOST_LOCK_TIMEOUT_SECONDS if timeout_seconds is None else max(0.0, timeout_seconds)
    deadline = time.monotonic() + timeout
    acquired = False

    with path.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()

        if os.name == "nt":
            import msvcrt

            while not acquired:
                handle.seek(0)
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    acquired = True
                except OSError as exc:
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f"Timed out waiting for host playback lock: {path}") from exc
                    time.sleep(DEFAULT_HOST_LOCK_POLL_SECONDS)
        else:
            import fcntl

            while not acquired:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                except BlockingIOError as exc:
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f"Timed out waiting for host playback lock: {path}") from exc
                    time.sleep(DEFAULT_HOST_LOCK_POLL_SECONDS)

        try:
            yield path
        finally:
            if acquired:
                if os.name == "nt":
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def play_wav_blocking(path: Path) -> None:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Playback WAV not found: {path}")
    with wave.open(str(path), "rb") as handle:
        if handle.getnframes() <= 0:
            raise ValueError(f"Playback WAV is empty: {path}")
    if os.name != "nt":
        raise RuntimeError("Global OumuQ playback currently requires Windows winsound.")
    import winsound

    with host_playback_lock():
        winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_NODEFAULT)


class GlobalPlaybackCoordinator:
    """A process-local FIFO; the default player also holds a host-wide mutex."""

    def __init__(self, player: PlaybackFunction | None = None, *, start_thread: bool = True) -> None:
        self._player = player or play_wav_blocking
        self._sequence = count(1)
        self._next_dispatch = 1
        self._records: dict[int, dict[str, Any]] = {}
        self._completed_generation: dict[int, bool] = {}
        self._play_queue: queue.Queue[int] = queue.Queue()
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._active_sequence: int | None = None
        self._thread: threading.Thread | None = None
        if start_thread:
            self._thread = threading.Thread(target=self._playback_loop, name="oumuq-global-playback", daemon=True)
            self._thread.start()

    def reserve(
        self,
        *,
        session_id: str | None,
        character_id: str | None,
        worker_url: str,
    ) -> int:
        with self._condition:
            sequence = next(self._sequence)
            self._records[sequence] = {
                "sequence": sequence,
                "status": "waiting_generation",
                "session_id": session_id,
                "character_id": character_id,
                "worker_url": worker_url,
                "job_id": None,
                "output": None,
                "error": None,
                "reserved_at": utc_now(),
                "ready_at": None,
                "started_at": None,
                "completed_at": None,
            }
            self._condition.notify_all()
            return sequence

    def mark_ready(self, sequence: int, output: str | Path, *, job_id: str | None = None) -> None:
        path = Path(output).resolve()
        with self._condition:
            record = self._record(sequence)
            if record["status"] in {"done", "playback_error", "generation_error"}:
                return
            record.update(
                status="ready_waiting_turn",
                output=str(path),
                job_id=job_id or record.get("job_id"),
                ready_at=utc_now(),
            )
            self._completed_generation[sequence] = True
            self._dispatch_completed_generation()
            self._condition.notify_all()

    def mark_failed(self, sequence: int, error: str, *, job_id: str | None = None) -> None:
        with self._condition:
            record = self._record(sequence)
            if record["status"] in {"done", "playback_error", "generation_error"}:
                return
            record.update(
                status="generation_error",
                error=str(error),
                job_id=job_id or record.get("job_id"),
                completed_at=utc_now(),
            )
            self._completed_generation[sequence] = False
            self._dispatch_completed_generation()
            self._condition.notify_all()

    def snapshot(self, *, limit: int = 100) -> dict[str, Any]:
        with self._condition:
            records = [dict(self._records[key]) for key in sorted(self._records, reverse=True)[: max(1, limit)]]
            queued = sum(
                record["status"] in {"waiting_generation", "ready_waiting_turn", "queued_playback"}
                for record in self._records.values()
            )
            return {
                "mode": "process-fifo+host-lock",
                "ordering_scope": "process",
                "playback_mutex_scope": "host",
                "cross_process_fifo": False,
                "overlap_allowed": False,
                "active_sequence": self._active_sequence,
                "queued": queued,
                "records": records,
            }

    def wait_until_idle(self, timeout: float = 10.0) -> bool:
        deadline = time.monotonic() + timeout
        with self._condition:
            while True:
                active = any(
                    record["status"]
                    in {"waiting_generation", "ready_waiting_turn", "queued_playback", "playing"}
                    for record in self._records.values()
                )
                if not active:
                    return True
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(timeout=remaining)

    def _record(self, sequence: int) -> dict[str, Any]:
        try:
            return self._records[sequence]
        except KeyError as exc:
            raise KeyError(f"Unknown playback sequence: {sequence}") from exc

    def _dispatch_completed_generation(self) -> None:
        while self._next_dispatch in self._completed_generation:
            sequence = self._next_dispatch
            generation_ok = self._completed_generation.pop(sequence)
            record = self._record(sequence)
            if generation_ok:
                record["status"] = "queued_playback"
                self._play_queue.put(sequence)
            self._next_dispatch += 1

    def _playback_loop(self) -> None:
        while True:
            sequence = self._play_queue.get()
            try:
                with self._condition:
                    record = self._record(sequence)
                    self._active_sequence = sequence
                    record.update(status="playing", started_at=utc_now())
                    self._condition.notify_all()
                    output = Path(str(record["output"]))
                self._player(output)
                with self._condition:
                    record = self._record(sequence)
                    record.update(status="done", completed_at=utc_now())
            except Exception as exc:
                with self._condition:
                    record = self._record(sequence)
                    record.update(status="playback_error", error=str(exc), completed_at=utc_now())
            finally:
                with self._condition:
                    self._active_sequence = None
                    self._condition.notify_all()
                self._play_queue.task_done()
