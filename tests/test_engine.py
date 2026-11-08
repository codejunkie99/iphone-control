"""Engine policy tests. SIMULATED backend and SIMULATED owner: no phone involved."""
import os
import stat
import unittest

from helpers import Clock, Owner, fast_policy, make_engine

from iphone_control.engine import EngineError
from iphone_control.identity import NoDocumentedIdentity


class Base(unittest.TestCase):
    def setUp(self):
        self.eng, self.be, self.home = make_engine()
        self.owner = None

    def tearDown(self):
        if self.owner:
            self.owner.close()

    def approve_all(self, **kw):
        self.owner = Owner(self.eng, **kw)

    def err(self, fn, *a, **kw):
        with self.assertRaises(EngineError) as cm:
            fn(*a, **kw)
        return cm.exception.code

    def observe(self, who="claude-code"):
        return self.eng.observe(who)

    def scroll(self, obs, request="r1", who="claude-code", direction="down"):
        return self.eng.scroll(who, obs["session_id"], obs["observation_id"], request, direction)


class TestStatus(Base):
    def test_status_reports_simulation_and_blocks(self):
        st = self.eng.status("claude-code")
        self.assertTrue(st["simulated"])
        self.assertTrue(st["connection"]["window_present"])
        self.assertIsNone(st["session"])
        self.assertEqual(st["capabilities"]["operations"],
                         ["status", "observe", "scroll", "tap", "type", "key", "batch", "release"])
        # stream_live is unknown in the simulation, like on the real Mac: scroll is reported blocked
        self.assertIn("no documented signal confirms the phone stream is live", st["capabilities"]["blocked_reasons"])

    def test_unknown_controller(self):
        self.assertEqual(self.err(self.eng.observe, "someone"), "unknown_controller")


class TestObserve(Base):
    def test_first_observe_needs_owner_approval(self):
        self.approve_all()
        obs = self.observe()
        self.assertTrue(obs["ok"] and obs["simulated"])
        self.assertEqual(self.owner.seen[0]["kind"], "session")
        # private files: 0600 file in a 0700 directory
        mode = stat.S_IMODE(os.stat(obs["image_path"]).st_mode)
        self.assertEqual(mode, 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(os.path.dirname(obs["image_path"])).st_mode), 0o700)
        # second observe in the same session: no new approval
        self.observe()
        self.assertEqual(len(self.owner.seen), 1)

    def test_unattended_never_asks_owner(self):
        self.eng.policy.unattended = True
        self.approve_all()
        obs = self.observe()
        self.assertTrue(obs["ok"] and obs["simulated"])
        self.assertTrue(self.scroll(obs)["ok"])
        self.assertEqual(self.owner.seen, [])

    def test_unattended_activates_window(self):
        self.eng.policy.unattended = True
        self.be.frontmost = False
        obs = self.observe()
        self.assertTrue(obs["ok"] and self.be.frontmost)

    def test_denied(self):
        self.approve_all(answer="deny")
        self.assertEqual(self.err(self.observe), "denied")
        self.assertIsNone(self.eng.session)
        self.assertEqual(os.listdir(self.eng.shots_dir), [])

    def test_approval_timeout(self):
        self.eng.policy.approval_timeout = 0.05
        self.assertEqual(self.err(self.observe), "approval_timeout")
        self.assertIsNone(self.eng.session)

    def test_blank_capture_rejected_and_deleted(self):
        self.approve_all()
        self.be.blank = True
        self.assertEqual(self.err(self.observe), "capture_blank")
        self.assertEqual(os.listdir(self.eng.shots_dir), [])

    def test_disconnect_halts(self):
        self.approve_all()
        self.observe()
        self.be.window = None
        self.assertEqual(self.err(self.observe), "not_connected")
        self.assertEqual(self.eng.halted, "disconnect")
        self.assertIsNone(self.eng.session)


class TestScroll(Base):
    def test_happy_path_simulated(self):
        self.approve_all()
        obs = self.observe()
        r = self.scroll(obs)
        self.assertTrue(r["ok"])
        self.assertTrue(r["simulated"])
        self.assertTrue(r["executed"] and r["screen_changed"])
        self.assertEqual(self.be.scrolls, 1)
        self.assertNotEqual(r["observation"]["observation_id"], obs["observation_id"])
        self.assertEqual([p["kind"] for p in self.owner.seen], ["session", "scroll"])

    def test_scroll_denied_does_nothing(self):
        self.approve_all()
        obs = self.observe()
        self.owner.answer = "deny"
        self.assertEqual(self.err(self.scroll, obs), "denied")
        self.assertEqual(self.be.scrolls, 0)

    def test_duplicate_request_rejected(self):
        self.approve_all()
        obs = self.observe()
        self.scroll(obs, "same")
        obs2 = self.observe()
        self.assertEqual(self.err(self.scroll, obs2, "same"), "duplicate_request")
        self.assertEqual(self.be.scrolls, 1)

    def test_observation_used_once(self):
        self.approve_all()
        obs = self.observe()
        self.be.scroll_effect = True
        self.scroll(obs, "a")
        self.eng.resume()
        self.assertEqual(self.err(self.scroll, obs, "b"), "stale_observation")
        self.assertEqual(self.be.scrolls, 1)

    def test_not_latest_observation(self):
        self.approve_all()
        old = self.observe()
        self.observe()
        self.assertEqual(self.err(self.scroll, old), "stale_observation")
        self.assertEqual(self.be.scrolls, 0)

    def test_old_observation(self):
        clock = Clock()
        self.eng, self.be, _ = make_engine(clock=clock)
        self.approve_all()
        obs = self.observe()
        clock.t += 16
        self.assertEqual(self.err(self.scroll, obs), "stale_observation")
        self.assertEqual(self.be.scrolls, 0)

    def test_screen_changed_while_owner_decided(self):
        def change(_p):
            self.be.ambient = 4  # the page moved by itself
        self.approve_all()
        obs = self.observe()
        self.owner.before = change
        self.assertEqual(self.err(self.scroll, obs), "stale_observation")
        self.assertEqual(self.be.scrolls, 0)

    def test_device_changed_halts(self):
        self.approve_all()
        obs = self.observe()
        from iphone_control.backend import WindowRef
        self.be.window = WindowRef(7777, 999, self.be.window.bounds)
        self.assertEqual(self.err(self.scroll, obs), "device_changed")
        self.assertEqual(self.eng.halted, "device_changed")
        self.assertEqual(self.be.scrolls, 0)

    def test_not_frontmost(self):
        self.approve_all()
        obs = self.observe()
        self.be.frontmost = False
        self.assertEqual(self.err(self.scroll, obs), "not_frontmost")
        self.assertEqual(self.be.scrolls, 0)

    def test_takeover_halts_without_retry(self):
        self.approve_all()
        obs = self.observe()
        self.be.fail_scroll = "takeover"
        self.assertEqual(self.err(self.scroll, obs), "owner_takeover")
        self.assertEqual(self.eng.halted, "owner_takeover")
        self.assertEqual(self.be.scrolls, 1)
        self.assertEqual(self.err(self.observe), "halted")  # no automatic reconnect

    def test_uncertain_delivery_halts_without_retry(self):
        self.approve_all()
        obs = self.observe()
        self.be.fail_scroll = "uncertain"
        self.assertEqual(self.err(self.scroll, obs), "uncertain_delivery")
        self.assertEqual(self.be.scrolls, 1)
        self.assertEqual(self.eng.halted, "uncertain_delivery")

    def test_no_visible_change_halts(self):
        self.approve_all()
        obs = self.observe()
        self.be.scroll_effect = False
        r = self.scroll(obs)
        self.assertFalse(r["ok"])
        self.assertEqual(r["code"], "no_visible_change")
        self.assertTrue(self.eng.halted.startswith("uncertain_delivery"))
        self.assertEqual(self.be.scrolls, 1)

    def test_stop_during_approval(self):
        self.approve_all()
        obs = self.observe()
        self.owner.answer = "stop"
        self.assertEqual(self.err(self.scroll, obs), "cancelled")
        self.assertEqual(self.eng.halted, "owner_stop")
        self.assertIsNone(self.eng.session)
        self.assertEqual(os.listdir(self.eng.shots_dir), [])
        self.assertEqual(self.be.scrolls, 0)

    def test_stop_during_gesture(self):
        self.approve_all()
        obs = self.observe()
        self.be.on_scroll = lambda: self.eng.stop_event.set()
        self.assertEqual(self.err(self.scroll, obs), "uncertain_delivery")
        self.assertIsNotNone(self.eng.halted)

    def test_resume_requires_new_approval(self):
        self.approve_all()
        self.observe()
        self.eng.stop()
        self.eng.resume()
        self.observe()
        self.assertEqual([p["kind"] for p in self.owner.seen], ["session", "session"])

    def test_bad_arguments(self):
        self.approve_all()
        obs = self.observe()
        self.assertEqual(self.err(self.scroll, obs, direction="left"), "invalid_argument")
        self.assertEqual(self.err(self.scroll, obs, request="bad id!"), "invalid_argument")
        self.assertEqual(self.be.scrolls, 0)


class TestInput(Base):
    def act(self, obs, action, request="a1", **kw):
        return self.eng.act("claude-code", obs["session_id"], obs["observation_id"], request, action, **kw)

    def test_tap_maps_pixels_to_window_points(self):
        self.approve_all()
        obs = self.observe()  # SIMULATED capture is 32 x 64 px of a 330 x 720 pt window at (100, 100)
        r = self.act(obs, "tap", x=16, y=32)
        self.assertTrue(r["ok"] and r["simulated"])
        self.assertEqual(self.be.inputs, [("tap", 265, 460)])
        self.assertEqual([p["kind"] for p in self.owner.seen], ["session", "tap"])

    def test_tap_outside_screenshot_rejected(self):
        self.approve_all()
        obs = self.observe()
        self.assertEqual(self.err(self.act, obs, "tap", x=32, y=10), "invalid_argument")
        self.assertEqual(self.be.inputs, [])

    def test_type_and_key_chain_observations(self):
        self.approve_all()
        obs = self.observe()
        r = self.act(obs, "type", text="Spotify")
        r = self.act(r["observation"], "key", request="a2", key="return")
        self.assertTrue(r["ok"])
        self.assertEqual(self.be.inputs, [("type", "Spotify"), ("key", "return")])

    def test_bad_key_and_empty_text(self):
        self.approve_all()
        obs = self.observe()
        self.assertEqual(self.err(self.act, obs, "key", key="power"), "invalid_argument")
        self.assertEqual(self.err(self.act, obs, "type", text=""), "invalid_argument")
        self.assertEqual(self.be.inputs, [])

    def test_typed_text_not_logged(self):
        self.approve_all()
        obs = self.observe()
        self.act(obs, "type", text="secretword")
        with open(self.eng.log.path) as f:
            self.assertNotIn("secretword", f.read())


class TestIdentityGate(Base):
    def test_production_identity_blocks_mutation(self):
        self.eng, self.be, _ = make_engine(identity=NoDocumentedIdentity())
        self.approve_all()
        obs = self.observe()  # read-only observation still works, with approval
        self.assertEqual(self.err(self.scroll, obs), "identity_unverified")
        self.assertEqual(self.be.scrolls, 0)
        self.assertEqual([p["kind"] for p in self.owner.seen], ["session"])  # owner not asked to approve a blocked scroll
        st = self.eng.status("claude-code")
        self.assertFalse(st["capabilities"]["scroll"])
        self.assertIn("device identity unverified", st["capabilities"]["blocked_reasons"])


class TestControllers(Base):
    def test_one_controller_at_a_time(self):
        self.approve_all()
        obs = self.observe("claude-code")
        self.assertEqual(self.err(self.observe, "grok-bot"), "controller_busy")
        self.assertEqual(self.err(self.eng.scroll, "grok-bot", obs["session_id"], obs["observation_id"], "x", "down"),
                         "controller_busy")
        self.assertEqual(self.err(self.eng.release, "grok-bot"), "controller_busy")
        self.eng.release("claude-code")
        self.assertTrue(self.observe("grok-bot")["ok"])

    def test_release_cleans_up(self):
        self.approve_all()
        obs = self.observe()
        self.observe()
        r = self.eng.release("claude-code", obs["session_id"])
        self.assertEqual(r["code"], "released")
        self.assertIsNone(self.eng.session)
        self.assertEqual(os.listdir(self.eng.shots_dir), [])
        self.assertEqual(self.err(self.scroll, obs, "after"), "no_session")

    def test_session_expires_when_idle(self):
        clock = Clock()
        self.eng, self.be, _ = make_engine(clock=clock, policy=fast_policy(session_idle_timeout=10))
        self.approve_all()
        self.observe()
        clock.t += 11
        self.assertIsNone(self.eng.status()["session"])
        self.assertEqual(os.listdir(self.eng.shots_dir), [])


class TestLogPrivacy(Base):
    def test_log_holds_no_paths_or_content(self):
        self.approve_all()
        obs = self.observe()
        self.scroll(obs)
        log = open(os.path.join(self.home, "engine.log")).read()
        self.assertNotIn(self.eng.shots_dir, log)
        self.assertNotIn(".png", log)
        self.assertIn("scroll_execute", log)
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.home, "engine.log")).st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
