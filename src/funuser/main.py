from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .database.database import engine
from .models import user
from .routers import user as user_router

# Create database tables
user.Base.metadata.create_all(bind=engine)

app = FastAPI(title="User Management System")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(user_router.router, prefix="/api/v1", tags=["users"])
