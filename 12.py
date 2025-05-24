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
from typing import Tuple

# Адрес API вашего сервера
API_HOST = 'http://127.0.0.1:5001'     # или 'http://<IP_СЕРВЕРА>:5001'
API_URL  = API_HOST + '/api'
# Настройка логирования в файл
logging.basicConfig(
    filename='server/data/access.log',
    level=logging.INFO,
    format='%(asctime)s %(levelname)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Папка для хранения эталонных лиц
KNOWN_FACES_DIR = 'server/data/known_faces'
DEPARTMENTS_FILE = 'server/data/departments.txt'
ENVIRONMENT_FILE = 'environment.txt'
os.makedirs(KNOWN_FACES_DIR, exist_ok=True)

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
    resp = requests.get(f"{API_URL}/employees")
    for emp in resp.json():
        # тянем фото по URL
        # emp['photo_url'] == "/api/employees/photo/<filename>"
        photo_url = API_HOST + emp['photo_url']
        r = requests.get(photo_url, timeout=5)
        r.raise_for_status()
        img_pil = Image.open(io.BytesIO(r.content)).convert('RGB')
        img = np.array(img_pil)
        encs = face_recognition.face_encodings(img)
        if encs:
            known_encodings.append(encs[0])
            known_names.append(emp['name'])
    return known_encodings, known_names

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
    envs = []
    if os.path.exists(ENVIRONMENT_FILE):
        with open(ENVIRONMENT_FILE, "r", encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split(";")
                if len(parts) >= 3:
                    envs.append({"name": parts[0], "location": parts[1], "image": parts[2]})
    return envs


def save_environments(envs):
    with open(ENVIRONMENT_FILE, "w", encoding="utf-8") as f:
        for env in envs:
            f.write(f"{env['name']};{env['location']};{env['image']}\n")




class FaceRecognitionApp:
    def __init__(self):
        self.known_face_encodings, self.known_face_names = load_known_faces()
        self.employee_depts = load_department_mapping()
        self.environments = load_environments()
        self.env_selected_image = ''
        self.process_frame = True
        self.cap = None
        self.start_time = None
        self.fail_count = 0
        self.auth_timeout = 5

        self.root = tk.Tk()
        self.root.title("Система распознавания лиц")
        self.root.attributes('-fullscreen', True)
        self.style = ttk.Style(self.root)
        self._setup_style()

        # Фреймы ролей
        self.frame_role = ttk.Frame(self.root)
        self.frame_employee = ttk.Frame(self.root)
        self.frame_admin_choice = ttk.Frame(self.root)
        self.frame_admin = ttk.Frame(self.root)
        self.frame_admin_env = ttk.Frame(self.root)
        self.frame_security = ttk.Frame(self.root)

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

        self._show_frame(self.frame_role)
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.root.mainloop()

    def _setup_style(self):
        s = self.style
        s.theme_use('clam')
        s.configure('TButton', font=('Arial', 18), padding=10)
        s.configure('Title.TLabel', font=('Arial', 24, 'bold'), foreground='white', background='#2c3e50')
        s.configure('Status.TLabel', font=('Arial', 18), foreground='white', background='#2c3e50')
        s.configure('Attempts.TLabel', font=('Arial', 16), foreground='#e74c3c', background='#34495e')
        self.root.configure(background='#2c3e50')

    def _gradient_button(self, parent: tk.Widget, text: str, command, c1: Tuple[int, int, int], c2: Tuple[int, int, int]):
        width, height = 180, 50
        cv = tk.Canvas(parent, width=width, height=height, highlightthickness=0)
        for x in range(width):
            r = int(c1[0] + (c2[0] - c1[0]) * x / width)
            g = int(c1[1] + (c2[1] - c1[1]) * x / width)
            b = int(c1[2] + (c2[2] - c1[2]) * x / width)
            cv.create_line(x, 0, x, height, fill=f"#{r:02x}{g:02x}{b:02x}")
        cv.create_text(width/2, height/2, text=text, fill='white', font=('Arial', 16, 'bold'))
        cv.bind('<Button-1>', lambda e: command())
        return cv

    def _add_gradient_bg(self, frame: tk.Frame):
        w = self.root.winfo_screenwidth()
        h = self.root.winfo_screenheight()
        cv = tk.Canvas(frame, width=w, height=h, highlightthickness=0)
        for i in range(h):
            r = int(44 + (52 - 44) * i / h)
            g = int(62 + (152 - 62) * i / h)
            b = int(80 + (219 - 80) * i / h)
            cv.create_line(0, i, w, i, fill=f"#{r:02x}{g:02x}{b:02x}")
        cv.place(x=0, y=0, relwidth=1, relheight=1)
        frame.tk.call('lower', cv._w)
        return cv

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
        btn('Служба безопасности', lambda: self._show_frame(self.frame_security), 0.7, (52, 152, 219), (41, 128, 185))
        btn('Завершить', self.on_closing, 0.85, (231, 76, 60), (192, 57, 43))

    def _build_employee_frame(self):
        f = self.frame_employee
        self._add_gradient_bg(f)
        self.emp_back_btn = self._gradient_button(f, "Назад", lambda: self._show_frame(self.frame_role), (46,204,113), (39,174,96))
        self.emp_back_btn.place(x=10, y=10)
        self.emp_exit_btn = self._gradient_button(f, "Завершить", self.on_closing, (231,76,60), (192,57,43))
        self.emp_exit_btn.place(relx=1.0, x=-190, y=10)
        self.attempts_label = ttk.Label(f, text="Неудачные попытки: 0", style='Attempts.TLabel')
        self.attempts_label.pack(side='left', padx=20, pady=20)
        self.video_label = tk.Label(f, bg='#34495e')
        self.video_label.pack(side='left', expand=True, fill='both')
        self.status_label = ttk.Label(f, text="Камера не запущена", style='Status.TLabel')
        self.status_label.pack(pady=10)

    def _build_admin_choice_frame(self):
        f = self.frame_admin_choice
        nav = ttk.Frame(f)
        nav.pack(fill='x')
        ttk.Button(nav, text="Назад", command=lambda: self._show_frame(self.frame_role)).pack(side='left', padx=10, pady=10)
        ttk.Button(nav, text="Завершить", command=self.on_closing).pack(side='right', padx=10, pady=10)
        ttk.Label(f, text="Панель администратора", style='Title.TLabel').pack(pady=20)
        ttk.Button(f, text="Зарегистрировать сотрудника", command=lambda: self._show_frame(self.frame_admin)).pack(pady=10)
        ttk.Button(f, text="Настроить окружение", command=lambda: self._show_frame(self.frame_admin_env)).pack(pady=10)

    def _build_admin_frame(self):
        f = self.frame_admin
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

    def _build_security_frame(self):
        f = self.frame_security
        nav = ttk.Frame(f)
        nav.pack(fill="x")
        ttk.Button(nav, text="Назад", command=lambda: self._show_frame(self.frame_role)).pack(side="left", padx=10,
                      pady=10)
        self.sort_var = tk.StringVar(value="По убыванию")
        ttk.Label(nav, text="Сортировка:").pack(side="left", padx=5)
        ttk.OptionMenu(nav, self.sort_var, "По убыванию", "По убыванию", "По возрастанию", command=lambda _=None: self._load_logs()).pack(side="left")
        ttk.Label(f, text="Служба безопасности - Логи доступа", style="Title.TLabel").pack(pady=10)
        self.log_text = scrolledtext.ScrolledText(f, width=100, height=30, font=("Courier", 12))
        self.log_text.pack(expand=True, fill="both", padx=20, pady=10)
        ttk.Button(f, text="Обновить", command=self._load_logs).pack(pady=5)

    def _load_logs(self):
        # Определяем направление сортировки для сервера
        order = 'asc' if self.sort_var.get() == "По возрастанию" else 'desc'
        try:
            # Делаем запрос GET /api/logs?order=asc|desc
            resp = requests.get(f"{API_URL}/logs", params={'order': order}, timeout=5)
            resp.raise_for_status()
            # Сервер возвращает JSON-массив строк
            lines = resp.json()
            data = "\n".join(lines)
        except Exception as e:
            # На случай сетевых ошибок
            data = f"Не удалось получить логи: {e}"

        # Обновляем виджет
        self.log_text.delete('1.0', tk.END)
        self.log_text.insert('1.0', data)

    def _show_frame(self, target):
        for frm in (self.frame_role, self.frame_employee, self.frame_admin_choice, self.frame_admin,
                     self.frame_admin_env, self.frame_security):
            frm.pack_forget()
        target.pack(expand=True, fill='both')
        self.root.update_idletasks()
        if target == self.frame_employee:
            self._start_employee_cam()
        else:
            self._stop_camera()
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
        if target == self.frame_security:
            self._load_logs();
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
            messagebox.showwarning("Ошибка", "Заполните все поля и выберите изображение")
            return

        # 1) Подготовка multipart/form-data
        files = {'image': open(img_path, 'rb')}
        data = {'name': name, 'location': loc}

        # 2) POST на /api/environments
        resp = requests.post(f"{API_URL}/environments", data=data, files=files)
        if resp.status_code == 201:
            # 3) Сервер вернул JSON с данными нового помещения
            env = resp.json()
            # env = {'id':..., 'name': name, 'location': loc, 'image_url': ...}

            # 4) Обновляем локальный список и интерфейс
            self.environments.append(env)
            self.env_status.config(text="Помещение добавлено на сервер")
            # Сброс полей формы
            self.env_name_entry.delete(0, 'end')
            self.env_loc_entry.delete(0, 'end')
            self.env_image_label.config(text="")
            self.env_selected_image = ''
            # Перерисовать каталог
            self._refresh_env_catalog()

        else:
            # Если сервер вернул ошибку
            messagebox.showerror("Ошибка сервера", f"{resp.status_code}: {resp.text}")

    def _upload_employee(self):
        name = self.name_entry.get().strip()
        dept = self.dept_var.get()
        if not name or not self.selected_file or not dept:
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
            # Обновляем локальные списки лиц
            self.known_face_encodings, self.known_face_names = load_known_faces()
            self._refresh_catalog()
            # Сбрасываем поля формы
            self.name_entry.delete(0, 'end')
            self.selected_file = None
        else:
            messagebox.showerror("Ошибка сервера", f"Код {resp.status_code}: {resp.text}")

    def _refresh_env_catalog(self):
        for w in self.env_inner.winfo_children():
            w.destroy()
        for env in self.environments:
            rec = ttk.Frame(self.env_inner, padding=5)
            rec.pack(fill='x', pady=5)
            try:
                img = Image.open(env['image'])
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
            self.environments.remove(env)
            save_environments(self.environments)
            self._refresh_env_catalog()

    def _refresh_catalog(self):
        for w in self.inner.winfo_children():
            w.destroy()
        for root_dir, _dirs, files in os.walk(KNOWN_FACES_DIR):
            for fn in files:
                if not fn.lower().endswith((".jpg", ".png")):
                    continue
                name = os.path.splitext(fn)[0]
                path = os.path.join(root_dir, fn)
                rec = ttk.Frame(self.inner, padding=5)
                rec.pack(fill='x', pady=5)
                img = Image.open(path)
                img.thumbnail((64, 64))
                ph = ImageTk.PhotoImage(img)
                lbl = tk.Label(rec, image=ph)
                lbl.image = ph
                lbl.pack(side='left', padx=5)
                dept = self.employee_depts.get(name, os.path.basename(root_dir))
                ttk.Label(rec, text=f"{name} ({dept})", style='Status.TLabel').pack(side='left', padx=10)
                ttk.Button(rec, text="Удалить", command=lambda n=name: self._delete_employee(n)).pack(side='right', padx=5)

    def _delete_employee(self, name):
        for root_dir, _dirs, files in os.walk(KNOWN_FACES_DIR):
            for e in ('.jpg', '.png'):
                file = f"{name}{e}"
                if file in files:
                    os.remove(os.path.join(root_dir, file))
        if name in self.employee_depts:
            del self.employee_depts[name]
            save_department_mapping(self.employee_depts)
        self.known_face_encodings, self.known_face_names = load_known_faces()
        self._refresh_catalog()

    def _start_employee_cam(self):
        if self.cap is None:
            self.cap = cv2.VideoCapture(0)
            self.start_time = time.time()
            self.fail_count = 0
            self.attempts_label.config(text="Неудачные попытки: 0")
            self.status_label.config(text="Камера запущена. Ожидание распознавания...")
            self._update_frame()

    def _stop_camera(self):
        if self.cap: self.cap.release(); self.cap = None

    def _show_access_granted(self):
        self._stop_camera();
        self.emp_back_btn.place_forget();
        self.emp_exit_btn.place_forget()
        overlay = ttk.Label(self.frame_employee, text="Вход разрешен", style='Title.TLabel');
        overlay.place(relx=0.5, rely=0.5, anchor='center')

        def reset(): overlay.destroy(); self._show_frame(self.frame_role)

        self.root.after(5000, reset)

    def _update_frame(self):
        if self.cap is None: return
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
                self._send_log('INFO', f"Access granted for {name} ({dept})")
                self._show_access_granted()
                return
            if time.time() - self.start_time >= self.auth_timeout:
                self._send_log('WARNING', f"Failed authentication attempt {self.fail_count + 1}")
                self.fail_count += 1;
                self.attempts_label.config(text=f"Неудачные попытки: {self.fail_count}");
                self.start_time = time.time()
                if self.fail_count > 3:
                    overlay_denied = ttk.Label(self.frame_employee, text="Похоже, вам сюда нельзя",
                                               style='Title.TLabel');
                    overlay_denied.place(relx=0.5, rely=0.5, anchor='center')
                    self._stop_camera()

                    def reset_denied():
                        overlay_denied.destroy(); self._show_frame(self.frame_role)

                    self.root.after(5000, reset_denied);
                    return
                else:
                    self.status_label.config(text="Лицо не опознано. Попробуйте снова.")
        self.process_frame = not self.process_frame;
        self.root.after(30, self._update_frame)
    def _send_log(self, level: str, msg: str):
        """
        Отправляет одну строку лога на сервер.
        level — 'INFO' или 'WARNING'
        msg   — сообщение вида "Access granted for Иван Иванов (dept)"
        """
        entry = {
            'timestamp': datetime.datetime.utcnow().isoformat(),
            'level': level,
            'message': msg
        }
        try:
            requests.post(f"{API_URL}/logs", json=entry, timeout=2)
        except Exception as e:
            # на случай, если сервер недоступен, можно просто пропустить
            print("Не удалось отправить лог:", e)

    def on_closing(self):
        self._stop_camera();
        self.root.destroy()



if __name__ == '__main__':
    app = FaceRecognitionApp()
