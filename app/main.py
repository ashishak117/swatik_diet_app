from fastapi import FastAPI
from pydantic import BaseModel
import pandas as pd
import os
from app.recommender import prepare_dataset, calculate_nutrition, generate_30_day_plan

DATA_PATH = "dataset/satwik_diet_dataset_6k.csv"
OUTPUT_DIR = "generated_plans"
os.makedirs(OUTPUT_DIR, exist_ok=True)

df = prepare_dataset(DATA_PATH)

app = FastAPI()

class ProfileInput(BaseModel):
    age: int
    weight: float
    height: float
    gender: str
    activity_level: str
    goal: str   # "weight_loss" or "strict_diabetes"

@app.post("/plan")
def generate_plan(profile: ProfileInput):
    goal = profile.goal.lower()
    condition = "diabetes" if goal == "strict_diabetes" else "weight_loss"

    needs = calculate_nutrition(
        age=profile.age,
        weight=profile.weight,
        height=profile.height,
        gender=profile.gender,
        activity_level=profile.activity_level,
        goal="weight_loss" if condition=="weight_loss" else "maintenance"
    )

    plan, totals = generate_30_day_plan(df, needs, condition=condition)

    # Save CSVs
    plan_file = os.path.join(OUTPUT_DIR, f"30_day_plan_{condition}.csv")
    totals_file = os.path.join(OUTPUT_DIR, f"30_day_totals_{condition}.csv")
    plan.to_csv(plan_file, index=False)
    totals.to_csv(totals_file, index=False)

    # Build response for calendar UI
    calendar = {}
    for day, day_df in plan.groupby("Day"):
        calendar[day] = day_df.to_dict(orient="records")

    return {
        "needs": needs,
        "calendar": calendar,
        "csv_downloads": {
            "plan": plan_file,
            "totals": totals_file
        }
    }
