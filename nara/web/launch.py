"""웹 버튼이 누른 조회를 별도 프로세스로 띄운다. 기다리지 않는다 — 결과는 run_log에 남는다."""

import os
import subprocess
import sys
from pathlib import Path


def launch(args: list[str], db_path: Path) -> None:
    """`nara <args> --db <db>`를 서버와 같은 파이썬·작업 폴더로 띄운다."""
    cmd = [sys.executable, "-c", "from nara.cli import app; app()", *args, "--db", str(db_path)]
    extra: dict = {}
    if os.name == "nt":
        extra["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        extra["start_new_session"] = True
    subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd=os.getcwd(),
        **extra,
    )
