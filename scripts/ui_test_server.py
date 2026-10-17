"""An isolated review database using the real sample media, for browser QA."""

import shutil

import uvicorn
from badminton.api import create_app
from badminton.config import DATA, ROOT
from badminton.storage import Store

if __name__ == "__main__":
    target = ROOT / ".cache" / "ui-test-data"
    store = Store(target)
    source = Store(DATA)
    for video in source.videos():
        folder = target / video["id"]
        folder.mkdir(parents=True, exist_ok=True)
        for name in ("timestamps.json", "poster.jpg", "contact-sheet.jpg"):
            shutil.copyfile(DATA / video["id"] / name, folder / name)
        store.register(video)
    for job in reversed(source.jobs()):
        if job["status"] != "completed" or job["kind"] not in (
            "players",
            "shuttle",
            "contacts",
            "recognition",
            "segments",
        ):
            continue
        run = DATA / job["video_id"] / "runs" / f"{job['id']}.json"
        if run.exists():
            folder = target / job["video_id"] / "runs"
            folder.mkdir(exist_ok=True)
            shutil.copyfile(run, folder / run.name)
            store.put_job(job)
    uvicorn.run(create_app(ROOT, target), host="127.0.0.1", port=8001)
