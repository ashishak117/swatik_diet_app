# # main.py
# from fastapi import FastAPI
# from pydantic import BaseModel
# from fastapi.responses import StreamingResponse
# import pandas as pd
# import io
# import os
# import json

# from app.recommender import calculate_nutrition, generate_30_day_plan, prepare_dataset

# import firebase_admin
# from firebase_admin import credentials, firestore

# # ----------------------
# # Firebase Setup
# # ----------------------
# firebase_key = os.getenv("FIREBASE_KEY")
# if not firebase_admin._apps:
#     cred = credentials.Certificate(json.loads(firebase_key))
#     firebase_admin.initialize_app(cred)
# db = firestore.client()

# app = FastAPI()

# # ✅ Load dataset
# df = prepare_dataset("dataset/satwik_diet_dataset_6k.csv")

# # ----------------------
# # Request Schemas
# # ----------------------
# class ProfileInput(BaseModel):
#     user_id: str
#     age: int
#     weight: float
#     height: float
#     gender: str
#     activity_level: str
#     goal: str  # "weight_loss" or "diabetes"

# # ----------------------
# # Helper
# # ----------------------
# def normalize_goal(goal: str):
#     goal = goal.lower().replace("-", "_")
#     if goal in ["weight_loss", "weightloss"]:
#         return "weight_loss"
#     return "diabetes"

# def regenerate_plan(user_id, profile: dict, needs, condition="weight_loss"):
#     plan, totals = generate_30_day_plan(df, needs, condition)
#     plan_list = plan.to_dict(orient="records")

#     # Save plan & profile in Firestore
#     db.collection("meal_plans").document(user_id).set({
#         "plan": plan_list,
#         "needs": needs,
#         "condition": condition,
#         "updatedAt": firestore.SERVER_TIMESTAMP
#     })
#     db.collection("profiles").document(user_id).set(profile)

#     return plan_list

# # ----------------------
# # Routes
# # ----------------------
# @app.post("/plan")
# def generate_plan(profile: ProfileInput):
#     condition = normalize_goal(profile.goal)

#     profile_dict = profile.dict()
#     profile_ref = db.collection("profiles").document(profile.user_id)
#     profile_doc = profile_ref.get()

#     needs = calculate_nutrition(
#         age=profile.age,
#         weight=profile.weight,
#         height=profile.height,
#         gender=profile.gender,
#         activity_level=profile.activity_level,
#         goal="weight_loss" if condition == "weight_loss" else "maintenance"
#     )

#     # If profile exists and is identical → return old plan
#     if profile_doc.exists:
#         stored_profile = profile_doc.to_dict()
#         if stored_profile == profile_dict:
#             plan_doc = db.collection("meal_plans").document(profile.user_id).get()
#             if plan_doc.exists:
#                 return {
#                     "needs": plan_doc.to_dict()["needs"],
#                     "plan": plan_doc.to_dict()["plan"]
#                 }

#     # Else regenerate
#     plan = regenerate_plan(profile.user_id, profile_dict, needs, condition)
#     return {"needs": needs, "plan": plan}

# @app.post("/plan/csv")
# def download_plan(profile: ProfileInput):
#     condition = normalize_goal(profile.goal)

#     # Call /plan logic
#     result = generate_plan(profile)

#     buffer = io.StringIO()
#     pd.DataFrame(result["plan"]).to_csv(buffer, index=False)
#     buffer.seek(0)

#     return StreamingResponse(
#         iter([buffer.getvalue().encode()]),
#         media_type="text/csv",
#         headers={"Content-Disposition": "attachment; filename=plan.csv"}
#     )

# # ----------------------
# # Food Explorer (JSON-only, no external APIs)
# # ----------------------
# from app.food_search_local import router as ayur_local_router
# app.include_router(ayur_local_router, prefix="/api")

# app/main.py
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi.responses import StreamingResponse
import pandas as pd
import io
import os
import json
import traceback
import logging

from app.recommender import calculate_nutrition, generate_30_day_plan, prepare_dataset

import firebase_admin
from firebase_admin import credentials, firestore

# ----------------------
# Logging
# ----------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("satwik-backend")

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
DF_PATH = "dataset/satwik_diet_dataset_6k.csv"
df = prepare_dataset(DF_PATH)

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
# Helpers
# ----------------------
def normalize_goal(goal: str):
    goal = (goal or "").lower().replace("-", "_")
    if goal in ["weight_loss", "weightloss"]:
        return "weight_loss"
    return "diabetes"

def regenerate_plan(user_id, profile: dict, needs: dict, condition="weight_loss"):
    plan, totals = generate_30_day_plan(df, needs, condition)
    plan_list = plan.to_dict(orient="records")

    # Save plan & profile in Firestore (overwrite)
    try:
        db.collection("meal_plans").document(user_id).set({
            "plan": plan_list,
            "needs": needs,
            "condition": condition,
            "updatedAt": firestore.SERVER_TIMESTAMP
        })
        db.collection("profiles").document(user_id).set(profile)
    except Exception:
        logger.exception("Failed to save plan/profile to Firestore")

    return plan_list

# ----------------------
# Routes
# ----------------------
@app.post("/plan")
def generate_plan(profile: ProfileInput):
    try:
        condition = normalize_goal(profile.goal)
        profile_dict = profile.dict()
        user_id = profile.user_id

        # compute needs (BMR + macros)
        needs = calculate_nutrition(
            age=profile.age,
            weight=profile.weight,
            height=profile.height,
            gender=profile.gender,
            activity_level=profile.activity_level,
            goal="weight_loss" if condition == "weight_loss" else "maintenance"
        )

        profile_ref = db.collection("profiles").document(user_id)
        profile_doc = profile_ref.get()

        # If profile exists and looks identical, try to return cached plan if present.
        # NOTE: we avoid strict dict equality (types in Firestore differ), instead compare important fields.
        if profile_doc.exists:
            stored_profile = profile_doc.to_dict() or {}
            # quick equality check on core fields (strings/ints)
            core_keys = ["age", "weight", "height", "gender", "activity_level", "goal"]
            same = True
            for k in core_keys:
                # normalize both to strings for comparison to avoid int/float mismatch
                a = str(stored_profile.get(k, "")).strip()
                b = str(profile_dict.get(k, "")).strip()
                if a != b:
                    same = False
                    break

            if same:
                plan_doc = db.collection("meal_plans").document(user_id).get()
                if plan_doc.exists:
                    plan_map = plan_doc.to_dict() or {}
                    # Use cached plan list if present, otherwise empty list
                    cached_plan = plan_map.get("plan", [])
                    # If cached needs isn't present, fall back to freshly computed `needs`
                    cached_needs = plan_map.get("needs")
                    result_needs = cached_needs if cached_needs is not None else needs

                    logger.info(f"Returning cached plan for user={user_id}. had_needs={cached_needs is not None} plan_len={len(cached_plan)}")
                    return {"needs": result_needs, "plan": cached_plan}

        # Not same or no cached plan -> regenerate
        logger.info(f"Regenerating plan for user={user_id}, goal={condition}")
        plan = regenerate_plan(user_id, profile_dict, needs, condition)
        return {"needs": needs, "plan": plan}

    except Exception as e:
        # Log full stack and return HTTP 500 with a friendly message
        logger.error("Error in /plan: %s", str(e))
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")

@app.post("/plan/csv")
def download_plan(profile: ProfileInput):
    try:
        # Reuse /plan logic to ensure plan exists & is up to date
        result = generate_plan(profile)

        buffer = io.StringIO()
        pd.DataFrame(result["plan"]).to_csv(buffer, index=False)
        buffer.seek(0)

        return StreamingResponse(
            iter([buffer.getvalue().encode()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=plan.csv"}
        )

    except Exception as e:
        logger.exception("Error in /plan/csv")
        raise HTTPException(status_code=500, detail=str(e))

# Food explorer router included as before
from app.food_search_local import router as ayur_local_router
app.include_router(ayur_local_router, prefix="/api")

