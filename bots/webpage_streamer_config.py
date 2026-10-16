"""Resolution and frame rate for the webpage streamer.

Per-platform defaults (overridden by WEBPAGE_STREAMER_VIDEO_FRAME_SIZE and
WEBPAGE_STREAMER_VIDEO_FPS, and by explicit CLI flags):

- Google Meet: 1920x1080 at 30 fps (Meet's screen-share ceiling)
- Zoom, Microsoft Teams, and local/test: 1920x1080 at 60 fps

Google Meet rejects canvas.captureStream() below 30 fps, so the meeting bot
never captures the Meet canvas slower than that. A higher configured fps raises
the capture rate instead of leaving 30 as a hidden cap.
"""

import os

MEET_VIDEO_FPS = 30
DEFAULT_VIDEO_FPS = 60
DEFAULT_VIDEO_FRAME_SIZE = (1920, 1080)
# Google Meet rejects canvas.captureStream() frame rates below 30.
MEET_CAPTURE_STREAM_FPS_FLOOR = 30

_PLATFORM_ALIASES = {
    "google_meet": "google_meet",
    "googlemeet": "google_meet",
    "meet": "google_meet",
    "zoom": "zoom",
    "zoom_web": "zoom",
    "teams": "teams",
    "microsoft_teams": "teams",
    "microsoftteams": "teams",
    "local": "local",
    "test": "local",
}


def canonical_platform(platform):
    """Map a meeting platform to google_meet, zoom, teams, or local."""
    if platform is None:
        return "local"
    key = str(platform).strip().lower().replace("-", "_").replace(" ", "_")
    if not key:
        return "local"
    return _PLATFORM_ALIASES.get(key, "local")


def default_fps_for_platform(platform):
    """Google Meet stays at 30. Zoom, Teams, and local/test use 60."""
    if canonical_platform(platform) == "google_meet":
        return MEET_VIDEO_FPS
    return DEFAULT_VIDEO_FPS


def default_frame_size_for_platform(platform):
    """Every supported platform shares 1920x1080. `platform` selects the table row."""
    canonical_platform(platform)
    return DEFAULT_VIDEO_FRAME_SIZE


def parse_video_frame_size(value):
    """Parse WIDTHxHEIGHT. Both dimensions must be positive even integers (I420)."""
    if not isinstance(value, str):
        raise ValueError(f"Video frame size must look like 1920x1080, got {value!r}")
    parts = value.strip().lower().split("x")
    if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
        raise ValueError(f"Video frame size must look like 1920x1080, got {value!r}")
    width, height = int(parts[0]), int(parts[1])
    if width < 2 or height < 2 or width % 2 or height % 2:
        raise ValueError(f"Video frame size must be positive even width and height, got {width}x{height}")
    return width, height


def parse_video_fps(value):
    """Parse a positive integer frame rate."""
    if isinstance(value, bool):
        raise ValueError(f"Video fps must be a positive integer, got {value!r}")
    if isinstance(value, int):
        fps = value
    elif isinstance(value, str) and value.strip().isdigit():
        fps = int(value.strip())
    else:
        raise ValueError(f"Video fps must be a positive integer, got {value!r}")
    if fps < 1:
        raise ValueError(f"Video fps must be a positive integer, got {value!r}")
    return fps


def _platform_from_env(platform, env):
    if platform not in (None, ""):
        return platform
    return env.get("WEBPAGE_STREAMER_PLATFORM", "")


def resolve_video_frame_size(cli_value, platform=None, environ=None):
    """CLI, then WEBPAGE_STREAMER_VIDEO_FRAME_SIZE, then the platform default."""
    env = os.environ if environ is None else environ
    if cli_value:
        return parse_video_frame_size(cli_value)
    raw = env.get("WEBPAGE_STREAMER_VIDEO_FRAME_SIZE", "").strip()
    if raw:
        return parse_video_frame_size(raw)
    return default_frame_size_for_platform(_platform_from_env(platform, env))


def resolve_video_fps(cli_value, platform=None, environ=None):
    """CLI, then WEBPAGE_STREAMER_VIDEO_FPS, then the platform default."""
    env = os.environ if environ is None else environ
    if cli_value not in (None, ""):
        return parse_video_fps(cli_value)
    raw = env.get("WEBPAGE_STREAMER_VIDEO_FPS", "").strip()
    if raw:
        return parse_video_fps(raw)
    return default_fps_for_platform(_platform_from_env(platform, env))


def format_video_frame_size(frame_size):
    width, height = frame_size
    return f"{width}x{height}"


def build_gstreamer_pipeline_description(display_var, width, height, framerate):
    """X11 capture pipeline. videoscale/videorate enforce the configured size and fps."""
    fps = parse_video_fps(framerate)
    if width < 2 or height < 2 or width % 2 or height % 2:
        raise ValueError(f"Video frame size must be positive even width and height, got {width}x{height}")
    return f"""
            ximagesrc display-name={display_var} use-damage=0 show-pointer=false
                ! videoscale
                ! videorate
                ! video/x-raw,framerate={fps}/1,width={width},height={height}
                ! videoconvert
                ! video/x-raw,format=I420,width={width},height={height}
                ! queue max-size-buffers=5 max-size-time=0 leaky=downstream
                ! appsink name=video_sink emit-signals=false max-buffers=1 drop=true

            alsasrc device=default
                ! audio/x-raw,format=S16LE,channels=1,rate=16000
                ! audioconvert
                ! audioresample
                ! queue max-size-buffers=8000 leaky=downstream
                ! appsink name=audio_sink emit-signals=false max-buffers=8000 drop=true
        """


def meeting_bot_output_rates(video_fps, platform=None):
    """Rates for the meeting bot that re-publishes the streamer video.

    The canvas draw rate matches the configured fps. On Google Meet, captureStream
    stays at least 30 because Meet rejects slower tracks, and rises with the
    configured fps when that is higher.
    """
    fps = parse_video_fps(video_fps)
    if canonical_platform(platform) == "google_meet":
        capture_stream_fps = max(MEET_CAPTURE_STREAM_FPS_FLOOR, fps)
    else:
        capture_stream_fps = fps
    return {
        "draw_fps": fps,
        "capture_stream_fps": capture_stream_fps,
    }


def initial_data_webpage_streamer_js_fields(platform=None, environ=None):
    """JS object fields injected into window.initialData on the meeting bot."""
    env = os.environ if environ is None else environ
    fps = resolve_video_fps(None, platform=platform, environ=env)
    rates = meeting_bot_output_rates(fps, platform=platform)
    return f"webpageStreamerVideoFps: {rates['draw_fps']}, webpageStreamerCaptureFps: {rates['capture_stream_fps']}"


def webpage_streamer_cli_args(platform=None, environ=None):
    env = os.environ if environ is None else environ
    frame_size = resolve_video_frame_size(None, platform=platform, environ=env)
    fps = resolve_video_fps(None, platform=platform, environ=env)
    return [
        "python",
        "bots/webpage_streamer/run_webpage_streamer.py",
        "--video-frame-size",
        format_video_frame_size(frame_size),
        "--video-fps",
        str(fps),
        "--platform",
        canonical_platform(_platform_from_env(platform, env)),
    ]


def webpage_streaming_cpu_request(environ=None):
    env = os.environ if environ is None else environ
    return env.get("WEBPAGE_STREAMING_CPU_REQUEST", "1")


def webpage_streaming_cpu_limit(environ=None):
    """Optional Kubernetes CPU limit. Unset means no CPU limit (upstream behavior)."""
    env = os.environ if environ is None else environ
    value = env.get("WEBPAGE_STREAMING_CPU_LIMIT", "").strip()
    return value or None


def webpage_streaming_resource_limits(environ=None):
    env = os.environ if environ is None else environ
    limits = {
        "memory": env.get("WEBPAGE_STREAMING_MEMORY_LIMIT", "4Gi"),
        "ephemeral-storage": env.get("WEBPAGE_STREAMING_EPHEMERAL_STORAGE_LIMIT", "0.5Gi"),
    }
    cpu_limit = webpage_streaming_cpu_limit(environ=env)
    if cpu_limit:
        limits["cpu"] = cpu_limit
    return limits


def webpage_streamer_env_vars(platform=None, environ=None):
    """Resolved size, fps, and platform passed into the streamer and meeting-bot pods."""
    env = os.environ if environ is None else environ
    resolved_platform = canonical_platform(_platform_from_env(platform, env))
    frame_size = resolve_video_frame_size(None, platform=resolved_platform, environ=env)
    fps = resolve_video_fps(None, platform=resolved_platform, environ=env)
    return [
        ("WEBPAGE_STREAMER_PLATFORM", resolved_platform),
        ("WEBPAGE_STREAMER_VIDEO_FRAME_SIZE", format_video_frame_size(frame_size)),
        ("WEBPAGE_STREAMER_VIDEO_FPS", str(fps)),
    ]
