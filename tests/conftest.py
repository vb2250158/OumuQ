from __future__ import annotations

import pytest


ARCHIVED_CLOUD_API_TESTS = {
    "test_route_resolve_hot_switches_by_character_id_without_worker_submit",
    "test_qwen_tts_api_engine_routes_to_api_worker",
    "test_voice_clone_requests_are_listed",
    "test_voice_clone_enroll_dry_run_builds_dashscope_payload",
    "test_voice_clone_enroll_rejects_untrusted_endpoint",
    "test_voice_clone_request_path_must_stay_in_authorized_directory",
    "test_voice_clone_request_character_must_match_api_character",
    "test_qwen_voice_enrollment_rejects_audio_outside_voice_references",
    "test_voice_clone_enroll_writes_voice_id_to_registry",
    "test_qwen_voice_design_dry_run_uses_official_payload",
    "test_qwen_voice_design_saves_voice_and_redacted_preview",
    "test_voice_enrollment_persists_actual_overridden_models_for_later_routing",
    "test_skill_separates_local_audio_cloud_clone_and_github_publication",
}


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    marker = pytest.mark.skip(reason="paid cloud TTS API support archived; local models only")
    for item in items:
        if item.name in ARCHIVED_CLOUD_API_TESTS:
            item.add_marker(marker)
