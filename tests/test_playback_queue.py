from __future__ import annotations

import asyncio
import multiprocessing
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from app import main
from app.core.playback_queue import (
    GlobalPlaybackCoordinator,
    PlaybackStatusPollGrace,
    host_playback_lock,
)
from tests.test_api import FakeAsyncClient, FakeResponse, client


def hold_host_playback_lock(
    lock_path: str,
    start_gate: Any,
    events: Any,
    label: str,
) -> None:
    start_gate.wait(timeout=5)
    with host_playback_lock(lock_path, timeout_seconds=5):
        events.put(("start", label, time.monotonic()))
        time.sleep(0.15)
        events.put(("end", label, time.monotonic()))


def recording_player(events: list[str], activity: dict[str, int], lock: threading.Lock):
    def play(path: Path) -> None:
        with lock:
            activity["active"] += 1
            activity["max_active"] = max(activity["max_active"], activity["active"])
        time.sleep(0.03)
        events.append(path.name)
        with lock:
            activity["active"] -= 1

    return play


def test_global_queue_waits_for_submission_order_and_never_overlaps(tmp_path: Path) -> None:
    events: list[str] = []
    activity = {"active": 0, "max_active": 0}
    lock = threading.Lock()
    coordinator = GlobalPlaybackCoordinator(player=recording_player(events, activity, lock))

    first = coordinator.reserve(session_id="a", character_id="char-a", worker_url="worker-a")
    second = coordinator.reserve(session_id="b", character_id="char-b", worker_url="worker-b")
    third = coordinator.reserve(session_id="c", character_id="char-c", worker_url="worker-c")
    coordinator.mark_ready(second, tmp_path / "second.wav", job_id="job-2")
    coordinator.mark_ready(third, tmp_path / "third.wav", job_id="job-3")
    time.sleep(0.05)
    assert events == []

    coordinator.mark_ready(first, tmp_path / "first.wav", job_id="job-1")

    assert coordinator.wait_until_idle(timeout=5)
    assert events == ["first.wav", "second.wav", "third.wav"]
    assert activity["max_active"] == 1
    snapshot = coordinator.snapshot()
    assert snapshot["mode"] == "process-fifo+host-lock"
    assert snapshot["ordering_scope"] == "process"
    assert snapshot["playback_mutex_scope"] == "host"
    assert snapshot["cross_process_fifo"] is False
    assert snapshot["overlap_allowed"] is False
    assert [record["status"] for record in snapshot["records"]] == ["done", "done", "done"]


def test_status_poll_errors_retry_until_continuous_grace_expires() -> None:
    now = [100.0]
    grace = PlaybackStatusPollGrace(grace_seconds=2.0, clock=lambda: now[0])

    assert grace.note_failure("temporary timeout") is False
    now[0] += 1.9
    assert grace.note_failure("temporary timeout") is False
    assert grace.snapshot()["failures"] == 2

    grace.note_success()
    assert grace.snapshot()["failures"] == 0
    now[0] += 10
    assert grace.note_failure("connection reset") is False
    now[0] += 2.0
    assert grace.note_failure("connection reset") is True
    assert grace.snapshot()["expired"] is True


def test_host_playback_lock_serializes_independent_processes(tmp_path: Path) -> None:
    context = multiprocessing.get_context("spawn")
    try:
        start_gate = context.Event()
        events = context.Queue()
    except PermissionError as exc:
        pytest.skip(f"Windows restricted token cannot create multiprocessing named pipes: {exc}")
    processes = [
        context.Process(
            target=hold_host_playback_lock,
            args=(str(tmp_path / "playback.lock"), start_gate, events, label),
        )
        for label in ("first", "second")
    ]
    try:
        for process in processes:
            process.start()
        start_gate.set()
        observed = [events.get(timeout=10) for _ in range(4)]
        for process in processes:
            process.join(timeout=10)
        assert all(process.exitcode == 0 for process in processes)
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
            process.join(timeout=2)
        events.close()
        events.join_thread()

    active = 0
    for event, _label, _timestamp in sorted(observed, key=lambda item: item[2]):
        if event == "start":
            assert active == 0
            active = 1
        else:
            assert event == "end"
            assert active == 1
            active = 0
    assert active == 0


def test_failed_generation_unblocks_later_playback(tmp_path: Path) -> None:
    events: list[str] = []
    activity = {"active": 0, "max_active": 0}
    coordinator = GlobalPlaybackCoordinator(
        player=recording_player(events, activity, threading.Lock())
    )

    first = coordinator.reserve(session_id="a", character_id="char-a", worker_url="worker-a")
    second = coordinator.reserve(session_id="b", character_id="char-b", worker_url="worker-b")
    coordinator.mark_ready(second, tmp_path / "second.wav")
    coordinator.mark_failed(first, "generation failed")

    assert coordinator.wait_until_idle(timeout=5)
    assert events == ["second.wav"]
    records = {record["sequence"]: record for record in coordinator.snapshot()["records"]}
    assert records[first]["status"] == "generation_error"
    assert records[second]["status"] == "done"


def test_oumuq_forces_workers_silent_and_serializes_different_sessions(
    tmp_path: Path, monkeypatch: Any
) -> None:
    client(tmp_path, monkeypatch)
    events: list[str] = []
    activity = {"active": 0, "max_active": 0}
    coordinator = GlobalPlaybackCoordinator(
        player=recording_player(events, activity, threading.Lock())
    )
    monkeypatch.setattr(main, "GLOBAL_PLAYBACK_ENABLED", True)
    monkeypatch.setattr(main, "PLAYBACK_COORDINATOR", coordinator)

    outputs = {
        "jp_companion": tmp_path / "session-a.wav",
        "zh_reader": tmp_path / "session-b.wav",
    }

    async def immediate_done(self: FakeAsyncClient, url: str, json: dict[str, Any], **kwargs: Any) -> FakeResponse:
        self.posts.append((url, json))
        character_id = json["character_id"]
        return FakeResponse(
            {
                "id": "job-" + character_id,
                "status": "done",
                "text": json["text"],
                "output": str(outputs[character_id]),
            }
        )

    monkeypatch.setattr(FakeAsyncClient, "post", immediate_done)

    async def submit() -> list[dict[str, Any]]:
        return await asyncio.gather(
            main.speak(
                main.SpeakRequest(
                    text="こんにちは",
                    session_id="session-a",
                    character_id="jp_companion",
                    play=True,
                )
            ),
            main.speak(
                main.SpeakRequest(
                    text="你好",
                    session_id="session-b",
                    character_id="zh_reader",
                    play=True,
                )
            ),
        )

    results = asyncio.run(submit())

    assert [result["playback"]["sequence"] for result in results] == [1, 2]
    assert all(result["playback"]["overlap_allowed"] is False for result in results)
    assert [payload["play"] for _, payload in FakeAsyncClient.posts] == [False, False]
    assert [payload["character_id"] for _, payload in FakeAsyncClient.posts] == [
        "jp_companion",
        "zh_reader",
    ]
    assert coordinator.wait_until_idle(timeout=5)
    assert events == ["session-a.wav", "session-b.wav"]
    assert activity["max_active"] == 1
