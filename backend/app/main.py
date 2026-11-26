from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .database import Base, engine
from .routers import (
    auth_router,
    batches_router,
    claims_router,
    corrections_router,
    offers_router,
    payments_router,
)

# 导入模型以注册 metadata
from . import models  # noqa: F401

settings = get_settings()

app = FastAPI(
    title="地震理赔办理平台 API",
    description="报案人 / 查勘员 / 理算员 / 付款复核员共用的分项核实、和解与付款平台（含支付模拟器）",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router.router)
app.include_router(claims_router.router)
app.include_router(offers_router.router)
app.include_router(batches_router.router)
app.include_router(payments_router.router)
app.include_router(corrections_router.router)


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)


@app.get("/health")
def health():
    return {"status": "ok"}
