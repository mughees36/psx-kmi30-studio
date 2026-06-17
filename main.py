from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from database import Base, engine, run_migrations
from auth import auth_routes
from routes import stocks


app = FastAPI()

# Create tables
Base.metadata.create_all(bind=engine)
run_migrations()

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
def serve_frontend():
    return FileResponse("static/index.html")

@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)
    run_migrations()

# Routes

app.include_router(auth_routes.router)
app.include_router(stocks.router)
