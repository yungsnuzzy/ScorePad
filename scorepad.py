import sqlite3, uuid, json, csv, io, os
from datetime import datetime
from flask import Flask, render_template, request, jsonify, redirect, url_for, session, make_response

app = Flask(__name__)

# Load dictionary cache
_dictionary_words = None
_definitions = None

def load_dictionary():
    global _dictionary_words
    if _dictionary_words is None:
        dict_path = os.path.join(os.path.dirname(__file__), 'dictionary', 'NWL2023.txt')
        try:
            with open(dict_path, 'r') as f:
                _dictionary_words = set(word.strip().upper() for word in f.readlines() if word.strip())
        except FileNotFoundError:
            _dictionary_words = set()
    return _dictionary_words

def load_definitions():
    global _definitions
    if _definitions is None:
        def_path = os.path.join(os.path.dirname(__file__), 'dictionary', 'dictionary.json')
        try:
            with open(def_path, 'r', encoding='utf-8') as f:
                definitions_list = json.load(f)
                _definitions = {}
                for entry in definitions_list:
                    word = entry.get('word', '').upper()
                    definitions = entry.get('definitions', [])
                    pos = entry.get('pos', '')
                    if word and definitions:
                        # Create a list to hold all parts of speech for a word
                        if word not in _definitions:
                            _definitions[word] = []
                        _definitions[word].append({
                            'pos': pos,
                            'definitions': definitions
                        })
        except (FileNotFoundError, json.JSONDecodeError):
            _definitions = {}
    return _definitions

def init_db():
    conn = sqlite3.connect('card_games.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS games (
            id TEXT PRIMARY KEY,
            game_type TEXT NOT NULL,
            variant TEXT,
            players TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP,
            status TEXT DEFAULT 'active',
            data TEXT
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id TEXT NOT NULL,
            round_number INTEGER,
            player_name TEXT NOT NULL,
            score INTEGER DEFAULT 0,
            bid TEXT,
            made_bid BOOLEAN,
            notes TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (game_id) REFERENCES games (id)
        )
    ''')
    
    conn.commit()
    conn.close()

def get_game_variants(game_type):
    variants_map = {
        'bridge': [
            {'id': 'draw', 'name': 'Draw Bridge', 'description': 'Two-player with card drawing phase'},
            {'id': 'draw_discard', 'name': 'Draw and Discard', 'description': 'Choose to take or discard from stock'},
            {'id': 'double_dummy', 'name': 'Double Dummy', 'description': 'Four hands, two dummies exposed'},
            {'id': 'single_dummy', 'name': 'Single Dummy', 'description': 'One dummy exposed before bidding'},
            {'id': 'memory', 'name': 'Memory Bridge', 'description': 'No replacement cards, memory challenge'}
        ],
        'rummy': [
            {'id': 'basic', 'name': 'Basic Rummy', 'description': 'Classic rummy rules'},
            {'id': 'gin', 'name': 'Gin Rummy', 'description': 'Two-player gin rummy'},
            {'id': 'oklahoma', 'name': 'Oklahoma Rummy', 'description': 'Gin rummy with wild card'}
        ],
        'canasta': [
            {'id': 'classic', 'name': 'Classic Canasta', 'description': 'Traditional four-player partnership'}
        ]
    }
    return variants_map.get(game_type, [{'id': 'basic', 'name': 'Standard', 'description': 'Standard rules'}])

def get_game_config(game_type, variant):
    configs = {
        'bridge': {
            'draw': {
                'name': 'Draw Bridge',
                'rules_url': 'https://www.pagat.com/auctionwhist/honeymoon.html#draw',
                'quick_tips': [
                    'First 13 tricks at no trump - no need to follow suit',
                    'Winner draws first card, loser draws second',
                    'After drawing phase, bid like contract bridge',
                    'Final contract played with normal bridge rules',
                    'Scoring follows rubber bridge rules'
                ],
                'scoring_info': [
                    'Overtricks: 20 points each (30 in NT)',
                    'Game: 100+ points below line',
                    'Small slam: 500 points (750 vulnerable)',
                    'Grand slam: 1000 points (1500 vulnerable)'
                ]
            }
        }
    }
    return configs.get(game_type, {}).get(variant, {})

@app.template_filter('from_json')
def from_json(value):
    if value:
        try:
            return json.loads(value)
        except:
            return []
    return []

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/game/<game_type>')
def select_variant(game_type):
    variants = get_game_variants(game_type)
    if len(variants) == 1:
        return redirect(url_for('setup_game', game_type=game_type, variant=variants[0]['id']))
    return render_template('variants.html', game_type=game_type, variants=variants)

@app.route('/setup/<game_type>/<variant>')
def setup_game(game_type, variant):
    return render_template('setup.html', game_type=game_type, variant=variant)

@app.route('/play/<game_type>/<variant>')
def play_game(game_type, variant):
    game_id = request.args.get('game_id')
    if not game_id:
        game_id = str(uuid.uuid4())
        players = request.args.getlist('players')
        
        conn = sqlite3.connect('card_games.db')
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO games (id, game_type, variant, players, data)
            VALUES (?, ?, ?, ?, ?)
        ''', (game_id, game_type, variant, json.dumps(players), json.dumps({})))
        conn.commit()
        conn.close()
    
    return render_template('game.html', 
                         game_type=game_type, 
                         variant=variant, 
                         game_id=game_id,
                         game_config=get_game_config(game_type, variant))

@app.route('/api/score', methods=['POST'])
def add_score():
    data = request.json
    game_id = data['game_id']
    
    conn = sqlite3.connect('card_games.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO scores (game_id, round_number, player_name, score, bid, made_bid, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (game_id, data.get('round_number', 1), data['player'], 
          data['score'], data.get('bid'), data.get('made_bid'), data.get('notes')))
    
    conn.commit()
    conn.close()
    
    return jsonify({'success': True})

@app.route('/api/scores/<game_id>')
def get_scores(game_id):
    conn = sqlite3.connect('card_games.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT id, round_number, player_name, score, bid, made_bid, notes, timestamp
        FROM scores WHERE game_id = ? ORDER BY round_number, timestamp
    ''', (game_id,))
    
    scores = cursor.fetchall()
    conn.close()
    
    return jsonify([{
        'id': s[0], 'round': s[1], 'player': s[2], 'score': s[3], 
        'bid': s[4], 'made_bid': s[5], 'notes': s[6], 'timestamp': s[7]
    } for s in scores])

@app.route('/api/recent-games')
def get_recent_games():
    conn = sqlite3.connect('card_games.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT id, game_type, variant, players, created_at, status
        FROM games 
        ORDER BY created_at DESC 
        LIMIT 5
    ''')
    
    games = cursor.fetchall()
    conn.close()
    
    return jsonify([{
        'id': g[0], 'game_type': g[1], 'variant': g[2], 
        'players': json.loads(g[3]) if g[3] else [], 
        'created_at': g[4], 'status': g[5]
    } for g in games])

@app.route('/api/game/<game_id>')
def get_game_details(game_id):
    conn = sqlite3.connect('card_games.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT id, game_type, variant, players, created_at, completed_at, status, data
        FROM games WHERE id = ?
    ''', (game_id,))
    
    game = cursor.fetchone()
    
    if not game:
        conn.close()
        return jsonify({'error': 'Game not found'}), 404
    
    cursor.execute('''
        SELECT id, round_number, player_name, score, bid, made_bid, notes, timestamp
        FROM scores WHERE game_id = ? ORDER BY round_number, timestamp
    ''', (game_id,))
    
    scores = cursor.fetchall()
    conn.close()
    
    return jsonify({
        'game': {
            'id': game[0], 'game_type': game[1], 'variant': game[2],
            'players': json.loads(game[3]) if game[3] else [],
            'created_at': game[4], 'completed_at': game[5],
            'status': game[6], 'data': json.loads(game[7]) if game[7] else {}
        },
        'scores': [{
            'id': s[0], 'round': s[1], 'player': s[2], 'score': s[3],
            'bid': s[4], 'made_bid': s[5], 'notes': s[6], 'timestamp': s[7]
        } for s in scores]
    })

@app.route('/api/game/<game_id>/finish', methods=['POST'])
def finish_game(game_id):
    conn = sqlite3.connect('card_games.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        UPDATE games 
        SET status = 'completed', completed_at = CURRENT_TIMESTAMP 
        WHERE id = ?
    ''', (game_id,))
    
    conn.commit()
    conn.close()
    
    return jsonify({'success': True, 'message': 'Game finished successfully'})

@app.route('/api/game/<game_id>/export')
def export_game(game_id):
    conn = sqlite3.connect('card_games.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT game_type, variant, players, created_at, completed_at, status
        FROM games WHERE id = ?
    ''', (game_id,))
    
    game = cursor.fetchone()
    if not game:
        return jsonify({'error': 'Game not found'}), 404
    
    cursor.execute('''
        SELECT round_number, player_name, score, bid, made_bid, notes, timestamp
        FROM scores WHERE game_id = ? ORDER BY round_number, timestamp
    ''', (game_id,))
    
    scores = cursor.fetchall()
    conn.close()
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    writer.writerow(['Game Information'])
    writer.writerow(['Game ID', game_id])
    writer.writerow(['Game Type', game[0].title()])
    writer.writerow(['Variant', game[1] or 'Standard'])
    writer.writerow(['Players', ', '.join(json.loads(game[2]) if game[2] else [])])
    writer.writerow(['Created', game[3]])
    writer.writerow(['Completed', game[4] or 'In Progress'])
    writer.writerow(['Status', game[5]])
    writer.writerow([])
    
    writer.writerow(['Round', 'Player', 'Score', 'Bid', 'Made Bid', 'Notes', 'Timestamp'])
    
    for score in scores:
        writer.writerow(score)
    
    writer.writerow([])
    writer.writerow(['Player Totals'])
    players = json.loads(game[2]) if game[2] else []
    for player in players:
        total = sum(s[2] for s in scores if s[1] == player)
        writer.writerow([player, total])
    
    response = make_response(output.getvalue())
    response.headers["Content-Disposition"] = f"attachment; filename={game[0]}_{game_id[:8]}.csv"
    response.headers["Content-type"] = "text/csv"
    
    return response

@app.route('/api/game/<game_id>/reset', methods=['POST'])
def reset_game(game_id):
    conn = sqlite3.connect('card_games.db')
    cursor = conn.cursor()
    
    cursor.execute('DELETE FROM scores WHERE game_id = ?', (game_id,))
    
    cursor.execute('''
        UPDATE games 
        SET status = 'active', completed_at = NULL 
        WHERE id = ?
    ''', (game_id,))
    
    conn.commit()
    conn.close()
    
    return jsonify({'success': True, 'message': 'Game reset successfully'})

@app.route('/api/game/<game_id>', methods=['DELETE'])
def delete_game(game_id):
    conn = sqlite3.connect('card_games.db')
    cursor = conn.cursor()
    
    cursor.execute('DELETE FROM scores WHERE game_id = ?', (game_id,))
    
    cursor.execute('DELETE FROM games WHERE id = ?', (game_id,))
    
    conn.commit()
    conn.close()
    
    return jsonify({'success': True, 'message': 'Game deleted successfully'})

@app.route('/api/score/<int:score_id>', methods=['DELETE'])
def delete_score(score_id):
    conn = sqlite3.connect('card_games.db')
    cursor = conn.cursor()
    
    cursor.execute('DELETE FROM scores WHERE id = ?', (score_id,))
    
    conn.commit()
    conn.close()
    
    return jsonify({'success': True, 'message': 'Score deleted successfully'})

@app.route('/history')
def game_history():
    conn = sqlite3.connect('card_games.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT id, game_type, variant, players, created_at, completed_at, status
        FROM games ORDER BY created_at DESC
    ''')
    
    games = cursor.fetchall()
    conn.close()
    
    return render_template('history.html', games=games)

@app.route('/scrabble')
def scrabble():
    return render_template('scrabble.html')

@app.route('/api/search-word')
def search_word():
    word = request.args.get('word', '').strip().upper()
    
    if not word:
        return jsonify({'valid': False, 'message': 'Please enter a word'})
    
    if len(word) < 3:
        return jsonify({'valid': False, 'message': 'Word must be at least 3 letters'})
    
    dictionary = load_dictionary()
    is_valid = word in dictionary
    
    result = {
        'word': word,
        'valid': is_valid,
        'message': f"'{word}' is {'VALID' if is_valid else 'NOT VALID'} in NWL2023"
    }
    
    # Add definitions if word is valid
    if is_valid:
        definitions = load_definitions()
        if word in definitions:
            result['word_entries'] = definitions[word]
    
    return jsonify(result)

if __name__ == '__main__':
    app.secret_key = 'your-secret-key-change-this'
    init_db()
    app.run(debug=True, host='0.0.0.0', port=2283)