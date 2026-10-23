"""Manual check that local transform needs a cached session result."""

from src.memory.result_store import result_cache


def main():
    session_id = "demo-session"
    result_cache.cache_result(
        session_id=session_id,
        question="net sales by rep",
        sql="SELECT 1",
        data=[{"RepName": "A", "NetSales": 100.0}, {"RepName": "B", "NetSales": 80.0}],
        tables=["sales_flat"],
        schema={"RepName": "str", "NetSales": "float"},
    )
    cached = result_cache.get_cached_result(session_id)
    assert cached is not None
    print(f"cached {len(cached.result_data)} rows for session {session_id}")


if __name__ == "__main__":
    main()
