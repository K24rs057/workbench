"""台本の say(なければ sub)を、edge-tts(Microsoft Edge の読み上げと同じ声)で1行ずつ WAV にする。

python make_voice.py                    … script.json → out/voice/(Nanami)
python make_voice.py --name Keita       … 男性の声

インターネットにつながっている必要がある。台本は Microsoft に送られる。無料で、回数の上限はない。
403 で断られたら pip install --upgrade edge-tts で直ることが多い。
"""
import argparse
import asyncio
import json
import subprocess
from pathlib import Path

import edge_tts

HERE = Path(__file__).parent
RATE = "+8%"


def scenes_of(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else data["scenes"]


async def one(text, voice, wav, sem):
    async with sem:
        mp3 = wav.with_suffix(".mp3")
        await edge_tts.Communicate(text, voice, rate=RATE).save(str(mp3))
        # build.py が読めるよう、24kHz・モノラルの WAV にそろえる
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3),
                        "-ar", "24000", "-ac", "1", "-sample_fmt", "s16", str(wav)], check=True)
        mp3.unlink()


async def main(args):
    out = HERE / args.voice_dir
    out.mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(4)
    jobs = [one(line.get("say") or line["sub"], f"ja-JP-{args.name}Neural", out / f"{s['id']}-{i}.wav", sem)
            for s in scenes_of(HERE / args.script) for i, line in enumerate(s["lines"])]
    await asyncio.gather(*jobs)
    print("voice done", args.name, len(jobs))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--script", default="script.json")
    p.add_argument("--voice-dir", default="out/voice")
    p.add_argument("--name", default="Nanami")
    asyncio.run(main(p.parse_args()))
