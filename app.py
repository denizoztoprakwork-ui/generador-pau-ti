import random
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Dict, Set

import streamlit as st
import yaml


# -----------------------------
# Model i utilitats
# -----------------------------
@dataclass(frozen=True)
class Question:
    id: str
    statement: str
    topic: str
    difficulty: str  # "facil" | "mitja" | "dificil"
    answer: str


def load_bank_yml(path: str) -> List[Question]:
    p = Path(path)
    if not p.exists():
        raise ValueError(f"No trobo el fitxer del banc: {p}")

    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
    except Exception as e:
        raise ValueError(f"El fitxer {p} no és un YAML vàlid: {e}") from e

    if not isinstance(data, list):
        raise ValueError("El banc ha de ser una llista (YAML) de preguntes.")

    seen: Set[str] = set()
    out: List[Question] = []

    for i, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Pregunta #{i} no és un objecte YAML (hauria de ser un mapa).")

        for k in ("id", "statement", "topic", "difficulty", "answer"):
            if k not in item:
                raise ValueError(f"Pregunta #{i} no té el camp obligatori '{k}'.")

        qid = str(item["id"]).strip()
        if not qid:
            raise ValueError(f"Pregunta #{i} té 'id' buit.")
        if qid in seen:
            raise ValueError(f"ID duplicat al banc: '{qid}'.")
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
    candidates = bank
    if topic != "Tots":
        candidates = [q for q in candidates if q.topic == topic]
    if difficulty != "Totes":
        candidates = [q for q in candidates if q.difficulty == difficulty.lower()]
    return candidates


def pick_questions(candidates: List[Question], rng: random.Random, n: int, avoid_ids: Set[str]) -> List[Question]:
    pool = [q for q in candidates if q.id not in avoid_ids]
    if len(pool) < n:
        raise ValueError(
            "No hi ha prou preguntes al banc per crear l'examen.\n"
            f"Disponibles després de filtres i evitant repetits: {len(pool)}\n"
            f"Necessàries: {n}\n"
            f"Preguntes evitades: {len(avoid_ids)}"
        )
    return rng.sample(pool, n)


def generate_exam(
    candidates: List[Question],
    seed: int,
    n_exercises: int,
    make_two_versions: bool,
    allow_repeat_between_versions: bool,
) -> Dict[str, List[Question]]:
    if n_exercises <= 0:
        raise ValueError("El nombre d'exercicis ha de ser > 0.")
    if not candidates:
        raise ValueError("Amb aquests filtres no hi ha cap pregunta disponible.")

    rng = random.Random(seed)

    if not make_two_versions:
        a = pick_questions(candidates, rng, n_exercises, avoid_ids=set())
        return {"A": a}

    # Si NO es repeteixen entre A i B, en calen el doble
    needed = n_exercises if allow_repeat_between_versions else 2 * n_exercises
    if len(candidates) < needed:
        raise ValueError(
            "No hi ha prou preguntes per fer dues versions (A i B) amb aquesta configuració.\n"
            f"Disponibles (després de filtres): {len(candidates)}\n"
            f"Necessàries: {needed}\n"
            f"(n_exercises={n_exercises}, repetir entre A i B={'sí' if allow_repeat_between_versions else 'no'})"
        )

    used: Set[str] = set()
    a = pick_questions(candidates, rng, n_exercises, avoid_ids=used)
    used.update(q.id for q in a)

    avoid_for_b = set() if allow_repeat_between_versions else used
    b = pick_questions(candidates, rng, n_exercises, avoid_ids=avoid_for_b)

    return {"A": a, "B": b}


# -----------------------------
# Streamlit app
# -----------------------------
st.set_page_config(page_title="Generador d'exàmens", page_icon="📝", layout="centered")
st.title("📝 Generador d'exàmens")
st.caption("Si falten preguntes, t'ho dirà amb un missatge (no petarà).")

BANK_PATH = "bank.yml"

try:
    bank = load_bank_yml(BANK_PATH)
except ValueError as e:
    st.error(f"Error carregant el banc: {e}")
    st.stop()

topics = sorted({q.topic for q in bank})
difficulties = sorted({q.difficulty for q in bank})

with st.sidebar:
    st.header("Configuració")

    n_exercises = st.number_input("Exercicis per versió", min_value=1, max_value=50, value=5, step=1)

    make_two_versions = st.checkbox("Crear dues versions (A i B)", value=True)
    allow_repeat = st.checkbox(
        "Permetre repetir preguntes entre A i B",
        value=False,
        disabled=not make_two_versions
    )

    seed_mode = st.selectbox("Seed", ["Aleatori", "Fixar seed"], index=0)
    seed = st.number_input(
        "Seed (si és fix)",
        min_value=0,
        max_value=999999,
        value=12345,
        step=1,
        disabled=(seed_mode != "Fixar seed"),
    )

    st.divider()
    topic = st.selectbox("Tema", ["Tots"] + topics, index=0)
    difficulty = st.selectbox("Dificultat", ["Totes"] + difficulties, index=0)

col1, col2 = st.columns([1, 1])
with col1:
    do_generate = st.button("✨ Generar examen", use_container_width=True)
with col2:
    st.download_button(
        "⬇️ Descarregar banc (YAML)",
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
            make_two_versions=bool(make_two_versions),
            allow_repeat_between_versions=bool(allow_repeat),
        )
    except ValueError as e:
        st.error(str(e))
        st.info("Solucions típiques: baixa el nombre d'exercicis, treu filtres, o permet repetició entre A i B.")
        st.stop()

    st.success(f"Examen generat ✅ (seed = {chosen_seed})")

    def render_version(name: str):
        st.subheader(f"Versió {name}")
        for idx, q in enumerate(exam[name], start=1):
            with st.expander(f"{idx}. [{q.topic} | {q.difficulty}] {q.id}", expanded=(idx <= 2)):
                st.markdown(q.statement)
                st.markdown(f"**Resposta:** {q.answer}")

    render_version("A")
    if "B" in exam:
        render_version("B")
