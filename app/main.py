from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.responses import StreamingResponse
import pandas as pd
import io
import os
import json

from app.recommender import calculate_nutrition, generate_30_day_plan, prepare_dataset
import firebase_admin
from firebase_admin import credentials, firestore

# ----------------------
# Firebase Setup
# ----------------------
firebase_key = os.getenv("FIREBASE_KEY")
if not firebase_admin._apps:
    cred = credentials.Certificate(json.loads(firebase_key))
    firebase_admin.initialize_app(cred)
db = firestore.client()

app = FastAPI()

# ✅ Load dataset
df = prepare_dataset("dataset/satwik_diet_dataset_6k.csv")

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
    goal: str  # "weight_loss" or "diabetes"

# ----------------------
# Helper
# ----------------------
def normalize_goal(goal: str):
    goal = goal.lower().replace("-", "_")
    if goal in ["weight_loss", "weightloss"]:
        return "weight_loss"
    return "diabetes"

def regenerate_plan(user_id, profile: dict, needs, condition="weight_loss"):
    plan, totals = generate_30_day_plan(df, needs, condition)
    plan_list = plan.to_dict(orient="records")

    # Save plan & profile in Firestore
    db.collection("meal_plans").document(user_id).set({
        "plan": plan_list,
        "needs": needs,
        "condition": condition,
        "updatedAt": firestore.SERVER_TIMESTAMP
    })
    db.collection("profiles").document(user_id).set(profile)

    return plan_list

# ----------------------
# Routes
# ----------------------
@app.post("/plan")
def generate_plan(profile: ProfileInput):
    condition = normalize_goal(profile.goal)

    profile_dict = profile.dict()
    profile_ref = db.collection("profiles").document(profile.user_id)
    profile_doc = profile_ref.get()

    needs = calculate_nutrition(
        age=profile.age,
        weight=profile.weight,
        height=profile.height,
        gender=profile.gender,
        activity_level=profile.activity_level,
        goal="weight_loss" if condition == "weight_loss" else "maintenance"
    )

    # If profile exists and is identical → return old plan
    if profile_doc.exists:
        stored_profile = profile_doc.to_dict()
        if stored_profile == profile_dict:
            plan_doc = db.collection("meal_plans").document(profile.user_id).get()
            if plan_doc.exists:
                return {
                    "needs": plan_doc.to_dict()["needs"],
                    "plan": plan_doc.to_dict()["plan"]
                }

    # Else regenerate
    plan = regenerate_plan(profile.user_id, profile_dict, needs, condition)
    return {"needs": needs, "plan": plan}


@app.post("/plan/csv")
def download_plan(profile: ProfileInput):
    condition = normalize_goal(profile.goal)

    # Call /plan logic
    result = generate_plan(profile)

    buffer = io.StringIO()
    pd.DataFrame(result["plan"]).to_csv(buffer, index=False)
    buffer.seek(0)

    return StreamingResponse(
        iter([buffer.getvalue().encode()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=plan.csv"}
    )
