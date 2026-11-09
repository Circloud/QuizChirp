"""Frozen desktop entry point; never spawn a visible helper console on Windows."""
import multiprocessing
import subprocess
import sys


if __name__ == "__main__":
    multiprocessing.freeze_support()
    if sys.platform == "win32":
        class BackgroundProcess(subprocess.Popen):
            def __init__(self, *args, **kwargs):
                kwargs["creationflags"] = kwargs.get("creationflags", 0) | subprocess.CREATE_NO_WINDOW
                super().__init__(*args, **kwargs)

        subprocess.Popen = BackgroundProcess
    from quizchirp.app import main
    main()
