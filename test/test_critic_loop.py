"""
Test script to verify the Critic Agent loop behavior.
Tests all scenarios: success, failure, max iterations, reflection errors, etc.

Usage:
    python scripts/test_critic_loop.py
"""

import sys 
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from typing import Any, Optional

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from loguru import logger
from src.agents.critic import CriticAgent
from src.config.config_management import settings

# Color codes for terminal output
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
RESET = "\033[0m"
BOLD = "\033[1m"

def print_header(text: str):
    """Print formatted header."""
    print(f"\n{BOLD}{BLUE}{'='*70}{RESET}")
    print(f"{BOLD}{BLUE}{text:^70}{RESET}")
    print(f"{BOLD}{BLUE}{'='*70}{RESET}\n")

def print_test(test_name: str):
    """Print test name."""
    print(f"\n{BOLD}{YELLOW}TEST: {test_name}{RESET}")
    print(f"{YELLOW}{'-'*70}{RESET}")

def print_result(passed: bool, message: str = ""):
    """Print test result."""
    status = f"{GREEN}✓ PASS{RESET}" if passed else f"{RED}✗ FAIL{RESET}"
    print(f"{status} {message}")

def verify_state(state: dict, expected: dict, test_name: str) -> bool:
    """Verify state matches expected values."""
    all_pass = True
    
    for key, expected_val in expected.items():
        actual_val = state.get(key)
        passed = actual_val == expected_val
        all_pass = all_pass and passed
        
        symbol = f"{GREEN}✓{RESET}" if passed else f"{RED}✗{RESET}"
        print(f"  {symbol} {key}: {actual_val} (expected: {expected_val})")
    
    return all_pass

# ============================================================================
# TEST 1: Query Execution SUCCESS
# ============================================================================
def test_query_success():
    """Test scenario: Query executes successfully."""
    print_test("Query Execution SUCCESS (should_retry = False)")
    
    critic = CriticAgent()
    
    # Mock the database manager to return success
    with patch('src.agents.critic.db_manager') as mock_db:
        mock_db.execute_query.return_value = (
            [{"id": 1, "name": "test"}],  # result
            None,  # error
            45.5  # exec_time
        )
        
        state = {
            "sql_query": "SELECT * FROM users",
            "iterations": 0,
        }
        
        result = critic.execute_and_validate(state)
        
        expected = {
            "error": None,
            "should_retry": False,
            "query_result": [{"id": 1, "name": "test"}],
            "execution_time_ms": 45.5
        }
        
        passed = verify_state(result, expected, "Query Success")
        print_result(passed, "Query succeeded - loop should STOP")
        return passed


# ============================================================================
# TEST 2: Query Execution FAILS (Retryable)
# ============================================================================
def test_query_fails_retryable():
    """Test scenario: Query fails but is retryable."""
    print_test("Query Execution FAILS (should_retry = True)")
    
    critic = CriticAgent()
    
    # Mock the database manager to return error
    with patch('src.agents.critic.db_manager') as mock_db:
        mock_db.execute_query.return_value = (
            None,  # result
            "Column 'invalid_col' does not exist",  # error
            12.3  # exec_time
        )
        
        state = {
            "sql_query": "SELECT invalid_col FROM users",
            "iterations": 0,
        }
        
        result = critic.execute_and_validate(state)
        
        expected = {
            "error": "Column 'invalid_col' does not exist",
            "should_retry": True,
            "error_type": "column_not_found",
            "query_result": None
        }
        
        passed = verify_state(result, expected, "Query Failure")
        print_result(passed, "Query failed - loop should CONTINUE to reflect node")
        return passed


# ============================================================================
# TEST 3: No SQL Query to Execute
# ============================================================================
def test_no_sql_query():
    """Test scenario: No SQL query provided."""
    print_test("No SQL Query Provided (should_retry = False)")
    
    critic = CriticAgent()
    
    state = {
        "sql_query": None,  # or missing
        "iterations": 0,
    }
    
    result = critic.execute_and_validate(state)
    
    expected = {
        "error": "No SQL query to execute",
        "should_retry": False,
    }
    
    passed = verify_state(result, expected, "No SQL Query")
    print_result(passed, "No query provided - loop should STOP (non-retryable)")
    return passed


# ============================================================================
# TEST 4: Reflection Succeeds (generates fixed SQL)
# ============================================================================
def test_reflection_success():
    """Test scenario: Reflection successfully generates fixed SQL."""
    print_test("Reflection SUCCESS (generates corrected SQL)")
    
    critic = CriticAgent()
    
    # Mock the LLM and generator
    with patch('src.agents.critic.ChatAnthropic') as mock_llm_class:
        mock_llm = Mock()
        mock_llm_class.return_value = mock_llm
        mock_llm.__or__ = Mock(return_value=mock_llm)
        mock_llm.invoke = Mock(return_value=Mock(content="SELECT col FROM users"))
        
        critic.llm = mock_llm
        
        with patch('src.agents.critic.SQLGeneratorAgent') as mock_gen_class:
            mock_gen = Mock()
            mock_gen_class.return_value = mock_gen
            mock_gen._clean_sql = Mock(return_value="SELECT col FROM users WHERE id=1")
            
            state = {
                "question": "Get user with id 1",
                "plan": "Retrieve user record",
                "schema_context": "users(id, col)",
                "sql_query": "SELECT invalid_col FROM users",
                "error": "Column 'invalid_col' does not exist",
                "iterations": 0,
            }
            
            result = critic.reflect_and_fix(state)
            
            expected = {
                "sql_query": "SELECT col FROM users WHERE id=1",
                "iterations": 1,
                "should_retry": True,
            }
            
            passed = verify_state(result, expected, "Reflection Success")
            print_result(passed, "Reflection succeeded - loop should CONTINUE with new query")
            return passed


# ============================================================================
# TEST 5: Reflection FAILS (exception thrown)
# ============================================================================
def test_reflection_fails():
    """Test scenario: Reflection fails with exception."""
    print_test("Reflection FAILS with Exception (should_retry = False)")
    
    critic = CriticAgent()
    
    # Mock the LLM to throw an exception
    with patch('src.agents.critic.ChatAnthropic') as mock_llm_class:
        mock_llm = Mock()
        mock_llm_class.return_value = mock_llm
        mock_llm.__or__ = Mock(return_value=mock_llm)
        mock_llm.invoke = Mock(side_effect=Exception("API Error: Rate limit exceeded"))
        
        critic.llm = mock_llm
        
        state = {
            "question": "Get user",
            "plan": "Retrieve user",
            "schema_context": "users table",
            "sql_query": "SELECT invalid_col FROM users",
            "error": "Column not found",
            "iterations": 0,
        }
        
        result = critic.reflect_and_fix(state)
        
        expected = {
            "should_retry": False,
            "iterations": 1,
            "error": "Failed to correct SQL: API Error: Rate limit exceeded"
        }
        
        passed = verify_state(result, expected, "Reflection Failure")
        print_result(passed, "Reflection crashed - loop should STOP (should_retry=False)")
        return passed


# ============================================================================
# TEST 6: Max Iterations Reached
# ============================================================================
def test_max_iterations_reached():
    """Test scenario: Maximum iterations exceeded."""
    print_test(f"Max Iterations Reached (max_iterations={settings.max_iterations})")
    
    critic = CriticAgent()
    
    # Set iterations to max
    state = {
        "question": "Get user",
        "plan": "Retrieve user",
        "schema_context": "users table",
        "sql_query": "SELECT invalid_col FROM users",
        "error": "Column not found",
        "iterations": settings.max_iterations,  # At max
    }
    
    result = critic.reflect_and_fix(state)
    
    expected = {
        "should_retry": False,
        "iterations": settings.max_iterations,
        "error": f"Failed to generate valid SQL after {settings.max_iterations} attempts"
    }
    
    passed = verify_state(result, expected, "Max Iterations")
    print_result(passed, "Max iterations reached - loop should STOP (should_retry=False)")
    return passed


# ============================================================================
# TEST 7: Execution Runtime Exception
# ============================================================================
def test_execution_runtime_error():
    """Test scenario: Runtime error during query execution."""
    print_test("Execution Runtime Error (should_retry = True)")
    
    critic = CriticAgent()
    
    # Mock the database manager to throw exception
    with patch('src.agents.critic.db_manager') as mock_db:
        mock_db.execute_query.side_effect = Exception("Connection timeout")
        
        state = {
            "sql_query": "SELECT * FROM users",
            "iterations": 0,
        }
        
        result = critic.execute_and_validate(state)
        
        expected = {
            "error": "Connection timeout",
            "should_retry": True,
            "error_type": "runtime",
        }
        
        passed = verify_state(result, expected, "Execution Runtime Error")
        print_result(passed, "Runtime error - loop should CONTINUE to reflect node")
        return passed


# ============================================================================
# TEST 8: Error Classification
# ============================================================================
def test_error_classification():
    """Test error type classification."""
    print_test("Error Classification")
    
    critic = CriticAgent()
    
    test_cases = [
        ("Column 'id' does not exist", "column_not_found", True),
        ("Table 'users' not found", "table_not_found", True),
        ("Syntax error near SELECT", "syntax_error", True),
        ("Ambiguous column reference", "ambiguous_column", True),
        ("Query execution timeout", "timeout", True),
        ("Unknown database error", "runtime_error", True),
    ]
    
    all_passed = True
    for error_msg, expected_type, _ in test_cases:
        actual_type = critic._classify_error(error_msg)
        passed = actual_type == expected_type
        all_passed = all_passed and passed
        
        symbol = f"{GREEN}✓{RESET}" if passed else f"{RED}✗{RESET}"
        print(f"  {symbol} '{error_msg}' → {actual_type} (expected: {expected_type})")
    
    return all_passed


# ============================================================================
# SUMMARY TEST
# ============================================================================
def print_summary(results: dict):
    """Print test summary."""
    print_header("TEST SUMMARY")
    
    total = len(results)
    passed = sum(1 for v in results.values() if v)
    failed = total - passed
    
    print(f"Total Tests: {total}")
    print(f"{GREEN}Passed: {passed}{RESET}")
    print(f"{RED}Failed: {failed}{RESET}\n")
    
    for test_name, passed in results.items():
        status = f"{GREEN}✓{RESET}" if passed else f"{RED}✗{RESET}"
        print(f"{status} {test_name}")
    
    if failed == 0:
        print(f"\n{GREEN}{BOLD}✓ ALL TESTS PASSED - CRITIC LOOP WORKING CORRECTLY{RESET}")
        return True
    else:
        print(f"\n{RED}{BOLD}✗ SOME TESTS FAILED - CHECK LOGIC{RESET}")
        return False


# ============================================================================
# MAIN
# ============================================================================
def main():
    print_header("CRITIC AGENT LOOP TEST SUITE")
    
    print(f"Configuration:")
    print(f"  • max_iterations: {settings.max_iterations}")
    print(f"  • enable_self_correction: {settings.enable_self_correction}")
    print(f"  • query_timeout_seconds: {settings.query_timeout_seconds}")
    
    results = {}
    
    try:
        results["Query Execution SUCCESS"] = test_query_success()
        results["Query Execution FAILS (Retryable)"] = test_query_fails_retryable()
        results["No SQL Query"] = test_no_sql_query()
        results["Reflection SUCCESS"] = test_reflection_success()
        results["Reflection FAILS"] = test_reflection_fails()
        results["Max Iterations Reached"] = test_max_iterations_reached()
        results["Execution Runtime Error"] = test_execution_runtime_error()
        results["Error Classification"] = test_error_classification()
        
    except Exception as e:
        print(f"\n{RED}{BOLD}ERROR: Test suite failed with exception:{RESET}")
        print(f"{RED}{str(e)}{RESET}")
        import traceback
        traceback.print_exc()
        return False
    
    # Print summary
    return print_summary(results)


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)