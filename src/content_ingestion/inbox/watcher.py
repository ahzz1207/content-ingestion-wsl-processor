import logging
import shutil
import time
from pathlib import Path

from content_ingestion.inbox.processor import JobProcessor
from content_ingestion.inbox.protocol import (
    JobPaths,
    ensure_shared_inbox,
    get_shared_inbox_paths,
    is_job_ready,
    iter_incoming_jobs,
)

logger = logging.getLogger(__name__)


class InboxWatcher:
    def __init__(self, shared_root: Path, processor: JobProcessor) -> None:
        self.shared_root = shared_root
        self.processor = processor
        ensure_shared_inbox(shared_root)

    def claim_job(self, job: JobPaths) -> Path | None:
        if not is_job_ready(job):
            return None
        target = get_shared_inbox_paths(self.shared_root).processing / job.job_id
        try:
            return Path(shutil.move(str(job.job_dir), str(target)))
        except FileNotFoundError:
            return None
        except OSError as exc:
            logger.warning("failed to claim job %s: %s", job.job_id, exc)
            return None

    def scan_once(self) -> list[Path]:
        results: list[Path] = []
        for job in iter_incoming_jobs(self.shared_root):
            claimed_dir = self.claim_job(job)
            if claimed_dir is None:
                continue
            results.append(self.processor.process(claimed_dir))
        return results

    def watch(self, interval_seconds: float) -> None:
        while True:
            try:
                self.scan_once()
            except Exception as exc:
                logger.exception("watch loop failed, continuing: %s", exc)
            time.sleep(interval_seconds)
