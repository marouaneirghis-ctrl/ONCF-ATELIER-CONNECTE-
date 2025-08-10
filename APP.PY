import streamlit as st
import sqlite3, os, datetime
import pandas as pd
import plotly.express as px
from PIL import Image

# ----------------------------
# Config et initialisation
# ----------------------------
DB_PATH = "oncf.db"
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

def get_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def init_db():
    conn = get_conn()
    c = conn.cursor()
    # Tables
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        username TEXT PRIMARY KEY, password TEXT, role TEXT, fullname TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS trains (
        id_train TEXT PRIMARY KEY, modele TEXT, date_mise_en_service TEXT,
        km_total INTEGER, etat_sante INTEGER, derniere_visite TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS components (
        name TEXT PRIMARY KEY, criticite_max INTEGER
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS parts (
        ref TEXT PRIMARY KEY, designation TEXT, qty INTEGER, seuil_min INTEGER, utilises TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS anomalies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        id_train TEXT, technicien TEXT, date_signalement TEXT,
        categorie TEXT, composant TEXT, description TEXT, photo TEXT,
        immobilisation INTEGER, gravite TEXT, criticite_calc INTEGER, urgence TEXT, statut TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS conformities (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        id_train TEXT, date_intervention TEXT, technicien TEXT,
        type_intervention TEXT, composant TEXT, piece_ref TEXT, resultat TEXT, observations TEXT
    )""")
    conn.commit()

    # Données démo si vides
    if c.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        c.executemany("INSERT INTO users VALUES (?,?,?,?)", [
            ("tech", "password", "technicien", "Technicien Démo"),
            ("responsable", "password", "responsable", "Responsable Démo")
        ])
    if c.execute("SELECT COUNT(*) FROM trains").fetchone()[0] == 0:
        c.executemany("INSERT INTO trains VALUES (?,?,?,?,?,?)", [
            ("Z2M-01","Z2M", "2010-05-20", 450000, 100, ""),
            ("Z2M-05","Z2M", "2011-07-12", 512000, 100, ""),
            ("Z2M-08","Z2M", "2009-03-03", 600000, 100, "")
        ])
    if c.execute("SELECT COUNT(*) FROM components").fetchone()[0] == 0:
        c.executemany("INSERT INTO components VALUES (?,?)", [
            ("frein", 95), ("porte", 80), ("moteur", 90),
            ("climatisation", 40), ("compresseur", 85),
            ("batterie", 70), ("pantographe", 88)
        ])
    if c.execute("SELECT COUNT(*) FROM parts").fetchone()[0] == 0:
        c.executemany("INSERT INTO parts VALUES (?,?,?,?,?)", [
            ("VP001","Valve de pression", 4, 2, "frein"),
            ("VR003","Vérin porte", 2, 1, "porte"),
            ("PLT10","Plaquette de frein", 20, 5, "frein")
        ])
    conn.commit()
    conn.close()

init_db()

# ----------------------------
# Fonctions
# ----------------------------
def now_iso():
    return datetime.datetime.utcnow().isoformat()

def days_ago_iso(days):
    return (datetime.datetime.utcnow() - datetime.timedelta(days=days)).isoformat()

def get_component_criticite(name):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT criticite_max FROM components WHERE name=?", (name,))
    r = c.fetchone()
    conn.close()
    return int(r[0]) if r else 50

def count_similar_recent(train_id, composant, days=90):
    conn = get_conn()
    since = days_ago_iso(days)
    n = conn.execute("SELECT COUNT(*) FROM anomalies WHERE id_train=? AND composant=? AND date_signalement>=?",
                     (train_id, composant, since)).fetchone()[0]
    conn.close()
    return n

def compute_criticite_calc(train_id, composant, gravite, immobilisation):
    criticite_max = get_component_criticite(composant)
    grav_map = {"Urgent":1.0, "Moyen":0.6, "Faible":0.3}
    grav = grav_map.get(gravite, 0.6)
    occ = count_similar_recent(train_id, composant)
    freq_factor = min(1.0, occ / 5.0)
    imm = 1.0 if immobilisation else 0.6
    score = criticite_max * (0.5 + 0.3 * grav + 0.2 * freq_factor * imm)
    return int(max(0, min(100, round(score))))

def recalc_train_health(train_id, days_window=90):
    conn = get_conn()
    since = days_ago_iso(days_window)
    rows = conn.execute("SELECT criticite_calc FROM anomalies WHERE id_train=? AND date_signalement>=?",
                        (train_id, since)).fetchall()
    if not rows:
        health = 100
    else:
        n = len(rows)
        s = sum(r[0] for r in rows)
        fraction = s / (n * 100)
        health = int(max(0, min(100, round(100 - fraction * 100))))
    conn.execute("UPDATE trains SET etat_sante=? WHERE id_train=?", (health, train_id))
    conn.commit()
    conn.close()
    return health

# ----------------------------
# Interface
# ----------------------------
st.set_page_config(page_title="ONCF Atelier Connecté", layout="wide")
st.title("🚄 ONCF - Atelier Connecté")

if 'auth' not in st.session_state:
    st.session_state.update({'auth': False, 'user': None, 'role': None})

def login(username, password):
    conn = get_conn()
    r = conn.execute("SELECT role FROM users WHERE username=? AND password=?", (username, password)).fetchone()
    conn.close()
    if r:
        st.session_state.update({'auth': True, 'user': username, 'role': r[0]})
        return True
    return False

def logout():
    st.session_state.update({'auth': False, 'user': None, 'role': None})

if not st.session_state['auth']:
    st.subheader("Connexion")
    username = st.text_input("Nom d'utilisateur")
    password = st.text_input("Mot de passe", type="password")
    if st.button("Se connecter"):
        if not login(username.strip(), password.strip()):
            st.error("Identifiants incorrects")
        else:
            st.success("Connecté")
            st.experimental_rerun()
    st.stop()

st.sidebar.write(f"Connecté : **{st.session_state['user']}** ({st.session_state['role']})")
if st.sidebar.button("Se déconnecter"):
    logout()
    st.experimental_rerun()

role = st.session_state['role']
user = st.session_state['user']

# Exemple : tableau trains
st.header("Liste des trains et état de santé")
df_trains = pd.read_sql_query("SELECT * FROM trains", get_conn())
st.dataframe(df_trains)

# Ajout d'une anomalie (tech)
if role == "technicien":
    st.subheader("Ajouter une anomalie")
    trains = df_trains['id_train'].tolist()
    sid = st.selectbox("Train", trains)
    comp = pd.read_sql_query("SELECT name FROM components", get_conn())['name'].tolist()
    composant = st.selectbox("Composant", comp)
    grav = st.selectbox("Gravité", ["Urgent","Moyen","Faible"])
    immobil = st.checkbox("Immobilisation ?")
    desc = st.text_area("Description")
    if st.button("Enregistrer"):
        crit = compute_criticite_calc(sid, composant, grav, immobil)
        conn = get_conn()
        conn.execute("""INSERT INTO anomalies 
            (id_train, technicien, date_signalement, categorie, composant, description, photo, immobilisation, gravite, criticite_calc, urgence, statut)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (sid, user, now_iso(), "mécanique", composant, desc, "", int(immobil), grav, crit,
             "critique" if crit >= 80 else "moyenne" if crit >= 50 else "faible", "à traiter"))
        conn.commit()
        conn.close()
        new_health = recalc_train_health(sid)
        st.success(f"Anomalie enregistrée. Santé du train = {new_health}%")
