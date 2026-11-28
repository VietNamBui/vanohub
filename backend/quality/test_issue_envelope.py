from __future__ import annotations

from django.test import SimpleTestCase

from accounts.datetime_utils import PG_INT32_MAX

from .issue_envelope import (
    DISPUTE_WORD_RE,
    TAXONOMY_SEVERITY_FLOOR,
    decode_3d_position,
    infer_primary_category,
    parse_envelope,
    should_skip_preqc,
)


class IssueEnvelopeUnitTests(SimpleTestCase):
    def test_untyped_vanilla_cvat_issue_defaults_to_minor_non_blocking(self) -> None:
        env = parse_envelope("  Vehicle missing at edge of frame  ")
        self.assertFalse(env["typed"])
        self.assertEqual(env["code"], "")
        self.assertEqual(env["eff_code"], "")
        self.assertEqual(env["primary_category"], "")
        self.assertEqual(env["severity"], "minor")
        self.assertEqual(env["clean_message"], "Vehicle missing at edge of frame")
        self.assertIsNone(env["frames_span"])

    def test_typed_code_with_severity_floor_and_stripping(self) -> None:
        env = parse_envelope(
            "[E6][minor][REF:manual-1] Track ID swapped after occlusion [FRAMES:10-25] [PARAMS:foo=bar]"
        )
        self.assertTrue(env["typed"])
        self.assertEqual(env["code"], "E6")
        self.assertEqual(env["eff_code"], "E6")
        self.assertEqual(env["primary_category"], "E6")
        # Floor for E6 is major, so explicit [minor] is upgraded to major.
        self.assertEqual(env["severity"], TAXONOMY_SEVERITY_FLOOR["E6"])
        self.assertEqual(env["ref"], "manual-1")
        self.assertEqual(env["frames_span"], (10, 25))
        self.assertEqual(env["params"], {"foo": "bar"})
        self.assertEqual(env["clean_message"], "Track ID swapped after occlusion")

    def test_sub_code_param_overrides_effective_code_and_category(self) -> None:
        env = parse_envelope("[E3][minor][PARAMS:sub_code=EXI-MISS;note=1] Car skipped")
        self.assertEqual(env["code"], "E3")
        self.assertEqual(env["sub_code"], "EXI-MISS")
        self.assertEqual(env["eff_code"], "EXI-MISS")
        self.assertEqual(env["primary_category"], "E1")
        self.assertEqual(env["severity"], "major")

        env_crit = parse_envelope("[CLS-UNK][critical] Ambiguous heavy vehicle")
        self.assertEqual(env_crit["eff_code"], "CLS-UNK")
        self.assertEqual(env_crit["primary_category"], "E2")
        self.assertEqual(env_crit["severity"], "critical")

    def test_frames_tag_bounds(self) -> None:
        self.assertEqual(parse_envelope("[E1] Missing [FRAMES:0-100]")["frames_span"], (0, 100))
        self.assertIsNone(parse_envelope("[E1] Missing [FRAMES:50-10]")["frames_span"])
        too_big = PG_INT32_MAX + 1
        self.assertIsNone(parse_envelope(f"[E1] Missing [FRAMES:1-{too_big}]")["frames_span"])

    def test_infer_primary_category(self) -> None:
        cases = {
            "": "",
            "e1": "E1",
            "EXI-MISS": "E1",
            "BDD_MISSED": "E1",
            "CLS-UNK": "E2",
            "CLS-UNCL": "E2",
            "CLS-ATTR": "E5",
            "ATR-BLUR": "E5",
            "OCC-FULL": "E5",
            "DMS_OCC": "E5",
            "GEO-HDG": "E3",
            "BDD_BOX": "E3",
            "DMS_004": "E3",
            "EXI-DUP": "E4",
            "BDD_DUPLICATE": "E4",
            "TRK-ID": "E6",
            "DMS_001": "E6",
            "XYZ-99": "",
        }
        for code, expected in cases.items():
            with self.subTest(code=code):
                self.assertEqual(infer_primary_category(code), expected)

    def test_should_skip_preqc_variants(self) -> None:
        self.assertTrue(should_skip_preqc(parse_envelope("[E1][REF:preqc:12] Auto check")))
        self.assertTrue(should_skip_preqc(parse_envelope("[E1][REF:preqc_external:abc] Auto check")))
        self.assertTrue(should_skip_preqc(parse_envelope("[E1][REF:auto:rule1] Auto check")))
        self.assertTrue(should_skip_preqc(parse_envelope("[E1][REF:ext-1][PARAMS:tool=checker] Auto")))
        self.assertFalse(should_skip_preqc(parse_envelope("[E1][REF:ext-1] Manual")))
        self.assertFalse(should_skip_preqc(parse_envelope("[E1] Plain typed")))

    def test_dispute_word_regex(self) -> None:
        self.assertIsNotNone(DISPUTE_WORD_RE.search("[ADDRESSED] Disputed: class matches guideline"))
        self.assertIsNotNone(DISPUTE_WORD_RE.search("dispute label"))
        self.assertIsNone(DISPUTE_WORD_RE.search("[ADDRESSED] Fixed heading angle"))

    def test_decode_3d_position_bounds_and_invalid_inputs(self) -> None:
        # 2D box position
        clean, tid, sid = decode_3d_position([10, 20.5, 30, 40])
        self.assertEqual(clean, [10.0, 20.5, 30.0, 40.0])
        self.assertIsNone(tid)
        self.assertIsNone(sid)

        # Valid 3D position with track_id = 42 (+1 convention -> 43.0 in slot 10)
        pos_track = [0.0] * 16
        pos_track[10] = 43.0
        clean, tid, sid = decode_3d_position(pos_track)
        self.assertEqual(tid, 42)
        self.assertIsNone(sid)

        # Valid 3D position with shape_id = PG_INT32_MAX (+1 -> PG_INT32_MAX + 1)
        pos_shape = [0.0] * 16
        pos_shape[11] = float(PG_INT32_MAX + 1)
        _, tid, sid = decode_3d_position(pos_shape)
        self.assertIsNone(tid)
        self.assertEqual(sid, PG_INT32_MAX)

        # Value 1.0 -> iv = 0 (invalid <= 0) -> None
        pos_zero = [0.0] * 16
        pos_zero[10] = 1.0
        _, tid, sid = decode_3d_position(pos_zero)
        self.assertIsNone(tid)
        self.assertIsNone(sid)

        # Out-of-int32-range value -> None
        pos_overflow = [0.0] * 16
        pos_overflow[10] = float(PG_INT32_MAX + 2)
        _, tid, sid = decode_3d_position(pos_overflow)
        self.assertIsNone(tid)
        self.assertIsNone(sid)

        # Mutually exclusive slots 10 and 11 both set -> (clean, None, None)
        pos_both = [0.0] * 16
        pos_both[10] = 5.0
        pos_both[11] = 6.0
        _, tid, sid = decode_3d_position(pos_both)
        self.assertIsNone(tid)
        self.assertIsNone(sid)

        # Non-zero trailing slots 12..15 -> (clean, None, None)
        pos_nonzero_tail = [0.0] * 16
        pos_nonzero_tail[10] = 5.0
        pos_nonzero_tail[12] = 0.5
        _, tid, sid = decode_3d_position(pos_nonzero_tail)
        self.assertIsNone(tid)
        self.assertIsNone(sid)

        for bad in (
            None,
            [],
            [True, 1.0],
            ["1.0", 2.0],
            [float("nan"), 1.0],
            [float("inf"), 1.0],
            [float("-inf"), 1.0],
        ):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                decode_3d_position(bad)
