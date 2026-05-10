from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["similarity"])

@router.get("/")
async def similarity_root():
    return {"message": "Similarity API"}
