from __future__ import annotations

from pathlib import Path

from dokodetector_backend.recording_event_corpus_rollout import (
    _event_version_keys,
    _output_parent_report,
)


def test_output_parent_mapping_requires_unique_legacy_identity_and_digest() -> None:
    snapshot = {
        "recordings": [
            {
                "recording_id": "recording-a",
                "event_nodes": [
                    {
                        "node_id": "event-set-a",
                        "revisions": [
                            {
                                "node_id": "event-set-a",
                                "revision_id": "version-a",
                                "legacy_revision_id": "old-a",
                                "content_sha256": "digest-a",
                            },
                            {
                                "node_id": "event-set-a",
                                "revision_id": "version-b",
                                "legacy_revision_id": "old-unique",
                                "content_sha256": "digest-b",
                            },
                            {
                                "node_id": "event-set-b",
                                "revision_id": "version-c",
                                "legacy_revision_id": "old-duplicate",
                                "content_sha256": "digest-c",
                            },
                            {
                                "node_id": "event-set-c",
                                "revision_id": "version-d",
                                "legacy_revision_id": "old-duplicate",
                                "content_sha256": "digest-d",
                            },
                        ],
                    }
                ],
            }
        ],
        "visible_card_outputs": [
            {
                "recording_id": "recording-a",
                "node_id": "output-a",
                "revision_id": "output-version",
                "file_sha256": "output-digest",
                "event_revision_id": "old-a",
            },
            {
                "recording_id": "recording-a",
                "node_id": "output-ambiguous",
                "revision_id": "output-version",
                "file_sha256": "output-digest",
                "event_revision_id": "old-duplicate",
            },
            {
                "recording_id": "recording-a",
                "node_id": "output-b",
                "revision_id": "output-version",
                "file_sha256": "output-digest",
                "event_revision_id": "absent",
            },
        ],
    }
    conversion = {
        "recordings": [
            {
                "recording_id": "recording-a",
                "converted_versions": [
                    {
                        "node_id": "event-set-a",
                        "revision_id": "version-a",
                        "content_sha256": "digest-a",
                    },
                    {
                        "node_id": "event-set-a",
                        "revision_id": "version-b",
                        "content_sha256": "digest-b",
                    },
                    {
                        "node_id": "event-set-b",
                        "revision_id": "version-c",
                        "content_sha256": "digest-c",
                    },
                    {
                        "node_id": "event-set-c",
                        "revision_id": "version-d",
                        "content_sha256": "digest-d",
                    },
                ],
            }
        ]
    }

    report = _output_parent_report(snapshot, conversion)

    assert report["mapped"][0]["match"] == "unique-provenance-digest"
    assert report["mapped"][0]["converted_parent"] == {
        "set_id": "event-set-a",
        "version": "version-a",
        "content_sha256": "digest-a",
    }
    assert report["exceptions"] == [
        {
            "recording_id": "recording-a",
            "output_node_id": "output-ambiguous",
            "output_revision_id": "output-version",
            "output_sha256": "output-digest",
            "legacy_event_revision_id": "old-duplicate",
            "reason": "ambiguous",
            "candidate_count": 2,
        },
        {
            "recording_id": "recording-a",
            "output_node_id": "output-b",
            "output_revision_id": "output-version",
            "output_sha256": "output-digest",
            "legacy_event_revision_id": "absent",
            "reason": "missing",
            "candidate_count": 0,
        },
    ]


def test_event_version_keys_name_recording_set_and_version(tmp_path: Path) -> None:
    metadata = (
        tmp_path
        / "recording-a"
        / "event-sets"
        / "set-a"
        / "versions"
        / "version-a"
        / "event-set.json"
    )
    metadata.parent.mkdir(parents=True)
    metadata.write_text("{}")

    assert _event_version_keys(tmp_path) == {"recording-a/set-a@version-a"}
