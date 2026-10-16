#!/usr/bin/env python3
"""Run the one frozen 0088 M9 real-plus-synthetic DINO identity fit."""

from __future__ import annotations

import argparse
import json
import random
import resource
import statistics
import time
from pathlib import Path

from table_evidence_analyzer.data import (
    LoadedCrop,
    MaterializedCropDataset,
    assert_valid_dataset,
    load_artifact_index,
    load_dataset_manifest,
    load_split_manifest,
)
from table_evidence_analyzer.dinov3_training import (
    DinoV3FrozenLinearTask,
    DinoV3TrainConfig,
    _batch_tensors,
    _epoch_schedule,
    _load_campaign_inputs,
    _predict,
    _resolve_identity,
    _torch_modules,
    load_dinov3_encoder,
)


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-root", type=Path, required=True)
    parser.add_argument("--synthetic-pool", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()

    root = args.campaign_root.expanduser().resolve()
    pool_root = args.synthetic_pool.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if output.exists() and any(output.iterdir()):
        raise SystemExit(f"M9 output directory is not empty: {output}")

    config = DinoV3TrainConfig(
        dataset=root / "data/dataset.json",
        split=root / "data/split.json",
        artifacts=root / "data/artifact-index.json",
        identity_config=root / "recipes/224-cls-mean-patch.json",
        weights_root=Path(
            "data/operations/dinov3-identity-bundles/0043-m1-dinov3-identity-75000a5eec53a52f088f9e6e"
        ),
        campaign_manifest=root / "manifest.json",
        output=output,
        seed=17,
        epochs=8,
        batch_size=1,
        learning_rate=0.001,
        weight_decay=0.0,
        encoder_training="frozen",
        device="mps",
        precision="fp32",
    )
    dataset = load_dataset_manifest(config.dataset)
    split = load_split_manifest(config.split)
    artifacts = load_artifact_index(config.artifacts)
    assert_valid_dataset(dataset, split=split, artifacts=artifacts)
    campaign, crop_cache = _load_campaign_inputs(config, dataset, split, artifacts)
    real_samples = tuple(MaterializedCropDataset(crop_cache, partition="train"))
    validation_samples = tuple(MaterializedCropDataset(crop_cache, partition="validation"))
    if len(real_samples) != 599:
        raise SystemExit(f"M6 real draw count changed: expected 599, found {len(real_samples)}")

    pool_manifest = _json(pool_root / "manifest.json")
    synthetic_samples = []
    for entry in pool_manifest["pool"]:
        crop_path = Path(entry["crop"]["path"])
        mask_path = Path(entry["visible_mask"]["path"])
        if not crop_path.is_absolute():
            crop_path = Path.cwd() / crop_path
        if not mask_path.is_absolute():
            mask_path = Path.cwd() / mask_path
        synthetic_samples.append(
            LoadedCrop(
                dataset_item_id=f"m8-synthetic:{entry['synthetic_id']}",
                crop_bytes=crop_path.read_bytes(),
                target=entry["label"],
                partition="train",
                source_frame_sha256=entry["source_frame_sha256"],
                visible_mask_bytes=mask_path.read_bytes(),
            )
        )
    if not synthetic_samples:
        raise SystemExit("M8 pool is empty; M9 must not train")

    identity = _resolve_identity(config)
    if args.preflight_only:
        print(
            json.dumps(
                {
                    "campaign_manifest_digest": campaign["manifest_digest"],
                    "identity_input_size": identity.input_size,
                    "identity_feature_layout": identity.recipe["feature_layout"],
                    "real_train_sample_count": len(real_samples),
                    "selection_sample_count": len(validation_samples),
                    "synthetic_pool_sample_count": len(synthetic_samples),
                    "synthetic_pool_manifest_digest": pool_manifest["manifest_digest"],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return
    torch, _ = _torch_modules()
    if not torch.backends.mps.is_available():
        raise SystemExit("M9 frozen recipe requires the declared MPS device")
    output.mkdir(parents=True, exist_ok=True)
    record = {
        "schema_version": "0088-m9-synthetic-fit/v1",
        "status": "running",
        "started_at_unix": time.time(),
        "campaign_manifest_digest": campaign["manifest_digest"],
        "synthetic_pool_manifest_digest": pool_manifest["manifest_digest"],
        "real_train_sample_count": len(real_samples),
        "synthetic_pool_sample_count": len(synthetic_samples),
        "recipe": {
            "input_size": 224,
            "feature_layout": "cls_mean_patch",
            "encoder_training": "frozen",
            "seed": 17,
            "epochs": 8,
            "batch_size": 1,
            "optimizer": "AdamW",
            "learning_rate": 0.001,
            "weight_decay": 0.0,
            "device": "mps",
            "precision": "fp32",
            "real_sampling_policy": "class_source_weighted_with_replacement",
            "real_samples_per_epoch": len(real_samples),
            "synthetic_draws_per_real_draw": 1,
            "pair_order": "real_then_synthetic",
        },
    }
    _write(output / "run.json", record)

    torch.manual_seed(17)
    random.seed(17)
    device = torch.device("mps")
    task = DinoV3FrozenLinearTask(
        load_dinov3_encoder(identity), feature_layout="cls_mean_patch", encoder_training="frozen"
    ).to(device)
    optimizer = torch.optim.AdamW(
        task.named_trainable_parameters()["head"], lr=0.001, weight_decay=0.0
    )
    steps_per_epoch = len(real_samples) * 2
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=steps_per_epoch * 8)
    started = time.monotonic()
    epoch_records = []
    best_selection_accuracy = -1.0
    best_epoch = 0
    best_validation_rows = []

    for epoch in range(8):
        real_schedule, receipt = _epoch_schedule(
            real_samples, seed=17, epoch=epoch, sample_count=len(real_samples)
        )
        synthetic_rng = random.Random(f"0088-m9-paired-synthetic-v1:17:{epoch}")
        synthetic_schedule = [synthetic_rng.choice(synthetic_samples) for _ in real_schedule]
        schedule = [
            sample
            for pair in zip(real_schedule, synthetic_schedule, strict=True)
            for sample in pair
        ]
        for sample in schedule:
            pixel_values, targets = _batch_tensors(
                [sample], train=True, epoch=epoch, seed=17, input_size=224
            )
            optimizer.zero_grad(set_to_none=True)
            loss = task.compute_loss(pixel_values.to(device), targets.to(device))
            if not torch.isfinite(loss):
                raise RuntimeError("M9 training produced a non-finite loss")
            loss.backward()
            optimizer.step()
            scheduler.step()
        train_rows, train_loss, train_accuracy = _predict(
            task, real_samples, device=device, seed=17, input_size=224
        )
        validation_rows, validation_loss, validation_accuracy = _predict(
            task, validation_samples, device=device, seed=17, input_size=224
        )
        if validation_accuracy > best_selection_accuracy:
            best_selection_accuracy = validation_accuracy
            best_epoch = epoch + 1
            best_validation_rows = validation_rows
            torch.save(task.state_dict(), output / "checkpoint-best.pt")
            _write(output / "predictions-selection.json", {"predictions": validation_rows})
        epoch_records.append(
            {
                "epoch": epoch + 1,
                "real_draws": len(real_schedule),
                "synthetic_draws": len(synthetic_schedule),
                "optimizer_steps": len(schedule),
                "real_schedule_digest": receipt["schedule_digest"],
                "train_loss": train_loss,
                "train_accuracy": train_accuracy,
                "selection_loss": validation_loss,
                "selection_accuracy": validation_accuracy,
            }
        )
        torch.save(task.state_dict(), output / "checkpoint-last.pt")
        record["epochs"] = epoch_records
        record["steps_completed"] = sum(item["optimizer_steps"] for item in epoch_records)
        _write(output / "run.json", record)

    task.load_state_dict(
        torch.load(output / "checkpoint-best.pt", map_location="cpu", weights_only=True)
    )
    task.eval()
    latencies = []
    with torch.no_grad():
        for sample in validation_samples:
            tensor, _ = _batch_tensors([sample], train=False, epoch=0, seed=17, input_size=224)
            start = time.perf_counter()
            task.forward(tensor.to(device))
            torch.mps.synchronize()
            latencies.append((time.perf_counter() - start) * 1000)

    record.update(
        {
            "status": "completed",
            "completed_at_unix": time.time(),
            "epochs": epoch_records,
            "best_selection_epoch": best_epoch,
            "best_selection_accuracy": best_selection_accuracy,
            "best_selection_prediction_count": len(best_validation_rows),
            "steps_completed": sum(item["optimizer_steps"] for item in epoch_records),
            "duration_seconds": round(time.monotonic() - started, 3),
            "max_rss_mb": round(
                resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024 / 1024, 3
            ),
            "selection_inference_mean_ms": round(statistics.mean(latencies), 3),
            "selection_inference_p95_ms": round(
                sorted(latencies)[int(len(latencies) * 0.95) - 1], 3
            ),
        }
    )
    _write(output / "run.json", record)


if __name__ == "__main__":
    _main()
