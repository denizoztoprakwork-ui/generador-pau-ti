import io
import random
import yaml
import streamlit as st

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, ListFlowable, ListItem


# ---------- Utils: load bank ----------
@st.cache_data
def load_bank(path: str = "bank.yml") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not data or "questions" not in data:
        raise ValueError("bank.yml ha de contenir una clau 'questions'.")
    return data


# ---------- Exam generation ----------
def pick_questions(bank: dict, rng: random.Random, n_exercises: int, avoid_ids: set[str]) -> list[dict]:
    candidates = [q for q in bank["questions"] if q["id"] not in avoid_ids]
    rng.shuffle(candidates)

    picked = []
    used_topics = set()

    for q in candidates:
        if len(picked) >= n_exercises:
            break
        topic = q.get("topic", "general")
        # preferim no repetir tema mentre es pugui
        if topic in used_topics and len(used_topics) < min(3, n_exercises):
            continue
        picked.append({**q})
        used_topics.add(topic)

    # fallback
    if len(picked) < n_exercises:
        for q in candidates:
            if len(picked) >= n_exercises:
                break
            if q["id"] in {p["id"] for p in picked}:
                continue
            picked.append({**q})

    if len(picked) < n_exercises:
        raise ValueError("No hi ha prou preguntes al banc per crear l'examen.")
    return picked


def round_quarter(x: float) -> float:
    return round(x * 4) / 4


def allocate_points(option_questions: list[dict], rng: random.Random, total: float) -> list[dict]:
    n = len(option_questions)
    base = total / n
    weights = [base] * n

    # petit ajust aleatori perquè no sigui sempre idèntic
    if n >= 2:
        delta = min(0.5, base * 0.25)
        i, j = 0, 1
        shift = rng.uniform(-delta, delta)
        weights[i] += shift
        weights[j] -= shift

    weights = [round_quarter(w) for w in weights]
    diff = total - sum(weights)
    weights[-1] = round_quarter(weights[-1] + diff)

    for q, pts in zip(option_questions, weights):
        q["points"] = pts
        parts = q.get("parts") or []
        if not parts:
            q["parts"] = [{"text": q.get("statement", ""), "points": pts}]
            continue

        per = round_quarter(pts / len(parts))
        acc = per * (len(parts) - 1)
        last = round_quarter(pts - acc)

        for idx, p in enumerate(parts):
            p["points"] = per if idx < len(parts) - 1 else last

    return option_questions


def generate_exam(bank: dict, seed: int | None, n_exercises: int, option_points: float, meta: dict) -> dict:
    rng = random.Random(seed)

    option_a = pick_questions(bank, rng, n_exercises=n_exercises, avoid_ids=set())
    used = {q["id"] for q in option_a}
    option_b = pick_questions(bank, rng, n_exercises=n_exercises, avoid_ids=used)

    option_a = allocate_points(option_a, rng, total=option_points)
    option_b = allocate_points(option_b, rng, total=option_points)

    return {
        "meta": {**meta, "seed": seed, "option_points": option_points},
        "instructions": [
            "Trieu UNA de les dues opcions (A o B).",
            "Responeu tots els apartats de l’opció escollida.",
            "Justifiqueu els càlculs i les respostes. La presentació i la claredat es valoraran.",
        ],
        "options": {"A": option_a, "B": option_b},
    }


# ---------- PDF rendering ----------
def styles():
    s = getSampleStyleSheet()
    s.add(ParagraphStyle(name="TitleBig", parent=s["Title"], fontSize=16, leading=18, spaceAfter=6))
    s.add(ParagraphStyle(name="Meta", parent=s["Normal"], fontSize=10, leading=12, textColor=colors.grey))
    s.add(ParagraphStyle(name="H2", parent=s["Heading2"], fontSize=12, leading=14, spaceBefore=10, spaceAfter=6))
    s.add(ParagraphStyle(name="Q", parent=s["Normal"], fontSize=11, leading=14, spaceAfter=4))
    s.add(ParagraphStyle(name="Part", parent=s["Normal"], fontSize=11, leading=14, leftIndent=10, spaceAfter=2))
    return s


def build_exam_pdf_bytes(exam: dict) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18*mm, rightMargin=18*mm, topMargin=16*mm, bottomMargin=16*mm)
    s = styles()
    story = []

    meta = exam["meta"]
    story.append(Paragraph(meta["title"], s["TitleBig"]))
    story.append(Paragraph(f"{meta['subject']} — {meta['year']}", s["Meta"]))
    if meta.get("seed") is not None:
        story.append(Paragraph(f"Seed: {meta['seed']}", s["Meta"]))
    story.append(Spacer(1, 8))

    story.append(Paragraph("Instruccions", s["H2"]))
    instr = [ListItem(Paragraph(t, s["Q"])) for t in exam["instructions"]]
    story.append(ListFlowable(instr, bulletType="bullet", leftIndent=14))
    story.append(Spacer(1, 10))

    for opt_key in ["A", "B"]:
        story.append(Paragraph(f"OPCIÓ {opt_key}", s["H2"]))
        option = exam["options"][opt_key]
        for idx, q in enumerate(option, start=1):
            pts = q.get("points", 0)
            title = q.get("title", f"Exercici {idx}")
            story.append(Paragraph(f"{idx}. {title} <font color='grey'>({pts} punts)</font>", s["Q"]))

            stmt = q.get("statement")
            if stmt:
                story.append(Paragraph(stmt, s["Q"]))

            parts = q.get("parts", [])
            for pi, part in enumerate(parts, start=1):
                ppts = part.get("points", 0)
                story.append(Paragraph(f"{chr(96+pi)}) {part['text']} <font color='grey'>({ppts} punts)</font>", s["Part"]))

            story.append(Spacer(1, 6))

        if opt_key == "A":
            story.append(PageBreak())

    doc.build(story)
    return buf.getvalue()


def build_solutions_pdf_bytes(exam: dict) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18*mm, rightMargin=18*mm, topMargin=16*mm, bottomMargin=16*mm)
    s = styles()
    story = []

    meta = exam["meta"]
    story.append(Paragraph("Solucionari", s["TitleBig"]))
    story.append(Paragraph(f"{meta['subject']} — {meta['year']}", s["Meta"]))
    story.append(Spacer(1, 10))

    for opt_key in ["A", "B"]:
        story.append(Paragraph(f"OPCIÓ {opt_key}", s["H2"]))
        option = exam["options"][opt_key]
        for idx, q in enumerate(option, start=1):
            story.append(Paragraph(f"{idx}. {q.get('title','Exercici')}", s["Q"]))
            sol = q.get("solution") or "— (sense solució definida al banc) —"
            story.append(Paragraph(sol, s["Part"]))
            story.append(Spacer(1, 6))
        if opt_key == "A":
            story.append(PageBreak())

    doc.build(story)
    return buf.getvalue()


# ---------- Streamlit UI ----------
st.set_page_config(page_title="Generador Exàmens PAU (TI)", page_icon="🧾", layout="centered")
st.title("🧾 Generador d’exàmens estil PAU — Tecnologia Industrial")

bank = load_bank()

with st.sidebar:
    st.header("Configuració")
    title = st.text_input("Títol", "Prova d’accés a la universitat (PAU)")
    subject = st.text_input("Matèria", "Tecnologia Industrial")
    year = st.text_input("Convocatòria / Any", "Model generat")
    n_exercises = st.number_input("Exercicis per opció", min_value=2, max_value=6, value=3, step=1)
    option_points = st.number_input("Punts per opció", min_value=5.0, max_value=10.0, value=10.0, step=0.5)
    seed_mode = st.selectbox("Reproduïbilitat", ["Aleatori", "Fixar seed"])
    seed = None
    if seed_mode == "Fixar seed":
        seed = st.number_input("Seed (enter)", min_value=0, max_value=999999, value=42, step=1)

st.write("Prem el botó i descarrega el PDF. L’examen tindrà **Opció A** i **Opció B** amb puntuacions.")

if len(bank["questions"]) < int(n_exercises) * 2:
    st.warning("El banc té poques preguntes per generar A i B sense repetir. Afegeix més ítems a bank.yml.")

col1, col2 = st.columns(2)

meta = {"title": title, "subject": subject, "year": year}

with col1:
    if st.button("Genera examen (PDF)"):
        exam = generate_exam(bank, seed=seed if seed_mode == "Fixar seed" else random.randint(0, 999999),
                             n_exercises=int(n_exercises), option_points=float(option_points), meta=meta)
        pdf_bytes = build_exam_pdf_bytes(exam)
        st.download_button("⬇️ Descarrega examen.pdf", data=pdf_bytes, file_name="examen_pau.pdf", mime="application/pdf")

with col2:
    if st.button("Genera examen + solucions"):
        exam = generate_exam(bank, seed=seed if seed_mode == "Fixar seed" else random.randint(0, 999999),
                             n_exercises=int(n_exercises), option_points=float(option_points), meta=meta)
        exam_pdf = build_exam_pdf_bytes(exam)
        sol_pdf = build_solutions_pdf_bytes(exam)
        st.download_button("⬇️ Descarrega examen.pdf", data=exam_pdf, file_name="examen_pau.pdf", mime="application/pdf")
        st.download_button("⬇️ Descarrega solucions.pdf", data=sol_pdf, file_name="solucions_pau.pdf", mime="application/pdf")
