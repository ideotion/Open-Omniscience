from fastapi import APIRouter, Depends
from typing import List
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func
from ..database.session import get_db
from ..database.models import Article, Keyword, Source

router = APIRouter(tags=["dashboard"])

class StatCard(BaseModel):
    label: str
    value: str

@router.get("/stats", response_model=List[StatCard])
async def get_stats(db: Session = Depends(get_db)):
    total_articles = db.query(Article).count()
    total_keywords = db.query(Keyword).count()
    total_sources = db.query(Source).count()
    total_words = db.query(func.sum(Article.word_count)).scalar() or 0
    return [
        StatCard(label="Total Articles", value=str(total_articles)),
        StatCard(label="Total Keywords", value=str(total_keywords)),
        StatCard(label="Total Sources", value=str(total_sources)),
        StatCard(label="Total Words", value=f"{total_words:,}")
    ]
