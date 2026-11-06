"""In-memory audit jobs.

An audit can take a minute or more (page, favicon, up to 15 links at 5 s,
then Gemini), so the form starts a job and the results page reloads until
it is done. Job ids are random and unguessable: only the person who started
an audit has the link to its results.
"""

import logging
import secrets
import threading
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Literal, Protocol
from urllib.parse import urlsplit

from website_audit_agent.models import Report

log = logging.getLogger("website_audit_agent.web")

JobStatus = Literal["queued", "running", "done", "error"]


@dataclass
class Job:
    id: str
    host: str
    status: JobStatus = "queued"
    report: Report | None = None


class Executor(Protocol):
    def submit(self, fn: Callable, /, *args): ...


class JobStore:
    def __init__(
        self,
        run: Callable[[str], Report],
        executor: Executor | None = None,
        max_workers: int = 2,
        max_jobs: int = 200,
    ) -> None:
        self._run = run
        self._executor = executor or ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="audit")
        self._max_jobs = max_jobs
        self._jobs: OrderedDict[str, Job] = OrderedDict()
        self._lock = threading.Lock()

    def submit(self, url: str) -> Job:
        job = Job(id=secrets.token_urlsafe(16), host=urlsplit(url).hostname or "?")
        with self._lock:
            self._jobs[job.id] = job
            while len(self._jobs) > self._max_jobs:  # forget the oldest
                self._jobs.popitem(last=False)
        self._executor.submit(self._work, job, url)
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def _work(self, job: Job, url: str) -> None:
        job.status = "running"
        try:
            job.report = self._run(url)
            job.status = "done"
        except Exception as exc:  # run_audit should not raise; never log the URL or the message
            log.error("audit host=%s result=error:%s", job.host, type(exc).__name__)
            job.status = "error"
