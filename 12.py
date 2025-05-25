import face_recognition
import cv2
import os
import numpy as np
import tkinter as tk
import tkinter.font as tkfont
import tkinter.ttk as ttk
from tkinter import filedialog, messagebox, scrolledtext
from PIL import Image, ImageTk
import shutil
import logging
import time
import requests, io, datetime
import json
import math

# Адрес API вашего сервера
API_HOST = 'http://192.168.0.111:5001'     # или 'http://<IP_СЕРВЕРА>:5001'
API_URL  = API_HOST + '/api'

# --- Настройка логирования ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)


class ServerLogHandler(logging.Handler):
    """Отправляет сообщения лога на сервер."""

    def emit(self, record):
        entry = {
            'timestamp': datetime.datetime.utcnow().isoformat(),
            'level': record.levelname,
            'message': self.format(record)
        }
        try:
            requests.post(f"{API_URL}/logs", json=entry, timeout=2)
        except Exception as e:
            # если сервер недоступен, просто выводим сообщение в консоль
            print("Не удалось отправить лог:", e)


logging.getLogger().addHandler(ServerLogHandler())

# Папка для хранения эталонных лиц
KNOWN_FACES_DIR = 'server/data/known_faces'
DEPARTMENTS_FILE = 'server/data/departments.txt'
ENVIRONMENT_FILE = 'environment.txt'
ASSIGNMENTS_FILE = 'assignments.json'
ZONES_DIR = 'zones'
os.makedirs(KNOWN_FACES_DIR, exist_ok=True)
os.makedirs(ZONES_DIR, exist_ok=True)
if not os.path.exists(ASSIGNMENTS_FILE):
    with open(ASSIGNMENTS_FILE, 'w', encoding='utf-8') as f:
        f.write('[]')

# Размер изображений помещений, используемый в интерфейсе руководителя
# Увеличен для более удобной работы с зонами
ENV_IMAGE_SIZE = (800, 600)

# Высоты окон в интерфейсе службы безопасности
SEC_PANE_MIN_HEIGHT = 300
SEC_PANE_MAX_HEIGHT = 600
SEC_LOGS_HEIGHT = 150

DEPARTMENT_OPTIONS = {
    'Блок по бизнес приложениям': [
        'Департамент систем поддержки эксплуатации АЭС',
        'Отдел внедрения НСИ'
    ],
    'Блок по информационной инфраструктуре и связи': [
        'Департамент обеспечения защиты ИТ инфраструктуры',
        'Департамент инфраструктуры систем',
        'Департамент научно-исследовательской работы и опытно-конструкторских работ и результатов интеллектуальной деятельности',
        'Департамент информационных систем'
    ],
    'Филиалы': [
        'Нововоронежская АЭС',
        'Балаковская АЭС',
        'Курская АЭС',
        'Курская АЭС-2'
    ]
}


# --- Функция загрузки эталонных лиц ---
def load_known_faces():
    known_encodings, known_names = [], []
    mapping = {}
    resp = requests.get(f"{API_URL}/employees")
    for emp in resp.json():
        # тянем фото по URL
        photo_url = API_HOST + emp['photo_url']
        r = requests.get(photo_url, timeout=5)
        r.raise_for_status()
        img_pil = Image.open(io.BytesIO(r.content)).convert('RGB')
        img = np.array(img_pil)
        encs = face_recognition.face_encodings(img)
        if encs:
            known_encodings.append(encs[0])
            known_names.append(emp['name'])
            mapping[emp['name']] = emp['dept']
    save_department_mapping(mapping)
    return known_encodings, known_names, mapping

def load_department_mapping():
    mapping = {}
    if os.path.exists(DEPARTMENTS_FILE):
        with open(DEPARTMENTS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                if ";" in line:
                    name, dept = line.strip().split(";", 1)
                    mapping[name] = dept
    return mapping


def save_department_mapping(mapping):
    with open(DEPARTMENTS_FILE, "w", encoding="utf-8") as f:
        for name, dept in mapping.items():
            f.write(f"{name};{dept}\n")


def load_environments():
    """Load environments from the API or local file."""
    envs = []
    try:
        resp = requests.get(f"{API_URL}/environments", timeout=5)
        resp.raise_for_status()
        envs = resp.json()
        # normalize and store absolute image paths
        for env in envs:
            img = env.get("image_url") or env.get("image", "")
            if img.startswith("/"):
                img = API_HOST + img
            env["image"] = img
        save_environments(envs)
        return envs
    except Exception:
        pass

    if os.path.exists(ENVIRONMENT_FILE):
        with open(ENVIRONMENT_FILE, "r", encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split(";")
                if len(parts) >= 3:
                    env = {"name": parts[0], "location": parts[1], "image": parts[2]}
                    if len(parts) >= 4:
                        env["id"] = parts[3]
                    envs.append(env)
    return envs


def save_environments(envs):
    with open(ENVIRONMENT_FILE, "w", encoding="utf-8") as f:
        for env in envs:
            img = env.get('image') or env.get('image_url', '')
            eid = env.get('id', '')
            f.write(f"{env['name']};{env['location']};{img};{eid}\n")


def load_assignments():
    """Load assignment records from server or local file."""
    try:
        resp = requests.get(f"{API_URL}/assignments", timeout=5)
        resp.raise_for_status()
        data = resp.json()
        save_assignments(data)
        return data
    except Exception:
        pass
    if not os.path.exists(ASSIGNMENTS_FILE):
        return []
    with open(ASSIGNMENTS_FILE, 'r', encoding='utf-8') as f:
        try:
            return json.load(f)
        except Exception:
            return []


def save_assignments(data):
    with open(ASSIGNMENTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_employees_version():
    """Return modification timestamp of employee metadata on the server."""
    try:
        resp = requests.get(f"{API_URL}/employees/version", timeout=5)
        resp.raise_for_status()
        return float(resp.json().get('version', 0))
    except Exception:
        return 0.0




class FaceRecognitionApp:
    def __init__(self):
        self.known_face_encodings, self.known_face_names, self.employee_depts = load_known_faces()
        self.emp_version = get_employees_version()
        self.last_emp_check = time.time()
        self.environments = load_environments()
        self.assignments = load_assignments()
        self.env_selected_image = ''
        self.process_frame = True
        self.cap = None
        self.start_time = None
        self.fail_count = 0
        self.total_failed_identifications = 0
        self.auth_timeout = 5

        self.root = tk.Tk()
        self.root.title("Система распознавания лиц")
        self.root.attributes('-fullscreen', True)
        self.style = ttk.Style(self.root)
        self._setup_style()
        self._create_icons()

        # Фреймы ролей
        self.frame_role = ttk.Frame(self.root)
        self.frame_employee = ttk.Frame(self.root)
        self.frame_admin_choice = ttk.Frame(self.root)
        self.frame_admin = ttk.Frame(self.root)
        self.frame_admin_env = ttk.Frame(self.root)
        self.frame_security = ttk.Frame(self.root)
        self.frame_manager = ttk.Frame(self.root)

        self.departments_map = DEPARTMENT_OPTIONS
        first_group = list(self.departments_map.keys())[0]
        self.group_var = tk.StringVar(value=first_group)
        self.dept_var = tk.StringVar(value=self.departments_map[first_group][0])

        # Построение интерфейсов
        self._build_role_frame()
        self._build_employee_frame()
        self._build_admin_choice_frame()
        self._build_admin_frame()
        self._build_admin_env_frame()
        self._build_security_frame()
        self._build_manager_frame()

        self._show_frame(self.frame_role)
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.root.mainloop()

    def _sync_employees(self):
        """Reload employee data if it changed on the server."""
        ver = get_employees_version()
        if ver and ver != self.emp_version:
            self.emp_version = ver
            self.known_face_encodings, self.known_face_names, self.employee_depts = load_known_faces()

    def _setup_style(self):
        s = self.style
        s.theme_use('clam')
        s.configure('TButton', font=('Arial', 18), padding=10)
        s.configure('Title.TLabel', font=('Arial', 24, 'bold'), foreground='white', background='#2c3e50')
        s.configure('Status.TLabel', font=('Arial', 18), foreground='white', background='#2c3e50')
        s.configure('Attempts.TLabel', font=('Arial', 30), foreground='#e74c3c', background='#34495e')
        s.configure('Success.TLabel', font=('Arial', 32, 'bold'), foreground='white', background='#27ae60')
        s.configure('Denied.TLabel', font=('Arial', 32, 'bold'), foreground='white', background='#c0392b')
        s.configure('Cam.TLabelframe', background='#2c3e50', foreground='white')
        s.configure('Cam.TLabelframe.Label', font=('Arial', 18, 'bold'), foreground='white', background='#2c3e50')
        self.root.configure(background='#2c3e50')

    def _apply_gradient_background(self, frame):
        """Draw the same blue gradient used on the role screen."""
        w, h = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        canvas = tk.Canvas(frame, width=w, height=h, highlightthickness=0)
        c1, c2 = (44, 62, 80), (52, 152, 219)
        for i in range(h):
            r = int(c1[0] + (c2[0] - c1[0]) * i / h)
            g = int(c1[1] + (c2[1] - c1[1]) * i / h)
            b = int(c1[2] + (c2[2] - c1[2]) * i / h)
            canvas.create_line(0, i, w, i, fill=f"#{r:02x}{g:02x}{b:02x}")
        canvas.place(relx=0, rely=0, relwidth=1, relheight=1)
        canvas.tk.call('lower', canvas._w)
        return canvas

    def _create_gradient_button(self, parent, text, command,
                                width=200, height=60,
                                c1=(46, 204, 113), c2=(39, 174, 96),
                                font=None):
        """Return a canvas widget drawn like a green gradient button."""
        if font is None:
            font = tkfont.Font(family='Helvetica', size=18)
        c = tk.Canvas(parent, width=width, height=height, highlightthickness=0)
        for x in range(width):
            cr = int(c1[0] + (c2[0] - c1[0]) * x / width)
            cg = int(c1[1] + (c2[1] - c1[1]) * x / width)
            cb = int(c1[2] + (c2[2] - c1[2]) * x / width)
            c.create_line(x, 0, x, height, fill=f"#{cr:02x}{cg:02x}{cb:02x}")
        c.create_text(width / 2, height / 2, text=text, font=font, fill='white')
        c.bind('<Button-1>', lambda e: command())
        return c

    def _create_icons(self):
        """Create small icons used on the zone toolbar."""
        ICON_SIZE = 32

        def rect_icon():
            img = tk.PhotoImage(width=ICON_SIZE, height=ICON_SIZE)
            for x in range(ICON_SIZE):
                for y in range(ICON_SIZE):
                    if 4 <= x <= ICON_SIZE - 5 and 4 <= y <= ICON_SIZE - 5:
                        img.put('#cccccc', (x, y))
                    if x in (4, ICON_SIZE - 5) or y in (4, ICON_SIZE - 5):
                        img.put('#000000', (x, y))
            return img

        def poly_icon():
            img = tk.PhotoImage(width=ICON_SIZE, height=ICON_SIZE)
            cx = cy = ICON_SIZE // 2
            for x in range(ICON_SIZE):
                for y in range(ICON_SIZE):
                    if abs(x - cx) + abs(y - cy) <= ICON_SIZE // 2 - 4:
                        color = '#cccccc' if abs(x - cx) + abs(y - cy) < ICON_SIZE // 2 - 4 else '#000000'
                        img.put(color, (x, y))
            return img

        def del_icon():
            img = tk.PhotoImage(width=ICON_SIZE, height=ICON_SIZE)
            for i in range(ICON_SIZE):
                img.put('#ff0000', (i, i))
                img.put('#ff0000', (ICON_SIZE - 1 - i, i))
            return img

        def clear_icon():
            img = tk.PhotoImage(width=ICON_SIZE, height=ICON_SIZE)
            # Корпус урны
            for x in range(10, ICON_SIZE - 10):
                img.put('#000000', (x, ICON_SIZE - 9))
                img.put('#000000', (x, ICON_SIZE - 3))
            for y in range(ICON_SIZE - 9, ICON_SIZE - 3):
                img.put('#000000', (10, y))
                img.put('#000000', (ICON_SIZE - 11, y))
            # Крышка и ручка
            for x in range(8, ICON_SIZE - 8):
                img.put('#000000', (x, ICON_SIZE - 10))
            for x in range(14, ICON_SIZE - 14):
                img.put('#000000', (x, ICON_SIZE - 12))
            return img

        def drag_icon():
            img = tk.PhotoImage(width=ICON_SIZE, height=ICON_SIZE)
            mid = ICON_SIZE // 2
            for i in range(ICON_SIZE):
                img.put('#000000', (mid, i))
                img.put('#000000', (i, mid))
            for d in range(6):
                img.put('#000000', (mid-d-2, d))
                img.put('#000000', (mid+d+2, d))
                img.put('#000000', (mid-d-2, ICON_SIZE-1-d))
                img.put('#000000', (mid+d+2, ICON_SIZE-1-d))
            return img

        def move_icon():
            img = tk.PhotoImage(width=ICON_SIZE, height=ICON_SIZE)
            # Простая иконка руки
            for x in range(12, ICON_SIZE - 12):
                for y in range(ICON_SIZE // 2, ICON_SIZE - 8):
                    img.put('#000000', (x, y))
            for i, x in enumerate(range(12, ICON_SIZE - 12, 4)):
                for y in range(ICON_SIZE // 2 - 6, ICON_SIZE // 2):
                    img.put('#000000', (x, y))
                    img.put('#000000', (x + 1, y))
            return img

        self.icon_rect = rect_icon()
        self.icon_poly = poly_icon()
        self.icon_delete = del_icon()
        self.icon_clear = clear_icon()
        self.icon_drag = drag_icon()
        self.icon_move = move_icon()

    def _build_role_frame(self):
        f = self.frame_role
        f.pack(expand=True, fill='both')
        w, h = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        canvas_bg = tk.Canvas(f, width=w, height=h, highlightthickness=0)
        for i in range(h):
            r = int(44 + (52 - 44) * i / h)
            g = int(62 + (152 - 62) * i / h)
            b = int(80 + (219 - 80) * i / h)
            canvas_bg.create_line(0, i, w, i, fill=f"#{r:02x}{g:02x}{b:02x}")
        canvas_bg.pack(expand=True, fill='both')

        tf = tkfont.Font(family='Helvetica', size=36, weight='bold')
        canvas_bg.create_text(w / 2, h * 0.2, text='Выберите роль', font=tf, fill='white')
        bf = tkfont.Font(family='Helvetica', size=24)

        def btn(text, cmd, y, c1, c2):
            c = tk.Canvas(f, width=300, height=60, highlightthickness=0)
            for x in range(300):
                cr = int(c1[0] + (c2[0] - c1[0]) * x / 300)
                cg = int(c1[1] + (c2[1] - c1[1]) * x / 300)
                cb = int(c1[2] + (c2[2] - c1[2]) * x / 300)
                c.create_line(x, 0, x, 60, fill=f"#{cr:02x}{cg:02x}{cb:02x}")
            c.create_text(150, 30, text=text, font=bf, fill='white')
            c.bind('<Button-1>', lambda e: cmd())
            c.place(relx=0.5, rely=y, anchor='center')

        green1, green2 = (46, 204, 113), (39, 174, 96)
        btn('Сотрудник', lambda: self._show_frame(self.frame_employee), 0.4, green1, green2)
        btn('Администратор', lambda: self._show_frame(self.frame_admin_choice), 0.55, green1,
            green2)
        btn('Руководитель', lambda: self._show_frame(self.frame_manager), 0.7, green1, green2)
        btn('Служба безопасности', lambda: self._show_frame(self.frame_security), 0.8, (52, 152, 219), (41, 128, 185))
        btn('Завершить', self.on_closing, 0.9, (231, 76, 60), (192, 57, 43))

    def _build_employee_frame(self):
        f = self.frame_employee
        self._apply_gradient_background(f)
        nav = ttk.Frame(f)
        nav.pack(fill='x')
        self.emp_back_btn = self._create_gradient_button(
            nav, "Назад", lambda: self._show_frame(self.frame_role), width=170, height=50)
        self.emp_back_btn.pack(side='left', padx=10, pady=10)

        self.attempts_label = ttk.Label(f, text="Неудачные попытки: 0", style='Attempts.TLabel')
        self.attempts_label.pack(pady=10)

        # выбор помещения для получения доступа
        env_select = ttk.Frame(f)
        env_select.pack(pady=5)
        ttk.Label(env_select, text="Помещение:").pack(side='left')
        self.employee_env = tk.StringVar()
        self.emp_env_menu = ttk.OptionMenu(env_select, self.employee_env, '')
        self.emp_env_menu.pack(side='left')


        self.emp_exit_btn = self._create_gradient_button(
            nav, "Завершить", self.on_closing, width=170, height=50)
        self.emp_exit_btn.pack(side='right', padx=10, pady=10)
        self.emp_back_pack = self.emp_back_btn.pack_info()
        self.emp_exit_pack = self.emp_exit_btn.pack_info()
        self.start_button = self._create_gradient_button(
            f, "Начать идентификацию", self._on_start_identification,
            width=300, height=80)
        self.start_button.pack(expand=True)

        self.cam_box = ttk.LabelFrame(f, text="Камера", style='Cam.TLabelframe')
        self.video_label = tk.Label(self.cam_box, bg='#34495e', bd=2, relief='sunken')
        self.video_label.pack(expand=True, fill='both')
        self.status_label = ttk.Label(f, text="Камера не запущена", style='Status.TLabel')

    def _build_admin_choice_frame(self):
        f = self.frame_admin_choice
        self._apply_gradient_background(f)
        nav = ttk.Frame(f)
        nav.pack(fill='x')
        ttk.Button(nav, text="Назад", command=lambda: self._show_frame(self.frame_role)).pack(side='left', padx=10, pady=10)
        ttk.Button(nav, text="Завершить", command=self.on_closing).pack(side='right', padx=10, pady=10)
        ttk.Label(f, text="Панель администратора", style='Title.TLabel').pack(pady=20)
        ttk.Button(f, text="Зарегистрировать сотрудника", command=lambda: self._show_frame(self.frame_admin)).pack(pady=10)
        ttk.Button(f, text="Настроить окружение", command=lambda: self._show_frame(self.frame_admin_env)).pack(pady=10)

    def _build_admin_frame(self):
        f = self.frame_admin
        self._apply_gradient_background(f)
        nav = ttk.Frame(f);
        nav.pack(fill='x')
        ttk.Button(nav, text="Назад", command=lambda: self._show_frame(self.frame_admin_choice)).pack(side='left', padx=10,
                      pady=10)
        ttk.Button(nav, text="Завершить", command=self.on_closing).pack(side='right', padx=10, pady=10)
        ttk.Label(f, text="Управление сотрудниками", style='Title.TLabel').pack(pady=10)
        frm = ttk.Frame(f);
        frm.pack(pady=10)
        ttk.Label(frm, text="ФИО:").grid(row=0, column=0, sticky='e')
        self.name_entry = ttk.Entry(frm, width=30)
        self.name_entry.grid(row=0, column=1, columnspan=2, sticky='w')
        ttk.Label(frm, text="Блок:").grid(row=1, column=0, sticky='e')
        self.group_menu = ttk.OptionMenu(frm, self.group_var, self.group_var.get(), *self.departments_map.keys(), command=self._update_dept_menu)
        self.group_menu.grid(row=1, column=1, sticky='w')
        ttk.Label(frm, text="Подразделение:").grid(row=1, column=2, sticky='e')
        self.dept_menu = ttk.OptionMenu(frm, self.dept_var, self.dept_var.get(), '')
        self.dept_menu.grid(row=1, column=3, sticky='w')
        self._update_dept_menu()
        ttk.Label(frm, text="Фото:").grid(row=2, column=0, sticky='e')
        ttk.Button(frm, text="Выбрать файл", command=self._choose_file).grid(row=2, column=1, sticky='w')
        self.selected_file = None
        ttk.Button(f, text="Загрузить", command=self._upload_employee).pack(pady=10)
        self.admin_status = ttk.Label(f, text="", style='Status.TLabel');
        self.admin_status.pack(pady=5)
        cat = tk.Frame(f, bg='#2c3e50');
        cat.pack(expand=True, fill='both', padx=10, pady=10)
        self.canvas = tk.Canvas(cat, bg='#2c3e50', highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(cat, orient='vertical', command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)
        self.inner.bind('<Configure>', lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.create_window((0, 0), window=self.inner, anchor='nw')
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side='left', fill='both', expand=True)
        self.scrollbar.pack(side='right', fill='y')

    def _build_admin_env_frame(self):
        f = self.frame_admin_env
        self._apply_gradient_background(f)
        nav = ttk.Frame(f)
        nav.pack(fill='x')
        ttk.Button(nav, text="Назад", command=lambda: self._show_frame(self.frame_admin_choice)).pack(side='left', padx=10, pady=10)
        ttk.Button(nav, text="Завершить", command=self.on_closing).pack(side='right', padx=10, pady=10)
        ttk.Label(f, text="Настройка окружения", style='Title.TLabel').pack(pady=10)
        frm = ttk.Frame(f)
        frm.pack(pady=10)
        ttk.Label(frm, text="Название помещения:").grid(row=0, column=0, sticky='e')
        self.env_name_entry = ttk.Entry(frm, width=30)
        self.env_name_entry.grid(row=0, column=1, sticky='w')
        ttk.Label(frm, text="Местоположение:").grid(row=1, column=0, sticky='e')
        self.env_loc_entry = ttk.Entry(frm, width=30)
        self.env_loc_entry.grid(row=1, column=1, sticky='w')
        ttk.Label(frm, text="Изображение:").grid(row=2, column=0, sticky='e')
        ttk.Button(frm, text="Выбрать файл", command=self._choose_env_image).grid(row=2, column=1, sticky='w')
        self.env_image_label = ttk.Label(frm, text="")
        self.env_image_label.grid(row=3, column=0, columnspan=2)
        ttk.Button(f, text="Добавить помещение", command=self._add_environment).pack(pady=10)
        self.env_status = ttk.Label(f, text="", style='Status.TLabel')
        self.env_status.pack()

        cat = tk.Frame(f, bg='#2c3e50')
        cat.pack(expand=True, fill='both', padx=10, pady=10)
        self.env_canvas = tk.Canvas(cat, bg='#2c3e50', highlightthickness=0)
        self.env_scrollbar = ttk.Scrollbar(cat, orient='vertical', command=self.env_canvas.yview)
        self.env_inner = ttk.Frame(self.env_canvas)
        self.env_inner.bind('<Configure>', lambda e: self.env_canvas.configure(scrollregion=self.env_canvas.bbox("all")))
        self.env_canvas.create_window((0, 0), window=self.env_inner, anchor='nw')
        self.env_canvas.configure(yscrollcommand=self.env_scrollbar.set)
        self.env_canvas.pack(side='left', fill='both', expand=True)
        self.env_scrollbar.pack(side='right', fill='y')

    def _update_dept_menu(self, *_):
        menu = self.dept_menu['menu']
        menu.delete(0, 'end')
        options = self.departments_map.get(self.group_var.get(), [])
        for opt in options:
            menu.add_command(label=opt, command=lambda v=opt: self.dept_var.set(v))
        if options:
            self.dept_var.set(options[0])

    def _reset_employee_screen(self):
        """Подготовить экран сотрудника для начала идентификации."""
        self._stop_camera()
        self.cam_box.pack_forget()
        self.status_label.pack_forget()
        if not self.start_button.winfo_ismapped():
            self.start_button.pack(expand=True)
        self.attempts_label.config(text="Неудачные попытки: 0")
        self.status_label.config(text="Камера не запущена")
        # обновляем список помещений
        self.environments = load_environments()
        env_menu = self.emp_env_menu['menu']
        env_menu.delete(0, 'end')
        names = [e['name'] for e in self.environments]
        for n in names:
            env_menu.add_command(label=n, command=lambda v=n: self.employee_env.set(v))
        if names:
            self.employee_env.set(names[0])
        else:
            self.employee_env.set('')
        # подгружаем назначения
        self.assignments = load_assignments()
        self.current_env = None

    def _on_start_identification(self):
        if not self.employee_env.get():
            messagebox.showwarning('Ошибка', 'Выберите помещение')
            return
        self.current_env = self.employee_env.get()
        self.start_button.pack_forget()
        self.cam_box.pack(expand=True, fill='both', padx=20, pady=10)
        self.status_label.pack(pady=5)
        self._start_employee_cam()

    def _build_security_frame(self):
        f = self.frame_security
        self._apply_gradient_background(f)
        nav = ttk.Frame(f)
        nav.pack(fill="x")
        ttk.Button(nav, text="Назад", command=lambda: self._show_frame(self.frame_role)).pack(side="left", padx=10, pady=10)
        ttk.Button(nav, text="Завершить", command=self.on_closing).pack(side="right", padx=10, pady=10)
        self.sec_nav = nav

        outer = tk.PanedWindow(f, orient='vertical', sashwidth=5, bg='#2c3e50')
        outer.pack(side='top', expand=True, fill='both')
        self.sec_outer = outer

        paned = tk.PanedWindow(outer, orient='horizontal', sashwidth=5, bg='#2c3e50')
        paned.pack(expand=True, fill='both')
        self.sec_paned = paned

        left = tk.Frame(paned, bg='#2c3e50', height=SEC_PANE_MAX_HEIGHT)
        left.pack_propagate(False)
        ttk.Label(left, text='Камера', style='Title.TLabel').pack(pady=5)
        self.security_video = tk.Label(left, bg='#34495e', bd=2, relief='sunken')
        self.security_video.pack(expand=True, fill='both', padx=10, pady=10)
        paned.add(left, minsize=200)
        self.sec_left = left

        right = tk.Frame(paned, bg='#2c3e50', height=SEC_PANE_MAX_HEIGHT)
        right.pack_propagate(False)
        ttk.Label(right, text='Нарушения', style='Title.TLabel').pack(pady=5)
        self.warning_text = scrolledtext.ScrolledText(right, width=50, font=("Courier", 12))
        self.warning_text.pack(expand=True, fill='both', padx=10, pady=10)
        paned.add(right, minsize=200)
        self.sec_right = right

        bottom = tk.Frame(outer, bg='#2c3e50', height=SEC_LOGS_HEIGHT)
        bottom.pack_propagate(False)
        ttk.Label(bottom, text='Общие логи', style='Title.TLabel').pack(pady=5)
        self.general_log_text = scrolledtext.ScrolledText(bottom, height=10, font=("Courier", 12))
        self.general_log_text.pack(expand=True, fill='both')
        self.sec_bottom = bottom

        outer.add(paned, minsize=SEC_PANE_MIN_HEIGHT)
        outer.add(bottom, minsize=SEC_LOGS_HEIGHT)

        f.bind('<Configure>', self._limit_security_heights)

        self.root.update_idletasks()
        nav_h = self.sec_nav.winfo_height()
        cur_w = max(800, self.root.winfo_width())
        min_h = nav_h + SEC_LOGS_HEIGHT + SEC_PANE_MIN_HEIGHT
        max_h = nav_h + SEC_LOGS_HEIGHT + SEC_PANE_MAX_HEIGHT
        self.root.minsize(cur_w, min_h)
        self.root.maxsize(cur_w, max_h)

    def _build_manager_frame(self):
        f = self.frame_manager
        self._apply_gradient_background(f)
        nav = ttk.Frame(f)
        nav.pack(fill='x')
        self.mgr_back_btn = self._create_gradient_button(
            nav, 'Назад', lambda: self._show_frame(self.frame_role),
            width=170, height=50)
        self.mgr_back_btn.pack(side='left', padx=10, pady=10)
        self.mgr_exit_btn = self._create_gradient_button(
            nav, 'Завершить', self.on_closing, width=170, height=50)
        self.mgr_exit_btn.pack(side='right', padx=10, pady=10)
        ttk.Label(f, text='Руководитель', style='Title.TLabel').pack(pady=10)
        frm = ttk.Frame(f)
        frm.pack(pady=10)
        emp_frame = ttk.Frame(frm)
        emp_frame.pack(side='left', padx=5)
        ttk.Label(emp_frame, text='Сотрудник:').pack(side='left')
        self.manager_emp = tk.StringVar()
        self.emp_menu = ttk.OptionMenu(emp_frame, self.manager_emp, '')
        self.emp_menu.pack(side='left')
        env_frame = ttk.Frame(frm)
        env_frame.pack(side='left', padx=15)
        ttk.Label(env_frame, text='Окружение:').pack(side='left')
        self.manager_env = tk.StringVar()
        self.env_menu = ttk.OptionMenu(env_frame, self.manager_env, '', command=self._load_manager_env)
        self.env_menu.pack(side='left')
        time_frame = ttk.Frame(frm)
        time_frame.pack(side='left', padx=5)
        ttk.Label(time_frame, text='Войти до:').grid(row=0, column=0, sticky='e')
        self.enter_entry = ttk.Entry(time_frame, width=20)
        self.enter_entry.grid(row=0, column=1, sticky='w')
        ttk.Label(time_frame, text='Выйти до:').grid(row=1, column=0, sticky='e')
        self.exit_entry = ttk.Entry(time_frame, width=20)
        self.exit_entry.grid(row=1, column=1, sticky='w')
        ttk.Button(time_frame, text='Сохранить допуск', command=self._assign_employee).grid(row=2, column=0, columnspan=2, pady=5)
        canvas_frame = tk.Frame(f, bg='#2c3e50')
        canvas_frame.pack(expand=True, fill='both')

        toolbar = tk.Frame(canvas_frame, bg='#2c3e50')
        toolbar.pack(side='top', pady=(5,0), anchor='n')

        content_frame = tk.Frame(canvas_frame, bg='#2c3e50')
        content_frame.pack(expand=True, fill='both')

        left_area = tk.Frame(content_frame, bg='#2c3e50')
        left_area.pack(side='left', expand=True, fill='both')
        self.zone_tool_buttons = {}
        btn_opts = {'width': 32, 'height': 32}
        self.zone_tool_buttons['rect'] = tk.Button(toolbar, image=self.icon_rect,
                                                  command=lambda: self._set_zone_tool('rect'),
                                                  **btn_opts)
        self.zone_tool_buttons['rect'].pack(side='left', padx=2)
        self.zone_tool_buttons['poly'] = tk.Button(toolbar, image=self.icon_poly,
                                                  command=lambda: self._set_zone_tool('poly'),
                                                  **btn_opts)
        self.zone_tool_buttons['poly'].pack(side='left', padx=2)
        self.zone_tool_buttons['move'] = tk.Button(toolbar, image=self.icon_move,
                                                  command=lambda: self._set_zone_tool('move'),
                                                  **btn_opts)
        self.zone_tool_buttons['move'].pack(side='left', padx=2)
        self.zone_tool_buttons['drag'] = tk.Button(toolbar, image=self.icon_drag,
                                                  command=lambda: self._set_zone_tool('drag'),
                                                  **btn_opts)
        self.zone_tool_buttons['drag'].pack(side='left', padx=2)
        self.zone_tool_buttons['delete'] = tk.Button(toolbar, image=self.icon_delete,
                                                    command=lambda: self._set_zone_tool('delete'),
                                                    **btn_opts)
        self.zone_tool_buttons['delete'].pack(side='left', padx=2)
        tk.Button(toolbar, image=self.icon_clear, command=self._clear_zones,
                 **btn_opts).pack(side='left', padx=2)

        self.default_tool_bg = self.zone_tool_buttons['rect'].cget('bg')

        canvas_holder = tk.Frame(left_area, bg='#2c3e50')
        canvas_holder.pack(side='top', expand=True, fill='both', pady=(0,5),padx=(275,0),  anchor='n')
        self.zone_canvas = tk.Canvas(canvas_holder, bg='#2c3e50',
                                     width=ENV_IMAGE_SIZE[0], height=ENV_IMAGE_SIZE[1],
                                     highlightthickness=1, highlightbackground='white')
        self.zone_canvas.place(relx=0.5, rely=0, anchor='n')
        self.zone_canvas.bind('<ButtonPress-1>', self._zone_press)
        self.zone_canvas.bind('<B1-Motion>', self._zone_drag)
        self.zone_canvas.bind('<ButtonRelease-1>', self._zone_release)
        self.current_rect = None
        self.creating_poly = None
        self.dragging_handle = None
        self.dragging_zone = None
        self.zone_tool = 'rect'
        self.zones = []
        self._set_zone_tool('rect')

        right_area = ttk.Frame(content_frame)
        right_area.pack(side='left', fill='y', pady=5,padx=(0,10))
        ttk.Label(right_area, text='Выданные допуски:').pack(anchor='n')
        self.assign_list = tk.Listbox(right_area, height=30, width=30)
        self.assign_scroll_x = ttk.Scrollbar(right_area, orient='horizontal',
                                             command=self.assign_list.xview)
        self.assign_list.configure(xscrollcommand=self.assign_scroll_x.set)
        self.assign_list.pack(fill='both', expand=True, padx=5)
        self.assign_scroll_x.pack(fill='x', padx=5)
        ttk.Button(right_area, text='Удалить', command=self._delete_assignment).pack(pady=5)

        btn_frame = ttk.Frame(f)
        btn_frame.pack(pady=5)
        tk.Button(btn_frame, text='Сохранить зоны', command=self._save_zones).pack(side='left', padx=5)

    def _load_all_logs(self):
        try:
            resp = requests.get(f"{API_URL}/logs", params={'order': 'desc'}, timeout=5)
            resp.raise_for_status()
            lines = resp.json()
            data = "\n".join(lines)
        except Exception as e:
            data = f"Не удалось получить логи: {e}"

        self.general_log_text.delete('1.0', tk.END)
        self.general_log_text.insert('1.0', data)

    def _load_warning_logs(self):
        try:
            resp = requests.get(f"{API_URL}/logs", params={'order': 'desc'}, timeout=5)
            resp.raise_for_status()
            lines = [l for l in resp.json() if 'WARNING' in l]
            data = "\n".join(lines)
        except Exception as e:
            data = f"Не удалось получить логи: {e}"

        self.warning_text.delete('1.0', tk.END)
        self.warning_text.insert('1.0', data)

    def _show_frame(self, target):
        for frm in (self.frame_role, self.frame_employee, self.frame_admin_choice, self.frame_admin,
                     self.frame_admin_env, self.frame_security, self.frame_manager):
            frm.pack_forget()
        target.pack(expand=True, fill='both')
        self.root.update_idletasks()
        if target == self.frame_employee:
            self.emp_back_btn.pack(**self.emp_back_pack)
            self.emp_exit_btn.pack(**self.emp_exit_pack)
            self._reset_employee_screen()
        else:
            self._stop_camera()
        if target == self.frame_security:
            self._start_security_cam()
            self._load_warning_logs()
            self._load_all_logs()
            return
        if target == self.frame_admin:
            self._refresh_catalog()
            return
        if target == self.frame_admin_env:
            self.env_name_entry.delete(0, 'end')
            self.env_loc_entry.delete(0, 'end')
            self.env_image_label.config(text="")
            self.env_selected_image = ''
            self._refresh_env_catalog()
            return
        if target == self.frame_manager:
            self._prepare_manager()
            return

    def _choose_file(self):
        path = filedialog.askopenfilename(filetypes=[('Image Files', ('*.jpg', '*.png'))])
        if path:
            self.selected_file = path
            self.admin_status.config(text=os.path.basename(path))

    def _choose_env_image(self):
        path = filedialog.askopenfilename(filetypes=[('Image Files', ('*.jpg', '*.png'))])
        if path:
            self.env_selected_image = path
            self.env_image_label.config(text=os.path.basename(path))

    def _add_environment(self):
        name = self.env_name_entry.get().strip()
        loc = self.env_loc_entry.get().strip()
        img_path = self.env_selected_image
        if not name or not loc or not img_path:
            logging.warning("Попытка добавить помещение без всех обязательных полей")
            messagebox.showwarning("Ошибка", "Заполните все поля и выберите изображение")
            return

        # 1) Подготовка изображения к единому размеру
        try:
            img = Image.open(img_path)
            img = img.convert('RGB')
            img = img.resize(ENV_IMAGE_SIZE, Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format='JPEG')
            buf.seek(0)
            files = {'image': ('image.jpg', buf, 'image/jpeg')}
        except Exception as e:
            logging.error("Не удалось обработать изображение: %s", e)
            messagebox.showerror("Ошибка", "Не удалось загрузить изображение")
            return
        data = {'name': name, 'location': loc}

        # 2) POST на /api/environments
        resp = requests.post(f"{API_URL}/environments", data=data, files=files)
        if resp.status_code == 201:
            # 3) Сервер вернул JSON с данными нового помещения
            self.env_status.config(text="Помещение добавлено на сервер")
            # Обновляем локальный список из сервера
            self.environments = load_environments()
            # Сброс полей формы
            self.env_name_entry.delete(0, 'end')
            self.env_loc_entry.delete(0, 'end')
            self.env_image_label.config(text="")
            self.env_selected_image = ''
            # Перерисовать каталог
            self._refresh_env_catalog()

        else:
            # Если сервер вернул ошибку
            logging.error("Сервер ответил ошибкой при добавлении помещения: %s %s", resp.status_code, resp.text)
            messagebox.showerror("Ошибка сервера", f"{resp.status_code}: {resp.text}")

    def _upload_employee(self):
        name = self.name_entry.get().strip()
        dept = self.dept_var.get()
        if not name or not self.selected_file or not dept:
            logging.warning("Попытка добавить сотрудника без всех обязательных данных")
            messagebox.showwarning("Ошибка", "Введите ФИО, подразделение и файл")
            return

        # Готовим multipart/form-data запрос
        files = {'photo': open(self.selected_file, 'rb')}
        data = {'name': name, 'dept': dept}

        # POST /api/employees
        resp = requests.post(f"{API_URL}/employees", data=data, files=files)
        if resp.status_code == 201:
            # Успешно добавили на сервер
            self.admin_status.config(text=f"Сотрудник {name} добавлен на сервер")
            # Обновляем локальные списки лиц и отображение
            self.known_face_encodings, self.known_face_names, self.employee_depts = load_known_faces()
            self.emp_version = get_employees_version()
            self._refresh_catalog()
            # Сбрасываем поля формы
            self.name_entry.delete(0, 'end')
            self.selected_file = None
        else:
            logging.error("Сервер ответил ошибкой при добавлении сотрудника: %s %s", resp.status_code, resp.text)
            messagebox.showerror("Ошибка сервера", f"Код {resp.status_code}: {resp.text}")

    def _refresh_env_catalog(self):
        for w in self.env_inner.winfo_children():
            w.destroy()
        # always try to get fresh data from the server
        self.environments = load_environments()
        for env in self.environments:
            rec = ttk.Frame(self.env_inner, padding=5)
            rec.pack(fill='x', pady=5)
            try:
                img_path = env.get('image', '')
                if img_path.startswith('http'):
                    r = requests.get(img_path, timeout=5)
                    r.raise_for_status()
                    img = Image.open(io.BytesIO(r.content))
                else:
                    img = Image.open(img_path)
                img.thumbnail((64, 64))
                ph = ImageTk.PhotoImage(img)
                lbl = tk.Label(rec, image=ph)
                lbl.image = ph
                lbl.pack(side='left', padx=5)
            except Exception:
                ttk.Label(rec, text="[Нет изображения]").pack(side='left', padx=5)
            ttk.Label(rec, text=f"{env['name']} ({env['location']})", style='Status.TLabel').pack(side='left', padx=10)
            ttk.Button(rec, text="Удалить", command=lambda e=env: self._delete_environment(e)).pack(side='right', padx=5)

    def _delete_environment(self, env):
        if env in self.environments:
            if env.get('id'):
                try:
                    requests.delete(f"{API_URL}/environments/{env['id']}")
                except Exception as e:
                    logging.error("Не удалось удалить помещение на сервере: %s", e)
            self.environments.remove(env)
            save_environments(self.environments)
            # получить актуальный список
            self.environments = load_environments()
            self._refresh_env_catalog()

    def _refresh_catalog(self):
        for w in self.inner.winfo_children():
            w.destroy()
        try:
            resp = requests.get(f"{API_URL}/employees", timeout=5)
            resp.raise_for_status()
            employees = resp.json()
        except Exception as e:
            ttk.Label(self.inner, text=f"Ошибка загрузки данных: {e}").pack()
            return
        for emp in employees:
            rec = ttk.Frame(self.inner, padding=5)
            rec.pack(fill='x', pady=5)
            try:
                img_resp = requests.get(API_HOST + emp['photo_url'], timeout=5)
                img_resp.raise_for_status()
                img = Image.open(io.BytesIO(img_resp.content))
                img.thumbnail((64, 64))
                ph = ImageTk.PhotoImage(img)
                lbl = tk.Label(rec, image=ph)
                lbl.image = ph
                lbl.pack(side='left', padx=5)
            except Exception:
                ttk.Label(rec, text='[Нет изображения]').pack(side='left', padx=5)
            ttk.Label(rec, text=f"{emp['name']} ({emp['dept']})", style='Status.TLabel').pack(side='left', padx=10)
            ttk.Button(rec, text='Удалить', command=lambda n=emp['name']: self._delete_employee(n)).pack(side='right', padx=5)

    def _delete_employee(self, name):
        try:
            requests.delete(f"{API_URL}/employees/{name}", timeout=5)
        except Exception as e:
            logging.error("Не удалось удалить сотрудника: %s", e)
            messagebox.showerror("Ошибка", f"Не удалось удалить: {e}")
            return
        if name in self.employee_depts:
            del self.employee_depts[name]
            save_department_mapping(self.employee_depts)
        self.known_face_encodings, self.known_face_names, self.employee_depts = load_known_faces()
        self.emp_version = get_employees_version()
        self._refresh_catalog()

    # --- Руководитель ---
    def _prepare_manager(self):
        # обновляем меню сотрудников
        menu = self.emp_menu['menu']
        menu.delete(0, 'end')
        for name in self.known_face_names:
            menu.add_command(label=name, command=lambda v=name: self.manager_emp.set(v))
        if self.known_face_names:
            self.manager_emp.set(self.known_face_names[0])

        env_menu = self.env_menu['menu']
        env_menu.delete(0, 'end')
        names = [e['name'] for e in self.environments]
        for n in names:
            env_menu.add_command(label=n, command=lambda v=n: (self.manager_env.set(v), self._load_manager_env()))
        if names:
            self.manager_env.set(names[0])
            self._load_manager_env()
        self.enter_entry.delete(0, 'end')
        self.exit_entry.delete(0, 'end')
        self.zones = []
        self.zone_tool = 'rect'
        self.creating_poly = None
        self.current_rect = None
        self.dragging_handle = None
        self._refresh_assignments()

    def _load_manager_env(self, *_):
        env = next((e for e in self.environments if e['name'] == self.manager_env.get()), None)
        if not env:
            return
        img_path = env.get('image', '')
        try:
            if img_path.startswith('http'):
                r = requests.get(img_path, timeout=5)
                r.raise_for_status()
                img = Image.open(io.BytesIO(r.content))
            else:
                img = Image.open(img_path)
            img = img.convert('RGB')
            img = img.resize(ENV_IMAGE_SIZE, Image.LANCZOS)
            self.zone_image = ImageTk.PhotoImage(img)
            self.zone_canvas.config(width=ENV_IMAGE_SIZE[0], height=ENV_IMAGE_SIZE[1])
            self.zone_canvas.delete('all')
            self.zone_canvas.create_image(ENV_IMAGE_SIZE[0]//2, 0, anchor='n', image=self.zone_image)
            self.zone_canvas.create_rectangle(0, 0, ENV_IMAGE_SIZE[0], ENV_IMAGE_SIZE[1], outline='white', tags='image_border')
            # загрузить зоны
            self.zones = []
            if env.get('id'):
                try:
                    resp = requests.get(f"{API_URL}/environments/{env['id']}/zones", timeout=5)
                    if resp.status_code == 200:
                        self.zones = resp.json()
                except Exception:
                    pass
            processed = []
            for z in self.zones:
                if isinstance(z, dict):
                    pts = [tuple(p) for p in z.get('points', [])]
                    typ = z.get('type', 'rect')
                else:
                    pts = [(z[0], z[1]), (z[2], z[1]), (z[2], z[3]), (z[0], z[3])]
                    typ = 'rect'
                shape = self.zone_canvas.create_polygon(
                    *self._flatten(pts), outline='red', fill=''
                )
                handles = [self._create_handle(px, py) for px, py in pts]
                processed.append({'type': typ, 'points': pts, 'shape': shape, 'handles': handles})
            self.zones = processed
        except Exception:
            pass

    def _set_zone_tool(self, tool):
        """Switch active tool for zone editing."""
        self.zone_tool = tool
        if hasattr(self, 'zone_tool_buttons'):
            for name, btn in self.zone_tool_buttons.items():
                relief = 'sunken' if name == tool else 'raised'
                bg = '#d0d0ff' if name == tool else self.default_tool_bg
                btn.config(relief=relief, bg=bg)

    def _create_handle(self, x, y):
        return self.zone_canvas.create_oval(x-4, y-4, x+4, y+4, fill='yellow', outline='black', tags='handle')

    def _point_in_poly(self, x, y, pts):
        inside = False
        n = len(pts)
        px, py = pts[0]
        for i in range(1, n+1):
            nx, ny = pts[i % n]
            if ((py > y) != (ny > y)) and (x < (nx-px)*(y-py)/(ny-py+1e-9)+px):
                inside = not inside
            px, py = nx, ny
        return inside

    def _find_near_handle(self, x, y, radius=15):
        """Return (zone, index) of handle close to (x,y) or None."""
        if self.creating_poly:
            for idx, h in enumerate(self.creating_poly['handles']):
                coords = self.zone_canvas.coords(h)
                if not coords:
                    continue
                hx = (coords[0] + coords[2]) / 2
                hy = (coords[1] + coords[3]) / 2
                if (hx - x) ** 2 + (hy - y) ** 2 <= radius ** 2:
                    return ('creating', idx)
        for z in self.zones:
            for idx, h in enumerate(z.get('handles', [])):
                coords = self.zone_canvas.coords(h)
                if not coords:
                    continue
                hx = (coords[0] + coords[2]) / 2
                hy = (coords[1] + coords[3]) / 2
                if (hx - x) ** 2 + (hy - y) ** 2 <= radius ** 2:
                    return (z, idx)
        return None

    def _zone_press(self, event):
        if self.zone_tool == 'move':
            res = self._find_near_handle(event.x, event.y)
            if res:
                self.dragging_handle = res
                return
            return
        if self.zone_tool == 'drag':
            for z in reversed(self.zones):
                if self._point_in_poly(event.x, event.y, z['points']):
                    self.dragging_zone = (z, event.x, event.y)
                    return
            return
        res = self._find_near_handle(event.x, event.y)
        if res:
            self.dragging_handle = res
            return
        if self.zone_tool == 'delete':
            self._delete_zone_at(event.x, event.y)
            return
        if self.zone_tool == 'rect':
            self.zone_start = (event.x, event.y)
            self.current_rect = self.zone_canvas.create_polygon(
                event.x, event.y, event.x, event.y, event.x, event.y, event.x, event.y,
                outline='red', fill=''
            )
        elif self.zone_tool == 'poly':
            if not self.creating_poly:
                self.creating_poly = {'points': [(event.x, event.y)], 'handles': [self._create_handle(event.x, event.y)], 'temp': []}
            else:
                self.creating_poly['points'].append((event.x, event.y))
                self.creating_poly['handles'].append(self._create_handle(event.x, event.y))
                if len(self.creating_poly['points']) == 4:
                    pts = self.creating_poly['points']
                    cx = sum(p[0] for p in pts) / 4
                    cy = sum(p[1] for p in pts) / 4
                    pts = sorted(pts, key=lambda p: math.atan2(p[1]-cy, p[0]-cx))
                    poly = self.zone_canvas.create_polygon(
                        *self._flatten(pts), outline='red', fill=''
                    )
                    zone = {'type': 'poly', 'points': pts, 'shape': poly, 'handles': self.creating_poly['handles']}
                    self.zones.append(zone)
                    self.creating_poly = None

    def _zone_drag(self, event):
        if self.dragging_handle:
            z, idx = self.dragging_handle
            if z == 'creating':
                self.creating_poly['points'][idx] = (event.x, event.y)
                self.zone_canvas.coords(self.creating_poly['handles'][idx], event.x-4, event.y-4, event.x+4, event.y+4)
            else:
                z['points'][idx] = (event.x, event.y)
                self.zone_canvas.coords(z['handles'][idx], event.x-4, event.y-4, event.x+4, event.y+4)
                self.zone_canvas.coords(z['shape'], *self._flatten(z['points']))
        elif self.dragging_zone:
            z, lx, ly = self.dragging_zone
            dx = event.x - lx
            dy = event.y - ly
            z['points'] = [(px + dx, py + dy) for px, py in z['points']]
            for h in z['handles']:
                self.zone_canvas.move(h, dx, dy)
            self.zone_canvas.move(z['shape'], dx, dy)
            self.dragging_zone = (z, event.x, event.y)
        elif self.current_rect:
            x0, y0 = self.zone_start
            pts = [(x0, y0), (event.x, y0), (event.x, event.y), (x0, event.y)]
            self.zone_canvas.coords(self.current_rect, *self._flatten(pts))

    def _zone_release(self, event):
        if self.dragging_handle:
            self.dragging_handle = None
            return
        if self.dragging_zone:
            self.dragging_zone = None
            return
        if self.current_rect:
            x0, y0 = self.zone_start
            pts = [(x0, y0), (event.x, y0), (event.x, event.y), (x0, event.y)]
            handles = [self._create_handle(px, py) for px, py in pts]
            self.zone_canvas.delete(self.current_rect)
            poly = self.zone_canvas.create_polygon(
                *self._flatten(pts), outline='red', fill=''
            )
            self.zones.append({'type': 'rect', 'points': pts, 'shape': poly, 'handles': handles})
            self.current_rect = None

    def _delete_zone_at(self, x, y):
        if self.creating_poly:
            for i, h in enumerate(list(self.creating_poly['handles'])):
                coords = self.zone_canvas.coords(h)
                if coords and coords[0] <= x <= coords[2] and coords[1] <= y <= coords[3]:
                    self.zone_canvas.delete(h)
                    del self.creating_poly['handles'][i]
                    del self.creating_poly['points'][i]
                    if not self.creating_poly['points']:
                        self.creating_poly = None
                    return
        for z in list(self.zones):
            if self._point_in_poly(x, y, z['points']):
                for h in z['handles']:
                    self.zone_canvas.delete(h)
                self.zone_canvas.delete(z['shape'])
                self.zones.remove(z)
                return
            xs = [p[0] for p in z['points']]
            ys = [p[1] for p in z['points']]
            if (max(xs)-min(xs))*(max(ys)-min(ys)) < 400:
                if (min(xs)-5 <= x <= max(xs)+5 and min(ys)-5 <= y <= max(ys)+5):
                    for h in z['handles']:
                        self.zone_canvas.delete(h)
                    self.zone_canvas.delete(z['shape'])
                    self.zones.remove(z)
                    return

    def _clear_zones(self):
        for z in list(self.zones):
            for h in z['handles']:
                self.zone_canvas.delete(h)
            self.zone_canvas.delete(z['shape'])
        self.zones.clear()
        if self.creating_poly:
            for h in self.creating_poly['handles']:
                self.zone_canvas.delete(h)
            self.creating_poly = None

    @staticmethod
    def _flatten(pts):
        return [coord for pt in pts for coord in pt]

    def _save_zones(self):
        env = next((e for e in self.environments if e['name'] == self.manager_env.get()), None)
        if not env or not env.get('id'):
            messagebox.showwarning('Ошибка', 'Выберите помещение')
            return
        try:
            data = [{'type': z['type'], 'points': z['points']} for z in self.zones]
            requests.post(f"{API_URL}/environments/{env['id']}/zones", json={'zones': data}, timeout=5)
            messagebox.showinfo('Сохранено', 'Зоны сохранены')
        except Exception as e:
            messagebox.showerror('Ошибка', str(e))

    def _assign_employee(self):
        emp = self.manager_emp.get()
        env = next((e for e in self.environments if e['name'] == self.manager_env.get()), None)
        if not emp or not env:
            messagebox.showwarning('Ошибка', 'Выберите сотрудника и помещение')
            return
        rec = {
            'employee': emp,
            'environment_id': env.get('id'),
            'enter_until': self.enter_entry.get(),
            'exit_until': self.exit_entry.get()
        }
        try:
            requests.post(f"{API_URL}/assignments", json=rec, timeout=5)
        except Exception:
            pass
        self.assignments.append(rec)
        save_assignments(self.assignments)
        messagebox.showinfo('Сохранено', 'Назначение сохранено')
        self._refresh_assignments()

    def _refresh_assignments(self):
        """Reload assignments and populate the listbox."""
        self.assignments = load_assignments()
        if not hasattr(self, 'assign_list'):
            return
        self.assign_list.delete(0, 'end')
        self.assign_map = []
        for idx, rec in enumerate(self.assignments):
            env = next((e for e in self.environments if e.get('id') == rec.get('environment_id')), None)
            env_name = env['name'] if env else '?'
            start = rec.get('enter_until') or '-'
            end = rec.get('exit_until') or '-'
            text = f"{rec.get('employee')} -> {env_name} ({start} - {end})"
            self.assign_list.insert('end', text)
            self.assign_map.append(idx)

    def _delete_assignment(self):
        sel = self.assign_list.curselection()
        if not sel:
            return
        real_idx = self.assign_map[sel[0]]
        try:
            requests.delete(f"{API_URL}/assignments/{real_idx}", timeout=5)
        except Exception:
            pass
        if 0 <= real_idx < len(self.assignments):
            self.assignments.pop(real_idx)
            save_assignments(self.assignments)
        self._refresh_assignments()

    def _has_permission(self, name, env_name):
        """Check if employee has valid permission for selected environment."""
        env = next((e for e in self.environments if e['name'] == env_name), None)
        if not env:
            return False
        now = datetime.datetime.now()
        for rec in self.assignments:
            if rec.get('employee') != name:
                continue
            if rec.get('environment_id') != env.get('id'):
                continue
            try:
                start = datetime.datetime.fromisoformat(rec.get('enter_until')) if rec.get('enter_until') else None
                end = datetime.datetime.fromisoformat(rec.get('exit_until')) if rec.get('exit_until') else None
            except Exception:
                start = end = None
            if start and now < start:
                continue
            if end and now > end:
                continue
            return True
        return False

    def _start_employee_cam(self):
        if self.cap is None:
            self.cap = cv2.VideoCapture(1)
            self.start_time = time.time()
            self.fail_count = 0
            self.attempts_label.config(text="Неудачные попытки: 0")
            self.status_label.config(text="Камера запущена. Ожидание распознавания...")
            self._update_frame()

    def _stop_camera(self):
        if self.cap: self.cap.release(); self.cap = None

    def _show_access_granted(self):
        self._stop_camera();
        self.emp_back_btn.pack_forget();
        self.emp_exit_btn.pack_forget()
        overlay = ttk.Label(self.frame_employee, text="Вход разрешен", style='Success.TLabel');
        overlay.place(relx=0.5, rely=0.5, anchor='center')

        def reset(): overlay.destroy(); self._show_frame(self.frame_role)

        self.root.after(5000, reset)

    def _show_access_denied(self):
        self._stop_camera();
        self.emp_back_btn.pack_forget();
        self.emp_exit_btn.pack_forget();
        overlay = ttk.Label(self.frame_employee, text="Доступ запрещен", style='Denied.TLabel')
        overlay.place(relx=0.5, rely=0.5, anchor='center')

        def reset():
            overlay.destroy();
            self._show_frame(self.frame_role)

        self.root.after(5000, reset)

    def _update_frame(self):
        if self.cap is None: return
        if time.time() - self.last_emp_check > 10:
            self.last_emp_check = time.time()
            self._sync_employees()
        ret, frame = self.cap.read();
        if not ret: self.root.after(30, self._update_frame); return
        img = ImageTk.PhotoImage(image=Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)))
        self.video_label.imgtk = img;
        self.video_label.config(image=img)
        if time.time() - self.start_time < 1: self.root.after(30, self._update_frame); return
        if self.process_frame:
            small = cv2.resize(frame, (0, 0), fx=0.25, fy=0.25);
            rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
            locs = face_recognition.face_locations(rgb);
            encs = face_recognition.face_encodings(rgb, locs)
            recognized = False
            for enc in encs:
                matches = face_recognition.compare_faces(self.known_face_encodings, enc)
                dists = face_recognition.face_distance(self.known_face_encodings, enc)
                if len(dists) > 0 and matches[np.argmin(dists)]: recognized = True; name = self.known_face_names[
                    np.argmin(dists)]; break
            if recognized:
                dept = self.employee_depts.get(name, 'Unknown')
                if self._has_permission(name, self.current_env):
                    self._send_log('INFO', f"Access granted for {name} ({dept}) in {self.current_env}")
                    self._show_access_granted()
                else:
                    self._send_log('WARNING', f"Access denied for {name} ({dept}) in {self.current_env}")
                    self._show_access_denied()
                return
            if time.time() - self.start_time >= self.auth_timeout:
                self._send_log('WARNING', f"Failed authentication attempt {self.fail_count + 1}")
                self.fail_count += 1
                self.total_failed_identifications += 1
                self.attempts_label.config(text=f"Неудачные попытки: {self.fail_count}")
                self.start_time = time.time()
                if self.fail_count > 3:
                    self._show_access_denied()
                    return
                else:
                    self.status_label.config(text="Лицо не опознано. Попробуйте снова.")
        self.process_frame = not self.process_frame;
        self.root.after(30, self._update_frame)

    def _start_security_cam(self):
        if self.cap is None:
            self.cap = cv2.VideoCapture(1)
            self._update_security_frame()

    def _limit_security_heights(self, event=None):
        if not hasattr(self, 'sec_outer'):
            return
        nav_h = self.sec_nav.winfo_height()
        total = self.frame_security.winfo_height() - nav_h
        bottom_h = self.sec_bottom.winfo_height()
        top_h = total - bottom_h
        target = max(SEC_PANE_MIN_HEIGHT, min(SEC_PANE_MAX_HEIGHT, top_h))
        if target != top_h:
            self.sec_outer.sash_place(0, 0, target)
        for pane in (self.sec_left, self.sec_right, self.sec_paned):
            pane.config(height=target)
        cur_w = max(800, self.root.winfo_width())
        min_h = nav_h + bottom_h + SEC_PANE_MIN_HEIGHT
        max_h = nav_h + bottom_h + SEC_PANE_MAX_HEIGHT
        self.root.minsize(cur_w, min_h)
        self.root.maxsize(cur_w, max_h)

    def _update_security_frame(self):
        if self.cap is None:
            return
        ret, frame = self.cap.read()
        if not ret:
            self.root.after(30, self._update_security_frame)
            return
        w = self.security_video.winfo_width()
        h = self.security_video.winfo_height()
        if w < 10 or h < 10:
            w, h = 600, 500
        frame = cv2.resize(frame, (w, h))
        img = ImageTk.PhotoImage(image=Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)))
        self.security_video.imgtk = img
        self.security_video.config(image=img)
        self.root.after(30, self._update_security_frame)
    def _send_log(self, level: str, msg: str):
        """Логирует событие и отправляет его на сервер."""
        lvl = logging.INFO if level.upper() == 'INFO' else logging.WARNING
        logging.log(lvl, msg)

    def on_closing(self):
        self._stop_camera();
        self.root.destroy()



if __name__ == '__main__':
    app = FaceRecognitionApp()
