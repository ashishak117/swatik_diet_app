from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.responses import StreamingResponse
import pandas as pd
import io
import os
import json

from app.recommender import calculate_nutrition, generate_30_day_plan
import firebase_admin
from firebase_admin import credentials, firestore

# ----------------------
# Firebase Setup
# ----------------------
firebase_key = os.getenv("FIREBASE_KEY")  # environment variable in Render
if not firebase_admin._apps:  # avoid re-init if hot reload
    cred = credentials.Certificate(json.loads(firebase_key))
    firebase_admin.initialize_app(cred)
db = firestore.client()

app = FastAPI()

# Load dataset once
df = pd.read_csv("dataset/satwik_diet_dataset_6k.csv")

# ----------------------
# Request Schemas
# ----------------------
class ProfileInput(BaseModel):
    user_id: str
    age: int
    weight: float
    height: float
    gender: str
    activity_level: str
    goal: str  # "weight_loss" or "strict_diabetes"

# ----------------------
# Helper: Fetch or Persist Plan
# ----------------------
def get_or_create_plan(user_id, needs, condition="weight_loss"):
    doc_ref = db.collection("meal_plans").document(user_id)
    doc = doc_ref.get()

    if doc.exists:
        return doc.to_dict()["plan"]

    plan, totals = generate_30_day_plan(df, needs, condition)
    plan_list = plan.to_dict(orient="records")

    doc_ref.set({
        "plan": plan_list,
        "needs": needs,
        "condition": condition
    })

    return plan_list

# ----------------------
# Routes
# ----------------------
@app.post("/plan")
def generate_plan(profile: ProfileInput):
    condition = "weight_loss" if profile.goal == "weight_loss" else "diabetes"

    needs = calculate_nutrition(
        age=profile.age,
        weight=profile.weight,
        height=profile.height,
        gender=profile.gender,
        activity_level=profile.activity_level,
        goal="weight_loss" if condition == "weight_loss" else "maintenance"
    )

    plan = get_or_create_plan(profile.user_id, needs, condition)
    return {"needs": needs, "plan": plan}

@app.post("/plan/csv")
def download_plan(profile: ProfileInput):
    condition = "weight_loss" if profile.goal == "weight_loss" else "diabetes"

    needs = calculate_nutrition(
        age=profile.age,
        weight=profile.weight,
        height=profile.height,
        gender=profile.gender,
        activity_level=profile.activity_level,
        goal="weight_loss" if condition == "weight_loss" else "maintenance"
    )

    plan = get_or_create_plan(profile.user_id, needs, condition)

    buffer = io.StringIO()
    pd.DataFrame(plan).to_csv(buffer, index=False)
    buffer.seek(0)

    return StreamingResponse(
        iter([buffer.getvalue().encode()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=plan.csv"}
    )
