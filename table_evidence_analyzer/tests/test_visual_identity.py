from __future__ import annotations

import pytest

from table_evidence_analyzer.card_classification import CardClassificationResult
from table_evidence_analyzer.pipeline_data import (
    PipelineDataError,
    VisualIdentityData,
    canonical_visual_identity_data_bytes,
    parse_visual_identity_data_bytes,
)
from table_evidence_analyzer.table_observation import IdentityCandidate
from table_evidence_analyzer.visual_identity import (
    CardIdentityClassifierProvider,
    VisualIdentityRequest,
)


def _frame() -> dict[str, object]:
    return {
        "schema_version": "exact-event/v1",
        "source_video_sha256": "a" * 64,
        "requested_time_us": 500_000,
        "frame_index": 1,
        "presentation_timestamp_us": 500_000,
        "width": 64,
        "height": 64,
        "decoder_version": "ffmpeg/test",
        "transform_version": "ffmpeg-mjpeg/test",
        "output_encoding": "jpeg",
        "content_type": "image/jpeg",
        "image_sha256": "b" * 64,
        "policy": "exact-event/v1",
    }


def _crop() -> dict[str, object]:
    return {
        "schema_version": "visible-region-crop/v1",
        "status": "usable",
        "frame_identity": _frame(),
        "geometry": {
            "kind": "detector-box/v1",
            "box_2d": {"x_min": 100, "y_min": 200, "x_max": 700, "y_max": 800},
        },
        "pixel_bounds": {"x_min": 6, "y_min": 12, "x_max": 45, "y_max": 52},
        "crop_policy": "raw_rectangular",
        "output_encoding": "ppm",
        "content_type": "image/x-portable-pixmap",
        "decoder_version": "ffmpeg/test",
        "transform_version": "pillow/test",
        "image_sha256": "c" * 64,
        "unusable_reason": None,
    }


def _content() -> dict[str, object]:
    return {
        "schema_version": "visual-identity-data/v1",
        "outcomes": [
            {
                "card_id": "run-1-card-0000",
                "frame_identity": _frame(),
                "geometry": _crop()["geometry"],
                "crop_identity": _crop(),
                "classifier": {
                    "provider": "local-dinov3",
                    "implementation": {
                        "name": "visual-identity-classifier-adapter",
                        "version": "v1",
                    },
                    "model": {"name": "dino-v3-bundle", "version": "dinov3-local-identity-v1"},
                },
                "status": "classified",
                "candidates": [
                    {
                        "identity": "CLUBS_NINE",
                        "score": 0.75,
                        "score_meaning": "probability",
                        "producer_id": "dino-v3-bundle.dinov3-local-identity-v1",
                    },
                    {
                        "identity": "SPADES_NINE",
                        "score": None,
                        "score_meaning": None,
                        "producer_id": "fixture-provider.v1",
                    },
                ],
                "unusable_reason": None,
                "error": None,
            }
        ],
    }


def test_visual_identity_data_preserves_lineage_order_and_optional_scores() -> None:
    content = VisualIdentityData.from_mapping(_content())
    raw = canonical_visual_identity_data_bytes(content)

    parsed = parse_visual_identity_data_bytes(raw)

    assert parsed == content
    assert [candidate.identity for candidate in parsed.outcomes[0].candidates] == [
        "CLUBS_NINE",
        "SPADES_NINE",
    ]
    assert parsed.outcomes[0].candidates[1].score is None
    assert raw == canonical_visual_identity_data_bytes(parsed)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value["outcomes"][0].update(status="unusable"),
        lambda value: value["outcomes"][0]["candidates"][0].update(score=0.5, score_meaning=None),
        lambda value: value["outcomes"][0]["candidates"][0].update(identity="UNKNOWN"),
        lambda value: value["outcomes"][0].update(unexpected=True),
    ],
)
def test_visual_identity_data_rejects_invalid_outcomes(mutate) -> None:
    value = _content()
    mutate(value)

    with pytest.raises(PipelineDataError):
        VisualIdentityData.from_mapping(value)


def test_visual_identity_data_rejects_classified_outcome_without_candidates() -> None:
    value = _content()
    value["outcomes"][0].update(candidates=[])

    with pytest.raises(PipelineDataError):
        VisualIdentityData.from_mapping(value)


class _Classifier:
    name = "fixture-identity"
    version = "fixture-identity-v1"
    calibration = "uncalibrated"

    def __init__(self) -> None:
        self.calls = 0

    def classify_ppm(self, crop_bytes: bytes) -> CardClassificationResult:
        self.calls += 1
        assert crop_bytes == b"crop"
        return CardClassificationResult(
            status="ok",
            candidates=(IdentityCandidate(card="CLUBS_NINE", probability=1.0),),
        )


def test_classifier_adapter_binds_provider_to_each_request() -> None:
    classifier = _Classifier()
    provider = CardIdentityClassifierProvider(classifier)

    result = provider.classify(
        VisualIdentityRequest(
            card_id="card-1",
            provider="fixture-identity",
            model="fixture-identity",
            crop_bytes=b"crop",
        )
    )

    assert result.candidates[0].card == "CLUBS_NINE"
    assert classifier.calls == 1
    with pytest.raises(PipelineDataError):
        VisualIdentityData.from_mapping(
            {
                **_content(),
                "outcomes": [{**_content()["outcomes"][0], "status": "failed"}],
            }
        )
