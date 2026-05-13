"""
Astronomy KG Query System: Standalone GUI
All code same as in notebook
"""

import os, json, random, re, threading
import tkinter as tk
from tkinter import messagebox

# Set up vars
TESTING_MODE = True          # True → rating radios + expected output + Save button

# Theme parms
BG      = "#0d1117"    # near-black background
BG2     = "#161b22"    # slightly lighter — used for text areas
FG      = "#c9d1d9"    # main text
ACCENT  = "#58a6ff"    # blue accent (dividers, highlights)
GOLD    = "#f0a500"    # title / star colour
MUTED   = "#8b949e"    # metadata / secondary text
ERR     = "#f85149"    # error red
BTN_BG  = "#21262d"    # button background
FONT    = ("Courier New", 10)
FONT_B  = ("Courier New", 10, "bold")
FONT_LG = ("Courier New", 13, "bold")
FONT_SM = ("Courier New", 9)

# item holders
g             = None
ner           = None
intent_clf    = None
ALL_QUESTIONS = []

# Get paths
_DIR       = os.path.dirname(os.path.abspath(__file__))
KG_PATH    = os.path.join(_DIR, "astronomy_kg.ttl")
EVAL_PATH  = os.path.join(_DIR, "eval_questions.txt")
SAVE_FILE  = os.path.join(_DIR, "testing_log.json")

# =============================================================================
# Pipeline set up (from notebook)
# =============================================================================

# Set ups for pipline
INTENT_MAP = {
    "chemical composition elements or what something is made of": "composition",
    "location or where something is found":                       "location",
    "temperature or how hot or cold something is":                "temperature",
    "size mass or how big something is":                          "size",
    "discovery or who found it or when it was discovered":        "discovery",
    "general description definition or overview of what it is":   "description",
    "orbital mechanics or what objects orbit around something":   "orbital",
}
INTENT_LABELS = list(INTENT_MAP.keys())

SEARCH_TYPE_MAP = {
    "star":           "dbo:Star",
    "stars":          "dbo:Star",
    "planet":         "dbo:Planet",
    "planets":        "dbo:Planet",
    "galaxy":         "dbo:Galaxy",
    "galaxies":       "dbo:Galaxy",
    "nebula":         "dbo:Nebula",
    "nebulae":        "dbo:Nebula",
    "nebulas":        "dbo:Nebula",
    "constellation":  "dbo:Constellation",
    "constellations": "dbo:Constellation",
}

CONSTRAINT_WORDS = [
    "contain", "contains", "have", "has", "with",
    "below", "above", "less than", "more than",
    "between", "in", "that are", "that have",
]

CONSTRAINT_KEYWORD_MAP = {
    "composition": ["contain", "contains", "made of", "consist", "composed"],
    "temperature": ["temperature", "hot", "cold", "warm", "cool", "kelvin"],
    "location":    ["in", "located", "location", "within", "inside"],
    "size":        ["big", "large", "small", "mass", "radius", "size", "diameter"],
    "discovery":   ["discovered", "found", "discoverer"],
    "orbital":     ["orbit", "orbits", "orbiting", "period"],
}

COMPARISON_MAP = {
    "below":     "<",  "less than":  "<",  "under":        "<",  "colder than": "<",
    "above":     ">",  "more than":  ">",  "over":         ">",  "hotter than": ">",
    "equal to":  "=",  "exactly":    "=",
}

INTENT_TO_PRED = {
    "composition": ["dbo:hasChemicalElement"],
    "temperature": ["dbo:meanTemperature", "dbo:surfaceTemperature", "dbo:effectiveTemperature"],
    "orbital":     ["dbo:orbitalPeriod", "dbo:numberOfMoons"],
    "location":    ["dbo:locatedIn", "dbo:location", "dbo:constellation", "dbp:constellation"],
    "size":        ["dbo:mass", "dbo:radius", "dbo:diameter", "dbp:mass", "dbp:radius"],
    "discovery":   ["dbo:discoverer", "dbo:discoveryDate", "dbp:discoverer"],
    "description": ["dbo:description"],
}

TEMPLATES = {
    "temperature":  "{entity} has a mean temperature of {value} K.",
    "description":  "{entity}: {value}.",
    "orbital":      "{entity} has an orbital period of {value} seconds.",
    "composition":  "{entity} contains {value}.",
    "location":     "{entity} is located in {value}.",
    "size":         "{entity} has a {predicate} of {value}.",
    "discovery":    "{entity} — {predicate}: {value}.",
}

PLURAL_MAP = {
    "Star": "stars", "Planet": "planets", "Galaxy": "galaxies",
    "Nebula": "nebulae", "Constellation": "constellations",
}

COMPARISON_WORDS = {"<": "below", ">": "above", "=": "matching"}

# Functoins from notebook for pipeline
def kg_label_fallback(question, graph):
    q_lower = question.lower()
    matches, seen = [], set()
    rows = graph.query("""
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        SELECT DISTINCT ?label WHERE {
            ?entity rdfs:label ?label .
            FILTER (lang(?label) = 'en')
        }
    """)
    for row in rows:
        label = str(row.label)
        if label.lower() in q_lower and label not in seen:
            matches.append(label)
            seen.add(label)
    return sorted(matches, key=len, reverse=True)


def parse_question(question, ner_model, clf_model):
    entities       = [r['word'] for r in ner_model(question) if r['score'] > 0.5]
    if not entities:
        entities = kg_label_fallback(question, g)
    result         = clf_model(question, candidate_labels=INTENT_LABELS)
    verbose_intent = result['labels'][0]
    confidence     = result['scores'][0]
    intent         = INTENT_MAP[verbose_intent]
    if confidence < 0.50:
        intent = "description"
    return {"entities": entities, "intent": intent, "confidence": round(confidence, 2)}


def detect_query_type(question):
    q_lower        = question.lower()
    has_type_word  = any(word in q_lower.split() for word in SEARCH_TYPE_MAP)
    has_constraint = any(c in q_lower for c in CONSTRAINT_WORDS)
    if has_type_word and has_constraint:
        return "filter"
    return "lookup"


def parse_filter_question(question, ner_model):
    q_lower = question.lower()
    words   = q_lower.split()

    search_type = None
    for word in words:
        if word in SEARCH_TYPE_MAP:
            search_type = SEARCH_TYPE_MAP[word]
            break

    clauses_lower    = [c.strip() for c in q_lower.split(" and ")]
    clauses_original = [c.strip() for c in question.split(" and ")]

    constraints = []
    for clause, clause_orig in zip(clauses_lower, clauses_original):
        constraint_intent = None
        for intent, keywords in CONSTRAINT_KEYWORD_MAP.items():
            if any(kw in clause for kw in keywords):
                constraint_intent = intent
                break
        if not constraint_intent:
            continue

        comparison = ">"
        for phrase, op in COMPARISON_MAP.items():
            if phrase in clause:
                comparison = op
                break

        entities = [r["word"] for r in ner_model(clause_orig) if r["score"] > 0.5]
        values   = [e for e in entities if e.lower() not in SEARCH_TYPE_MAP]

        if not values:
            for pattern in [r"contain(?:s)?\s+(\w+)", r"made\s+of\s+(\w+)",
                            r"composed\s+of\s+(\w+)", r"consist(?:s)?\s+of\s+(\w+)"]:
                match = re.search(pattern, clause)
                if match:
                    values = [match.group(1).capitalize()]
                    break

        if not values:
            numbers = re.findall(r'\d+\.?\d*', clause)
            values  = numbers if numbers else ["0"]

        constraints.append({"intent": constraint_intent, "comparison": comparison, "values": values})

    return {"search_type": search_type, "constraints": constraints}


def _clean_value(v):
    if v.startswith("http://dbpedia.org/resource/"):
        name = v[len("http://dbpedia.org/resource/"):]
        if "_(" in name:
            name = name[:name.rfind("_(")]
        return name.replace("_", " ").strip()
    return v


def lookup_entity(graph, name, intent="description"):
    safe_name   = name.replace("'", "\\'")
    predicates  = INTENT_TO_PRED.get(intent, ["dbo:description"])
    pred_filter = " || ".join([f"?p = {p}" for p in predicates])

    results = graph.query(f"""
        PREFIX dbo:  <http://dbpedia.org/ontology/>
        PREFIX dbp:  <http://dbpedia.org/property/>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

        SELECT ?p ?o WHERE {{
            ?entity rdfs:label ?label .
            ?entity ?p ?o .
            FILTER (str(?label) = '{safe_name}')
            FILTER ({pred_filter})
        }}
    """)
    return [{"predicate": str(row.p).split("/")[-1], "value": _clean_value(str(row.o))}
            for row in results]


def filter_entities(graph, filter_params, limit=10):
    search_type = filter_params["search_type"]
    constraints = filter_params["constraints"]

    if not search_type or not constraints:
        return []

    where_blocks = []
    for i, c in enumerate(constraints):
        pred  = INTENT_TO_PRED.get(c["intent"], ["dbo:description"])[0]
        value = c["values"][0]
        var   = f"?val{i}"

        try:
            num_val = float(value)
            where_blocks.append(f"?entity {pred} {var} . FILTER ({var} {c['comparison']} {num_val})")
        except ValueError:
            where_blocks.append(f"""?entity {pred} ?obj{i} .
                BIND(str(?obj{i}) AS {var})
                FILTER (CONTAINS(LCASE({var}), LCASE("{value}")))""")

    where_str = "\n".join(where_blocks)
    query = f"""
        PREFIX dbo:  <http://dbpedia.org/ontology/>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        SELECT DISTINCT ?label WHERE {{
            ?entity a {search_type} .
            ?entity rdfs:label ?label .
            {where_str}
            FILTER (lang(?label) = 'en')
        }}
        LIMIT {limit}
    """
    results = graph.query(query)
    return [{"label": str(row.label)} for row in results]


def answer_question(question):
    query_type = detect_query_type(question)

    if query_type == "filter":
        filter_params = parse_filter_question(question, ner)
        data = filter_entities(g, filter_params)
        return {"query_type": "filter", "filter_params": filter_params, "data": data}
    else:
        parsed  = parse_question(question, ner, intent_clf)
        results = []
        for entity in parsed["entities"]:
            rows = lookup_entity(g, entity, parsed["intent"])
            results.append({"entity": entity, "intent": parsed["intent"], "data": rows})
        return {"query_type": "lookup", "results": results}


def format_template(pipeline_output):
    if isinstance(pipeline_output, str):
        return pipeline_output

    if pipeline_output["query_type"] == "filter":
        data        = pipeline_output["data"]
        params      = pipeline_output["filter_params"]
        type_word   = params["search_type"].replace("dbo:", "")
        type_plural = PLURAL_MAP.get(type_word, type_word.lower() + "s")
        if not data:
            return f"No {type_plural} found matching that criteria in the knowledge graph."
        seen, lines = set(), []
        for row in data:
            if row["label"] not in seen:
                lines.append(row["label"])
                seen.add(row["label"])
        parts = []
        for c in params["constraints"]:
            cword = COMPARISON_WORDS.get(c["comparison"], "")
            parts.append(f"{c['intent']} {cword} {c['values'][0]}")
        constraint_summary = " and ".join(parts)
        return f"{type_plural.capitalize()} with {constraint_summary}: {', '.join(lines)}."

    else:
        lines = []
        for item in pipeline_output["results"]:
            entity = item["entity"]
            intent = item["intent"]
            data   = item["data"]
            if not data:
                lines.append(f"No {intent} information found for {entity} in the knowledge graph.")
                continue
            template = TEMPLATES.get(intent, "{entity} — {predicate}: {value}.")
            for row in data:
                if not row["value"].strip():
                    continue
                lines.append(template.format(entity=entity,
                                             predicate=row["predicate"],
                                             value=row["value"]))
        if not lines:
            return "No information found in the knowledge graph."
        return " ".join(lines)


# =============================================================================
# GUI (not from notebook)
# =============================================================================

class AstroApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Astronomy KG Query System")
        self.root.configure(bg=BG)
        self.root.minsize(700, 500)
        self.root.resizable(True, True)

        self._rating_var = tk.IntVar(value=0)
        self._build_ui()
        self.root.after(120, self._start_loading)   # let window render first

    # biuld Gui layout

    def _build_ui(self):
        # Title bar
        hdr = tk.Frame(self.root, bg=BG, pady=10)
        hdr.pack(fill="x", padx=16)
        tk.Label(hdr, text="ASTRONOMY KG QUERY SYSTEM",
                 bg=BG, fg=GOLD, font=FONT_LG).pack(side="left")
        if TESTING_MODE:
            tk.Label(hdr, text="[ TESTING MODE ]",
                     bg=BG, fg=ACCENT, font=FONT_B).pack(side="right")

        self._divider()

        # Question row
        q_outer = tk.Frame(self.root, bg=BG, pady=8)
        q_outer.pack(fill="x", padx=16)
        tk.Label(q_outer, text="Question", bg=BG, fg=MUTED, font=FONT_SM).pack(anchor="w")

        q_row = tk.Frame(q_outer, bg=BG)
        q_row.pack(fill="x", pady=(2, 0))

        self.q_entry = tk.Entry(
            q_row, bg=BG2, fg=FG, font=FONT,
            insertbackground=FG, relief="flat",
            highlightthickness=1, highlightcolor=ACCENT, highlightbackground=MUTED,
        )
        self.q_entry.pack(side="left", fill="x", expand=True, ipady=5)
        self.q_entry.bind("<Return>", lambda _e: self._submit())

        self.sub_btn = self._btn(q_row, "Run", self._submit, state="disabled")
        self.sub_btn.pack(side="left", padx=(4, 0))

        self.gen_btn = self._btn(q_row, "Exsample", self._generate, state="disabled")
        self.gen_btn.pack(side="left", padx=(4, 0))

        # Answer area
        ans_frame = tk.Frame(self.root, bg=BG)
        ans_frame.pack(fill="both", expand=True, padx=16, pady=(0, 4))
        tk.Label(ans_frame, text="Answer", bg=BG, fg=MUTED, font=FONT_SM).pack(anchor="w")

        self.out_text = tk.Text(
            ans_frame, bg=BG2, fg=FG, font=FONT, wrap="word",
            relief="flat", highlightthickness=1,
            highlightcolor=ACCENT, highlightbackground=MUTED,
            state="disabled", height=5, padx=8, pady=6,
        )
        self.out_text.pack(fill="both", expand=True)

        # Metadata (plain labels, not a text box)
        meta = tk.Frame(self.root, bg=BG, pady=4)
        meta.pack(fill="x", padx=16)
        self.meta1 = tk.Label(meta, text="", bg=BG, fg=MUTED, font=FONT_SM, anchor="w")
        self.meta1.pack(fill="x")
        self.meta2 = tk.Label(meta, text="", bg=BG, fg=MUTED, font=FONT_SM, anchor="w")
        self.meta2.pack(fill="x")

        # Testing mode extras
        if TESTING_MODE:
            self._divider()
            self._build_testing_section()

        # Status bar
        self._divider()
        status_bar = tk.Frame(self.root, bg=BG, pady=4)
        status_bar.pack(fill="x", padx=16)
        self.status_lbl = tk.Label(
            status_bar, text="Loading models...",
            bg=BG, fg=GOLD, font=FONT_SM, anchor="w",
        )
        self.status_lbl.pack(side="left")

    def _build_testing_section(self):
        test = tk.Frame(self.root, bg=BG, pady=8)
        test.pack(fill="x", padx=16)

        tk.Label(test, text="Rating", bg=BG, fg=MUTED, font=FONT_SM).grid(
            row=0, column=0, sticky="w")

        radio_row = tk.Frame(test, bg=BG)
        radio_row.grid(row=0, column=1, sticky="w", padx=(8, 0))
        for val, label in [(0, "0 — Wrong"), (1, "1 — Partial"), (2, "2 — Correct")]:
            tk.Radiobutton(
                radio_row, text=label, variable=self._rating_var, value=val,
                bg=BG, fg=FG, selectcolor=BG2,
                activebackground=BG, activeforeground=ACCENT, font=FONT,
            ).pack(side="left", padx=(0, 12))

        tk.Label(test, text="Expected output", bg=BG, fg=MUTED, font=FONT_SM).grid(
            row=1, column=0, sticky="nw", pady=(8, 0))

        self.expected_entry = tk.Text(
            test, bg=BG2, fg=FG, font=FONT, relief="flat", height=2,
            highlightthickness=1, highlightcolor=ACCENT, highlightbackground=MUTED,
            insertbackground=FG, padx=6, pady=4,
        )
        self.expected_entry.grid(row=1, column=1, sticky="ew", pady=(8, 0), padx=(8, 0))
        test.columnconfigure(1, weight=1)

        save_row = tk.Frame(self.root, bg=BG, pady=6)
        save_row.pack(fill="x", padx=16)
        self._btn(save_row, "Save Entry", self._save).pack(side="right")

    # Load Models

    def _start_loading(self):
        self._set_output("Loading knowledge graph and NLP models...\n"
                         "This takes 30–60 s on first run (models are cached after that).")
        threading.Thread(target=self._load_worker, daemon=True).start()

    def _load_worker(self):
        global g, ner, intent_clf, ALL_QUESTIONS
        errors = []

        try:
            import rdflib
            g = rdflib.Graph()
            g.parse(KG_PATH, format="turtle")
        except Exception as e:
            errors.append(f"Knowledge graph ({os.path.basename(KG_PATH)}): {e}")

        try:
            from transformers import pipeline as hf_pipeline
            _hf_available = True
        except ImportError as e:
            errors.append(f"transformers package not found: {e}")
            _hf_available = False

        if _hf_available:
            try:
                ner = hf_pipeline("ner", model="dslim/bert-base-NER",
                                  aggregation_strategy="simple")
            except Exception as e:
                errors.append(f"NER model (dslim/bert-base-NER): {e}")

            try:
                intent_clf = hf_pipeline("zero-shot-classification",
                                         model="facebook/bart-large-mnli")
            except Exception as e:
                errors.append(f"Intent classifier (facebook/bart-large-mnli): {e}")

        try:
            with open(EVAL_PATH) as f:
                ALL_QUESTIONS = [
                    ln.strip() for ln in f
                    if ln.strip() and not ln.startswith('#')
                ]
        except Exception as e:
            errors.append(f"Eval questions file ({os.path.basename(EVAL_PATH)}): {e}")

        self.root.after(0, self._on_load_done, errors)

    def _on_load_done(self, errors):
        if errors:
            detail = "\n".join(f"• {e}" for e in errors)
            messagebox.showerror("Load Error",
                                 f"One or more components failed to load:\n\n{detail}")
            self.status_lbl.config(
                text="⚠  Load failed — see popup for details.", fg=ERR)
            self._set_output("Could not load required components.\n"
                             "Check the error popup and your file paths.")
        else:
            self.sub_btn.config(state="normal")
            self.gen_btn.config(state="normal")
            triple_count = len(g) if g else 0
            self.status_lbl.config(
                text=(f"✓  Ready  |  KG: {triple_count:,} triples  "
                      f"|  {len(ALL_QUESTIONS)} eval questions loaded"),
                fg=FG,
            )
            self._set_output("Ready — type a question or press Generate ✦")

    # Button conectoin functoins

    def _generate(self):
        if ALL_QUESTIONS:
            self.q_entry.delete(0, "end")
            self.q_entry.insert(0, random.choice(ALL_QUESTIONS))
            self.q_entry.focus()

    def _submit(self):
        question = self.q_entry.get().strip()
        if not question:
            return
        self._set_output("Running pipeline...")
        self.meta1.config(text="")
        self.meta2.config(text="")
        self.sub_btn.config(state="disabled")
        self.gen_btn.config(state="disabled")
        threading.Thread(target=self._run_pipeline, args=(question,), daemon=True).start()

    def _run_pipeline(self, question):
        try:
            query_type = detect_query_type(question)
            raw        = answer_question(question)
            formatted  = format_template(raw)

            if query_type == "filter":
                fp   = raw["filter_params"]
                meta = {
                    "query_type":  "filter",
                    "search_type": fp.get("search_type", ""),
                    "constraints": fp.get("constraints", []),
                }
            else:
                # Call parse_question separately to surface confidence in the UI
                parsed = parse_question(question, ner, intent_clf)
                meta   = {
                    "query_type": "lookup",
                    "intent":     parsed["intent"],
                    "confidence": parsed["confidence"],
                    "entities":   parsed["entities"],
                }
        except Exception as exc:
            self.root.after(0, self._on_error, str(exc))
            return

        self.root.after(0, self._on_done, formatted, meta)

    def _on_done(self, formatted, meta):
        self._set_output(formatted)

        if meta["query_type"] == "filter":
            st = meta["search_type"].replace("dbo:", "") if meta["search_type"] else "?"
            cs = ", ".join(
                f"{c['intent']} {c['comparison']} {c['values'][0]}"
                for c in meta["constraints"]
            )
            self.meta1.config(text=f"Query type:  filter  |  Search type: {st}")
            self.meta2.config(text=f"Constraints: {cs}")
        else:
            self.meta1.config(
                text=(f"Query type:  lookup  |  Intent: {meta['intent']}"
                      f"  |  Confidence: {meta['confidence']}"))
            self.meta2.config(text=f"Entities:    {meta['entities']}")

        self.sub_btn.config(state="normal")
        self.gen_btn.config(state="normal")

    def _on_error(self, msg):
        self._set_output(f"Pipeline error:\n{msg}")
        self.sub_btn.config(state="normal")
        self.gen_btn.config(state="normal")

    def _save(self):
        question     = self.q_entry.get().strip()
        output       = self.out_text.get("1.0", "end").strip()
        score        = self._rating_var.get()
        expected_raw = self.expected_entry.get("1.0", "end").strip()
        expected     = expected_raw if expected_raw else None

        entry = {"question": question, "output": output,
                 "score": score, "expected": expected}

        existing = []
        if os.path.exists(SAVE_FILE):
            try:
                with open(SAVE_FILE) as f:
                    existing = json.load(f)
            except Exception:
                existing = []

        existing.append(entry)
        with open(SAVE_FILE, "w") as f:
            json.dump(existing, f, indent=2)

        self.expected_entry.delete("1.0", "end")
        self._rating_var.set(0)
        self.status_lbl.config(
            text=f"✓  Saved entry #{len(existing)} → {os.path.basename(SAVE_FILE)}",
            fg=FG,
        )

    # helper functoins

    def _btn(self, parent, text, cmd, state="normal"):
        return tk.Button(
            parent, text=text, command=cmd, state=state,
            bg=BTN_BG, fg=FG, font=FONT, relief="flat",
            activebackground=ACCENT, activeforeground=BG,
            padx=10, pady=4, cursor="hand2",
        )

    def _divider(self):
        tk.Frame(self.root, bg=ACCENT, height=1).pack(fill="x", padx=16, pady=2)

    def _set_output(self, text):
        self.out_text.config(state="normal")
        self.out_text.delete("1.0", "end")
        self.out_text.insert("1.0", text)
        self.out_text.config(state="disabled")


# =============================================================================
# Entry point
# =============================================================================

if __name__ == "__main__":
    root = tk.Tk()
    AstroApp(root)
    root.mainloop()
