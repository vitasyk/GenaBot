from typing import List, Optional
from bot.database.models import RefuelSession


def get_all_workers_for_session(session: RefuelSession) -> List[int]:
    """
    Get all worker IDs assigned to a session (worker1, worker2, worker3 + additional_workers).
    Returns a list of unique worker IDs.
    """
    workers = []
    
    if session.worker1_id:
        workers.append(session.worker1_id)
    if session.worker2_id:
        workers.append(session.worker2_id)
    if session.worker3_id:
        workers.append(session.worker3_id)
    
    # Add additional workers from JSONB field
    if session.additional_workers:
        workers.extend(session.additional_workers)
    
    # Return unique workers only
    return list(dict.fromkeys(workers))


def split_workers(worker_ids: List[int]) -> tuple[Optional[int], Optional[int], Optional[int], List[int]]:
    """
    Split a list of worker IDs into first 3 + additional workers.
    Returns: (worker1_id, worker2_id, worker3_id, additional_workers)
    """
    worker1 = worker_ids[0] if len(worker_ids) > 0 else None
    worker2 = worker_ids[1] if len(worker_ids) > 1 else None
    worker3 = worker_ids[2] if len(worker_ids) > 2 else None
    additional = worker_ids[3:] if len(worker_ids) > 3 else []
    
    return worker1, worker2, worker3, additional
