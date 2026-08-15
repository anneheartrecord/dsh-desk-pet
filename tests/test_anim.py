"""Timelines and motion. Pure logic, so these assert the *feel*, not the plumbing."""

from __future__ import annotations

import unittest

from dsh_desk_pet.anim import (
    LEAN_MAX_PX,
    Timeline,
    auto_timeline,
    breath_offset,
    lean_offset,
    motion_for,
    sequence_frames,
)


class TimelineTests(unittest.TestCase):
    def test_holds_each_frame_for_its_own_duration(self) -> None:
        tl = Timeline(((0, 100), (1, 50)))
        self.assertEqual(tl.total_ms, 150)
        self.assertEqual(tl.frame_at(0), 0)
        self.assertEqual(tl.frame_at(99), 0)
        self.assertEqual(tl.frame_at(100), 1)
        self.assertEqual(tl.frame_at(149), 1)

    def test_loops_forever(self) -> None:
        tl = Timeline(((0, 100), (1, 50)))
        self.assertEqual(tl.frame_at(150), 0)
        far = tl.total_ms * 6_667
        self.assertEqual(tl.frame_at(far + 20), 0)
        self.assertEqual(tl.frame_at(far + 120), 1)

    def test_empty_timeline_is_safe(self) -> None:
        self.assertEqual(Timeline(()).frame_at(500), 0)
        self.assertEqual(Timeline(()).total_ms, 0)


class AutoTimelineTests(unittest.TestCase):
    def test_single_frame_state_still_has_a_timeline(self) -> None:
        tl = auto_timeline("working", 1)
        self.assertEqual(tl.frame_at(0), 0)
        self.assertEqual(tl.frame_at(99_999), 0)

    def test_two_frame_idle_is_mostly_open_eyed(self) -> None:
        """A blink is rare and quick — uniform timing would look like a strobe."""

        tl = auto_timeline("idle", 2)
        samples = sequence_frames(tl, step_ms=10, span_ms=tl.total_ms)
        closed = samples.count(1)
        self.assertGreater(len(samples), 0)
        self.assertLess(closed / len(samples), 0.15, "eyes are shut too much of the cycle")
        self.assertGreater(closed, 0, "never blinks")

    def test_two_frame_idle_blinks_more_than_once_per_cycle(self) -> None:
        tl = auto_timeline("idle", 2)
        samples = sequence_frames(tl, step_ms=10, span_ms=tl.total_ms)
        transitions = sum(1 for a, b in zip(samples, samples[1:]) if a == 0 and b == 1)
        self.assertGreaterEqual(transitions, 2, "expected a double blink")

    def test_three_frame_idle_passes_through_the_half_lid_both_ways(self) -> None:
        """A blink that cuts straight to shut reads as a glitch, not an eyelid."""

        tl = auto_timeline("idle", 3)
        samples = sequence_frames(tl, step_ms=10, span_ms=tl.total_ms)
        runs = [f for f, _ in ((s, None) for s in samples)]
        collapsed = [k for k, _ in zip(runs, runs[1:] + [None]) if k is not _]
        # Every transition into or out of the shut frame goes via frame 2.
        for before, current, after in zip(collapsed, collapsed[1:], collapsed[2:]):
            if current == 1:
                self.assertEqual(before, 2, "eyes snapped shut without the half-lid")
                self.assertEqual(after, 2, "eyes snapped open without the half-lid")

    def test_three_frame_idle_still_spends_most_time_open(self) -> None:
        tl = auto_timeline("idle", 3)
        samples = sequence_frames(tl, step_ms=10, span_ms=tl.total_ms)
        self.assertGreater(samples.count(0) / len(samples), 0.75)

    def test_every_state_cycles_through_all_of_its_frames(self) -> None:
        for state in ("idle", "working", "waiting", "error", "happy", "sleeping"):
            for count in (2, 3, 5):
                tl = auto_timeline(state, count)
                seen = set(sequence_frames(tl, step_ms=10, span_ms=tl.total_ms))
                self.assertEqual(
                    seen, set(range(count)), f"{state} with {count} frames skipped {set(range(count)) - seen}"
                )

    def test_zero_frames_does_not_explode(self) -> None:
        self.assertEqual(auto_timeline("idle", 0).total_ms, 0)

    def test_tempo_matches_the_mood(self) -> None:
        """A loop's speed carries as much of the state as its drawings do."""

        cycles = {state: auto_timeline(state, 3).total_ms for state in ("happy", "working", "sleeping")}
        self.assertLess(cycles["happy"], cycles["working"])
        self.assertLess(cycles["working"], cycles["sleeping"])

    def test_sleeping_does_not_flutter(self) -> None:
        tl = auto_timeline("sleeping", 3)
        self.assertGreater(min(ms for _f, ms in tl.steps), 900)


class MotionTests(unittest.TestCase):
    def test_breath_moves_and_returns(self) -> None:
        """A single-frame state is carried entirely by this, so it must move."""

        offsets = [breath_offset("working", t) for t in range(0, 1100, 25)]
        self.assertGreater(max(offsets) - min(offsets), 1.0)
        self.assertAlmostEqual(breath_offset("working", 0), 0.0, places=6)

    def test_states_breathe_at_their_own_tempo(self) -> None:
        excited = [breath_offset("happy", t) for t in range(0, 2000, 20)]
        drowsy = [breath_offset("sleeping", t) for t in range(0, 2000, 20)]
        crossings = lambda xs: sum(1 for a, b in zip(xs, xs[1:]) if a <= 0 < b)
        self.assertGreater(crossings(excited), crossings(drowsy))

    def test_lean_is_clamped_and_signed(self) -> None:
        self.assertEqual(lean_offset(None, 100), 0.0)
        self.assertLessEqual(lean_offset(99_999, 100), LEAN_MAX_PX)
        self.assertGreaterEqual(lean_offset(-99_999, 100), -LEAN_MAX_PX)
        self.assertGreater(lean_offset(200, 100), 0)
        self.assertLess(lean_offset(-200, 100), 0)

    def test_hop_only_applies_while_it_is_running(self) -> None:
        during = motion_for("idle", 0, hop_until_ms=500, now_ms=100)
        after = motion_for("idle", 0, hop_until_ms=500, now_ms=900)
        self.assertNotEqual(during.hop, 0.0)
        self.assertEqual(after.hop, 0.0)

    def test_hop_lifts_the_pet(self) -> None:
        """Screen coordinates grow downward, so a hop has to be negative."""

        during = motion_for("idle", 0, hop_until_ms=520, now_ms=260)
        self.assertLess(during.hop, 0.0)


if __name__ == "__main__":
    unittest.main()
