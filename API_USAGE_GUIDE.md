# Unified Query API - Usage Guide

## Overview

The `/query` endpoint now handles **both** initial queries and clarification responses in a single unified conversation flow. This makes the API simpler and more conversational.

---

## API Workflow

### Step 1: Send Initial Query

```bash
POST /query
Content-Type: application/json

{
  "question": "What are our sales this month?",
  "use_cache": true,
  "max_iterations": 3
}
```

### Possible Responses:

#### Response A: Query Succeeded ✅

```json
{
  "success": true,
  "sql_query": "SELECT SUM(amount) FROM sales WHERE MONTH(date) = MONTH(NOW())",
  "result_preview": "[[1250000]]\nTotal Sales: $1,250,000",
  "plan": "1. Identify metric: Net Sales\n2. Filter: Current month\n3. Aggregate: SUM",
  "relevant_tables": ["sales", "products"],
  "execution_time_ms": 156,
  "total_latency_ms": 1234,
  "iterations": 0,
  "cache_hit": false,
  "clarification_needed": false,
  "success": true
}
```

#### Response B: Clarification Needed 🤔

```json
{
  "success": null,
  "clarification_needed": true,
  "turn_id": "turn_1683024593.451",
  "clarification_request": {
    "instructions": "I need some clarifications to better understand your request.\nPlease answer the following questions:",
    "questions": [
      {
        "gap_id": "metric_sales_definition",
        "gap_type": "metric",
        "question": "By 'sales', do you mean NET sales (after returns) or GROSS sales?",
        "examples": [
          "Net sales (after deducting returns)",
          "Gross sales (total invoice amounts)",
          "Adjusted sales (per company policy)"
        ],
        "hint": "Check your business dashboard - most commonly refers to Net Sales"
      },
      {
        "gap_id": "time_period_clarification",
        "gap_type": "time_period",
        "question": "By 'this month', do you mean calendar month or fiscal month?",
        "examples": [
          "Calendar month (Jan-Dec)",
          "Fiscal month (as per company calendar)"
        ],
        "hint": "Your company typically uses calendar months unless specified otherwise"
      }
    ],
    "max_retries_remaining": 2,
    "response_endpoint": "/query"
  }
}
```

#### Response C: Query Failed ❌

```json
{
  "success": false,
  "clarification_needed": false,
  "error": "Could not find relevant tables for your query",
  "error_details": {
    "exception": "NoTablesFoundError: Schema does not contain 'revenue' table"
  }
}
```

---

### Step 2: Send Clarification Response (if needed)

If you received Response B, send clarification responses using the same `/query` endpoint:

```bash
POST /query
Content-Type: application/json

{
  "question": "What are our sales this month?",
  "turn_id": "turn_1683024593.451",
  "clarification_responses": {
    "metric_sales_definition": "Net sales (after deducting returns)",
    "time_period_clarification": "Calendar month (Jan-Dec)"
  }
}
```

### Step 3: Receive Updated Response

The system will now process your clarifications and return one of the three response types (Success, More Clarifications Needed, or Failed).

---

## Client Implementation Examples

### Python (requests)

```python
import requests
import json

BASE_URL = "http://localhost:8000"

# Step 1: Send query
query_request = {
    "question": "What are our sales this month?",
    "use_cache": True
}

response = requests.post(f"{BASE_URL}/query", json=query_request)
result = response.json()

print(f"Clarification needed: {result['clarification_needed']}")

# Step 2: If clarification needed, ask user and respond
if result['clarification_needed']:
    turn_id = result['turn_id']

    # Display questions to user (in real app, this would be UI)
    for question in result['clarification_request']['questions']:
        print(f"\n{question['question']}")
        print(f"Examples: {', '.join(question['examples'])}")

    # Get user responses (simplified for example)
    user_responses = {
        "metric_sales_definition": "Net sales (after deducting returns)",
        "time_period_clarification": "Calendar month (Jan-Dec)"
    }

    # Step 3: Send clarification response
    clarification_request = {
        "question": query_request["question"],
        "turn_id": turn_id,
        "clarification_responses": user_responses
    }

    response = requests.post(f"{BASE_URL}/query", json=clarification_request)
    result = response.json()

# Final result
if result['success']:
    print(f"\nSQL Query: {result['sql_query']}")
    print(f"Results:\n{result['result_preview']}")
elif result['success'] is False:
    print(f"Error: {result['error']}")
```

### JavaScript (fetch)

```javascript
const BASE_URL = "http://localhost:8000";

async function queryDatabase(question) {
  let queryRequest = {
    question: question,
    use_cache: true,
  };

  // Step 1: Send query
  let response = await fetch(`${BASE_URL}/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(queryRequest),
  });

  let result = await response.json();

  // Step 2: Handle clarification if needed
  if (result.clarification_needed) {
    console.log("Clarification needed:");
    console.log(result.clarification_request.instructions);

    // In a real app, show questions in UI and get user input
    const userResponses = await getUserResponses(
      result.clarification_request.questions,
    );

    // Step 3: Send clarification response
    const clarificationRequest = {
      question: question,
      turn_id: result.turn_id,
      clarification_responses: userResponses,
    };

    response = await fetch(`${BASE_URL}/query`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(clarificationRequest),
    });

    result = await response.json();
  }

  // Return final result
  return result;
}

// Usage
const queryResult = await queryDatabase("What are our sales this month?");
console.log(queryResult);
```

### cURL

```bash
# Step 1: Send initial query
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What are our sales this month?",
    "use_cache": true
  }' \
  | jq .

# Step 2 (if clarification needed): Send clarification response
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What are our sales this month?",
    "turn_id": "turn_1683024593.451",
    "clarification_responses": {
      "metric_sales_definition": "Net sales (after deducting returns)",
      "time_period_clarification": "Calendar month (Jan-Dec)"
    }
  }' \
  | jq .
```

---

## Response Status Reference

| Scenario                   | `success` | `clarification_needed` | What to do                                                                             |
| -------------------------- | --------- | ---------------------- | -------------------------------------------------------------------------------------- |
| Query succeeded            | `true`    | `false`                | Display SQL and results                                                                |
| Clarification needed       | `null`    | `true`                 | Show questions, wait for user input, resend with `turn_id` + `clarification_responses` |
| Query failed               | `false`   | `false`                | Display error message                                                                  |
| More clarifications needed | `null`    | `true`                 | Show new questions (rare)                                                              |

---

## Architecture Benefits

### Before (Separate Endpoints)

```
POST /query → response
POST /clarify → response  ❌ Extra endpoint, confusing
```

### After (Unified Endpoint)

```
POST /query → response
  ├─ If clarification: return turn_id
  └─ Client sends: turn_id + responses
       └─ POST /query → final response ✅ Single flow
```

---

## Chat History & Memory

The system automatically maintains conversation memory:

- **Conversation Turns**: Each query + response is recorded
- **Clarifications Log**: All user clarifications are stored
- **Enriched Context**: Previous clarifications are available to future queries

This means if you ask about the same KPI later, the bot remembers your previous definitions!

---

## Best Practices

1. **Always check `clarification_needed`** in the response
2. **Include the original question** with clarification responses
3. **Use the `turn_id`** provided to link clarification responses to the request
4. **Display examples to users** to help them answer questions
5. **Retry with same parameters** if the bot asks for more clarifications

---

## Error Handling

```python
try:
    response = requests.post(f"{BASE_URL}/query", json=query_request)
    response.raise_for_status()
    result = response.json()

    if result['success'] is False:
        # Query failed
        print(f"Error: {result['error']}")
        if result.get('error_details'):
            print(f"Details: {result['error_details']}")

except requests.exceptions.RequestException as e:
    print(f"API error: {e}")
```

---

## Rate Limiting

No rate limits currently enforced. Monitor system resources for long-running queries.

---

## Version History

- **v1.0.0** (May 2026): Unified query endpoint with conversation memory
