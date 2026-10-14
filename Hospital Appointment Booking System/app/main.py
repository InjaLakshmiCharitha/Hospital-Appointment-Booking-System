
from fastapi import FastAPI
from pathlib import Path
from fastapi.responses import FileResponse

from app.routers import auth
from app.routers import departments
from app.routers import doctors
from app.routers import schedules
from app.routers import leaves
from app.routers import appointments
from app.routers import consultations
from app.routers import files
from app.routers import patient
from app.routers import queue
from app.routers import notifications
from app.routers import reports
from app.routers import ratings

from contextlib import asynccontextmanager

from app.jobs.scheduler import start_scheduler, stop_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(
    title="Hospital Appointment Booking System",
    version="1.0.0",
    lifespan=lifespan
)

BASE_DIR = Path(__file__).resolve().parent.parent


@app.get("/queue-test", include_in_schema=False)
def queue_test_page():
    return FileResponse(BASE_DIR / "static" / "queue_test.html")

app.include_router(auth.router)
app.include_router(departments.router)
app.include_router(doctors.router)
app.include_router(schedules.router)
app.include_router(leaves.router)
app.include_router(appointments.router)
app.include_router(consultations.router)
app.include_router(files.router)
app.include_router(patient.router)
app.include_router(queue.router)
app.include_router(notifications.router)
app.include_router(reports.router)
app.include_router(ratings.router)

@app.get("/")
def root():
    return {"message": "Hospital Appointment Booking System API is running"}
