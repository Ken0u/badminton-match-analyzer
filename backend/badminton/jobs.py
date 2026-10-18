"""Synchronous job runner sharing admission control with the web worker."""

from uuid import uuid4


class JobCancelled(Exception):
    """A cooperative stop leaves completed pipeline artifacts available to resume."""


def run_local_job(store, kind, video_id, task):
    job = {
        "id": uuid4().hex,
        "kind": kind,
        "video_id": video_id,
        "status": "running",
        "progress": 0,
        "message": "Processing",
    }
    store.claim_job(job)

    def progress(value):
        job["progress"] = round(min(1, max(0, value)), 3)
        store.put_job(job)

    try:
        result = task(job["id"], progress)
        job.update(status="completed", progress=1, message="Completed", summary=result)
        return result
    except BaseException as exc:
        job.update(
            status="interrupted"
            if isinstance(exc, KeyboardInterrupt | JobCancelled)
            else "failed",
            message=str(exc) or type(exc).__name__,
        )
        raise
    finally:
        store.put_job(job)
