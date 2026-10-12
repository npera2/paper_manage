from fastapi import APIRouter

router = APIRouter(prefix="/papers", tags=["papers"])


@router.get("")
def list_pappers() -> list:
    return []
