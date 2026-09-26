"""Điểm vào cho PyInstaller (glabs-gateway.exe): glabs-gateway.exe serve [--host --port --mock] | admin ..."""
import multiprocessing
import sys

from gateway.__main__ import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
