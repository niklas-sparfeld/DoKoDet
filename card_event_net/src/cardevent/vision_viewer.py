"""Small local OpenCV viewer for table-observation review."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

from .video import _import_cv2
from .vision_annotation import (
    ACTIVE_AREA_CLASSES,
    MOVEMENT_STATES,
    OCCLUSION_STATES,
    VISION_CARD_IDENTITIES,
    VISION_VISIBILITY_STATES,
    BoundingBox,
    FrameObservation,
    ObservedCard,
    TableObservationAnnotation,
)
from .vision_review import (
    TableObservationReview,
    VisionReviewError,
    build_table_observation_review,
    save_table_observation_review,
)


class VisionViewerError(RuntimeError):
    """Raised when the local visual review viewer cannot open its frames."""


def _parse_box(value: str) -> BoundingBox | None:
    if not value.strip():
        return None
    try:
        coordinates = [int(part.strip()) for part in value.split(",")]
    except ValueError as exc:
        raise VisionViewerError("A bbox needs four comma-separated integers.") from exc
    if len(coordinates) != 4:
        raise VisionViewerError("A bbox needs four comma-separated integers.")
    return BoundingBox(*coordinates)


def _parse_tags(value: str) -> tuple[str, ...]:
    return tuple(tag.strip() for tag in value.split(",") if tag.strip())


def _frame_path(frame_paths: Mapping[str, str | Path], frame_id: str) -> Path:
    try:
        path = Path(frame_paths[frame_id])
    except KeyError as exc:
        raise VisionViewerError(f"No frame was supplied for {frame_id}.") from exc
    if not path.is_file():
        raise VisionViewerError(f"Frame does not exist: {path}")
    return path


def _all_frame_ids(annotation: TableObservationAnnotation) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            observation.frame_id
            for card in annotation.observed_cards
            for observation in card.frame_observations
        )
    )


def _draw_card(
    frame: object, card: ObservedCard, observation: FrameObservation, *, label_y: int
) -> object:
    cv2 = _import_cv2()
    if observation.bbox is not None:
        box = observation.bbox
        colour = (0, 200, 0) if observation.usable_for_identity else (0, 165, 255)
        cv2.rectangle(frame, (box.x_min, box.y_min), (box.x_max, box.y_max), colour, 3)
    label = card.visual_card_identity or card.visibility
    if observation.tags:
        label += " [" + ", ".join(observation.tags) + "]"
    cv2.putText(
        frame,
        label,
        (16, label_y),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.75,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )
    return frame


@dataclass(slots=True)
class VisionAnnotationViewer:
    """Review all selected frames for one table-observation annotation."""

    annotation: TableObservationAnnotation
    frame_paths: Mapping[str, str | Path]
    snippet_path: str | Path | None = None
    window_name: str = "Table observation review"

    def _read(self, frame_id: str) -> object:
        cv2 = _import_cv2()
        frame = cv2.imread(str(_frame_path(self.frame_paths, frame_id)))
        if frame is None:
            raise VisionViewerError(f"OpenCV could not decode {frame_id}.")
        label_index = 0
        for card in self.annotation.observed_cards:
            for observation in card.frame_observations:
                if observation.frame_id == frame_id:
                    _draw_card(frame, card, observation, label_y=32 + 28 * label_index)
                    label_index += 1
        return frame

    def render_frame(self, frame_index: int) -> object:
        """Return one annotated frame without opening a window."""

        frame_ids = _all_frame_ids(self.annotation)
        if frame_index < 0 or frame_index >= len(frame_ids):
            raise VisionViewerError("Frame index is outside the annotation.")
        return self._read(frame_ids[frame_index])

    def run(
        self,
        *,
        reviewer: str,
        review_id: str | None = None,
        input_fn: Callable[[str], str] = input,
    ) -> TableObservationReview | None:
        """Show every frame and collect one confirm or reject decision."""

        frame_ids = _all_frame_ids(self.annotation)
        if not frame_ids:
            raise VisionViewerError("The annotation has no frame observations to review.")
        cv2 = _import_cv2()
        index = 0
        try:
            cv2.namedWindow(self.window_name, cv2.WINDOW_NORMAL)
            while True:
                cv2.imshow(self.window_name, self._read(frame_ids[index]))
                key = getattr(cv2, "waitKeyEx", cv2.waitKey)(0) & 0xFF
                if key in (ord("n"), ord(".")):
                    index = (index + 1) % len(frame_ids)
                elif key in (ord("p"), ord(",")):
                    index = (index - 1) % len(frame_ids)
                elif key == ord("s"):
                    self._show_snippet(cv2)
                elif key in (ord("q"), 27):
                    return None
                elif key == ord("r"):
                    return build_table_observation_review(
                        self.annotation,
                        reviewer=reviewer,
                        event_decision="reject_event",
                        review_id=review_id,
                    )
                elif key in (ord("y"), ord("a")):
                    return self._confirm(
                        reviewer=reviewer,
                        frame_id=frame_ids[index],
                        review_id=review_id,
                        input_fn=input_fn,
                    )
        except VisionReviewError:
            raise
        except (OSError, RuntimeError, ValueError) as exc:
            raise VisionViewerError(f"The visual review viewer failed: {exc}") from exc
        finally:
            cv2.destroyWindow(self.window_name)

    def _show_snippet(self, cv2: object) -> None:
        if self.snippet_path is None:
            return
        capture = cv2.VideoCapture(str(self.snippet_path))
        if not capture.isOpened():
            capture.release()
            raise VisionViewerError(f"Could not open video snippet: {self.snippet_path}")
        try:
            while True:
                ok, frame = capture.read()
                if not ok:
                    break
                cv2.imshow(self.window_name, frame)
                key = getattr(cv2, "waitKeyEx", cv2.waitKey)(30) & 0xFF
                if key in (ord("q"), 27, ord("s")):
                    break
        finally:
            capture.release()

    def _confirm(
        self,
        *,
        reviewer: str,
        frame_id: str,
        review_id: str | None,
        input_fn: Callable[[str], str],
    ) -> TableObservationReview:
        current_cards = list(self.annotation.observed_cards)
        count_value = input_fn(
            f"Visible card count (blank keeps {len(current_cards)}): "
        ).strip()
        count = len(current_cards) if not count_value else int(count_value)
        if count < 0:
            raise VisionViewerError("Visible card count must not be negative.")
        cards: list[ObservedCard] = []
        for card_index in range(count):
            existing = current_cards[card_index] if card_index < len(current_cards) else None
            identity_default = existing.visual_card_identity if existing else ""
            identity_value = input_fn(
                f"Card {card_index + 1} identity "
                f"({', '.join(VISION_CARD_IDENTITIES[:3])}, ...; blank unknown) "
                f"[{identity_default}]: "
            ).strip()
            identity = (
                None
                if identity_value.casefold() == "none"
                else identity_value or identity_default or None
            )
            visibility_default = existing.visibility if existing else "identifiable"
            visibility = input_fn(
                "Visibility (identifiable, card_not_visible, "
                f"visible_but_not_identifiable, ambiguous_card) [{visibility_default}]: "
            ).strip() or visibility_default
            if visibility not in VISION_VISIBILITY_STATES:
                raise VisionViewerError(f"Unknown visibility: {visibility}")
            existing_observation = next(
                (
                    observation
                    for observation in (existing.frame_observations if existing else ())
                    if observation.frame_id == frame_id
                ),
                None,
            )
            current_box = (
                existing_observation.bbox.to_value()
                if existing_observation and existing_observation.bbox
                else None
            )
            box_value = input_fn(
                f"Card {card_index + 1} bbox x1,y1,x2,y2 "
                f"(blank keeps {current_box or 'none'}): "
            )
            box = _parse_box(box_value) or (
                existing_observation.bbox if existing_observation else None
            )
            tags = _parse_tags(
                input_fn(f"Card {card_index + 1} tags comma-separated (blank clears): ")
            )
            newly_visible_default = "y" if existing and existing.became_newly_visible else "n"
            became_newly_visible = input_fn(
                f"Card {card_index + 1} became newly visible? [y/N] ({newly_visible_default}): "
            ).strip().casefold()
            if not became_newly_visible:
                became_newly_visible = newly_visible_default
            active_area_default = existing.active_area_class if existing else "none"
            active_area = input_fn(
                f"Card {card_index + 1} active area "
                f"({', '.join(sorted(ACTIVE_AREA_CLASSES))}) [{active_area_default}]: "
            ).strip() or active_area_default
            active_area = None if active_area == "none" else active_area
            tracklet_default = existing.card_tracklet_id if existing else "none"
            tracklet = input_fn(
                f"Card {card_index + 1} tracklet ID (blank keeps {tracklet_default}): "
            ).strip() or tracklet_default
            tracklet = None if tracklet == "none" else tracklet
            movement_default = existing.movement if existing else "unknown"
            movement = input_fn(
                f"Card {card_index + 1} movement "
                f"({', '.join(sorted(MOVEMENT_STATES))}) [{movement_default}]: "
            ).strip() or movement_default
            occlusion_default = existing.occlusion if existing else "unknown"
            occlusion = input_fn(
                f"Card {card_index + 1} occlusion "
                f"({', '.join(sorted(OCCLUSION_STATES))}) [{occlusion_default}]: "
            ).strip() or occlusion_default
            frame_observations = list(existing.frame_observations if existing else ())
            if existing_observation is None:
                frame_observations.append(
                    FrameObservation(
                        frame_id=frame_id,
                        bbox=box,
                        usable_for_identity=visibility == "identifiable",
                        tags=tags,
                    )
                )
            else:
                frame_observations[
                    next(
                        index
                        for index, observation in enumerate(frame_observations)
                        if observation.frame_id == frame_id
                    )
                ] = FrameObservation(
                    frame_id=frame_id,
                    bbox=box,
                    usable_for_identity=visibility == "identifiable",
                    tags=tags,
                )
            cards.append(
                ObservedCard(
                    observed_card_id=existing.observed_card_id
                    if existing
                    else f"observed-card-{card_index + 1}",
                    visual_card_identity=identity,
                    visibility=visibility,
                    frame_observations=tuple(frame_observations),
                    became_newly_visible=became_newly_visible in {"y", "yes"},
                    active_area_class=active_area,
                    card_tracklet_id=tracklet,
                    movement=movement,
                    occlusion=occlusion,
                )
            )
        return build_table_observation_review(
            self.annotation,
            reviewer=reviewer,
            event_decision="confirm_card_play",
            observed_cards=cards,
            review_id=review_id,
        )


def review_vision_annotation(
    annotation_path: str | Path,
    *,
    frames_dir: str | Path,
    review_path: str | Path,
    reviewer: str,
    review_id: str | None = None,
    snippet_path: str | Path | None = None,
) -> TableObservationReview | None:
    """Run the local viewer for one annotation and save its immutable review."""

    from .vision_annotation import load_vision_annotation

    annotation = load_vision_annotation(annotation_path)
    frames_root = Path(frames_dir)
    frame_ids = _all_frame_ids(annotation)
    frame_paths = {frame_id: frames_root / f"{frame_id}.jpg" for frame_id in frame_ids}
    viewer = VisionAnnotationViewer(annotation, frame_paths, snippet_path=snippet_path)
    review = viewer.run(reviewer=reviewer, review_id=review_id)
    if review is not None:
        save_table_observation_review(review, review_path)
    return review


__all__ = ["VisionAnnotationViewer", "VisionViewerError", "review_vision_annotation"]
