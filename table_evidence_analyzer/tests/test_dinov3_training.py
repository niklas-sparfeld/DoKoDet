from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from table_evidence_analyzer.data import build_smoke_fixture
from table_evidence_analyzer.dinov3_training import (
    DINOV3_CHECKPOINT_SCHEMA,
    DINOV3_TASK_ADAPTER,
    DinoV3FrozenLinearTask,
    DinoV3TrainConfig,
    DinoV3TrainingInterrupted,
    load_dinov3_checkpoint,
    train_dinov3_identity,
)
from table_evidence_analyzer.local_identity import (
    DINOV3_LICENSE_ID,
    build_dinov3_identity_config,
    materialize_dinov3_weights,
)

torch = pytest.importorskip("torch")


def _identity_config(root: Path):
    weights_root = root / "weights"
    weights_root.mkdir()
    (weights_root / "config.json").write_text(
        json.dumps({"model_type": "dinov3", "hidden_size": 4}), encoding="utf-8"
    )
    (weights_root / "preprocessor_config.json").write_text(
        json.dumps({"do_resize": True, "size": {"height": 224, "width": 224}}), encoding="utf-8"
    )
    weight_bytes = b"generated local DINOv3 training double"
    (weights_root / "model.safetensors").write_bytes(weight_bytes)
    weights = materialize_dinov3_weights(
        weights_root,
        model_revision="revision-abc123",
        license_record={
            "license_id": DINOV3_LICENSE_ID,
            "name": "DINOv3 License",
            "version": "2025-08-19",
            "url": "https://github.com/facebookresearch/dinov3/blob/main/LICENSE.md",
            "accepted": True,
            "accepted_at_utc": "2026-09-01T12:00:00Z",
        },
    )
    return build_dinov3_identity_config(
        weights,
        license_record={
            "license_id": DINOV3_LICENSE_ID,
            "name": "DINOv3 License",
            "version": "2025-08-19",
            "url": "https://github.com/facebookresearch/dinov3/blob/main/LICENSE.md",
            "accepted": True,
            "accepted_at_utc": "2026-09-01T12:00:00Z",
        },
    )


class _FakeEncoder(torch.nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.config = SimpleNamespace(hidden_size=4)

    def forward(self, *, pixel_values):
        pooled = pixel_values.mean(dim=(2, 3))
        return SimpleNamespace(pooler_output=torch.cat((pooled, pooled[:, :1]), dim=1))


def _factory(_identity):
    return _FakeEncoder()


def _config(fixture, identity, output, **overrides):
    values = {
        "dataset": fixture.dataset_path,
        "split": fixture.split_path,
        "artifacts": fixture.artifact_index_path,
        "identity_config": identity,
        "output": output,
        "seed": 17,
        "epochs": 12,
        "batch_size": 1,
        "learning_rate": 0.5,
    }
    values.update(overrides)
    return DinoV3TrainConfig(**values)


def test_task_freezes_encoder_and_exposes_only_linear_head() -> None:
    encoder = _FakeEncoder()
    task = DinoV3FrozenLinearTask(encoder)

    assert all(not parameter.requires_grad for parameter in encoder.parameters())
    assert task.head.weight.shape == (24, 4)
    assert sum(parameter.numel() for parameter in task.trainable_parameters()) == 24 * 4 + 24


def test_generated_cpu_training_overfits_and_writes_loadable_checkpoint(tmp_path: Path) -> None:
    fixture = build_smoke_fixture(tmp_path / "fixture")
    identity = _identity_config(tmp_path)
    output = tmp_path / "run"

    train_dinov3_identity(_config(fixture, identity, output), encoder_factory=_factory)

    run = json.loads((output / "run.json").read_text(encoding="utf-8"))
    checkpoint = load_dinov3_checkpoint(output / "checkpoint-last.pt")
    assert run["status"] == "completed"
    assert run["quality_state"] == "unusable_smoke_artifact"
    assert run["model"]["adapter"] == DINOV3_TASK_ADAPTER
    assert run["inputs"]["identity_digest"] == identity.identity_digest
    assert run["metrics"]["train_top_1_accuracy"] == 1.0
    assert checkpoint["schema_version"] == DINOV3_CHECKPOINT_SCHEMA
    assert checkpoint["progress"]["step"] == run["progress"]["step"]
    assert checkpoint["model_state"]["head.weight"].shape == (24, 4)
    assert (output / "predictions-train.json").exists()


def test_interrupted_training_resumes_from_frozen_inputs_and_same_progress(tmp_path: Path) -> None:
    fixture = build_smoke_fixture(tmp_path / "fixture")
    identity = _identity_config(tmp_path)
    interrupted_output = tmp_path / "interrupted"

    with pytest.raises(DinoV3TrainingInterrupted):
        train_dinov3_identity(
            _config(fixture, identity, interrupted_output, max_steps=1),
            encoder_factory=_factory,
        )

    interrupted = json.loads((interrupted_output / "run.json").read_text(encoding="utf-8"))
    assert interrupted["status"] == "interrupted"
    assert interrupted["inputs"]["identity_digest"] == identity.identity_digest

    train_dinov3_identity(
        _config(
            fixture,
            identity,
            interrupted_output,
            resume=interrupted_output / "checkpoint-last.pt",
        ),
        encoder_factory=_factory,
    )
    resumed = json.loads((interrupted_output / "run.json").read_text(encoding="utf-8"))

    uninterrupted_output = tmp_path / "uninterrupted"
    train_dinov3_identity(
        _config(fixture, identity, uninterrupted_output), encoder_factory=_factory
    )
    uninterrupted = json.loads((uninterrupted_output / "run.json").read_text(encoding="utf-8"))
    assert resumed["status"] == "completed"
    assert resumed["progress"] == uninterrupted["progress"]
    assert resumed["metrics"]["train_top_1_accuracy"] == 1.0
    assert resumed["inputs"] == uninterrupted["inputs"]


def test_training_failure_writes_complete_failure_record(tmp_path: Path) -> None:
    fixture = build_smoke_fixture(tmp_path / "fixture")
    identity = _identity_config(tmp_path)
    output = tmp_path / "failed"

    def failing_factory(_identity):
        raise RuntimeError("generated encoder failure")

    with pytest.raises(RuntimeError, match="generated encoder failure"):
        train_dinov3_identity(_config(fixture, identity, output), encoder_factory=failing_factory)

    run = json.loads((output / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "failed"
    assert run["error"] == {
        "type": "RuntimeError",
        "message": "generated encoder failure",
    }
    assert run["inputs"]["identity_digest"] == identity.identity_digest
    assert run["license"]["license_id"] == DINOV3_LICENSE_ID


@pytest.mark.skipif(not torch.backends.mps.is_available(), reason="MPS is not available")
def test_generated_mps_smoke_writes_checkpoint(tmp_path: Path) -> None:
    fixture = build_smoke_fixture(tmp_path / "fixture")
    identity = _identity_config(tmp_path)
    output = tmp_path / "mps-run"

    train_dinov3_identity(
        _config(fixture, identity, output, device="mps", epochs=2), encoder_factory=_factory
    )

    run = json.loads((output / "run.json").read_text(encoding="utf-8"))
    assert run["device"] == "mps"
    assert load_dinov3_checkpoint(output / "checkpoint-last.pt")["progress"]["step"] > 0


def test_checkpoint_loader_rejects_non_checkpoint(tmp_path: Path) -> None:
    path = tmp_path / "not-a-checkpoint.pt"
    path.write_bytes(hashlib.sha256(b"not a checkpoint").digest())

    with pytest.raises(ValueError, match="checkpoint"):
        load_dinov3_checkpoint(path)
