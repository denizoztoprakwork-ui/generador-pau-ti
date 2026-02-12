import io
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Set

import streamlit as st
import yaml

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


# -----------------------------
# Model + càrrega YAML
# -----------------------------
@dataclass(frozen=True)
class Question:
    id: str
    statement: str
    topic: str
    difficulty: str
    answer: str


def load_bank_yml(path: str) -> List[Question]:
    p = Path(path)
    if not p.exists():
        raise ValueError(f"No trobo el fitxer del banc: {p}")

    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("bank.yml ha de ser una llista de preguntes.")

    out: List[Question] = []
    seen: Set[str] = set()

    for i, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Pregunta #{i} no és un objecte YAML.")

        for k in ("id", "statement", "topic", "difficulty", "answer"):
            if k not in item:
                raise ValueError(f"Pregunta #{i} no té el camp '{k}'.")

        qid = str(item["id"]).strip()
        if not qid:
            raise ValueError(f"Pregunta #{i} té id buit.")
        if qid in seen:
            raise ValueError(f"ID duplicat: {qid}")
        seen.add(qid)

        out.append(
            Question(
                id=qid,
                statement=str(item["statement"]).strip(),
                topic=str(item["topic"]).strip(),
                difficulty=str(item["difficulty"]).strip().lower(),
                answer=str(item["answer"]).strip(),
            )
        )

    if not out:
        raise ValueError("El banc està buit.")
    return out


def filter_bank(bank: List[Question], topic: str, difficulty: str) -> List[Question]:
    c = bank
    if topic != "Tots":
        c = [q for q in c if q.topic == topic]
    if difficulty != "Totes":
        c = [q for q in c if q.difficulty == difficulty.lower()]
    return c


def pick_questions(candidates: List[Question], rng: random.Random, n: int, avoid_ids: Set[str]) -> List[Question]:
    pool = [q for q in candidates if q.id not in avoid_ids]
    if len(pool) < n:
        raise ValueError(
            "No hi ha prou preguntes al banc per crear l'examen.\n"
            f"Disponibles (després de filtres i evitant repetits): {len(pool)}\n"
            f"Necessàries: {n}\n"
            f"Preguntes evitades: {len(avoid_ids)}"
        )
    return rng.sample(pool, n)


def generate_exam(
    candidates: List[Question],
    seed: int,
    n_exercises: int,
    two_versions: bool,
    allow_repeat_between_versions: bool,
) -> Dict[str, List[Question]]:
    if n_exercises <= 0:
        raise ValueError("n_exercises ha de ser > 0")
    if not candidates:
        raise ValueError("Amb aquests filtres no hi ha cap pregunta disponible.")

    rng = random.Random(seed)

    if not two_versions:
        return {"A": pick_questions(candidates, rng, n_exercises, avoid_ids=set())}

    needed = n_exercises if allow_repeat_between_versions else 2 * n_exercises
    if len(candidates) < needed:
        raise ValueError(
            "No hi ha prou preguntes per fer dues versions (A i B) amb aquesta configuració.\n"
            f"Disponibles: {len(candidates)} | Necessàries: {needed}\n"
            f"(n_exercises={n_exercises}, repetir entre A i B={'sí' if allow_repeat_between_versions else 'no'})"
        )

    used: Set[str] = set()
    a = pick_questions(candidates, rng, n_exercises, avoid_ids=used)
    used.update(q.id for q in a)

    avoid_for_b = set() if allow_repeat_between_versions else used
    b = pick_questions(candidates, rng, n_exercises, avoid_ids=avoid_for_b)

    return {"A": a, "B": b}


# -----------------------------
# PDF (ReportLab) - simple i robust
# -----------------------------
def wrap_text(c: canvas.Canvas, text: str, x: float, y: float, max_width: float, leading: float) -> float:
    """Dibuixa text amb salt de línia automàtic. Retorna la nova y."""
    for paragraph in text.split("\n"):
        paragraph = paragraph.rstrip()
        if not paragraph:
            y -= leading
            continue

        words = paragraph.split()
        line = ""
        for w in words:
            test = (line + " " + w).strip()
            if c.stringWidth(test, "Helvetica", 11) <= max_width:
                line = test
            else:
                c.drawString(x, y, line)
                y -= leading
                line = w
        if line:
            c.drawString(x, y, line)
            y -= leading
    return y


def make_exam_pdf(
    exam: Dict[str, List[Question]],
    title: str,
    seed: int,
    include_solutions: bool,
    points_per_ex: float,
) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4

    margin_x = 2.0 * cm
    margin_y = 2.0 * cm
    max_width = width - 2 * margin_x
    leading = 14

    def header(page_title: str):
        c.setFont("Helvetica-Bold", 14)
        c.drawString(margin_x, height - margin_y, page_title)
        c.setFont("Helvetica", 10)
        c.drawRightString(width - margin_x, height - margin_y, f"seed: {seed}")
        c.setLineWidth(0.5)
        c.line(margin_x, height - margin_y - 8, width - margin_x, height - margin_y - 8)

    for version_name, questions in exam.items():
        header(f"{title} — Versió {version_name}")
        y = height - margin_y - 30

        c.setFont("Helvetica", 11)
        c.drawString(margin_x, y, f"Instruccions: respon a TOTES les qüestions. Cada exercici val {points_per_ex:g} punts.")
        y -= 22

        for i, q in enumerate(questions, start=1):
            block_title = f"{i}. [{q.topic} | {q.difficulty}]"
            c.setFont("Helvetica-Bold", 11)
            c.drawString(margin_x, y, block_title)
            y -= leading

            c.setFont("Helvetica", 11)
            y = wrap_text(c, q.statement, margin_x, y, max_width, leading)

            if include_solutions:
                y -= 4
                c.setFont("Helvetica-Oblique", 10)
                y = wrap_text(c, "Resposta orientativa: " + q.answer, margin_x, y, max_width, 12)

            y -= 10

            # salt de pàgina si cal
            if y < margin_y + 60:
                c.showPage()
                header(f"{title} — Versió {version_name}")
                y = height - margin_y - 30

        c.showPage()

    c.save()
    return buf.getvalue()


# -----------------------------
# Streamlit UI
# -----------------------------
st.set_page_config(page_title="Generador PAU Tecnologia (PDF)", page_icon="🧾", layout="centered")
st.title("🧾 Generador d’exàmens tipus PAU Tecnologia (amb PDF)")

st.caption(
    "Genera un examen a partir del teu bank.yml i descarrega’l en PDF. "
    "Pots usar Selecat com a repositori per consultar exàmens reals i el teu banc per generar-ne de nous."
)

BANK_PATH = "bank.yml"

try:
    bank = load_bank_yml(BANK_PATH)
except ValueError as e:
    st.error(f"Error carregant bank.yml: {e}")
    st.stop()

topics = sorted({q.topic for q in bank})
difficulties = sorted({q.difficulty for q in bank})

with st.sidebar:
    st.header("Configuració examen")

    title = st.text_input("Títol al PDF", value="Tecnologia (model tipus PAU)")
    n_exercises = st.number_input("Exercicis per versió", min_value=1, max_value=50, value=5, step=1)
    points_per_ex = st.number_input("Punts per exercici", min_value=0.5, max_value=5.0, value=2.5, step=0.5)

    two_versions = st.checkbox("Crear dues versions (A i B)", value=True)
    allow_repeat = st.checkbox("Permetre repetir preguntes entre A i B", value=False, disabled=not two_versions)

    include_solutions = st.checkbox("Incloure solucions al PDF", value=False)

    seed_mode = st.selectbox("Seed", ["Aleatori", "Fixar seed"], index=0)
    seed = st.number_input("Seed (si és fix)", min_value=0, max_value=999999, value=12345, step=1, disabled=(seed_mode != "Fixar seed"))

    st.divider()
    topic = st.selectbox("Tema", ["Tots"] + topics, index=0)
    difficulty = st.selectbox("Dificultat", ["Totes"] + difficulties, index=0)

col1, col2 = st.columns([1, 1])
with col1:
    do_generate = st.button("✨ Generar", use_container_width=True)
with col2:
    st.download_button(
        "⬇️ Descarregar bank.yml",
        data=Path(BANK_PATH).read_bytes(),
        file_name="bank.yml",
        mime="text/yaml",
        use_container_width=True,
    )

if do_generate:
    chosen_seed = int(seed) if seed_mode == "Fixar seed" else random.randint(0, 999999)
    candidates = filter_bank(bank, topic=topic, difficulty=difficulty)

    try:
        exam = generate_exam(
            candidates=candidates,
            seed=chosen_seed,
            n_exercises=int(n_exercises),
            two_versions=bool(two_versions),
            allow_repeat_between_versions=bool(allow_repeat),
        )
    except ValueError as e:
        st.error(str(e))
        st.info("Solucions: baixa exercicis, treu filtres, afegeix més preguntes al bank.yml, o permet repetició entre A i B.")
        st.stop()

    st.success(f"Examen generat ✅ (seed = {chosen_seed})")

    pdf_bytes = make_exam_pdf(
        exam=exam,
        title=title,
        seed=chosen_seed,
        include_solutions=include_solutions,
        points_per_ex=float(points_per_ex),
    )

    st.download_button(
        "🧾 Descarregar PDF",
        data=pdf_bytes,
        file_name=f"examen_{chosen_seed}.pdf",
        mime="application/pdf",
        use_container_width=True,
    )

    # vista ràpida a pantalla
    for v in exam:
        st.subheader(f"Versió {v}")
        for i, q in enumerate(exam[v], start=1):
            with st.expander(f"{i}. {q.topic} | {q.difficulty} | {q.id}", expanded=(i <= 1)):
                st.markdown(q.statement)
                if include_solutions:
                    st.markdown(f"**Resposta:** {q.answer}")
