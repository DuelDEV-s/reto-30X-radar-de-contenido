"""Claim before a potentially billable POST. No automatic resubmission on ambiguity."""
from datetime import datetime, timezone
import hashlib
from uuid import uuid4

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from .database import ProfileCollectionJob


ACTIVE = {"requesting", "pending"}


def aware(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def new_job(key):
    now = datetime.now(timezone.utc)
    return {"id": key, "generation": str(uuid4()), "state": "requesting", "snapshot_id": None, "result": None, "message": "", "created_at": now, "updated_at": now}


class MemoryJobStore:
    """Used for isolated connector tests; production always injects DBJobStore."""
    def __init__(self):
        self.jobs = {}

    def get(self, key):
        return self.jobs.get(key)

    def claim(self, key, refresh=False):
        previous = self.get(key)
        if previous and (not refresh or previous["state"] in ACTIVE):
            return previous, False
        job = new_job(key)
        self.jobs[key] = job
        return job, True

    def save(self, job, **values):
        current = self.jobs[job["id"]]
        if current["generation"] == job["generation"]:
            current = {**current, **values, "updated_at": datetime.now(timezone.utc)}
            self.jobs[job["id"]] = current
        return current


class DBJobStore:
    def __init__(self, session, brand_id):
        self.session, self.brand_id = session, brand_id

    def _id(self, key):
        return hashlib.sha256(f"{self.brand_id}:{key}".encode()).hexdigest()

    @staticmethod
    def _data(row):
        if not row:
            return None
        return {"id": row.id, "generation": row.generation, "state": row.state, "snapshot_id": row.snapshot_id, "result": row.result, "message": row.message, "created_at": aware(row.created_at), "updated_at": aware(row.updated_at)}

    def get(self, key):
        self.session.expire_all()
        return self._data(self.session.get(ProfileCollectionJob, self._id(key)))

    def claim(self, key, refresh=False):
        previous = self.get(key)
        if previous and (not refresh or previous["state"] in ACTIVE):
            return previous, False
        values = new_job(self._id(key))
        if previous:
            result = self.session.execute(update(ProfileCollectionJob).where(
                ProfileCollectionJob.id == previous["id"],
                ProfileCollectionJob.generation == previous["generation"],
                ProfileCollectionJob.state == previous["state"],
            ).values(**{k: v for k, v in values.items() if k != "id"}))
            self.session.commit()
            return self.get(key), result.rowcount == 1
        self.session.add(ProfileCollectionJob(brand_id=self.brand_id, **values))
        try:
            self.session.commit()
            return self.get(key), True
        except IntegrityError:
            self.session.rollback()
            return self.get(key), False

    def save(self, job, **values):
        self.session.execute(update(ProfileCollectionJob).where(
            ProfileCollectionJob.id == job["id"], ProfileCollectionJob.generation == job["generation"],
        ).values(**values, updated_at=datetime.now(timezone.utc)))
        self.session.commit()
        self.session.expire_all()
        return self._data(self.session.get(ProfileCollectionJob, job["id"]))
