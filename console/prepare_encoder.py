"""Fetch pinned encoder wheel into an isolated tools directory; install nothing."""
from pathlib import Path
import hashlib
import json
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def prepare():
    folder = ROOT / "console/.tools"
    folder.mkdir(exist_ok=True)
    wheel = folder / "imageio_ffmpeg-0.6.0-py3-none-win_amd64.whl"
    if not wheel.is_file():
        subprocess.run([sys.executable, "-m", "pip", "download", "--no-deps", "--only-binary=:all:",
                        "--dest", str(folder), "imageio-ffmpeg==0.6.0"], check=True)
    pin = json.loads((ROOT / "console/encoder_pin.json").read_text())
    if hashlib.sha256(wheel.read_bytes()).hexdigest() != pin["wheel_sha256"]:
        raise RuntimeError("Encoder wheel differs from pinned identity")
    with zipfile.ZipFile(wheel) as archive:
        member = next(name for name in archive.namelist() if name.endswith(".exe"))
        binary = archive.read(member)
    if hashlib.sha256(binary).hexdigest() != pin["executable_sha256"]:
        raise RuntimeError("Encoder executable differs from pinned identity")
    (folder / "ffmpeg.exe").write_bytes(binary)
    print("Pinned Windows encoder ready in console/.tools; no environment packages changed")


if __name__ == "__main__":
    prepare()
