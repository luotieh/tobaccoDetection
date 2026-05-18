#!/usr/bin/env python3
import sys

import requests


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: scripts/infer_video.py /path/to/video.mp4")
    with open(sys.argv[1], "rb") as fh:
        res = requests.post("http://127.0.0.1:8000/infer/video", files={"file": fh})
    print(res.text)


if __name__ == "__main__":
    main()
