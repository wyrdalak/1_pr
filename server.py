from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os, uuid, datetime, json

# Инициализация приложения
app = Flask(__name__)
CORS(app)

# Абсолютные пути
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
EMP_DIR = os.path.join(DATA_DIR, 'employees')
ENV_DIR = os.path.join(DATA_DIR, 'environments')
LOG_FILE = os.path.join(DATA_DIR, 'access.log')
EMP_META = os.path.join(DATA_DIR, 'employees.json')
ENV_META = os.path.join(DATA_DIR, 'environments.json')

# Создаём каталоги и файлы
os.makedirs(EMP_DIR, exist_ok=True)
os.makedirs(ENV_DIR, exist_ok=True)
for path in (EMP_META, ENV_META, LOG_FILE):
    if not os.path.exists(path):
        # пустой JSON для метаданных, пустой файл для логов
        with open(path, 'w', encoding='utf-8') as f:
            f.write('[]' if path.endswith('.json') else '')

# Загружаем метаданные
with open(EMP_META, 'r', encoding='utf-8') as f:
    employees = {item['name']: item for item in json.load(f)}
with open(ENV_META, 'r', encoding='utf-8') as f:
    env_list = json.load(f)
    environments = {item['id']: item for item in env_list}

# Утилиты сохранения

def _save_employees():
    with open(EMP_META, 'w', encoding='utf-8') as f:
        json.dump(list(employees.values()), f, ensure_ascii=False, indent=2)


@app.route('/api/employees/version', methods=['GET'])
def employees_version():
    """Return modification timestamp of employee metadata."""
    return jsonify({'version': os.path.getmtime(EMP_META)})


def _save_environments():
    with open(ENV_META, 'w', encoding='utf-8') as f:
        json.dump(list(environments.values()), f, ensure_ascii=False, indent=2)

# --- REST для сотрудников ---
@app.route('/api/employees', methods=['GET'])
def list_employees():
    return jsonify(list(employees.values()))

@app.route('/api/employees', methods=['POST'])
def add_employee():
    name = request.form['name']
    dept = request.form['dept']
    photo = request.files['photo']
    ext = os.path.splitext(photo.filename)[1]
    fn = f"{uuid.uuid4().hex}{ext}"
    photo.save(os.path.join(EMP_DIR, fn))
    entry = {'name': name, 'dept': dept, 'photo_url': f"/api/employees/photo/{fn}"}
    employees[name] = entry
    _save_employees()
    return jsonify(entry), 201

@app.route('/api/employees/<name>', methods=['DELETE'])
def del_employee(name):
    meta = employees.pop(name, None)
    if meta:
        try:
            os.remove(os.path.join(EMP_DIR, os.path.basename(meta['photo_url'])))
        except OSError:
            pass
        _save_employees()
    return jsonify({'status': 'ok'})

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
    entry = {'id': eid, 'name': nm, 'location': loc, 'image_url': f"/api/environments/image/{fn}"}
    environments[eid] = entry
    _save_environments()
    return jsonify(entry), 201

@app.route('/api/environments/<eid>', methods=['DELETE'])
def del_env(eid):
    env = environments.pop(eid, None)
    if env:
        try:
            os.remove(os.path.join(ENV_DIR, os.path.basename(env['image_url'])))
        except OSError:
            pass
        _save_environments()
    return jsonify({'status': 'ok'})

@app.route('/api/environments/image/<filename>')
def get_env_img(filename):
    return send_from_directory(ENV_DIR, filename)

# --- REST для логов ---
@app.route('/api/logs', methods=['POST'])
def post_log():
    entry = request.json
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(f"{entry['timestamp']} {entry['level']}: {entry['message']}\n")
    return jsonify({'status': 'ok'}), 201

@app.route('/api/logs', methods=['GET'])
def get_logs():
    order = request.args.get('order', 'desc')
    try:
        lines = open(LOG_FILE, 'r', encoding='utf-8').read().splitlines()
    except FileNotFoundError:
        lines = []
    lines.sort(reverse=(order == 'desc'))
    return jsonify(lines)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001)
