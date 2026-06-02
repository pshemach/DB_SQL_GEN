"""
Verification script for Text-to-SQL system in-memory transforms and dialogue orchestrator updates.
"""

import sys
from loguru import logger

def verify_imports():
    try:
        logger.info("Verifying module imports...")
        import pandas as pd
        import duckdb
        logger.info("✓ Core libraries (pandas, duckdb) imported successfully.")
        
        # Test DuckDB
        con = duckdb.connect(database=':memory:')
        res = con.execute("SELECT 42 AS value").fetchone()
        logger.info(f"✓ DuckDB query execution check: {res[0]} (Expected: 42)")
        
        # Test local components
        from src.agents.tools.local_sql_engine import local_sql_engine
        from src.agents.agent.table_analyst import table_analyst
        from src.agents.agent.result_transformer import result_transformer
        from src.agents.agent.turn_router import TurnRouterAgent
        
        logger.info("✓ Custom agent modules imported successfully.")
        return True
    except Exception as e:
        logger.error(f"✗ Verification import failed: {e}")
        return False

def verify_local_duckdb_execution():
    from src.agents.tools.local_sql_engine import local_sql_engine
    
    mock_data = [
        {"rep_name": "Alice", "region": "East", "sales": 15000},
        {"rep_name": "Bob", "region": "West", "sales": 8000},
        {"rep_name": "Charlie", "region": "East", "sales": 23000},
    ]
    mock_schema = {"rep_name": "str", "region": "str", "sales": "int"}
    
    follow_up = "Sort the reps by sales descending and filter to only show routes in the East region"
    
    logger.info(f"Running mock follow-up: '{follow_up}'")
    needs_live_db, results, explanation = local_sql_engine.execute_follow_up(
        follow_up_question=follow_up,
        cached_data=mock_data,
        schema=mock_schema
    )
    
    if needs_live_db:
        logger.error("✗ In-memory execution erroneously indicated live DB query needed.")
        return False
        
    logger.info(f"✓ Transformed Rows: {results}")
    logger.info(f"✓ Explanation: {explanation}")
    
    # Assertions
    if len(results) != 2:
        logger.error(f"✗ Expected 2 rows, got {len(results)}")
        return False
        
    if results[0]["rep_name"] != "Charlie" or results[1]["rep_name"] != "Alice":
        logger.error("✗ Sorting logic failed. Charlie (23000) should be before Alice (15000).")
        return False
        
    logger.info("✓ Local DuckDB query execution verified successfully!")
    return True

if __name__ == "__main__":
    logger.info("=== TEXT-TO-SQL AGENT VERIFICATION ===")
    success = verify_imports()
    if success:
        success = verify_local_duckdb_execution()
        
    if success:
        logger.info("=== ALL VERIFICATION CHECKS PASSED SUCCESSFULLY! ===")
        sys.exit(0)
    else:
        logger.error("=== VERIFICATION CHECKS FAILED ===")
        sys.exit(1)
