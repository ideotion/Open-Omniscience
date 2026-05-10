from fastapi import APIRouter, Depends
from typing import List
from pydantic import BaseModel
from sqlalchemy.orm import Session
from ..database.session import get_db
from ..database.models import Source

router = APIRouter(tags=["sources"])

class SourceResponse(BaseModel):
    id: str
    url: str
    domain: str
    source_type: str

@router.get("/", response_model=List[SourceResponse])
async def list_sources(db: Session = Depends(get_db)):
    sources = db.query(Source).all()
    return [SourceResponse(id=s.id, url=s.url, domain=s.domain, source_type=s.source_type) for s in sources]
