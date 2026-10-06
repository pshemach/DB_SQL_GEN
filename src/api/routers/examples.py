from fastapi import APIRouter, BackgroundTasks, HTTPException
from loguru import logger

from ...agents.tools import few_shot_retriever, seed_examples
from ..data_models import ExampleRequest

router = APIRouter(tags=["examples"])


@router.post("/examples")
async def add_example(request: ExampleRequest):
    try:
        few_shot_retriever.add_example(
            question=request.question,
            sql=request.sql,
            explanation=request.explanation,
            complexity=request.complexity,
        )
        return {"message": "Example added successfully"}
    except Exception as e:
        logger.error(f"Error adding example: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/examples/seed")
async def seed_default_examples(background_tasks: BackgroundTasks):
    try:
        background_tasks.add_task(seed_examples)
        return {"message": "Seeding examples in background"}
    except Exception as e:
        logger.error(f"Error seeding examples: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/examples/search")
async def search_examples(query: str, k: int = 3):
    try:
        examples = few_shot_retriever.retrieve(query, k=k)
        return {"examples": examples, "count": len(examples)}
    except Exception as e:
        logger.error(f"Error searching examples: {e}")
        raise HTTPException(status_code=500, detail=str(e))
