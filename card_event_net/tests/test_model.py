from __future__ import annotations

import torch

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
