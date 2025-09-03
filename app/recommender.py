import numpy as np
import pandas as pd
import random

random.seed(42)
np.random.seed(42)

# ---------------------------
# Normalize + prep dataset
# ---------------------------
def prepare_dataset(csv_path):
    df = pd.read_csv(csv_path)

    def _normalize_category(x):
        if pd.isna(x):
            return None
        x = str(x).strip().title()
        mapping = {
            'Breakfast':'Breakfast',
            'Lunch':'Lunch',
            'Dinner':'Dinner',
            'Snack':'Snack',
            'Snacks':'Snack',
            'Beverage':'Beverage',
            'Beverages':'Beverage'
        }
        return mapping.get(x, x)

    df['Category_norm'] = df['Category'].apply(_normalize_category)

    for col in ['Calories','Protein (g)','Carbs (g)','Fat (g)','Glycemic Index Estimate']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    df_nutri = df.dropna(subset=['Calories','Protein (g)','Carbs (g)','Fat (g)']).copy()
    return df_nutri

# ---------------------------
# User Needs (BMR + macros)
# ---------------------------
def calculate_nutrition(age, weight, height, gender, activity_level, goal="weight_loss"):
    if gender.lower() == "male":
        bmr = 10*weight + 6.25*height - 5*age + 5
    else:
        bmr = 10*weight + 6.25*height - 5*age - 161

    activity_factors = {
        "sedentary": 1.2, "light": 1.375, "moderate": 1.55, "active": 1.725, "very_active": 1.9
    }
    calories = bmr * activity_factors.get(activity_level.lower(), 1.2)

    if goal == "weight_loss":
        calories -= 500

    protein = (0.8 * weight)
    carbs   = (0.50 * calories) / 4
    fats    = (0.25 * calories) / 9

    return {
        "Calories": max(1200, round(calories)),
        "Protein (g)": round(protein),
        "Carbs (g)": round(carbs),
        "Fat (g)": round(fats),
    }

# ---------------------------
# Ranking + pools
# ---------------------------
def rank_foods(df, needs, condition="weight_loss"):
    d = df.copy()
    def _nutrition_score(row):
        diffs = []
        for col in ["Calories","Protein (g)","Carbs (g)","Fat (g)"]:
            if needs[col] > 0 and not pd.isna(row[col]):
                diffs.append(abs(row[col] - needs[col]/4) / (needs[col]/4))
        return 1 - np.mean(diffs) if diffs else 0.0

    d["NutritionScore"] = d.apply(_nutrition_score, axis=1)

    if condition == "diabetes":
        if "Diabetes Management Benefits" in d.columns:
            d = d[d["Diabetes Management Benefits"].notna()].copy()
        if "Glycemic Index Estimate" in d.columns:
            gi = d["Glycemic Index Estimate"]
            d["GI_Score"] = 1 - (gi / gi.max()).clip(0, 1)
        else:
            d["GI_Score"] = 0.5
        d["Score"] = 0.7 * d["NutritionScore"] + 0.3 * d["GI_Score"]
    else:
        d["Score"] = d["NutritionScore"]

    return d.sort_values("Score", ascending=False)

MEAL_ORDER = ["Breakfast","Lunch","Snack","Dinner"]

def build_candidate_pools(ranked_df, top_k=200):
    pools = {}
    for meal in MEAL_ORDER:
        pool = ranked_df[ranked_df["Category_norm"]==meal]
        if pool.empty:
            pool = ranked_df.copy()
        pools[meal] = pool.head(top_k).reset_index(drop=True)
    return pools

# ---------------------------
# Day assembly + 30-day plan
# ---------------------------
def assemble_one_day(pools, needs, meal_split=None, tolerance=0.12):
    if meal_split is None:
        meal_split = {"Breakfast":0.25, "Lunch":0.35, "Snack":0.15, "Dinner":0.25}

    target_cals = {m: needs["Calories"]*p for m,p in meal_split.items()}
    rows = []

    for meal in MEAL_ORDER:
        pool = pools[meal]
        chosen = pool.sample(n=1).iloc[0]

        rows.append({
            "Meal": meal,
            "Foods": chosen["Food Name"],
            "Calories": round(chosen["Calories"],1),
            "Protein (g)": round(chosen["Protein (g)"],1),
            "Carbs (g)": round(chosen["Carbs (g)"],1),
            "Fat (g)": round(chosen["Fat (g)"],1),
        })

    return pd.DataFrame(rows)

def generate_30_day_plan(df, needs, condition="weight_loss"):
    ranked = rank_foods(df, needs, condition=condition)
    pools = build_candidate_pools(ranked, top_k=200)

    all_days = []
    for day in range(1, 31):
        day_df = assemble_one_day(pools, needs)
        day_df.insert(0, "Day", day)
        all_days.append(day_df)

    plan = pd.concat(all_days, ignore_index=True)
    totals = (plan.groupby("Day")[["Calories","Protein (g)","Carbs (g)","Fat (g)"]]
              .sum()
              .reset_index())

    return plan, totals
