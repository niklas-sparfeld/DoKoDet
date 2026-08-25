from __future__ import annotations

from dataclasses import dataclass

from cardevent import viewer


@dataclass
class _FakeCV2:
    FONT_HERSHEY_SIMPLEX: int = 0
    LINE_AA: int = 1

    def __post_init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def putText(self, *args: object) -> None:
        self.calls.append(args)


def test_draw_overlay_uses_a_narrow_shadow_below_the_text(monkeypatch) -> None:
    fake_cv2 = _FakeCV2()
    monkeypatch.setattr(viewer, "_import_cv2", lambda: fake_cv2)

    frame = object()

    assert viewer.draw_overlay(frame, ["Review queue"]) is frame

    assert len(fake_cv2.calls) == 2
    shadow, text = fake_cv2.calls
    assert shadow[0:3] == (frame, "Review queue", (16, 29))
    assert shadow[5:7] == ((0, 0, 0), 1)
    assert text[0:3] == (frame, "Review queue", (16, 28))
    assert text[5:7] == ((255, 255, 255), 1)
