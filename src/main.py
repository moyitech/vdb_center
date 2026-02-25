from fastapi import FastAPI
from uvicorn import run
from src.router.kb import router as kb_router

app = FastAPI()

app.include_router(kb_router)


if __name__ == "__main__":
    run(app, host="0.0.0.0", port=8001)