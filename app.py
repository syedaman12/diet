import os, json, io, re
from datetime import datetime
from flask import Flask, request, render_template, send_file
from openai import OpenAI
import markdown
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.pagesizes import letter

app = Flask(__name__)

# ---------- OpenRouter client ----------
# Never hardcode keys in code. Set on Render as an env var: OPENROUTER_API_KEY
client = OpenAI(
    api_key="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",
    base_url="https://openrouter.ai/api/v1"
)


DATA_FILE = "diet_plans.json"


# ---------- Helpers ----------
def clean_markdown(text: str) -> str:
    """Remove most Markdown symbols for PDF export."""
    text = re.sub(r"[#*_>`-]", "", text)
    return text.strip()

_MEAL_RE = re.compile(
    r"(?is)"              # case-insensitive, dot matches newline
    r"(?:^|\n)\s*"
    r"(breakfast)[:\-]?\s*(.*?)(?=\n\s*(lunch|dinner|snacks?)\b|$)"
    r"|(?:^|\n)\s*(lunch)[:\-]?\s*(.*?)(?=\n\s*(breakfast|dinner|snacks?)\b|$)"
    r"|(?:^|\n)\s*(dinner)[:\-]?\s*(.*?)(?=\n\s*(breakfast|lunch|snacks?)\b|$)"
)

def parse_meals(text: str):
    """
    Pull out Breakfast, Lunch, Dinner sections from free-form LLM text.
    Returns dict with breakfast/lunch/dinner (plain text), safe fallbacks if missing.
    """
    out = {"breakfast": "", "lunch": "", "dinner": ""}

    for m in _MEAL_RE.finditer(text):
        # Matches come in groups depending on which branch hit
        if m.group(1):   # breakfast branch
            out["breakfast"] = m.group(2).strip()
        if m.group(4):   # lunch branch
            out["lunch"] = m.group(5).strip()
        if m.group(7):   # dinner branch
            out["dinner"] = m.group(8).strip()

    # Fallbacks if model used bullets under a “Step-by-step plan” header, etc.
    if not any(out.values()):
        # Heuristic split by keywords inside the text
        lower = text.lower()
        b_idx = lower.find("breakfast")
        l_idx = lower.find("lunch")
        d_idx = lower.find("dinner")
        # Build slices if at least one exists
        points = [(b_idx, "breakfast"), (l_idx, "lunch"), (d_idx, "dinner")]
        points = [(i, k) for i, k in points if i != -1]
        points.sort()
        for i, (start, key) in enumerate(points):
            end = len(text) if i == len(points) - 1 else points[i+1][0]
            out[key] = text[start:end].split(":", 1)[-1].strip()

    # If still empty, keep entire text under one meal so UI never breaks
    if not out["breakfast"] and text.strip():
        out["breakfast"] = text.strip()

    return out


def load_plans():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            plans = json.load(f)
    else:
        plans = []

    # Ensure each plan has breakfast/lunch/dinner fields (for older saves)
    for plan in plans:
        if not all(k in plan for k in ("breakfast", "lunch", "dinner")):
            meals = parse_meals(plan.get("diet_plan", ""))
            plan.update(meals)

    return plans


def save_plans(plans):
    with open(DATA_FILE, "w") as f:
        json.dump(plans, f, indent=4)


# ---------- Routes ----------
@app.route("/")
def home():
    return render_template("index.html")


@app.route("/predict", methods=["POST"])
def predict():
    query = request.form.get("query", "")
    weight = request.form.get("weight", "")
    height = request.form.get("height", "")
    age = request.form.get("age", "")
    gender = request.form.get("gender", "")
    activity = request.form.get("activity", "")

    prompt = f"""
You are a nutrition expert. Create a safe, personalized diet plan.

User details:
- Query: {query}
- Weight: {weight} kg
- Height: {height} cm
- Age: {age}
- Gender: {gender}
- Activity level: {activity}

Return only these sections in order:
Breakfast:
Lunch:
Dinner:

Do NOT include snacks, notes, tips, calorie count, or any extra text.
"""

    # Guard against missing API key
    if not client.api_key:
        diet_plan_raw = (
            "Breakfast: 1 cup oatmeal with berries\n\n"
            "Lunch: Grilled chicken salad\n\n"
            "Dinner: Baked salmon, veggies, brown rice\n\n"
            "Notes: Drink water; limit sugary drinks."
        )
    else:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=300,
        )
        diet_plan_raw = response.choices[0].message.content

    meals = parse_meals(diet_plan_raw)

    # Save record
    plans = load_plans()
    record = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "query": query,
        "weight": weight,
        "height": height,
        "age": age,
        "gender": gender,
        "activity": activity,
        "diet_plan": diet_plan_raw,
        **meals,
    }
    plans.append(record)
    save_plans(plans)

    # Show result page
    return render_template("result.html",  meals=meals)


@app.route("/saved")
def saved_plans():
    plans = load_plans()
    return render_template("saved.html", plans=plans)


@app.route("/download/<int:plan_index>")
def download_pdf(plan_index: int):
    plans = load_plans()
    if plan_index < 0 or plan_index >= len(plans):
        return "Invalid plan index."

    plan = plans[plan_index]

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    styles = getSampleStyleSheet()
    story = []

    # Title
    story.append(Paragraph("<b>Personalized Diet Plan</b>", styles["Title"]))
    story.append(Spacer(1, 12))

    # User info
    story.append(Paragraph(f"Date: {plan['timestamp']}", styles["Normal"]))
    story.append(Paragraph(f"Query: {plan['query']}", styles["Normal"]))
    story.append(Paragraph(f"Weight: {plan['weight']} kg | Height: {plan['height']} cm", styles["Normal"]))
    story.append(Paragraph(f"Age: {plan['age']} | Gender: {plan['gender']} | Activity: {plan['activity']}", styles["Normal"]))
    story.append(Spacer(1, 12))

    # Diet details (ONLY Breakfast, Lunch, Dinner)
    story.append(Paragraph("<b>Breakfast:</b> " + plan.get("breakfast", ""), styles["Normal"]))
    story.append(Spacer(1, 6))
    story.append(Paragraph("<b>Lunch:</b> " + plan.get("lunch", ""), styles["Normal"]))
    story.append(Spacer(1, 6))
    story.append(Paragraph("<b>Dinner:</b> " + plan.get("dinner", ""), styles["Normal"]))
    story.append(Spacer(1, 12))

    doc.build(story)
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name="diet_plan.pdf", mimetype="application/pdf")


@app.route("/delete/<int:index>", methods=["GET"])
def delete_plan(index):
    plans = load_plans()
    if 0 <= index < len(plans):
        plans.pop(index)
        save_plans(plans)
    return render_template("saved.html", plans=plans)


if __name__ == "__main__":
    app.run(debug=True)
