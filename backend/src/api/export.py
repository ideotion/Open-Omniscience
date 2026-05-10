from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["export"])

@router.get("/")
async def export_root():
    return {"message": "Export API"}
