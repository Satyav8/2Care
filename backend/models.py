from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Enum, Boolean
from sqlalchemy.orm import relationship
import enum
from database import Base


class AppointmentStatus(str, enum.Enum):
    scheduled = "scheduled"
    cancelled = "cancelled"
    completed = "completed"


class Doctor(Base):
    __tablename__ = "doctors"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    department = Column(String, nullable=False)
    specialization = Column(String, nullable=False)
    available_days = Column(String, nullable=False)  # comma-separated: "Mon,Tue,Wed"
    slot_duration_mins = Column(Integer, default=20)
    start_time = Column(String, default="09:00")  # HH:MM
    end_time = Column(String, default="17:00")

    appointments = relationship("Appointment", back_populates="doctor")


class Appointment(Base):
    __tablename__ = "appointments"

    id = Column(Integer, primary_key=True)
    patient_name = Column(String, nullable=False)
    patient_phone = Column(String, nullable=False)
    doctor_id = Column(Integer, ForeignKey("doctors.id"), nullable=False)
    appointment_datetime = Column(DateTime, nullable=False)
    reason = Column(String, default="")
    status = Column(Enum(AppointmentStatus), default=AppointmentStatus.scheduled)
    created_at = Column(DateTime, default=datetime.utcnow)
    confirmation_code = Column(String, unique=True)

    doctor = relationship("Doctor", back_populates="appointments")
