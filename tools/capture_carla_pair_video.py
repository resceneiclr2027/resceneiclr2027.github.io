"""Record an illustrative, matched CARLA scene pair (not a model rollout).

The vehicle-removal edit is authored in CARLA. Both camera passes follow the
same scripted ego path; the clip does not contain RESCENE outputs or benchmark
measurements. Requires CARLA's Python API, Pillow, NumPy, and FFmpeg.
"""

import argparse
import queue
import signal
import subprocess
import tempfile
import time
from pathlib import Path

import carla
import numpy as np
from PIL import Image, ImageDraw, ImageFont


WIDTH, HEIGHT = 960, 504
FRAMES, FPS = 80, 10
PANEL_HEIGHT = 72 + HEIGHT * 2


def wait_for_server(port, timeout=240):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            client = carla.Client("127.0.0.1", port)
            client.set_timeout(8)
            client.get_world()
            client.set_timeout(30)
            return client
        except RuntimeError:
            time.sleep(2)
    raise RuntimeError("CARLA did not respond on the isolated port")


def camera_image(sample):
    pixels = np.frombuffer(sample.raw_data, dtype=np.uint8)
    pixels = pixels.reshape(HEIGHT, WIDTH, 4)
    return Image.fromarray(pixels[:, :, 2::-1].copy(), "RGB")


def same_frame(stream, frame):
    image = stream.get(timeout=35)
    while image.frame < frame:
        image = stream.get(timeout=35)
    if image.frame != frame:
        raise RuntimeError("CARLA camera frames became unsynchronized")
    return image


def font(size, bold=False):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def compose(factual, edited, index):
    canvas = Image.new("RGB", (WIDTH * 2, PANEL_HEIGHT), "#f7f5f0")
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 0, WIDTH - 1, 71), fill="#193d50")
    draw.rectangle((WIDTH, 0, WIDTH * 2 - 1, 71), fill="#81543e")
    draw.text((30, 15), "FACTUAL WORLD", fill="white", font=font(24, True))
    draw.text((30, 44), "Vehicle present", fill="#d4e4eb", font=font(15))
    draw.text((WIDTH + 30, 15), "AUTHORED EDIT", fill="white", font=font(24, True))
    draw.text((WIDTH + 30, 44), "Vehicle removed", fill="#f4e7dc", font=font(15))
    for column, images in enumerate((factual, edited)):
        x = column * WIDTH
        canvas.paste(images["front"], (x, 72))
        canvas.paste(images["aerial"], (x, 72 + HEIGHT))
        draw.rectangle((x + 18, 88, x + 238, 126), fill="#f7f5f0")
        draw.text((x + 29, 96), "FRONT CAMERA", fill="#193d50", font=font(16, True))
        draw.rectangle((x + 18, 88 + HEIGHT, x + 306, 126 + HEIGHT), fill="#f7f5f0")
        draw.text((x + 29, 96 + HEIGHT), "EGO-CENTERED AERIAL", fill="#193d50", font=font(16, True))
    draw.rectangle((WIDTH - 2, 0, WIDTH + 1, PANEL_HEIGHT), fill="#f7f5f0")
    draw.rectangle((0, HEIGHT + 70, WIDTH * 2, HEIGHT + 73), fill="#f7f5f0")
    # A restrained timeline communicates that these are consecutive simulator frames.
    draw.rectangle((0, PANEL_HEIGHT - 5, int((index + 1) / FRAMES * WIDTH * 2), PANEL_HEIGHT), fill="#d29970")
    return canvas


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--poster", type=Path, required=True)
    parser.add_argument("--mobile-output", type=Path, required=True)
    parser.add_argument("--mobile-poster", type=Path, required=True)
    parser.add_argument("--carla-root", type=Path, required=True)
    parser.add_argument("--ffmpeg", type=Path, required=True)
    parser.add_argument("--port", type=int, default=42800)
    parser.add_argument("--graphicsadapter", type=int, default=2)
    args = parser.parse_args()
    if any(path.exists() for path in (args.output, args.poster,
                                     args.mobile_output, args.mobile_poster)):
        raise FileExistsError("An output already exists; choose fresh filenames")
    if not args.ffmpeg.is_file():
        raise FileNotFoundError(args.ffmpeg)

    server = None
    server_log = None
    world = None
    old_settings = None
    actors = []
    ffmpeg = None
    try:
        server_log = tempfile.TemporaryFile(mode="w+t")
        server = subprocess.Popen(
            [str(args.carla_root / "CarlaUE4.sh"), f"-carla-rpc-port={args.port}",
             f"-graphicsadapter={args.graphicsadapter}", "-RenderOffScreen",
             "-quality-level=Low", "-nosound"],
            stdout=server_log, stderr=subprocess.STDOUT, start_new_session=True,
        )
        client = wait_for_server(args.port)
        world = client.get_world()
        old_settings = world.get_settings()
        settings = world.get_settings()
        settings.synchronous_mode = True
        settings.fixed_delta_seconds = 0.05
        world.apply_settings(settings)
        world.set_weather(carla.WeatherParameters.ClearNoon)
        blueprints = world.get_blueprint_library()
        ego_bp = blueprints.find("vehicle.tesla.model3")
        lead_bp = blueprints.find("vehicle.audi.a2")
        ego = lead = lane = None
        for spawn in world.get_map().get_spawn_points():
            candidate = world.get_map().get_waypoint(spawn.location)
            if candidate.lane_type != carla.LaneType.Driving or candidate.is_junction:
                continue
            samples = [candidate.next(d) for d in (14, 28, 35)]
            if any(len(part) != 1 or part[0].road_id != candidate.road_id or
                   part[0].is_junction for part in samples):
                continue
            trial = world.try_spawn_actor(ego_bp, spawn)
            if trial is None:
                continue
            actors.append(trial)
            trial.set_simulate_physics(False)
            lead_transform = samples[1][0].transform
            lead_transform.location.z += 0.3
            trial_lead = world.try_spawn_actor(lead_bp, lead_transform)
            if trial_lead is not None:
                actors.append(trial_lead)
                trial_lead.set_simulate_physics(False)
                ego, lead, lane = trial, trial_lead, candidate
                break
            trial.destroy()
            actors.remove(trial)
        if ego is None:
            raise RuntimeError("No straight, clear CARLA road segment could be spawned")

        streams = {}
        for name, pose, fov in (
            ("front", carla.Transform(carla.Location(x=0.8, z=1.6)), "70"),
            ("aerial", carla.Transform(carla.Location(z=50), carla.Rotation(pitch=-90)), "70"),
        ):
            blueprint = blueprints.find("sensor.camera.rgb")
            blueprint.set_attribute("image_size_x", str(WIDTH))
            blueprint.set_attribute("image_size_y", str(HEIGHT))
            blueprint.set_attribute("fov", fov)
            camera = world.spawn_actor(blueprint, pose, attach_to=ego)
            actors.append(camera)
            streams[name] = queue.Queue()
            camera.listen(streams[name].put)

        # Fixed script and repeated world render, not a policy or a closed-loop run.
        path = []
        for i in range(FRAMES):
            phase = i / (FRAMES - 1)
            distance = 16 * (phase * phase * (3 - 2 * phase))
            chosen = lane.next(max(0.001, distance))
            if len(chosen) != 1:
                raise RuntimeError("Scripted CARLA route branched")
            pose = chosen[0].transform
            pose.location.z += 0.25
            path.append(pose)

        with tempfile.TemporaryDirectory(prefix="rescene-carla-pair-") as temp:
            temp = Path(temp)
            for label, present in (("factual", True), ("edited", False)):
                if present:
                    lead.set_transform(lead_transform)
                else:
                    lead.set_transform(carla.Transform(carla.Location(z=-100)))
                for index, pose in enumerate(path):
                    ego.set_transform(pose)
                    world.tick()
                    frame = world.tick()
                    for name, stream in streams.items():
                        image = camera_image(same_frame(stream, frame))
                        image.save(temp / f"{label}_{name}_{index:03d}.jpg", quality=91,
                                   subsampling=0)
                print(f"Captured {label}: {FRAMES} paired camera frames", flush=True)

            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.poster.parent.mkdir(parents=True, exist_ok=True)
            ffmpeg = subprocess.Popen(
                [str(args.ffmpeg), "-hide_banner", "-loglevel", "error", "-y",
                 "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{WIDTH * 2}x{PANEL_HEIGHT}",
                 "-r", str(FPS), "-i", "-", "-an", "-c:v", "libx264", "-preset", "medium",
                 "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                 str(args.output)], stdin=subprocess.PIPE)
            for index in range(FRAMES):
                views = {}
                for label in ("factual", "edited"):
                    views[label] = {}
                    for name in ("front", "aerial"):
                        with Image.open(temp / f"{label}_{name}_{index:03d}.jpg") as source:
                            views[label][name] = source.convert("RGB")
                frame = compose(views["factual"], views["edited"], index)
                if index == FRAMES // 2:
                    frame.save(args.poster, quality=89, subsampling=0)
                ffmpeg.stdin.write(frame.tobytes())
            ffmpeg.stdin.close()
            if ffmpeg.wait() != 0:
                raise RuntimeError("FFmpeg encoding failed")

        # Vertical ordering preserves full-resolution views on narrow screens.
        filter_graph = (
            f"[0:v]crop={WIDTH}:{PANEL_HEIGHT}:0:0[left];"
            f"[0:v]crop={WIDTH}:{PANEL_HEIGHT}:{WIDTH}:0[right];"
            "[left][right]vstack=inputs=2[out]"
        )
        subprocess.run(
            [str(args.ffmpeg), "-hide_banner", "-loglevel", "error", "-i",
             str(args.output), "-filter_complex", filter_graph, "-map", "[out]",
             "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "21",
             "-pix_fmt", "yuv420p", "-movflags", "+faststart",
             str(args.mobile_output)], check=True,
        )
        with Image.open(args.poster) as source:
            stacked = Image.new("RGB", (WIDTH, PANEL_HEIGHT * 2))
            stacked.paste(source.crop((0, 0, WIDTH, PANEL_HEIGHT)), (0, 0))
            stacked.paste(source.crop((WIDTH, 0, WIDTH * 2, PANEL_HEIGHT)),
                          (0, PANEL_HEIGHT))
            stacked.save(args.mobile_poster, quality=89, subsampling=0)
        print(f"Wrote paired desktop/mobile videos and posters", flush=True)
    finally:
        if ffmpeg is not None and ffmpeg.poll() is None:
            ffmpeg.terminate()
            ffmpeg.wait()
        for actor in reversed(actors):
            try:
                actor.destroy()
            except Exception:
                pass
        if world is not None and old_settings is not None:
            try:
                world.apply_settings(old_settings)
            except Exception:
                pass
        if server is not None:
            os.killpg(server.pid, signal.SIGTERM)
            try:
                server.wait(timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(server.pid, signal.SIGKILL)
                server.wait()
        if server_log is not None:
            server_log.close()


if __name__ == "__main__":
    main()
