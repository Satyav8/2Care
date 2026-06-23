import os
import random
import string
from datetime import datetime, date, timedelta
from typing import Optional
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db, engine
from models import Base, Doctor, Appointment, AppointmentStatus
from seed import seed

Base.metadata.create_all(bind=engine)
seed()

app = FastAPI(title="Apollo Voice Receptionist API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

DAY_MAP = {"Monday": "Mon", "Tuesday": "Tue", "Wednesday": "Wed",
           "Thursday": "Thu", "Friday": "Fri", "Saturday": "Sat", "Sunday": "Sun"}


def _confirmation_code():
    return "APL" + "".join(random.choices(string.digits, k=6))


def _find_doctor(name: str, db: Session) -> Doctor | None:
    """Multi-strategy fuzzy match: substring → any word match → first name only."""
    # Strategy 1: direct substring
    doc = db.query(Doctor).filter(Doctor.name.ilike(f"%{name}%")).first()
    if doc:
        return doc
    # Strategy 2: match any word in the query against any word in the name
    words = [w for w in name.lower().split() if len(w) > 2]
    for word in words:
        doc = db.query(Doctor).filter(Doctor.name.ilike(f"%{word}%")).first()
        if doc:
            return doc
    return None


def _slots_for_doctor(doctor: Doctor, on_date: date) -> list[str]:
    """Return list of HH:MM slot strings for a doctor on a given date."""
    day_abbr = on_date.strftime("%a")  # Mon, Tue …
    if day_abbr not in doctor.available_days.split(","):
        return []
    start_h, start_m = map(int, doctor.start_time.split(":"))
    end_h, end_m = map(int, doctor.end_time.split(":"))
    slots = []
    current = datetime.combine(on_date, datetime.min.time()).replace(hour=start_h, minute=start_m)
    end_dt = datetime.combine(on_date, datetime.min.time()).replace(hour=end_h, minute=end_m)
    while current < end_dt:
        slots.append(current.strftime("%H:%M"))
        current += timedelta(minutes=doctor.slot_duration_mins)
    return slots


def _booked_slots(doctor_id: int, on_date: date, db: Session) -> set[str]:
    appts = db.query(Appointment).filter(
        Appointment.doctor_id == doctor_id,
        Appointment.status == AppointmentStatus.scheduled,
    ).all()
    return {
        a.appointment_datetime.strftime("%H:%M")
        for a in appts
        if a.appointment_datetime.date() == on_date
    }


# ── Request / Response schemas ─────────────────────────────────────────────

class ListDoctorsReq(BaseModel):
    department: Optional[str] = None
    specialization: Optional[str] = None

class CheckSlotsReq(BaseModel):
    doctor_name: str
    date: str  # YYYY-MM-DD

class BookReq(BaseModel):
    patient_name: str
    patient_phone: str
    doctor_name: str
    date: str        # YYYY-MM-DD
    time: str        # HH:MM
    reason: Optional[str] = ""

class RescheduleReq(BaseModel):
    confirmation_code: str
    new_date: str    # YYYY-MM-DD
    new_time: str    # HH:MM

class CancelReq(BaseModel):
    confirmation_code: str

class LookupReq(BaseModel):
    patient_phone: str


# ── Endpoints ──────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/seed")
def run_seed(db: Session = Depends(get_db)):
    count = db.query(Doctor).count()
    if count > 0:
        return {"status": "already seeded", "doctors": count}
    from seed import DOCTORS
    for d in DOCTORS:
        db.add(Doctor(**d))
    db.commit()
    return {"status": "seeded", "doctors": len(DOCTORS)}


@app.post("/list_doctors")
def list_doctors(req: ListDoctorsReq, db: Session = Depends(get_db)):
    q = db.query(Doctor)
    if req.department:
        q = q.filter(Doctor.department.ilike(f"%{req.department}%"))
    if req.specialization:
        q = q.filter(Doctor.specialization.ilike(f"%{req.specialization}%"))
    doctors = q.all()
    return {
        "doctors": [
            {
                "name": d.name,
                "department": d.department,
                "specialization": d.specialization,
                "available_days": d.available_days,
            }
            for d in doctors
        ]
    }


@app.post("/check_slots")
def check_slots(req: CheckSlotsReq, db: Session = Depends(get_db)):
    doctor = _find_doctor(req.doctor_name, db)
    if not doctor:
        raise HTTPException(404, "Doctor not found")
    try:
        on_date = date.fromisoformat(req.date)
    except ValueError:
        raise HTTPException(400, "date must be YYYY-MM-DD")
    all_slots = _slots_for_doctor(doctor, on_date)
    if not all_slots:
        return {"available_slots": [], "message": f"{doctor.name} is not available on {req.date}"}
    booked = _booked_slots(doctor.id, on_date, db)
    free = [s for s in all_slots if s not in booked]
    return {
        "doctor": doctor.name,
        "date": req.date,
        "available_slots": free,
        "next_available": free[0] if free else None,
    }


@app.post("/book_appointment")
def book_appointment(req: BookReq, db: Session = Depends(get_db)):
    doctor = _find_doctor(req.doctor_name, db)
    if not doctor:
        raise HTTPException(404, "Doctor not found")
    try:
        appt_dt = datetime.strptime(f"{req.date} {req.time}", "%Y-%m-%d %H:%M")
    except ValueError:
        raise HTTPException(400, "date must be YYYY-MM-DD and time HH:MM")

    # Check slot is valid
    on_date = appt_dt.date()
    free = _slots_for_doctor(doctor, on_date)
    booked = _booked_slots(doctor.id, on_date, db)
    if req.time not in free or req.time in booked:
        # suggest alternatives
        alt = [s for s in free if s not in booked][:3]
        return {
            "success": False,
            "message": f"Slot {req.time} is unavailable.",
            "alternatives": alt,
        }

    code = _confirmation_code()
    appt = Appointment(
        patient_name=req.patient_name,
        patient_phone=req.patient_phone,
        doctor_id=doctor.id,
        appointment_datetime=appt_dt,
        reason=req.reason,
        confirmation_code=code,
    )
    db.add(appt)
    db.commit()
    return {
        "success": True,
        "confirmation_code": code,
        "message": (
            f"Appointment confirmed with {doctor.name} ({doctor.department}) "
            f"on {req.date} at {req.time}. Confirmation code: {code}."
        ),
    }


@app.post("/reschedule_appointment")
def reschedule_appointment(req: RescheduleReq, db: Session = Depends(get_db)):
    appt = db.query(Appointment).filter(
        Appointment.confirmation_code == req.confirmation_code,
        Appointment.status == AppointmentStatus.scheduled,
    ).first()
    if not appt:
        raise HTTPException(404, "Appointment not found or already cancelled")

    doctor = appt.doctor
    try:
        new_dt = datetime.strptime(f"{req.new_date} {req.new_time}", "%Y-%m-%d %H:%M")
    except ValueError:
        raise HTTPException(400, "new_date must be YYYY-MM-DD and new_time HH:MM")

    on_date = new_dt.date()
    free = _slots_for_doctor(doctor, on_date)
    booked = _booked_slots(doctor.id, on_date, db)
    booked.discard(appt.appointment_datetime.strftime("%H:%M"))  # don't count self

    if req.new_time not in free or req.new_time in booked:
        alt = [s for s in free if s not in booked][:3]
        return {"success": False, "message": "Slot unavailable.", "alternatives": alt}

    appt.appointment_datetime = new_dt
    db.commit()
    return {
        "success": True,
        "message": (
            f"Appointment rescheduled to {req.new_date} at {req.new_time} "
            f"with {doctor.name}. Confirmation code unchanged: {req.confirmation_code}."
        ),
    }


@app.post("/cancel_appointment")
def cancel_appointment(req: CancelReq, db: Session = Depends(get_db)):
    appt = db.query(Appointment).filter(
        Appointment.confirmation_code == req.confirmation_code,
        Appointment.status == AppointmentStatus.scheduled,
    ).first()
    if not appt:
        raise HTTPException(404, "Appointment not found or already cancelled")
    appt.status = AppointmentStatus.cancelled
    db.commit()
    return {
        "success": True,
        "message": f"Appointment with {appt.doctor.name} on {appt.appointment_datetime.strftime('%Y-%m-%d at %H:%M')} has been cancelled.",
    }


@app.post("/lookup_appointments")
def lookup_appointments(req: LookupReq, db: Session = Depends(get_db)):
    appts = db.query(Appointment).filter(
        Appointment.patient_phone == req.patient_phone,
        Appointment.status == AppointmentStatus.scheduled,
    ).all()
    return {
        "appointments": [
            {
                "confirmation_code": a.confirmation_code,
                "doctor": a.doctor.name,
                "department": a.doctor.department,
                "datetime": a.appointment_datetime.strftime("%Y-%m-%d %H:%M"),
                "reason": a.reason,
            }
            for a in appts
        ]
    }
