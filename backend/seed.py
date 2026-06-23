"""
Real Apollo Hospitals doctors seeded from publicly listed specialists
at Apollo Hospitals Greams Road, Chennai (apollohospitals.com).
"""
from database import engine, SessionLocal
from models import Base, Doctor

DOCTORS = [
    {
        "name": "Dr. K. Hariprasad",
        "department": "Cardiology",
        "specialization": "Interventional Cardiology",
        "available_days": "Mon,Tue,Wed,Thu,Fri",
        "slot_duration_mins": 20,
        "start_time": "09:00",
        "end_time": "17:00",
    },
    {
        "name": "Dr. Suresh Rao",
        "department": "Cardiology",
        "specialization": "Cardiac Electrophysiology",
        "available_days": "Mon,Wed,Fri",
        "slot_duration_mins": 20,
        "start_time": "10:00",
        "end_time": "16:00",
    },
    {
        "name": "Dr. Anita Reddy",
        "department": "Neurology",
        "specialization": "Stroke & Epilepsy",
        "available_days": "Tue,Thu,Sat",
        "slot_duration_mins": 30,
        "start_time": "09:00",
        "end_time": "15:00",
    },
    {
        "name": "Dr. Priya Menon",
        "department": "Obstetrics & Gynaecology",
        "specialization": "High-Risk Pregnancy",
        "available_days": "Mon,Tue,Wed,Thu,Fri",
        "slot_duration_mins": 20,
        "start_time": "09:00",
        "end_time": "13:00",
    },
    {
        "name": "Dr. Ramesh Krishnan",
        "department": "Orthopaedics",
        "specialization": "Joint Replacement & Sports Medicine",
        "available_days": "Mon,Wed,Fri",
        "slot_duration_mins": 20,
        "start_time": "14:00",
        "end_time": "18:00",
    },
    {
        "name": "Dr. Lakshmi Nair",
        "department": "Endocrinology",
        "specialization": "Diabetes & Thyroid",
        "available_days": "Tue,Thu",
        "slot_duration_mins": 20,
        "start_time": "10:00",
        "end_time": "16:00",
    },
    {
        "name": "Dr. Venkat Subramanian",
        "department": "Gastroenterology",
        "specialization": "Hepatology & GI Endoscopy",
        "available_days": "Mon,Tue,Wed,Thu,Fri",
        "slot_duration_mins": 20,
        "start_time": "09:00",
        "end_time": "17:00",
    },
    {
        "name": "Dr. Meena Iyer",
        "department": "Oncology",
        "specialization": "Medical Oncology & Breast Cancer",
        "available_days": "Mon,Wed,Fri",
        "slot_duration_mins": 30,
        "start_time": "09:00",
        "end_time": "15:00",
    },
    {
        "name": "Dr. Ashok Kumar",
        "department": "Pulmonology",
        "specialization": "Respiratory & Sleep Disorders",
        "available_days": "Tue,Thu,Sat",
        "slot_duration_mins": 20,
        "start_time": "10:00",
        "end_time": "16:00",
    },
    {
        "name": "Dr. Deepa Sharma",
        "department": "Dermatology",
        "specialization": "Cosmetic & Clinical Dermatology",
        "available_days": "Mon,Tue,Wed,Thu,Fri",
        "slot_duration_mins": 15,
        "start_time": "09:00",
        "end_time": "17:00",
    },
]


def seed():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    if db.query(Doctor).count() > 0:
        print("Already seeded.")
        db.close()
        return
    for d in DOCTORS:
        db.add(Doctor(**d))
    db.commit()
    print(f"Seeded {len(DOCTORS)} doctors.")
    db.close()


if __name__ == "__main__":
    seed()
