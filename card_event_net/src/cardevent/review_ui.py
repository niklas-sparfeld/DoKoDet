from __future__ import annotations

from typing import Any, Callable

from .annotation import EVENT_TYPE_SHORTCUTS
from .review_session import ReviewSession, ReviewSessionError
from .viewer import VideoViewer, format_timestamp


def _current_time(session: ReviewSession, viewer: VideoViewer) -> float:
    if session.current_frame_index is None:
        session.current_frame_index = session.frame_index_for(viewer.metadata.fps)
    return session.current_frame_index / viewer.metadata.fps


def _review_help() -> None:
    print()
    print("Review controls:")
    print("  P       pause or play")
    print("  A / D   seek backward or forward about 250 ms")
    print("  J / L   seek backward or forward about 2 s")
    print("  C       toggle before/after comparison")
    print("  1-7     select semantic event type")
    print("  N / B   next or previous queue item")
    print("  Y       add a new confirmed positive at the current frame")
    print("  E       confirm the nearest existing annotation")
    print("  H       confirmed hard negative")
    print("  R       correct the nearest annotation timestamp")
    print("  I       ignore this item")
    print("  U       clear the decision and return the item to unreviewed")
    print("  M       add or edit a review note")
    print("  Q       save and exit")
    print()


def _item_lines(session: ReviewSession, viewer: VideoViewer, playing: bool) -> list[str]:
    item = session.current_item
    if item is None:
        return ["Review queue is complete.", "Press Q to exit."]
    selection = session.selection
    nearest = item.get("nearest_annotation")
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
    return [
        f"Item {session.current_selection + 1} / {selection.selected_count} "
        f"(remaining {selection.remaining_count})",
        f"Video: {item['video']}  Time: {format_timestamp(current_time)}",
        f"Category: {item.get('category', '?')}  Score: {item.get('score', '?')}",
        f"Nearest annotation: {nearest_text}",
        f"Selected type: {session.selected_event_type}  Outcome: {item['outcome']}",
        f"Status: {item['status']}  State: {'PLAY' if playing else 'PAUSE'}",
    ]


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
            viewer.render(
                session.current_frame_index,
                _item_lines(session, viewer, playing),
                compare=compare_before_after,
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
                if _run_decision(
                    session,
                    lambda confirm=False: session.decide(
                        "confirmed_positive", positive_target="existing_annotation", confirm=confirm
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
                if _run_decision(
                    session,
                    lambda confirm=False, current_time=current_time: session.decide(
                        "annotation_timestamp_corrected",
                        current_time_s=current_time,
                        confirm=confirm,
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
