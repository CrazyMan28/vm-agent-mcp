"""Persistent exec session state (cwd) and the background job registry."""

import itertools
import subprocess
import threading
from pathlib import Path

# Per-stream cap on retained background-job output.
_MAX_JOB_BUFFER = 1_000_000


class Session:
    """State that persists across exec calls — currently just the cwd."""

    def __init__(self) -> None:
        self.cwd: str = str(Path.home())


_sessions: dict[str, Session] = {}
_sessions_lock = threading.Lock()


def get_session(name: str = "default") -> Session:
    with _sessions_lock:
        if name not in _sessions:
            _sessions[name] = Session()
        return _sessions[name]


class Job:
    """A background process whose output is drained into capped buffers."""

    def __init__(self, job_id: str, command: str, proc: subprocess.Popen) -> None:
        self.id = job_id
        self.command = command
        self.proc = proc
        self.stdout = ""
        self.stderr = ""
        self.lock = threading.Lock()
        for stream, attr in ((proc.stdout, "stdout"), (proc.stderr, "stderr")):
            if stream is not None:
                threading.Thread(target=self._drain, args=(stream, attr), daemon=True).start()

    def _drain(self, stream, attr: str) -> None:
        try:
            for line in iter(stream.readline, ""):
                with self.lock:
                    buf = getattr(self, attr) + line
                    if len(buf) > _MAX_JOB_BUFFER:
                        buf = buf[-_MAX_JOB_BUFFER:]
                    setattr(self, attr, buf)
        except (ValueError, OSError):
            pass  # stream closed mid-read
        finally:
            try:
                stream.close()
            except OSError:
                pass

    def status(self) -> str:
        rc = self.proc.poll()
        return "running" if rc is None else f"exited({rc})"


_jobs: dict[str, Job] = {}
_jobs_lock = threading.Lock()
_job_counter = itertools.count(1)


def register_job(command: str, proc: subprocess.Popen) -> Job:
    job = Job(f"job-{next(_job_counter)}", command, proc)
    with _jobs_lock:
        _jobs[job.id] = job
    return job


def get_job(job_id: str) -> Job | None:
    with _jobs_lock:
        return _jobs.get(job_id)


def list_jobs() -> list[Job]:
    with _jobs_lock:
        return list(_jobs.values())
