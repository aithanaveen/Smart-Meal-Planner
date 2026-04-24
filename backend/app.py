from flask import Flask, jsonify, request, send_file
from flask_cors import CORS
import sqlite3
import os
import json
from datetime import datetime, timedelta, timezone
import random

app = Flask(__name__)
CORS(app)

FRONTEND_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'frontend', 'index.html')

@app.route('/')
def index():
    return send_file(os.path.abspath(FRONTEND_PATH))

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pantry.db')

# ---------------------------------------------------------------------------
# Recipe / Appliance hardcoded maps
# ---------------------------------------------------------------------------
RECIPE_REQUIREMENTS = {
    "Chicken Curry":   ["Rice", "Olive Oil", "Butter"],
    "Scrambled Eggs":  ["Eggs", "Butter", "Milk"],
    "Garlic Rice":     ["Rice", "Butter", "Olive Oil"],
    "Pancakes":        ["Flour", "Milk", "Eggs", "Butter"],
    "Pasta":           ["Flour", "Olive Oil"],
}

RECIPE_STEPS = {
    "Chicken Curry":   ["kettle", "food_processor", "rice_cooker"],
    "Scrambled Eggs":  ["kettle"],
    "Garlic Rice":     ["rice_cooker"],
    "Pancakes":        ["food_processor", "kettle"],
    "Pasta":           ["kettle", "food_processor"],
}

RECIPE_EMOJIS = {
    "Chicken Curry":   "🍛",
    "Scrambled Eggs":  "🍳",
    "Garlic Rice":     "🍚",
    "Pancakes":        "🥞",
    "Pasta":           "🍝",
}

RECIPE_TIMES = {
    "Chicken Curry":   "35 mins",
    "Scrambled Eggs":  "10 mins",
    "Garlic Rice":     "20 mins",
    "Pancakes":        "25 mins",
    "Pasta":           "30 mins",
}

# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()

    c.execute('''
        CREATE TABLE IF NOT EXISTS ingredients (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            rfid_uid      TEXT UNIQUE,
            name          TEXT NOT NULL,
            weight        REAL DEFAULT 0,
            max_weight    REAL DEFAULT 1000,
            threshold_pct REAL DEFAULT 20,
            last_updated  TEXT
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS alerts (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            ingredient_id INTEGER,
            alert_type    TEXT,
            message       TEXT,
            severity      TEXT,
            timestamp     TEXT,
            resolved      INTEGER DEFAULT 0
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS shopping_list (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            name     TEXT NOT NULL,
            quantity REAL DEFAULT 1,
            unit     TEXT DEFAULT 'unit',
            checked  INTEGER DEFAULT 0
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS weight_history (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            ingredient_id INTEGER,
            weight        REAL,
            recorded_at   TEXT
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS cooking_signals (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            recipe     TEXT,
            steps      TEXT,
            status     TEXT DEFAULT 'pending',
            created_at TEXT
        )
    ''')

    # Seed ingredients only if the table is empty
    c.execute('SELECT COUNT(*) FROM ingredients')
    if c.fetchone()[0] == 0:
        now = datetime.now(timezone.utc).isoformat()
        seeds = [
            ('A1B2C3D4', 'Rice',      1200, 1500, 20, now),
            ('B2C3D4E5', 'Milk',       800, 1000, 20, now),
            ('C3D4E5F6', 'Eggs',       180,  600, 20, now),
            ('D4E5F6A1', 'Butter',     450,  500, 20, now),
            ('E5F6A1B2', 'Olive Oil',  120,  750, 20, now),
            ('F6A1B2C3', 'Flour',      900, 1000, 20, now),
        ]
        c.executemany(
            'INSERT INTO ingredients (rfid_uid, name, weight, max_weight, threshold_pct, last_updated) '
            'VALUES (?,?,?,?,?,?)', seeds
        )

        # Seed 7 days of weight history per ingredient
        random.seed(42)
        for rfid, name, cur_w, max_w, thr, _ in seeds:
            c.execute('SELECT id FROM ingredients WHERE rfid_uid = ?', (rfid,))
            ing_id = c.fetchone()[0]
            for days_ago in range(6, -1, -1):
                dt = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
                w = max(0, cur_w + random.randint(-200, 100))
                c.execute(
                    'INSERT INTO weight_history (ingredient_id, weight, recorded_at) VALUES (?,?,?)',
                    (ing_id, w, dt)
                )

        # Seed alerts for Olive Oil (16%) and Eggs (30%)
        for rfid, name, cur_w, max_w, thr, _ in seeds:
            pct = (cur_w / max_w * 100)
            if pct <= thr:
                c.execute('SELECT id FROM ingredients WHERE rfid_uid = ?', (rfid,))
                ing_id = c.fetchone()[0]
                severity = 'critical' if pct <= thr / 2 else 'warning'
                msg = f'{name} is {"critically " if severity == "critical" else ""}low ({pct:.0f}%)'
                c.execute(
                    'INSERT INTO alerts (ingredient_id, alert_type, message, severity, timestamp, resolved) '
                    'VALUES (?,?,?,?,?,0)',
                    (ing_id, 'low_stock', msg, severity, now)
                )

        # Seed a couple of shopping list items
        c.executemany(
            'INSERT INTO shopping_list (name, quantity, unit, checked) VALUES (?,?,?,?)',
            [('Olive Oil', 1, 'bottle', 0), ('Eggs', 12, 'pcs', 0)]
        )

    conn.commit()
    conn.close()


def ingredient_status(weight, max_weight, threshold_pct):
    pct = (weight / max_weight * 100) if max_weight > 0 else 0
    if pct <= threshold_pct / 2:
        return 'critical'
    if pct <= threshold_pct:
        return 'low'
    return 'ok'


# ---------------------------------------------------------------------------
# ESP32 → Backend: POST /update-weight
# ---------------------------------------------------------------------------
@app.route('/update-weight', methods=['POST'])
def update_weight():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': 'No JSON payload'}), 400

    rfid_uid   = data.get('rfid_uid')
    ingredient = data.get('ingredient')
    weight     = data.get('weight')

    if not rfid_uid or not ingredient or weight is None:
        return jsonify({'error': 'Required: rfid_uid, ingredient, weight'}), 400

    now = datetime.utcnow().isoformat()
    conn = get_db()
    c = conn.cursor()

    # Upsert
    c.execute('''
        INSERT INTO ingredients (rfid_uid, name, weight, max_weight, threshold_pct, last_updated)
        VALUES (?, ?, ?, 1000, 20, ?)
        ON CONFLICT(rfid_uid) DO UPDATE SET
            name         = excluded.name,
            weight       = excluded.weight,
            last_updated = excluded.last_updated
    ''', (rfid_uid, ingredient, weight, now))

    c.execute('SELECT id, max_weight, threshold_pct FROM ingredients WHERE rfid_uid = ?', (rfid_uid,))
    row = c.fetchone()
    ing_id        = row['id']
    max_weight    = row['max_weight']
    threshold_pct = row['threshold_pct']

    # History
    c.execute('INSERT INTO weight_history (ingredient_id, weight, recorded_at) VALUES (?,?,?)',
              (ing_id, weight, now))

    # Alert if below threshold and no existing open alert
    alert_generated = False
    pct = (weight / max_weight * 100) if max_weight > 0 else 0
    if pct <= threshold_pct:
        c.execute('SELECT id FROM alerts WHERE ingredient_id = ? AND resolved = 0 AND alert_type = ?',
                  (ing_id, 'low_stock'))
        if not c.fetchone():
            severity = 'critical' if pct <= threshold_pct / 2 else 'warning'
            msg = f'{ingredient} is {"critically " if severity == "critical" else ""}low ({pct:.0f}%)'
            c.execute(
                'INSERT INTO alerts (ingredient_id, alert_type, message, severity, timestamp, resolved) '
                'VALUES (?,?,?,?,?,0)',
                (ing_id, 'low_stock', msg, severity, now)
            )
            alert_generated = True

    conn.commit()
    conn.close()
    return jsonify({'status': 'ok', 'alert_generated': alert_generated, 'percentage': round(pct, 1)})


# ---------------------------------------------------------------------------
# GET /ingredients
# ---------------------------------------------------------------------------
@app.route('/ingredients', methods=['GET'])
def get_ingredients():
    conn = get_db()
    rows = conn.execute('SELECT * FROM ingredients ORDER BY name ASC').fetchall()
    conn.close()

    result = []
    for r in rows:
        pct = (r['weight'] / r['max_weight'] * 100) if r['max_weight'] > 0 else 0
        result.append({
            'id':            r['id'],
            'name':          r['name'],
            'rfid_uid':      r['rfid_uid'],
            'weight':        r['weight'],
            'max_weight':    r['max_weight'],
            'threshold_pct': r['threshold_pct'],
            'status':        ingredient_status(r['weight'], r['max_weight'], r['threshold_pct']),
            'percentage':    round(pct, 1),
            'last_updated':  r['last_updated'],
        })
    return jsonify(result)


# ---------------------------------------------------------------------------
# GET /alerts
# ---------------------------------------------------------------------------
@app.route('/alerts', methods=['GET'])
def get_alerts():
    conn = get_db()
    rows = conn.execute('''
        SELECT a.id, i.name AS ingredient_name, a.alert_type,
               a.message, a.severity, a.timestamp
        FROM alerts a
        JOIN ingredients i ON a.ingredient_id = i.id
        WHERE a.resolved = 0
        ORDER BY a.timestamp DESC
    ''').fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


# ---------------------------------------------------------------------------
# Shopping list CRUD
# ---------------------------------------------------------------------------
@app.route('/shopping', methods=['GET'])
def get_shopping():
    conn = get_db()
    rows = conn.execute('SELECT * FROM shopping_list ORDER BY checked ASC, id DESC').fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/shopping', methods=['POST'])
def add_shopping():
    data = request.get_json(silent=True)
    if not data or not data.get('name'):
        return jsonify({'error': 'name is required'}), 400
    conn = get_db()
    c = conn.cursor()
    c.execute('INSERT INTO shopping_list (name, quantity, unit, checked) VALUES (?,?,?,0)',
              (data['name'], data.get('quantity', 1), data.get('unit', 'unit')))
    conn.commit()
    new_id = c.lastrowid
    conn.close()
    return jsonify({'id': new_id, 'status': 'added'}), 201


@app.route('/shopping/<int:item_id>', methods=['PATCH'])
def toggle_shopping(item_id):
    conn = get_db()
    conn.execute('UPDATE shopping_list SET checked = NOT checked WHERE id = ?', (item_id,))
    conn.commit()
    conn.close()
    return jsonify({'status': 'toggled'})


@app.route('/shopping/<int:item_id>', methods=['DELETE'])
def delete_shopping(item_id):
    conn = get_db()
    conn.execute('DELETE FROM shopping_list WHERE id = ?', (item_id,))
    conn.commit()
    conn.close()
    return jsonify({'status': 'deleted'})


# ---------------------------------------------------------------------------
# GET /analytics
# ---------------------------------------------------------------------------
@app.route('/analytics', methods=['GET'])
def get_analytics():
    conn = get_db()
    seven_days_ago = (datetime.utcnow() - timedelta(days=7)).isoformat()
    ingredients = conn.execute('SELECT id, name FROM ingredients').fetchall()

    result = {}
    for ing in ingredients:
        rows = conn.execute('''
            SELECT weight, recorded_at FROM weight_history
            WHERE ingredient_id = ? AND recorded_at >= ?
            ORDER BY recorded_at ASC
        ''', (ing['id'], seven_days_ago)).fetchall()
        result[ing['name']] = [
            {'weight': r['weight'], 'recorded_at': r['recorded_at']} for r in rows
        ]

    conn.close()
    return jsonify(result)


# ---------------------------------------------------------------------------
# PATCH /settings
# ---------------------------------------------------------------------------
@app.route('/settings', methods=['PATCH'])
def update_settings():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': 'No data'}), 400

    conn = get_db()
    if 'threshold_pct' in data:
        conn.execute('UPDATE ingredients SET threshold_pct = ?', (data['threshold_pct'],))
    conn.commit()
    conn.close()
    return jsonify({'status': 'ok'})


# ---------------------------------------------------------------------------
# POST /start-cooking
# ---------------------------------------------------------------------------
@app.route('/start-cooking', methods=['POST'])
def start_cooking():
    data = request.get_json(silent=True)
    if not data or not data.get('recipe'):
        return jsonify({'error': 'recipe is required'}), 400

    recipe = data['recipe']
    if recipe not in RECIPE_REQUIREMENTS:
        return jsonify({'error': f'Unknown recipe: {recipe}'}), 404

    required = RECIPE_REQUIREMENTS[recipe]
    steps    = RECIPE_STEPS.get(recipe, [])

    conn = get_db()
    rows = conn.execute('SELECT name, weight, max_weight, threshold_pct FROM ingredients').fetchall()
    conn.close()

    stock = {r['name']: r for r in rows}
    missing = []
    for ing_name in required:
        if ing_name not in stock:
            missing.append(ing_name)
        else:
            r   = stock[ing_name]
            pct = (r['weight'] / r['max_weight'] * 100) if r['max_weight'] > 0 else 0
            if pct <= r['threshold_pct']:
                missing.append(ing_name)

    if missing:
        return jsonify({'status': 'insufficient', 'missing': missing})

    now = datetime.utcnow().isoformat()
    conn = get_db()
    conn.execute(
        "INSERT INTO cooking_signals (recipe, steps, status, created_at) VALUES (?,?,'pending',?)",
        (recipe, json.dumps(steps), now)
    )
    conn.commit()
    conn.close()
    return jsonify({'status': 'ok', 'steps': steps})


# ---------------------------------------------------------------------------
# GET /cooking-signal  (polled by ESP32 every 5 s)
# ---------------------------------------------------------------------------
@app.route('/cooking-signal', methods=['GET'])
def get_cooking_signal():
    conn = get_db()
    c = conn.cursor()
    row = c.execute(
        "SELECT id, recipe, steps FROM cooking_signals WHERE status = 'pending' "
        "ORDER BY created_at ASC LIMIT 1"
    ).fetchone()

    if not row:
        conn.close()
        return jsonify({'pending': False})

    c.execute("UPDATE cooking_signals SET status = 'dispatched' WHERE id = ?", (row['id'],))
    conn.commit()
    conn.close()
    return jsonify({'pending': True, 'recipe': row['recipe'], 'steps': json.loads(row['steps'])})


# ---------------------------------------------------------------------------
# GET /recipes  (used by frontend meal planner)
# ---------------------------------------------------------------------------
@app.route('/recipes', methods=['GET'])
def get_recipes():
    conn = get_db()
    rows = conn.execute('SELECT name, weight, max_weight, threshold_pct FROM ingredients').fetchall()
    conn.close()

    stock = {r['name']: r for r in rows}
    recipes_out = []

    for recipe, required in RECIPE_REQUIREMENTS.items():
        missing = []
        for ing in required:
            if ing not in stock:
                missing.append(ing)
            else:
                r   = stock[ing]
                pct = (r['weight'] / r['max_weight'] * 100) if r['max_weight'] > 0 else 0
                if pct <= r['threshold_pct']:
                    missing.append(ing)
        recipes_out.append({
            'name':        recipe,
            'emoji':       RECIPE_EMOJIS.get(recipe, '🍽️'),
            'time':        RECIPE_TIMES.get(recipe, '30 mins'),
            'can_cook':    len(missing) == 0,
            'missing':     missing,
            'ingredients': required,
            'steps':       RECIPE_STEPS.get(recipe, []),
        })

    # Can-cook recipes first
    recipes_out.sort(key=lambda x: (0 if x['can_cook'] else 1, x['name']))
    return jsonify(recipes_out)


if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5000, debug=True)
