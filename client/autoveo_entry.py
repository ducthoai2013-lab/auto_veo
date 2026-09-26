"""Điểm vào cho PyInstaller (Auto_veo3.exe)."""
import multiprocessing
import sys

from autoveo.main import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
