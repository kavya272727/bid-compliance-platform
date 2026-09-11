from fastapi import FastAPI
from backend.routes.ai_reasoning import router as ai_reasoning_router
from backend.routes.compliance import router as compliance_router
from backend.routes.documents import router as documents_router
from backend.routes.mock_government import router as mock_government_router
from backend.routes.verification import router as verification_router

app = FastAPI(title="Bid Compliance Platform")

app.include_router(verification_router)
app.include_router(mock_government_router)
app.include_router(documents_router)
app.include_router(ai_reasoning_router)
app.include_router(compliance_router)


@app.get("/")
def root():
    return {"message": "Bid Compliance Platform API is running"}


@app.get("/health")
def health():
    return {"status": "healthy"}