"""Punto de entrada de Traffiqui.exe (PyInstaller). La lógica está en app/launcher.py."""
import multiprocessing
import sys

if __name__ == "__main__":
    multiprocessing.freeze_support()
    from app.launcher import main
    sys.exit(main())
