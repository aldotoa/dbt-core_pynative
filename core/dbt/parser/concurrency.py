import os
import threading
from concurrent.futures import Executor, Future, ThreadPoolExecutor
from typing import Any, Callable, Iterable, Iterator, List, Optional, TypeVar

from dbt.flags import get_flags

T = TypeVar("T")
R = TypeVar("R")

DEFAULT_MAX_WORKERS = min(32, max(1, os.cpu_count() or 4))
_EXECUTOR: Optional[ThreadPoolExecutor] = None
_EXECUTOR_WORKERS: Optional[int] = None
_EXECUTOR_LOCK = threading.Lock()


def get_shared_executor(max_workers: int) -> ThreadPoolExecutor:
    """Return a warm shared ThreadPoolExecutor to avoid thread creation overhead."""
    global _EXECUTOR, _EXECUTOR_WORKERS
    with _EXECUTOR_LOCK:
        if _EXECUTOR is None or _EXECUTOR_WORKERS != max_workers:
            if _EXECUTOR is not None:
                _EXECUTOR.shutdown(wait=False)
            _EXECUTOR = ThreadPoolExecutor(max_workers=max_workers)
            _EXECUTOR_WORKERS = max_workers
        return _EXECUTOR


def get_parser_concurrency() -> int:
    """Return the number of concurrent workers configured for the parser."""
    try:
        flags = get_flags()
    except Exception:
        flags = None

    if flags is not None:
        if getattr(flags, "SINGLE_THREADED", False):
            return 1
        custom_concurrency = getattr(flags, "PARSER_CONCURRENCY", None)
        if custom_concurrency is not None:
            try:
                val = int(custom_concurrency)
                if val > 0:
                    return val
            except (ValueError, TypeError):
                pass

    env_concurrency = os.environ.get("DBT_ENGINE_PARSER_CONCURRENCY")
    if env_concurrency is not None:
        try:
            val = int(env_concurrency)
            if val > 0:
                return val
        except (ValueError, TypeError):
            pass

    return DEFAULT_MAX_WORKERS


def parallel_map(
    func: Callable[[T], R],
    items: Iterable[T],
    max_workers: Optional[int] = None,
    chunksize: int = 1,
) -> List[R]:
    """Execute func over items in parallel when concurrency > 1, or sequentially otherwise."""
    item_list = list(items)
    if not item_list:
        return []

    workers = max_workers if max_workers is not None else get_parser_concurrency()

    # Short-circuit sequential path for single worker or small batches
    if workers <= 1 or len(item_list) <= 1:
        return [func(item) for item in item_list]

    # Bound workers to item count
    actual_workers = min(workers, len(item_list))
    executor = get_shared_executor(actual_workers)
    return list(executor.map(func, item_list, chunksize=chunksize))


def mp_parallel_map(
    func: Callable[[T], R],
    items: Iterable[T],
    max_workers: Optional[int] = None,
    chunksize: int = 1,
) -> List[R]:
    """Execute top-level picklable func over items using multiprocessing Pool across CPU cores."""
    item_list = list(items)
    if not item_list:
        return []

    workers = max_workers if max_workers is not None else get_parser_concurrency()

    if workers <= 1 or len(item_list) <= 1:
        return [func(item) for item in item_list]

    actual_workers = min(workers, len(item_list))
    try:
        from dbt.mp_context import get_mp_context

        ctx = get_mp_context()
        with ctx.Pool(processes=actual_workers) as pool:
            return pool.map(func, item_list, chunksize=max(1, chunksize))
    except Exception:
        # Fallback to parallel_map (threads) if multiprocessing encounters environment constraints
        return parallel_map(func, item_list, max_workers=actual_workers, chunksize=chunksize)
