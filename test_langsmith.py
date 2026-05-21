#!/usr/bin/env python3
"""
Quick test to verify LangSmith integration is working.
"""

import asyncio
import time
from langsmith import traceable
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()

# Verify env vars are loaded
print("=" * 60)
print("🔍 LANGSMITH CONFIGURATION CHECK")
print("=" * 60)

config = {
    "LANGCHAIN_TRACING_V2": os.getenv("LANGCHAIN_TRACING_V2"),
    "LANGCHAIN_API_KEY": os.getenv("LANGCHAIN_API_KEY", "NOT SET")[:20] + "...",
    "LANGCHAIN_PROJECT": os.getenv("LANGCHAIN_PROJECT"),
    "LANGCHAIN_ENDPOINT": os.getenv("LANGCHAIN_ENDPOINT"),
}

for key, value in config.items():
    print(f"✓ {key}: {value}")

print("\n" + "=" * 60)
print("🧪 RUNNING TRACED FUNCTIONS TEST")
print("=" * 60 + "\n")


@traceable(name="test_sync_function", run_type="chain", tags=["test", "sync"])
def test_sync_function(text: str) -> str:
    """Simple synchronous traced function."""
    print(f"  ✓ test_sync_function called with: '{text}'")
    time.sleep(0.5)  # Simulate work
    return f"Processed: {text}"


@traceable(name="test_async_function", run_type="chain", tags=["test", "async"])
async def test_async_function(text: str) -> str:
    """Simple asynchronous traced function."""
    print(f"  ✓ test_async_function called with: '{text}'")
    await asyncio.sleep(0.5)  # Simulate work
    return f"Async Processed: {text}"


@traceable(name="test_nested_trace", run_type="chain", tags=["test", "nested"])
def test_nested_trace():
    """Nested traced function calls."""
    print(f"  ✓ test_nested_trace called")
    result1 = test_sync_function("first call")
    result2 = test_sync_function("second call")
    return f"Nested results: {result1}, {result2}"


async def main():
    """Run all tests."""
    print("1️⃣  Testing sync trace...")
    result1 = test_sync_function("Hello LangSmith")
    print(f"   Result: {result1}\n")

    print("2️⃣  Testing async trace...")
    result2 = await test_async_function("Async Hello")
    print(f"   Result: {result2}\n")

    print("3️⃣  Testing nested traces...")
    result3 = test_nested_trace()
    print(f"   Result: {result3}\n")

    print("=" * 60)
    print("✅ ALL TESTS COMPLETED!")
    print("=" * 60)
    print("\n📊 CHECK LANGSMITH DASHBOARD:")
    print(f"   Project: {os.getenv('LANGCHAIN_PROJECT')}")
    print(f"   URL: {os.getenv('LANGCHAIN_ENDPOINT')}/projects")
    print("\n⏱️  Traces may take 5-10 seconds to appear in LangSmith dashboard.")
    print("   Look for runs with tags: 'test', 'sync', 'async', 'nested'\n")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
