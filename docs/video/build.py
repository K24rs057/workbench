"""しくみ解説の縦動画を作る。

1. 声のWAV(make_voice.py で作る)の長さから、各行の開始時刻を決める
2. 無音をはさんで1本のナレーションにする
3. 動く絵のページ(video.html)を Playwright で1コマずつ撮り、ffmpeg で音とあわせて MP4 にする

python build.py                          … script.json + out/voice → out/<name>.mp4
python build.py --timing                 … 時刻と音声だけ(撮影しない。stills.py の前に使う)
python build.py --voice-dir out/voice_gemini --name shikumi_gemini
"""
import argparse
import json
import subprocess
import wave
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "out"
W, H = 1080, 1920

SCENE_LEAD = 0.9   # 場面が変わってから話しはじめるまで
LINE_GAP = 0.45    # 行と行のあいだ
SCENE_TAIL = 1.0   # 話し終えてから次の場面まで


def fmt(t):
    return f"{int(t // 60)}:{int(t % 60):02d}"


def load_script(path):
    """台本は場面の配列か、{"title": 上の札に出す名前, "scenes": [...]}"""
    data = json.loads(path.read_text(encoding="utf-8"))
    return (data, "") if isinstance(data, list) else (data["scenes"], data.get("title", ""))


def build_timing(a):
    scenes, title = load_script(HERE / a.script)
    voice = HERE / a.voice_dir
    t = 0.0
    timing = []
    clips = []  # (開始秒, wavのバイト列)
    params = None
    for s in scenes:
        start = t
        t += SCENE_LEAD
        lines = []
        for i, line in enumerate(s["lines"]):
            with wave.open(str(voice / f"{s['id']}-{i}.wav"), "rb") as w:
                params = params or w.getparams()
                data = w.readframes(w.getnframes())
                dur = w.getnframes() / w.getframerate()
            lines.append({"sub": line["sub"], "start": round(t, 3), "end": round(t + dur, 3)})
            clips.append((t, data))
            t += dur + LINE_GAP
        t += SCENE_TAIL - LINE_GAP
        scene = {k: s[k] for k in s if k != "lines"}
        scene.update(start=round(start, 3), end=round(t, 3), lines=lines)
        timing.append(scene)
    total = t

    rate, width = params.framerate, params.sampwidth
    buf = bytearray(int(total * rate) * width + width)
    for start, data in clips:
        pos = int(start * rate) * width
        buf[pos:pos + len(data)] = data
    with wave.open(str(OUT / "narration.wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(bytes(buf))

    data = {"title": title, "total": round(total, 3), "scenes": timing}
    (OUT / "timing.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    # ブラウザで直接開いて確かめられるよう、同じ内容を js でも置く
    (OUT / "timing.js").write_text("window.TIMING=" + json.dumps(data, ensure_ascii=False) + ";", encoding="utf-8")

    # 章の目次(chapter の場面があるときだけ)
    chapters = ["0:00 はじめに"] + [
        f"{fmt(s['start'])} 第{s['data']['no']}章 {s['data']['name'].replace(chr(10), ' ')}"
        for s in timing if s.get("type") == "chapter"]
    if len(chapters) > 1:
        (OUT / "chapters.txt").write_text("\n".join(chapters) + "\n", encoding="utf-8")
    print(f"total {fmt(total)} ({total:.1f}s)")
    return data


def render(a, timing):
    from playwright.sync_api import sync_playwright

    fps = a.fps
    n = int(timing["total"] * fps)
    mp4 = OUT / f"{a.name}.mp4"
    ff = subprocess.Popen([
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "image2pipe", "-framerate", str(fps), "-c:v", "mjpeg", "-i", "-",
        "-i", str(OUT / "narration.wav"),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "medium", "-crf", "20",
        "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", str(mp4),
    ], stdin=subprocess.PIPE)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": W, "height": H})
        page.goto((HERE / a.html).as_uri())
        page.wait_for_function("window.READY === true")
        for f in range(n):
            page.evaluate(f"window.render({f / fps})")
            ff.stdin.write(page.screenshot(type="jpeg", quality=92))
            if f % 600 == 0:
                print(f"frame {f}/{n}", flush=True)
        browser.close()
    ff.stdin.close()
    ff.wait()
    print("done", mp4)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--script", default="script.json")
    ap.add_argument("--voice-dir", default="out/voice")
    ap.add_argument("--html", default="video.html")
    ap.add_argument("--name", default="shikumi", help="できあがりの名前(out/<name>.mp4)")
    ap.add_argument("--fps", type=int, default=30, help="長い動画は 24 にすると撮影が早い")
    ap.add_argument("--timing", action="store_true")
    a = ap.parse_args()
    OUT.mkdir(exist_ok=True)
    t = build_timing(a)
    if not a.timing:
        render(a, t)
