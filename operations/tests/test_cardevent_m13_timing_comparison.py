from __future__ import annotations

from doko_operations.cardevent_m13 import evaluate_cardeventnet_m13_gates


def _metrics(
    *,
    stable_end_matches: int = 60,
    confirmed_no_event_triggers: int = 20,
    duplicate_detections: int = 32,
    emission_p95_s: float = 0.75,
    event_presence_recall: float = 0.98,
) -> dict[str, object]:
    return {
        "event_diagnostics": {
            "stable_end_matches": stable_end_matches,
            "confirmed_no_event_triggers": confirmed_no_event_triggers,
            "duplicate_detections_per_reviewed_change": duplicate_detections,
        },
        "event_presence": {"recall": event_presence_recall},
        "causal_emission_delay_s": {"p95": emission_p95_s},
    }


def test_m13_gates_pass_at_declared_boundaries() -> None:
    gates = evaluate_cardeventnet_m13_gates(_metrics())

    assert all(item["passed"] for item in gates.values())


def test_m13_reports_each_failed_gate_without_relaxing_the_contract() -> None:
    gates = evaluate_cardeventnet_m13_gates(
        _metrics(
            stable_end_matches=54,
            duplicate_detections=35,
            event_presence_recall=0.867741935483871,
        )
    )

    assert gates["stable_end_matches"]["passed"] is False
    assert gates["duplicate_detections_per_reviewed_change"]["passed"] is False
    assert gates["event_presence_recall"]["passed"] is False
    assert gates["confirmed_no_event_triggers"]["passed"] is True
    assert gates["causal_emission_delay_p95_s"]["passed"] is True
