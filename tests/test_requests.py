import unittest

from quizchirp.core import Gate


class Requests(unittest.TestCase):
    def setUp(self):
        self.gate = Gate(0.5, (4, 4))
        self.gate.enable(True)

    def burst(self, start):
        return [self.gate.click(40, 20, start + i / 10) for i in range(3)]

    def test_four_clicks_only_one_even_after_fast_response(self):
        a, b, req = self.burst(1)
        self.assertIsNone(a)
        self.assertIsNone(b)
        self.assertEqual(self.gate.finish(req, "C", 1.25), "C")
        self.assertIsNone(self.gate.click(40, 20, 1.3))

    def test_timeout_and_late_result(self):
        req = self.burst(1)[2]
        self.assertEqual(self.gate.finish(req, "C", req.deadline), "FAIL")
        next_req = self.burst(310)[2]
        self.assertIsNone(self.gate.finish(req, "A", 311))
        self.assertEqual(self.gate.finish(next_req, "B", 312), "B")

    def test_busy_burst_cannot_spill_into_next_question(self):
        req = self.burst(1)[2]
        self.assertIsNone(self.gate.click(40, 20, 3))
        self.gate.finish(req, "A", 3.05)
        self.assertIsNone(self.gate.click(40, 20, 3.1))
        self.assertIsNone(self.gate.click(40, 20, 3.2))
        self.assertIsNotNone(self.burst(4)[2])

    def test_shutdown_invalidates_every_request(self):
        req = self.burst(1)[2]
        self.gate.close()
        self.assertIsNone(self.gate.finish(req, "B", 2))
        self.assertEqual(self.burst(3), [None]*3)

    def test_position_and_time_reset_sequence(self):
        for x, t in [(1, 1), (1, 1.1), (100, 1.2), (100, 3), (100, 3.1)]:
            self.assertIsNone(self.gate.click(x, 4, t))
        self.assertIsNotNone(self.gate.click(100, 4, 3.2))

    def test_middle_click_busy_disabled_and_closed(self):
        self.gate.set_trigger_mode("middle_single")
        self.assertEqual(self.burst(1), [None] * 3)
        self.assertIsNone(self.gate.click(20, 30, 2, "right"))
        req = self.gate.click(20, 30, 3, "middle")
        self.assertEqual((req.x, req.y, req.deadline), (20, 30, 303))
        self.assertIsNone(self.gate.click(20, 30, 3.1, "middle"))
        self.gate.finish(req, "A", 4)
        self.gate.enable(False)
        self.assertIsNone(self.gate.click(20, 30, 5, "middle"))
        self.gate.enable(True)
        self.assertIsNotNone(self.gate.click(20, 30, 6, "middle"))
        self.gate.close()
        self.assertIsNone(self.gate.click(20, 30, 7, "middle"))

    def test_switch_resets_partial_burst_and_preserves_active_request(self):
        self.gate.click(40, 20, 1)
        self.gate.click(40, 20, 1.1)
        self.gate.set_trigger_mode("middle_single")
        self.gate.set_trigger_mode("left_triple")
        self.assertIsNone(self.gate.click(40, 20, 1.2))
        self.assertIsNone(self.gate.click(40, 20, 1.3))
        req = self.gate.click(40, 20, 1.4)
        self.gate.set_trigger_mode("middle_single")
        self.assertEqual(self.gate.current, req)
        self.assertIsNone(self.gate.click(40, 20, 1.5, "middle"))
        self.gate.finish(req, "B", 2)
        self.assertIsNotNone(self.gate.click(40, 20, 2.1, "middle"))

    def test_right_chord_saves_and_releasing_right_does_not_resubmit(self):
        self.gate.set_right_pressed(True)
        req = self.burst(1)[2]
        self.assertTrue(req.capture_only)
        self.gate.finish(req, True, 1.25)
        self.gate.set_right_pressed(False)
        for t in (1.3, 1.4, 1.5):
            self.assertIsNone(self.gate.click(40, 20, t))
        final = self.burst(3)[2]
        self.assertFalse(final.capture_only)

    def test_changing_right_state_cannot_complete_a_partial_burst(self):
        for pressed in (True, False):
            with self.subTest(pressed=pressed):
                self.gate = Gate(0.5, (4, 4))
                self.gate.enable(True)
                self.gate.set_right_pressed(not pressed)
                self.gate.click(40, 20, 1)
                self.gate.click(40, 20, 1.1)
                self.gate.set_right_pressed(pressed)
                self.assertIsNone(self.gate.click(40, 20, 1.2))
                self.assertIsNone(self.gate.click(40, 20, 1.3))
                req = self.gate.click(40, 20, 1.4)
                self.assertEqual(req.capture_only, pressed)

    def test_right_modifies_middle_trigger_and_left_stays_inactive(self):
        self.gate.set_trigger_mode("middle_single")
        self.gate.set_right_pressed(True)
        self.assertEqual(self.burst(1), [None] * 3)
        req = self.gate.click(40, 20, 1.2, "middle")
        self.assertTrue(req.capture_only)
        self.assertIsNone(self.gate.click(40, 20, 1.21, "middle"))
        self.gate.finish(req, True, 1.25)
        self.gate.set_right_pressed(False)
        self.assertEqual(self.burst(3), [None] * 3)
        req = self.gate.click(40, 20, 4, "middle")
        self.assertFalse(req.capture_only)

    def test_busy_save_burst_is_discarded_even_if_right_is_released(self):
        req = self.burst(1)[2]
        self.gate.set_right_pressed(True)
        self.assertIsNone(self.gate.click(40, 20, 3))
        self.gate.finish(req, "A", 3.05)
        self.gate.set_right_pressed(False)
        for t in (3.1, 3.2, 3.3):
            self.assertIsNone(self.gate.click(40, 20, t))
        self.assertIsNotNone(self.burst(4)[2])
