import copy
import unittest

import numpy as np
from badminton.contact_features import build_contact_features as descriptors
from badminton.contact_features import match_bags, peaks, weak_targets


def fixture(times=None):
    times = np.arange(90) / 30 if times is None else np.asarray(times)
    video = {"id": "source", "sha256": "truth", "width": 1280, "height": 720}
    player = {
        "track_id": 1,
        "box": [300, 200, 400, 400],
        "keypoints": [[350, 280, 0.9] for _ in range(17)],
    }
    rows = [
        {
            "frame": i,
            "time_s": float(t),
            "players": [copy.deepcopy(player)],
            "calibration_valid": True,
        }
        for i, t in enumerate(times)
    ]
    prows = {
        "stage": "players",
        "video_id": "source",
        "video_sha256": "truth",
        "stride": 1,
        "frames": rows,
        "cut_frames": [],
    }
    srows = {
        "stage": "shuttle",
        "video_id": "source",
        "video_sha256": "truth",
        "frames": [
            {
                "frame": i,
                "time_s": float(t),
                "shuttle": {
                    "visible": True,
                    "x": 360 + i,
                    "y": 260.0,
                    "repaired": False,
                },
            }
            for i, t in enumerate(times)
        ],
        "cut_frames": [],
    }
    return video, prows, srows


class DescriptorTests(unittest.TestCase):
    def test_uncertain_source_contact_crossing_camera_is_not_supervised(self):
        labels = [{"id": "cue", "source_start_frame": 105, "kind": "shot"}]
        bags, negative = weak_targets(labels, np.arange(100, 131), cut_frames=[4])
        self.assertEqual(bags[0]["indices"], [])
        self.assertEqual(bags[0]["source_possible_indices"], list(range(1, 8)))
        self.assertTrue(bags[0]["source_context_blocked"])
        self.assertFalse(negative[:15].any())

    def test_unknown_scene_within_weak_interval_preserves_unavailable_reference(self):
        labels = [{"id": "cue", "source_start_frame": 105, "kind": "shot"}]
        bags, _ = weak_targets(labels, np.arange(100, 131), excluded_frames=[3])
        self.assertEqual(len(bags), 1)
        self.assertEqual(bags[0]["id"], "cue")
        self.assertTrue(bags[0]["source_context_blocked"])
        self.assertEqual(bags[0]["indices"], [])

    def test_interval_entirely_in_new_camera_keeps_weak_target(self):
        labels = [{"id": "cue", "source_start_frame": 105, "kind": "shot"}]
        bags, _ = weak_targets(labels, np.arange(100, 131), cut_frames=[1])
        self.assertEqual(bags[0]["indices"], list(range(1, 8)))
        self.assertFalse(bags[0]["source_context_blocked"])

    def test_velocity_lookback_is_in_reported_source_context(self):
        out = descriptors(*fixture())
        np.testing.assert_array_equal(out["context"][40], [33, 47])

    def test_excluded_velocity_lookback_blocks_window(self):
        v, p, s = fixture()
        # The first nominal sample for center40 is34, but its velocity reads33.
        p["frames"][33]["scene"] = "replay"
        out = descriptors(v, p, s)
        self.assertFalse(out["arm_mask"][40].any())
        self.assertTrue(out["arm_mask"][41].any())

    def test_unused_previous_point_does_not_expand_context(self):
        v, p, s = fixture()
        p["frames"][33]["scene"] = "replay"
        s["frames"][33]["shuttle"]["repaired"] = True
        out = descriptors(v, p, s)
        self.assertTrue(out["arm_mask"][40].any())
        np.testing.assert_array_equal(out["context"][40], [34, 47])

    def test_selection_lineage_and_its_exclusions_are_transitive(self):
        v, p, s = fixture()
        s["frames"][33]["shuttle"].update(
            selection_context_start_frame=20, selection_context_end_frame=34
        )
        out = descriptors(v, p, s)
        np.testing.assert_array_equal(out["context"][40], [20, 47])
        p["frames"][25]["scene"] = "unknown"
        self.assertFalse(descriptors(v, p, s)["arm_mask"][40].any())

    def test_invalid_selection_lineage_rejected(self):
        for start, end in ((-1, 34), (35, 36), (20, 100), ("20", 34)):
            v, p, s = fixture()
            s["frames"][33]["shuttle"].update(
                selection_context_start_frame=start, selection_context_end_frame=end
            )
            with self.assertRaisesRegex(ValueError, "selection lineage"):
                descriptors(v, p, s)

    def test_camera_reset_does_not_read_previous_view_for_velocity(self):
        v, p, s = fixture()
        p["cut_frames"] = [34]
        out = descriptors(v, p, s)
        self.assertTrue(out["arm_mask"][40].any())
        np.testing.assert_array_equal(out["context"][40], [34, 47])
        first = out["x"][40, 0].reshape(7, 18)[0]
        np.testing.assert_array_equal(first[-2:], [0, 0])

    def test_observations_unchanged_and_edges_invalid(self):
        value = fixture()
        before = copy.deepcopy(value)
        out = descriptors(*value)
        self.assertEqual(value, before)
        self.assertEqual(out["x"].shape, (90, 12, 126))
        self.assertEqual(int(out["arm_mask"].any(1).sum()), 78)
        self.assertTrue(np.isfinite(out["x"]).all())

    def test_cut_blocks_entire_source_context(self):
        v, p, s = fixture()
        p["cut_frames"] = [45]
        out = descriptors(v, p, s)
        self.assertFalse(out["arm_mask"][39:51].any())
        self.assertTrue(out["arm_mask"][38].any())
        self.assertTrue(out["arm_mask"][51].any())

    def test_scene_and_selected_history_exclusion(self):
        for source in ("scene", "selection"):
            v, p, s = fixture()
            if source == "scene":
                p["frames"][45]["scene"] = "replay"
            else:
                s["frames"][45]["shuttle"]["selection_context_excluded"] = True
            out = descriptors(v, p, s)
            self.assertFalse(out["arm_mask"][39:52].any())

    def test_missing_wrists_are_masks_not_coordinates(self):
        v, p, s = fixture()
        for row in p["frames"]:
            for index in (9, 10):
                row["players"][0]["keypoints"][index][2] = 0
        out = descriptors(v, p, s)
        self.assertFalse(out["arm_mask"].any())
        self.assertFalse(out["x"].any())

    def test_repaired_shuttle_cannot_be_observation(self):
        v, p, s = fixture()
        for row in s["frames"]:
            row["shuttle"]["repaired"] = True
        out = descriptors(v, p, s)
        windows = out["x"].reshape(90, 12, 7, 18)
        self.assertFalse(windows[..., 11:14].any())

    def test_source_mismatch_and_sparse_pose_rejected(self):
        for kind in ("hash", "time", "stride"):
            v, p, s = fixture()
            if kind == "hash":
                p["video_sha256"] = "wrong"
            elif kind == "time":
                p["frames"][45]["time_s"] += 0.01
            else:
                p["stride"] = 2
            with self.assertRaises(ValueError):
                descriptors(v, p, s)

    def test_long_source_time_gap_blocks_context(self):
        times = np.arange(90) / 30
        times[45:] += 1
        out = descriptors(*fixture(times))
        self.assertFalse(out["arm_mask"][44].any())
        self.assertFalse(out["arm_mask"][45].any())

    def test_input_player_order_does_not_change_features(self):
        v, p, s = fixture()
        for row in p["frames"]:
            second = copy.deepcopy(row["players"][0])
            second["track_id"] = 2
            row["players"].append(second)
        expected = descriptors(v, p, s)
        for row in p["frames"]:
            row["players"].reverse()
        actual = descriptors(v, p, s)
        np.testing.assert_array_equal(actual["x"], expected["x"])
        np.testing.assert_array_equal(actual["arm_ids"], expected["arm_ids"])

    def test_weak_labels_do_not_promote_source(self):
        labels = [
            {
                "id": "cue",
                "source_start_frame": 105,
                "kind": "shot",
                "training_ready": False,
                "contact_frame": None,
            }
        ]
        before = copy.deepcopy(labels)
        bags, negative = weak_targets(labels, np.arange(100, 131))
        self.assertEqual(labels, before)
        self.assertEqual(bags[0]["parent_bounds"], [101, 107])
        self.assertFalse(negative[:15].any())
        self.assertTrue(negative[15:].all())

    def test_matching_is_one_to_one_and_reassigns_overlap(self):
        bags = [{"indices": [5, 6]}, {"indices": [5]}]
        self.assertEqual(match_bags([5, 6], bags), 2)
        self.assertEqual(match_bags([5], bags), 1)
        self.assertEqual(match_bags([5, 6], bags[:1]), 1)

    def test_peaks_use_source_time_and_mask(self):
        values = np.array([0.8, 0.9, 0.8, 0.7])
        times = np.array([0.0, 0.01, 0.10, 0.30])
        self.assertEqual(
            peaks(values, times, np.array([1, 0, 1, 1], bool), 0.5), [0, 3]
        )


if __name__ == "__main__":
    unittest.main()
