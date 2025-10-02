from fastapi import APIRouter, UploadFile, Form
from services.review import build_review

router = APIRouter(prefix="/games", tags=["games"])

@router.post("/review")
async def review_game(pgn: str = Form(...)):
    """
    Accept PGN text and return JSON review.
    """
    return await build_review(pgn)
