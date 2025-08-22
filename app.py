import os, json
from flask import Flask, request, render_template,send_file
from openai import OpenAI
from datetime import datetime
import markdown
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.pagesizes import letter
import io
import re

app = Flask(__name__)

# Connect to OpenRouter API
client = OpenAI(
    api_key="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",
    base_url="https://openrouter.ai/api/v1"
)

DATA_FILE = "diet_plans.json"




def clean_markdown(text):
    # Remove Markdown symbols like #, *, -, >, `
    text = re.sub(r'[#*_>`-]', '', text)
    return text.strip()

@app.route('/download/<int:plan_index>')
def download_pdf(plan_index):
    # Load plans
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            plans = json.load(f)
    else:
        return "No saved plans."

    if plan_index >= len(plans):
        return "Invalid plan index."

    plan = plans[plan_index]

    # Clean Markdown text
    diet_text = clean_markdown(plan["diet_plan"])

    # Create PDF in memory
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph("<b>Personalized Diet Plan</b>", styles["Title"]))
    story.append(Spacer(1, 12))

    story.append(Paragraph(f"Date: {plan['timestamp']}", styles["Normal"]))
    story.append(Paragraph(f"Query: {plan['query']}", styles["Normal"]))
    story.append(Paragraph(f"Weight: {plan['weight']} kg | Height: {plan['height']} cm", styles["Normal"]))
    story.append(Paragraph(f"Age: {plan['age']} | Gender: {plan['gender']} | Activity: {plan['activity']}", styles["Normal"]))
    story.append(Spacer(1, 12))

    # Add cleaned diet plan text
    story.append(Paragraph("<b>Diet Plan:</b>", styles["Heading2"]))
    story.append(Paragraph(diet_text.replace("\n", "<br/>"), styles["Normal"]))

    doc.build(story)
    buffer.seek(0)

    return send_file(buffer, as_attachment=True, download_name="diet_plan.pdf", mimetype="application/pdf")


@app.route('/')
def home():
    return render_template('index.html')

@app.route('/predict', methods=['POST'])
def predict():
    query = request.form.get("query")
    weight = request.form.get("weight")
    height = request.form.get("height")
    age = request.form.get("age")
    gender = request.form.get("gender")
    activity = request.form.get("activity")

    # Build prompt
    prompt = f"""
    You are a nutrition expert. Create a safe, personalized diet plan.

    User details:
    - Query: {query}
    - Weight: {weight} kg
    - Height: {height} cm
    - Age: {age}
    - Gender: {gender}
    - Activity level: {activity}

    Please give:
    1. Daily calorie target
    2. Step-by-step diet plan (Breakfast, Lunch, Dinner, Snacks)
    3. Nutrition notes and healthy habits
    """

    # Call OpenRouter API
    response = client.chat.completions.create(
        model="deepseek/deepseek-r1:free",
        messages=[{"role": "user", "content": prompt}],
    )

    diet_plan_raw = response.choices[0].message.content

    # Convert Markdown to HTML for display only
    diet_plan_html = markdown.markdown(diet_plan_raw)

    # Save raw text in JSON
    record = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "query": query,
        "weight": weight,
        "height": height,
        "age": age,
        "gender": gender,
        "activity": activity,
        "diet_plan": diet_plan_raw
    }

    # Load existing data or start new
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            plans = json.load(f)
    else:
        plans = []

    plans.append(record)

    # Save back to file
    with open(DATA_FILE, "w") as f:
        json.dump(plans, f, indent=4)

    return render_template("result.html", diet_plan=diet_plan_html)

@app.route('/saved')
def saved_plans():
    plans = load_plans()  # Load plans from your JSON or DB
    return render_template('saved.html', plans=plans)
def load_plans():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            plans = json.load(f)
    else:
        plans = []

    # Convert each saved plan to HTML for display
    for plan in plans:
        plan["diet_plan_html"] = markdown.markdown(plan["diet_plan"])

    return plans

def save_plans(plans):
    with open(DATA_FILE, "w") as f:
        json.dump(plans, f, indent=4)

@app.route('/delete/<int:index>', methods=['GET'])
def delete_plan(index):
    plans = load_plans()
    if 0 <= index < len(plans):
        plans.pop(index)
        save_plans(plans)
    return render_template('saved.html', plans=plans)

if __name__ == '__main__':
    app.run(debug=True)
