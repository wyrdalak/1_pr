# server.py
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os, uuid, datetime

app = Flask(__name__)
CORS(app)  # чтобы клиенты на любых хостах могли обращаться
# Абсолютный каталог, где лежит server.py
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Директории и файлы для хранения
DATA_DIR = os.path.join(BASE_DIR, 'data')
EMP_DIR = os.path.join(DATA_DIR, 'known_faces')
ENV_DIR = os.path.join(DATA_DIR, 'environments')
LOG_FILE = os.path.join(DATA_DIR, 'access.log')

os.makedirs(EMP_DIR, exist_ok=True)
os.makedirs(ENV_DIR, exist_ok=True)

# Храним словари в памяти; при перезапуске сервера они обнулятся,
# но фото и логи сохранятся в файловой системе.
employees = {}      # name -> {'dept', 'filename'}
environments = {}   # id -> {'id','name','location','filename'}

# --- REST для сотрудников ---
@app.route('/api/employees', methods=['GET'])
def list_employees():
    out = []
    for name, meta in employees.items():
        out.append({
            'name': name,
            'dept':  meta['dept'],
            'photo_url': f'/api/employees/photo/{meta["filename"]}'
        })
    return jsonify(out)

@app.route('/api/employees', methods=['POST'])
def add_employee():
    name = request.form['name']
    dept = request.form['dept']
    photo = request.files['photo']
    ext = os.path.splitext(photo.filename)[1]
    fn = f"{uuid.uuid4().hex}{ext}"
    photo.save(os.path.join(EMP_DIR, fn))
    employees[name] = {'dept': dept, 'filename': fn}
    return jsonify({'status':'ok'}), 201

@app.route('/api/employees/<name>', methods=['DELETE'])
def del_employee(name):
    meta = employees.pop(name, None)
    if meta:
        try: os.remove(os.path.join(EMP_DIR, meta['filename']))
        except: pass
    return jsonify({'status':'ok'})

@app.route('/api/employees/photo/<filename>')
def get_employee_photo(filename):
    return send_from_directory(EMP_DIR, filename)

# --- REST для помещений ---
@app.route('/api/environments', methods=['GET'])
def list_env():
    return jsonify(list(environments.values()))

@app.route('/api/environments', methods=['POST'])
def add_env():
    nm = request.form['name']
    loc = request.form['location']
    img = request.files['image']
    ext = os.path.splitext(img.filename)[1]
    eid = uuid.uuid4().hex
    fn = f"{eid}{ext}"
    img.save(os.path.join(ENV_DIR, fn))
    env = {'id': eid, 'name': nm, 'location': loc, 'image_url': f'/api/environments/image/{fn}'}
    environments[eid] = env
    return jsonify(env), 201

@app.route('/api/environments/<eid>', methods=['DELETE'])
def del_env(eid):
    env = environments.pop(eid, None)
    if env:
        try: os.remove(os.path.join(ENV_DIR, os.path.basename(env['image_url'])))
        except: pass
    return jsonify({'status':'ok'})

@app.route('/api/environments/image/<filename>')
def get_env_img(filename):
    return send_from_directory(ENV_DIR, filename)

# --- REST для логов ---
@app.route('/api/logs', methods=['POST'])
def post_log():
    entry = request.json
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        # timestamp, level, message
        f.write(f"{entry['timestamp']} {entry['level']}: {entry['message']}\n")
    return jsonify({'status':'ok'}), 201

@app.route('/api/logs', methods=['GET'])
def get_logs():
    order = request.args.get('order', 'desc')
    try:
        lines = open(LOG_FILE, 'r', encoding='utf-8').read().splitlines()
    except FileNotFoundError:
        lines = []
    lines.sort(reverse=(order=='desc'))
    return jsonify(lines)

if __name__ == '__main__':
    # слушаем на всех интерфейсах, порт 5001
    app.run(host='0.0.0.0', port=5001)