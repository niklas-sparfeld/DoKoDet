from __future__ import annotations

from typing import Any, Callable, Mapping

from .annotation import EVENT_TYPE_SHORTCUTS
from .evaluate import REVIEW_TIMELINE_DPI, plot_probability_axis
from .review_session import ReviewSession, ReviewSessionError
from .viewer import VideoViewer, format_timestamp


def _current_time(session: ReviewSession, viewer: VideoViewer) -> float:
    if session.current_frame_index is None:
        session.current_frame_index = session.frame_index_for(viewer.metadata.fps)
    return session.current_frame_index / viewer.metadata.fps


def _queue_candidate_time(item: Mapping[str, Any]) -> float:
    """Return the immutable queue candidate time for the timeline marker."""
    return float(item.get("original_timestamp_s", item["timestamp_s"]))


def _review_help() -> None:
    print()
    print("Review controls:")
    print("  P       pause or play")
    print("  A / D   seek backward or forward about 250 ms")
    print("  J / L   seek backward or forward about 2 s")
    print("  C       toggle before/after comparison")
    print("  , / .   select previous / next source annotation target")
    print("  1-7     select semantic event type")
    print("  N / B   next or previous queue item")
    print("  Y       add a new confirmed positive at the current frame")
    print("  E       confirm the selected existing annotation")
    print("  H       confirmed hard negative")
    print("  R       correct the selected annotation timestamp")
    print("  I       ignore this item")
    print("  U       clear the decision and return the item to unreviewed")
    print("  M       add or edit a review note")
    print("  Q       save and exit")
    print()


class TimelineRenderer:
    """Cache the static Matplotlib plot and update only review markers."""

    def __init__(self, stream: Mapping[str, Any], *, video_name: str = "") -> None:
        try:
            import matplotlib

            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            from matplotlib.backends.backend_agg import FigureCanvasAgg
        except ModuleNotFoundError as exc:
            raise ReviewSessionError("matplotlib is required for the review timeline.") from exc

        self.stream = stream
        self.figure, self.axis = plt.subplots(figsize=(10, 2.35), dpi=REVIEW_TIMELINE_DPI)
        plot_probability_axis(
            self.axis,
            times_s=stream.get("probability_times_s", ()),
            probabilities=stream.get("probabilities", ()),
            threshold=float(stream.get("threshold", 0.5)),
            ground_truth_events=stream.get("ground_truth_events", ()),
            predicted_events=stream.get("predicted_events", ()),
            comparison_times_s=stream.get("comparison_probability_times_s", ()),
            comparison_probabilities=stream.get("comparison_probabilities", ()),
            comparison_predicted_events=stream.get("comparison_predicted_events", ()),
            title=f"Timeline: {video_name}" if video_name else "Review timeline",
        )
        duration_s = float(stream.get("duration_s", 0.0))
        if duration_s > 0.0:
            self.axis.set_xlim(0.0, duration_s)
        self.axis.set_ylabel("score")
        self._candidate = self.axis.axvline(
            0.0, color="black", linewidth=1.3, alpha=0.8, label="queue candidate"
        )
        self._current = self.axis.axvline(
            0.0, color="magenta", linewidth=1.2, alpha=0.8, label="current position"
        )
        self._target = self.axis.axvline(
            0.0, color="tab:cyan", linewidth=1.5, alpha=0.9, label="selected annotation"
        )
        self.axis.legend(loc="upper right")
        self._canvas = FigureCanvasAgg(self.figure)
        self._canvas.draw()

    def render(
        self,
        *,
        candidate_time_s: float,
        current_time_s: float,
        target_time_s: float | None,
    ) -> Any:
        self._candidate.set_xdata((candidate_time_s, candidate_time_s))
        self._current.set_xdata((current_time_s, current_time_s))
        self._target.set_visible(target_time_s is not None)
        if target_time_s is not None:
            self._target.set_xdata((target_time_s, target_time_s))
        self._canvas.draw()
        import numpy as np

        rgba = np.asarray(self._canvas.buffer_rgba()).copy()
        return rgba[:, :, :3][:, :, ::-1]


def _item_lines(session: ReviewSession, viewer: VideoViewer, playing: bool) -> list[str]:
    item = session.current_item
    if item is None:
        return ["Review queue is complete.", "Press Q to exit."]
    selection = session.selection
    nearest = item.get("nearest_annotation")
    target = session.selected_annotation_target
    nearest_text = "none"
    if isinstance(nearest, dict):
        nearest_text = (
            f"{nearest.get('type', '?')} at {nearest.get('time_s', '?')}s "
            f"({item.get('distance_s', '?')}s away)"
        )
    current_time = (
        session.current_frame_index / viewer.metadata.fps
        if session.current_frame_index is not None
        else float(item["timestamp_s"])
    )
    target_text = "none"
    if target is not None:
        target_time = float(target["time_s"])
        target_text = (
            f"{target.get('type', '?')} at {target_time:.3f}s "
            f"(delta {current_time - target_time:+.3f}s, "
            f"abs {abs(current_time - target_time):.3f}s)"
        )
    lines = [
        f"Item {session.current_selection + 1} / {selection.selected_count} "
        f"(remaining {selection.remaining_count})",
        f"Video: {item['video']}  Time: {format_timestamp(current_time)}",
        f"Category: {item.get('category', '?')}  Score: {item.get('score', '?')}",
        f"Nearest annotation: {nearest_text}",
        f"Selected target: {target_text}",
        f"Selected type: {session.selected_event_type}  Outcome: {item['outcome']}",
        f"Status: {item['status']}  State: {'PLAY' if playing else 'PAUSE'}",
    ]
    if session.probability_stream_for(item) is None:
        lines.append("Timeline unavailable; regenerate the queue to include model evidence")
    return lines


def _ask_confirmation() -> bool:
    try:
        answer = input("Item is already reviewed. Change it? [y/N] ")
    except EOFError:
        return False
    return answer.strip().casefold() in {"y", "yes"}


def _ask_note() -> str | None:
    try:
        note = input("Review note (empty clears the note): ")
    except EOFError:
        return None
    return note or None


def _run_decision(
    session: ReviewSession,
    action: Callable[..., dict[str, Any]],
) -> bool:
    try:
        action()
    except ReviewSessionError as exc:
        if "already reviewed" not in str(exc) or not _ask_confirmation():
            print(f"Decision not applied: {exc}")
            return False
        try:
            action(confirm=True)
        except ReviewSessionError as retry_exc:
            print(f"Decision not applied: {retry_exc}")
            return False
    return True


def review_queue_interactively(
    session: ReviewSession,
    *,
    window_name: str = "CardEventNet review",
) -> None:
    """Run the queue review loop. The session owns all persistence and decisions."""
    _review_help()
    print(
        f"Selected {session.selection.selected_count} items; "
        f"reviewed {session.selection.reviewed_count}; "
        f"remaining {session.selection.remaining_count}."
    )
    if session.current_item is None:
        print("No queue items match the selected filters.")
        return

    viewer: VideoViewer | None = None
    opened_video: str | None = None
    playing = False
    compare_before_after = False
    timeline_renderers: dict[str, TimelineRenderer | None] = {}

    try:
        while session.current_item is not None:
            item = session.current_item
            if opened_video != item["video"]:
                if viewer is not None:
                    viewer.close()
                viewer = VideoViewer.open(
                    str(session.video_path_for(item)), window_name=window_name
                )
                opened_video = item["video"]
                session.current_frame_index = session.frame_index_for(viewer.metadata.fps, item)
                playing = False
            if viewer is None:
                break
            if session.current_frame_index is None:
                session.current_frame_index = session.frame_index_for(viewer.metadata.fps, item)
            current_time = session.current_frame_index / viewer.metadata.fps
            stream = session.probability_stream_for(item)
            timeline = None
            if stream is not None:
                if item["video"] not in timeline_renderers:
                    try:
                        timeline_renderers[item["video"]] = TimelineRenderer(
                            stream, video_name=item["video"]
                        )
                    except ReviewSessionError:
                        timeline_renderers[item["video"]] = None
                renderer = timeline_renderers[item["video"]]
                if renderer is not None:
                    target = session.selected_annotation_target
                    timeline = renderer.render(
                        candidate_time_s=_queue_candidate_time(item),
                        current_time_s=current_time,
                        target_time_s=(float(target["time_s"]) if target is not None else None),
                    )
            viewer.render(
                session.current_frame_index,
                _item_lines(session, viewer, playing),
                compare=compare_before_after,
                timeline=timeline,
            )
            delay_ms = max(1, int(round(1000.0 / viewer.metadata.fps))) if playing else 30
            key = viewer.wait_key(delay_ms)
            frame_changed = False

            if key is None:
                pass
            elif key in (ord("q"), ord("Q")):
                session.save()
                break
            elif key in (ord("p"), ord("P")):
                playing = not playing
            elif key in (
                ord("a"),
                ord("A"),
                ord("d"),
                ord("D"),
                ord("j"),
                ord("J"),
                ord("l"),
                ord("L"),
            ):
                steps = {
                    ord("a"): -0.25,
                    ord("A"): -0.25,
                    ord("d"): 0.25,
                    ord("D"): 0.25,
                    ord("j"): -2.0,
                    ord("J"): -2.0,
                    ord("l"): 2.0,
                    ord("L"): 2.0,
                }
                session.current_frame_index = max(
                    0,
                    min(
                        viewer.metadata.frame_count - 1,
                        session.current_frame_index + int(round(steps[key] * viewer.metadata.fps)),
                    ),
                )
                frame_changed = True
            elif key == ord("c") or key == ord("C"):
                compare_before_after = not compare_before_after
            elif key in (ord(","), ord(".")):
                if key == ord("."):
                    session.next_annotation_target()
                else:
                    session.previous_annotation_target()
            elif key in EVENT_TYPE_SHORTCUTS:
                session.set_event_type(EVENT_TYPE_SHORTCUTS[key])
            elif key in (ord("n"), ord("N")):
                session.next_item()
                frame_changed = True
            elif key in (ord("b"), ord("B")):
                session.previous_item()
                frame_changed = True
            elif key in (ord("y"), ord("Y")):
                current_time = _current_time(session, viewer)
                if _run_decision(
                    session,
                    lambda confirm=False, current_time=current_time: session.decide(
                        "confirmed_positive",
                        current_time_s=current_time,
                        event_type=session.selected_event_type,
                        positive_target="new_event",
                        confirm=confirm,
                    ),
                ):
                    session.advance_after_decision()
                    frame_changed = True
            elif key in (ord("e"), ord("E")):
                target = session.selected_annotation_target
                target_time = float(target["time_s"]) if target is not None else None
                if _run_decision(
                    session,
                    lambda confirm=False, target_time=target_time: session.decide(
                        "confirmed_positive",
                        positive_target="existing_annotation",
                        source_annotation_time_s=target_time,
                        confirm=confirm,
                    ),
                ):
                    session.advance_after_decision()
                    frame_changed = True
            elif key in (ord("h"), ord("H")):
                if _run_decision(
                    session,
                    lambda confirm=False: session.decide(
                        "confirmed_hard_negative", confirm=confirm
                    ),
                ):
                    session.advance_after_decision()
                    frame_changed = True
            elif key in (ord("r"), ord("R")):
                current_time = _current_time(session, viewer)
                target = session.selected_annotation_target
                target_time = float(target["time_s"]) if target is not None else None
                if _run_decision(
                    session,
                    lambda confirm=False, current_time=current_time, target_time=target_time: (
                        session.decide(
                            "annotation_timestamp_corrected",
                            current_time_s=current_time,
                            source_annotation_time_s=target_time,
                            confirm=confirm,
                        )
                    ),
                ):
                    session.advance_after_decision()
                    frame_changed = True
            elif key in (ord("i"), ord("I")):
                if _run_decision(
                    session, lambda confirm=False: session.decide("ignore", confirm=confirm)
                ):
                    session.advance_after_decision()
                    frame_changed = True
            elif key in (ord("u"), ord("U")):
                if _run_decision(session, session.clear_decision):
                    frame_changed = True
            elif key in (ord("m"), ord("M")):
                note = _ask_note()
                if _run_decision(
                    session,
                    lambda confirm=False, note=note: session.set_note(note, confirm=confirm),
                ):
                    frame_changed = True

            if session.current_item is None:
                break
            if opened_video != session.current_item["video"]:
                opened_video = None
            if playing and not frame_changed:
                if session.current_frame_index >= viewer.metadata.frame_count - 1:
                    playing = False
                else:
                    session.current_frame_index += 1
    finally:
        if viewer is not None:
            viewer.close()
        session.save()


__all__ = ["review_queue_interactively"]
