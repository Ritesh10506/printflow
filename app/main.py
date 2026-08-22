from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.database import Base, engine
from app.routers import shops, printers, pricing, orders, payments, agents

Base.metadata.create_all(bind=engine)

app = FastAPI(title="PrintFlow API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten to your actual frontend domains before going live
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/files", StaticFiles(directory="uploads"), name="files")

app.include_router(shops.router)
app.include_router(printers.router)
app.include_router(pricing.router)
app.include_router(orders.router)
app.include_router(payments.router)
app.include_router(agents.router)


@app.get("/")
def root():
    return {"status": "ok", "service": "PrintFlow API"}
