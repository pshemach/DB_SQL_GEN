"""Verification for DuckDB local transforms."""

from loguru import logger


def verify_imports():
    try:
        import duckdb
        import pandas as pd

        con = duckdb.connect(database=":memory:")
        res = con.execute("SELECT 42 AS value").fetchone()
        logger.info(f"DuckDB check: {res[0]}")
        from src.memory.result_store import result_cache
        logger.info(f"result cache ready: {result_cache is not None}")
        return True
    except Exception as e:
        logger.error(f"Verification import failed: {e}")
        return False


if __name__ == "__main__":
    ok = verify_imports()
    raise SystemExit(0 if ok else 1)
