"""Build the 50 finch answer cues from the source archives in sounds/LICENSE.txt."""
import argparse
from array import array
from collections import defaultdict
import csv
from io import BytesIO
from pathlib import Path
import sys
import tarfile
import wave

OUT = Path(__file__).resolve().parents[1] / "quizchirp" / "sounds"
MANIFEST = Path(__file__).with_name("sound_clips.csv")
RATE = 32000


def write_clip(src, row):
    name = row["cue"]
    start, end = int(row["start_frame"]), int(row["end_frame"])
    src.setpos(start)
    pcm = array("h", src.readframes(end - start))
    if len(pcm) != end - start:
        raise ValueError(f"Incomplete source interval for {name}")
    if sys.byteorder != "little":
        pcm.byteswap()
    gain = 18000 / max(abs(value) for value in pcm)
    fade = round(RATE * 0.002)
    for i, value in enumerate(pcm):
        pcm[i] = round(value * gain * min(1, i / fade, (len(pcm) - 1 - i) / fade))
    if name != "FAIL":
        frames = round(RATE * 0.115)
        if len(pcm) > frames:
            raise ValueError(f"{name} exceeds the beat length")
        pcm.extend([0] * (frames - len(pcm)))
    if sys.byteorder != "little":
        pcm.byteswap()
    with wave.open(str(OUT / f"{name}.wav"), "wb") as dst:
        dst.setparams((1, 2, RATE, 0, "NONE", ""))
        dst.writeframes(pcm.tobytes())


def build(archives):
    clips = defaultdict(list)
    with MANIFEST.open(newline="", encoding="utf-8") as manifest:
        for row in csv.DictReader(manifest):
            clips[row["source_wav"]].append(row)
    for path in archives:
        with tarfile.open(path, "r|gz") as archive:
            for member in archive:
                if member.name in clips:
                    with wave.open(BytesIO(archive.extractfile(member).read())) as src:
                        if (src.getframerate(), src.getsampwidth(), src.getnchannels()) != (RATE, 2, 1):
                            raise ValueError(f"Unexpected WAV format in {member.name}")
                        for row in clips.pop(member.name):
                            write_clip(src, row)
    if clips:
        raise ValueError(f"Missing source recordings: {', '.join(clips)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archives", nargs="+", type=Path)
    build(parser.parse_args().archives)
