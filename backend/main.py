from fastapi import FastAPI

app = FastAPI(title="Bid Compliance Platform")


@app.get("/")
def root():
    return {"message": "Bid Compliance Platform API is running"}


@app.get("/health")
def health():
    return {"status": "healthy"}