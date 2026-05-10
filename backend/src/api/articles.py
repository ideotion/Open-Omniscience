from fastapi import APIRouter, Depends
from typing import List, Optional
from pydantic import BaseModel
from sqlalchemy.orm import Session
from ..database.session import get_db
from ..database.models import Article

router = APIRouter(tags=["articles"])

class ArticleResponse(BaseModel):
    id: str
    title: str
    word_count: int

@router.get("/", response_model=List[ArticleResponse])
async def list_articles(db: Session = Depends(get_db)):
    articles = db.query(Article).all()
    return [ArticleResponse(id=a.id, title=a.title, word_count=a.word_count) for a in articles]
