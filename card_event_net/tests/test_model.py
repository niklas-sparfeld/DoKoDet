from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
import torch

from cardevent.config import load_config
from cardevent.infer import load_checkpoint
from cardevent.model import CardEventNet, backbone_is_frozen, freeze_backbone, unfreeze_backbone


def test_model_returns_one_logit_per_clip_and_backpropagates() -> None:
    model = CardEventNet(pretrained=False)
    clips = torch.randn(2, 8, 3, 224, 224)

    logits = model(clips)
    logits.mean().backward()

    assert tuple(logits.shape) == (2,)
    assert any(parameter.grad is not None for parameter in model.temporal_head.parameters())
    assert any(parameter.grad is not None for parameter in model.classifier.parameters())


def test_backbone_can_be_frozen_and_unfrozen() -> None:
    model = CardEventNet(pretrained=False)

    freeze_backbone(model)
    assert backbone_is_frozen(model)
    assert all(parameter.requires_grad for parameter in model.temporal_head.parameters())

    unfreeze_backbone(model)
    assert not backbone_is_frozen(model)


def test_full_clip_v2_returns_one_logit_and_uses_every_projected_frame() -> None:
    model = CardEventNet(
        pretrained=False,
        feature_dim=4,
        temporal_hidden_1=3,
        temporal_hidden_2=2,
        dropout=0.0,
        temporal_head="full_clip_v2",
    )
    with torch.no_grad():
        for parameter in model.temporal_head.parameters():
            parameter.fill_(1.0)
        model.classifier.weight.fill_(1.0)
        model.classifier.bias.zero_()
    projected = torch.ones((1, 8, 4), requires_grad=True)

    logits = model.classify_projected_features(projected)
    logits.sum().backward()

    assert tuple(logits.shape) == (1,)
    assert torch.all(projected.grad != 0)


def test_padded_tail_v1_retains_its_temporal_parameter_shapes() -> None:
    model = CardEventNet(pretrained=False, temporal_head="padded_tail_v1")
    state = model.state_dict()

    assert tuple(state["temporal_head.0.weight"].shape) == (64, 128, 3)
    assert tuple(state["temporal_head.2.weight"].shape) == (32, 64, 3)


@pytest.mark.parametrize("temporal_head", ("padded_tail_v1", "full_clip_v2"))
def test_checkpoint_reconstructs_both_temporal_heads(tmp_path: Path, temporal_head: str) -> None:
    config = load_config(Path(__file__).parents[1] / "configs" / "base.yaml")
    config = replace(
        config,
        model=replace(config.model, pretrained=False, temporal_head=temporal_head),
    )
    checkpoint_config = config.to_dict()
    if temporal_head == "padded_tail_v1":
        del checkpoint_config["model"]["temporal_head"]
    model = CardEventNet(
        pretrained=False,
        temporal_head=temporal_head,
    )
    checkpoint_path = tmp_path / f"{temporal_head}.pt"
    torch.save({"config": checkpoint_config, "model_state": model.state_dict()}, checkpoint_path)

    loaded = load_checkpoint(checkpoint_path, device_override="cpu")

    assert loaded.config.model.temporal_head == temporal_head
    assert loaded.model.temporal_head_name == temporal_head
