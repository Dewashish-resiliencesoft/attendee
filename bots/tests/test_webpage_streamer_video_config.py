import os
import unittest
from pathlib import Path
from unittest.mock import patch

from bots.webpage_streamer_config import (
    DEFAULT_VIDEO_FRAME_SIZE,
    build_gstreamer_pipeline_description,
    default_fps_for_platform,
    default_frame_size_for_platform,
    initial_data_webpage_streamer_js_fields,
    meeting_bot_output_rates,
    parse_video_fps,
    parse_video_frame_size,
    resolve_video_fps,
    resolve_video_frame_size,
    webpage_streamer_cli_args,
    webpage_streaming_cpu_limit,
    webpage_streaming_cpu_request,
    webpage_streaming_resource_limits,
)

ROOT = Path(__file__).resolve().parents[2]


class TestPlatformDefaults(unittest.TestCase):
    def test_platform_to_fps(self):
        self.assertEqual(default_fps_for_platform("google_meet"), 30)
        self.assertEqual(default_fps_for_platform("meet"), 30)
        self.assertEqual(default_fps_for_platform("zoom"), 60)
        self.assertEqual(default_fps_for_platform("zoom_web"), 60)
        self.assertEqual(default_fps_for_platform("teams"), 60)
        self.assertEqual(default_fps_for_platform("microsoft_teams"), 60)
        self.assertEqual(default_fps_for_platform("local"), 60)
        self.assertEqual(default_fps_for_platform("test"), 60)
        self.assertEqual(default_fps_for_platform(None), 60)

    def test_platform_frame_size_is_1080p(self):
        for platform in ("google_meet", "zoom", "teams", "local", None):
            self.assertEqual(default_frame_size_for_platform(platform), (1920, 1080))

    def test_env_fps_overrides_meet_default(self):
        with patch.dict(os.environ, {"WEBPAGE_STREAMER_VIDEO_FPS": "60"}, clear=False):
            os.environ.pop("WEBPAGE_STREAMER_PLATFORM", None)
            self.assertEqual(resolve_video_fps(None, platform="google_meet"), 60)

    def test_env_frame_size_overrides_platform_default(self):
        with patch.dict(os.environ, {"WEBPAGE_STREAMER_VIDEO_FRAME_SIZE": "1280x720"}):
            self.assertEqual(resolve_video_frame_size(None, platform="zoom"), (1280, 720))


class TestVideoFrameSize(unittest.TestCase):
    def test_default_frame_size_is_1080p(self):
        self.assertEqual(DEFAULT_VIDEO_FRAME_SIZE, (1920, 1080))

    def test_parses_1080p(self):
        self.assertEqual(parse_video_frame_size("1920x1080"), (1920, 1080))

    def test_parses_uppercase_separator(self):
        self.assertEqual(parse_video_frame_size("1920X1080"), (1920, 1080))

    def test_rejects_odd_dimensions(self):
        with self.assertRaises(ValueError):
            parse_video_frame_size("1919x1080")

    def test_rejects_missing_height(self):
        with self.assertRaises(ValueError):
            parse_video_frame_size("1920")

    def test_cli_overrides_env(self):
        with patch.dict(os.environ, {"WEBPAGE_STREAMER_VIDEO_FRAME_SIZE": "1280x720"}):
            self.assertEqual(resolve_video_frame_size("1920x1080"), (1920, 1080))

    def test_env_used_when_cli_omitted(self):
        with patch.dict(os.environ, {"WEBPAGE_STREAMER_VIDEO_FRAME_SIZE": "1920x1080"}):
            self.assertEqual(resolve_video_frame_size(None), (1920, 1080))

    def test_local_default_when_unset(self):
        env = os.environ.copy()
        env.pop("WEBPAGE_STREAMER_VIDEO_FRAME_SIZE", None)
        env.pop("WEBPAGE_STREAMER_PLATFORM", None)
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(resolve_video_frame_size(None, platform="local"), (1920, 1080))
            self.assertEqual(resolve_video_frame_size(None, platform="google_meet"), (1920, 1080))


class TestVideoFps(unittest.TestCase):
    def test_meet_defaults_to_30_and_others_to_60(self):
        self.assertEqual(default_fps_for_platform("google_meet"), 30)
        self.assertEqual(default_fps_for_platform("zoom"), 60)

    def test_parses_60(self):
        self.assertEqual(parse_video_fps("60"), 60)
        self.assertEqual(parse_video_fps(60), 60)

    def test_rejects_non_positive_and_garbage(self):
        for value in ("0", "-1", "abc", "", "15.5"):
            with self.assertRaises(ValueError):
                parse_video_fps(value)

    def test_cli_overrides_env(self):
        with patch.dict(os.environ, {"WEBPAGE_STREAMER_VIDEO_FPS": "15"}):
            self.assertEqual(resolve_video_fps("60"), 60)

    def test_env_used_when_cli_omitted(self):
        with patch.dict(os.environ, {"WEBPAGE_STREAMER_VIDEO_FPS": "60"}):
            self.assertEqual(resolve_video_fps(None), 60)

    def test_platform_default_when_unset(self):
        env = os.environ.copy()
        env.pop("WEBPAGE_STREAMER_VIDEO_FPS", None)
        env.pop("WEBPAGE_STREAMER_PLATFORM", None)
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(resolve_video_fps(None, platform="google_meet"), 30)
            self.assertEqual(resolve_video_fps(None, platform="zoom"), 60)
            self.assertEqual(resolve_video_fps(None, platform="teams"), 60)
            self.assertEqual(resolve_video_fps(None), 60)


class TestGstreamerPipeline(unittest.TestCase):
    def test_pipeline_uses_configured_size_and_fps(self):
        description = build_gstreamer_pipeline_description(display_var=":99", width=1920, height=1080, framerate=60)
        self.assertIn("framerate=60/1", description)
        self.assertIn("width=1920", description)
        self.assertIn("height=1080", description)
        self.assertNotIn("framerate=15/1", description)
        # videorate actually locks the capture rate; a caps field alone does not.
        self.assertIn("videorate", description)
        self.assertIn("videoscale", description)
        self.assertIn("display-name=:99", description)

    def test_default_pipeline_stays_720p15(self):
        description = build_gstreamer_pipeline_description(display_var=":1", width=1280, height=720, framerate=15)
        self.assertIn("framerate=15/1", description)
        self.assertIn("width=1280", description)
        self.assertIn("height=720", description)


class TestMeetingBotOutputRates(unittest.TestCase):
    def test_meet_capture_stays_at_30_floor_when_draw_is_slower(self):
        rates = meeting_bot_output_rates(15, platform="google_meet")
        self.assertEqual(rates["draw_fps"], 15)
        # captureStream below 30 makes Google Meet reject the track.
        self.assertEqual(rates["capture_stream_fps"], 30)

    def test_60fps_raises_draw_and_capture_above_the_old_caps(self):
        rates = meeting_bot_output_rates(60)
        self.assertEqual(rates["draw_fps"], 60)
        self.assertEqual(rates["capture_stream_fps"], 60)

    def test_fps_between_15_and_30_keeps_meet_capture_floor(self):
        rates = meeting_bot_output_rates(24, platform="google_meet")
        self.assertEqual(rates["draw_fps"], 24)
        self.assertEqual(rates["capture_stream_fps"], 30)

    def test_zoom_capture_matches_configured_fps(self):
        rates = meeting_bot_output_rates(60, platform="zoom")
        self.assertEqual(rates["draw_fps"], 60)
        self.assertEqual(rates["capture_stream_fps"], 60)

    def test_initial_data_defaults(self):
        env = os.environ.copy()
        env.pop("WEBPAGE_STREAMER_VIDEO_FPS", None)
        env.pop("WEBPAGE_STREAMER_PLATFORM", None)
        with patch.dict(os.environ, env, clear=True):
            meet_fields = initial_data_webpage_streamer_js_fields(platform="google_meet")
            zoom_fields = initial_data_webpage_streamer_js_fields(platform="zoom")
        self.assertIn("webpageStreamerVideoFps: 30", meet_fields)
        self.assertIn("webpageStreamerCaptureFps: 30", meet_fields)
        self.assertIn("webpageStreamerVideoFps: 60", zoom_fields)
        self.assertIn("webpageStreamerCaptureFps: 60", zoom_fields)

    def test_initial_data_follows_configured_fps(self):
        with patch.dict(os.environ, {"WEBPAGE_STREAMER_VIDEO_FPS": "60"}):
            fields = initial_data_webpage_streamer_js_fields()
        self.assertIn("webpageStreamerVideoFps: 60", fields)
        self.assertIn("webpageStreamerCaptureFps: 60", fields)


class TestPodResources(unittest.TestCase):
    def test_cli_args_default_to_upstream(self):
        env = os.environ.copy()
        env.pop("WEBPAGE_STREAMER_VIDEO_FRAME_SIZE", None)
        env.pop("WEBPAGE_STREAMER_VIDEO_FPS", None)
        env.pop("WEBPAGE_STREAMER_PLATFORM", None)
        with patch.dict(os.environ, env, clear=True):
            args = webpage_streamer_cli_args()
        self.assertEqual(
            args,
            [
                "python",
                "bots/webpage_streamer/run_webpage_streamer.py",
                "--video-frame-size",
                "1920x1080",
                "--video-fps",
                "60",
                "--platform",
                "local",
            ],
        )

    def test_cli_args_use_meet_fps(self):
        env = os.environ.copy()
        env.pop("WEBPAGE_STREAMER_VIDEO_FRAME_SIZE", None)
        env.pop("WEBPAGE_STREAMER_VIDEO_FPS", None)
        env.pop("WEBPAGE_STREAMER_PLATFORM", None)
        with patch.dict(os.environ, env, clear=True):
            args = webpage_streamer_cli_args(platform="google_meet")
        self.assertIn("1920x1080", args)
        self.assertIn("30", args)
        self.assertIn("google_meet", args)

    def test_cli_args_follow_env_over_platform(self):
        with patch.dict(os.environ, {"WEBPAGE_STREAMER_VIDEO_FRAME_SIZE": "1280x720", "WEBPAGE_STREAMER_VIDEO_FPS": "24"}):
            args = webpage_streamer_cli_args(platform="google_meet")
        self.assertIn("1280x720", args)
        self.assertIn("24", args)

    def test_cpu_request_default_stays_one(self):
        env = os.environ.copy()
        env.pop("WEBPAGE_STREAMING_CPU_REQUEST", None)
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(webpage_streaming_cpu_request(), "1")

    def test_cpu_limit_is_unset_by_default(self):
        env = os.environ.copy()
        env.pop("WEBPAGE_STREAMING_CPU_LIMIT", None)
        with patch.dict(os.environ, env, clear=True):
            self.assertIsNone(webpage_streaming_cpu_limit())
            self.assertNotIn("cpu", webpage_streaming_resource_limits())

    def test_cpu_limit_can_be_raised(self):
        with patch.dict(os.environ, {"WEBPAGE_STREAMING_CPU_LIMIT": "4"}):
            self.assertEqual(webpage_streaming_cpu_limit(), "4")
            self.assertEqual(webpage_streaming_resource_limits()["cpu"], "4")


class TestHiddenCapsRemovedFromSources(unittest.TestCase):
    def test_gstreamer_source_uses_configured_fps(self):
        source = (ROOT / "bots/webpage_streamer/webpage_streamer.py").read_text()
        self.assertNotIn("framerate=15/1", source)
        self.assertNotIn("framerate=15,", source)
        self.assertIn("build_gstreamer_pipeline_description", source)
        self.assertIn("self.video_fps", source)

    def test_canvas_capture_is_not_hardcoded_below_configured_fps(self):
        source = (ROOT / "bots/web_bot_adapter/shared_chromedriver_payload.js").read_text()
        self.assertNotIn("1000 / 15", source)
        self.assertNotIn("captureStream(30)", source)
        self.assertIn("webpageStreamerVideoFps", source)
        self.assertIn("webpageStreamerCaptureFps", source)

    def test_meeting_bot_receives_streamer_fps(self):
        source = (ROOT / "bots/web_bot_adapter/web_bot_adapter.py").read_text()
        self.assertIn("initial_data_webpage_streamer_js_fields", source)

    def test_pod_creator_passes_fps_and_optional_cpu_limit(self):
        source = (ROOT / "bots/bot_pod_creator/bot_pod_creator.py").read_text()
        self.assertIn("webpage_streamer_cli_args", source)
        self.assertIn("webpage_streaming_resource_limits", source)
        self.assertIn("webpage_streamer_env_vars(", source)
        # Streamer pod and meeting-bot pod both receive the configured size and fps.
        self.assertEqual(source.count("_webpage_streamer_env()"), 2)

    def test_local_1080p60_override_and_docs(self):
        override = (ROOT / "dev.docker-compose.1080p60.yaml").read_text()
        self.assertIn("1920x1080", override)
        self.assertIn("60", override)
        self.assertIn("cpus:", override)
        example = (ROOT / ".env.webpage-streamer.example").read_text()
        self.assertIn("WEBPAGE_STREAMER_VIDEO_FRAME_SIZE=1920x1080", example)
        self.assertIn("WEBPAGE_STREAMER_VIDEO_FPS=60", example)
        readme = (ROOT / "README.md").read_text()
        self.assertIn("dev.docker-compose.1080p60.yaml", readme)
        self.assertIn("limits screen share to about 30 fps", readme)


if __name__ == "__main__":
    unittest.main()
