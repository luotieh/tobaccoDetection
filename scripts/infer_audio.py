#!/usr/bin/env python3
import sys

import requests


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: scripts/infer_audio.py /path/to/audio.wav")
    with open(sys.argv[1], "rb") as fh:
        res = requests.post("http://127.0.0.1:8020/infer/audio", files={"file": fh}, timeout=30)
    print(res.text)


if __name__ == "__main__":
    main()
