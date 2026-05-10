from fastapi import APIRouter, Depends
from typing import List
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from ..database.session import get_db
from ..database.models import Keyword, KeywordAppearance

router = APIRouter(tags=["keywords"])

class KeywordResponse(BaseModel):
    id: str
    name: str
    article_count: int

@router.get("/", response_model=List[KeywordResponse])
async def list_keywords(db: Session = Depends(get_db)):
    query = db.query(Keyword, func.count(KeywordAppearance.keyword_id).label("article_count")).join(KeywordAppearance, Keyword.id == KeywordAppearance.keyword_id).group_by(Keyword.id)
    keywords = query.all()
    return [KeywordResponse(id=k.id, name=k.name, article_count=ac) for k, ac in keywords]
