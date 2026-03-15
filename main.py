"""Entry point — run the FastAPI server."""

import uvicorn
from app.config import settings

if __name__ == "__main__":
    uvicorn.run(
        "app.api:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        reload=True,
    )
