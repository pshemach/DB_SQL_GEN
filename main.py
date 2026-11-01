"""Start the Text-to-SQL API and the web UI it serves.

    python main.py
"""

import uvicorn

if __name__ == "__main__":
    uvicorn.run("src.api:app", host="0.0.0.0", port=8688, reload=True)
