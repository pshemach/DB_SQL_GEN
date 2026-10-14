from fastapi import APIRouter, HTTPException
from loguru import logger

from ...core import db_manager

router = APIRouter(prefix="/schema", tags=["schema"])


@router.get("/tables")
async def get_tables():
    try:
        tables = db_manager.get_all_table_names()
        return {"tables": tables, "count": len(tables)}
    except Exception as e:
        logger.error(f"Error fetching tables: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/table/{table_name}")
async def get_table_schema(table_name: str):
    try:
        metadata = db_manager.get_table_metadata(table_name)
        schema = db_manager.get_schema_for_tables([table_name])
        return {
            "table_name": table_name,
            "metadata": metadata,
            "schema": schema,
        }
    except Exception as e:
        logger.error(f"Error fetching schema for {table_name}: {e}")
        raise HTTPException(status_code=404, detail=f"Table not found: {table_name}")
