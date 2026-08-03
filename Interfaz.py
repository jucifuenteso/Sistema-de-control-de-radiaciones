import tkinter as tk
from tkinter import ttk, messagebox
import serial
import serial.tools.list_ports
import threading
import time
import os                         
from dotenv import load_dotenv     

load_dotenv()                     

# --- ADAFRUIT IO CONFIGURACIÓN ---
# Instala esta biblioteca usando pip:
# pip install adafruit-io
from Adafruit_IO import Client, RequestError

# Credenciales de Adafruit IO (¡CAMBIA ESTO CON TUS CREDENCIALES!)
# Puedes encontrar tu AIO_USERNAME y AIO_KEY en io.adafruit.com -> My Key
AIO_USERNAME = os.environ.get("AIO_USERNAME")
AIO_KEY = os.environ.get("AIO_KEY")
# Inicializa el cliente de Adafruit IO
aio = None
adafruit_io_connected = False # Bandera para indicar si la conexión fue exitosa

try:
    aio = Client(AIO_USERNAME, AIO_KEY)
    print("Conectado a Adafruit IO.")
    adafruit_io_connected = True
except RequestError as e:
    print(f"Error al conectar a Adafruit IO: {e}")
    messagebox.showerror("Error de Adafruit IO", f"No se pudo conectar a Adafruit IO. Verifica tus credenciales y conexión a internet.\nError: {e}")
except Exception as e:
    print(f"Error inesperado al inicializar Adafruit IO: {e}")
    messagebox.showerror("Error de Adafruit IO", f"Error inesperado al inicializar Adafruit IO.\nError: {e}")


# Define los feeds a los que vas a enviar datos
FEED_EVENTS_PER_SECOND = "conteos-por-segundo"
FEED_EVENTS_PER_MINUTE = "conteos-por-minuto"
FEED_LAST_COMMAND = "ultimo-comando"
# --- FIN ADAFRUIT IO CONFIGURACIÓN ---


# --- Configuración Serial Global ---
BAUD_RATE = 115200
ser = None # Objeto serial global, compartido entre modos si se usa.

# --- Variables para el hilo de lectura serial global ---
serial_read_thread = None
stop_serial_read_flag = threading.Event() # Evento para detener el hilo de lectura
last_adafruit_io_status_sent = "" # Para evitar enviar el mismo estado repetidamente

# --- Temporizador para Adafruit IO: Solo permite enviar datos cada X segundos ---
last_adafruit_io_publish_time = 0
ADA_IO_PUBLISH_INTERVAL_SEC = 5 # Publicar cada 5 segundos para conteos

# --- Comandos para el ESP32 (para el modo manual) ---
COMMAND_MOTOR1_CW = "MOTOR1D"   # Cuarto de vuelta Horario
COMMAND_MOTOR1_CCW = "MOTOR1I"  # Cuarto de vuelta Anti-horario
COMMAND_MOTOR1_THIRD_CW = "MOTOR1H" # Tercio de vuelta Horario
COMMAND_MOTOR1_THIRD_CCW = "MOTOR1T" # Tercio de vuelta Anti-horario

COMMAND_MOTOR2_CW = "MOTOR2D"
COMMAND_MOTOR2_CCW = "MOTOR2I"
COMMAND_MOTOR2_THIRD_CW = "MOTOR2H"
COMMAND_MOTOR2_THIRD_CCW = "MOTOR2T"

COMMAND_MOTOR3_CW = "MOTOR3D"
COMMAND_MOTOR3_CCW = "MOTOR3I"
COMMAND_MOTOR3_THIRD_CW = "MOTOR3H"
COMMAND_MOTOR3_THIRD_CCW = "MOTOR3T"

# --- Funciones de control de motores (Solo para el modo manual) ---
def send_command(command):
    """Envía un comando al puerto serial."""
    global ser
    if ser and ser.is_open:
        try:
            full_command = command + '\n'
            ser.write(full_command.encode())

        except serial.SerialException as e:
            messagebox.showerror("Error Serial", f"Error al enviar comando: {e}\nIntentando reconectar...")
            print(f"Error al enviar comando: {e}")
            disconnect_serial() # Usar la desconexión general
        except AttributeError:
            messagebox.showwarning("Puerto no conectado", "El puerto serial no está abierto o se desconectó.")
    else:
        messagebox.showwarning("Puerto no conectado", "El puerto serial no está abierto. Conéctate primero.")

# --- Funciones de Conexión y Desconexión Serial (Globales) ---
def list_serial_ports():
    """Lista los puertos seriales disponibles."""
    ports = serial.tools.list_ports.comports()
    return [port.device for port in ports]

def connect_serial_common(selected_port, status_label, connect_button):
    """Función común para conectar el serial, usada por ambos modos."""
    global ser, serial_read_thread, stop_serial_read_flag, last_adafruit_io_status_sent

    if not selected_port:
        messagebox.showwarning("Error de Conexión", "Por favor, selecciona un puerto serial.")
        return

    # Asegurarse de cerrar cualquier conexión existente antes de abrir una nueva
    if ser and ser.is_open:
        disconnect_serial()

    try:
        ser = serial.Serial(selected_port, BAUD_RATE, timeout=1)
        if ser.is_open:
            status_label.config(text=f"Estado: Conectado a {selected_port}", foreground="green")
            connect_button.config(text="Desconectar", command=disconnect_serial)
            print(f"Conectado a {selected_port}.")

            # Iniciar el hilo de lectura serial si aún no está corriendo
            if not (serial_read_thread and serial_read_thread.is_alive()):
                stop_serial_read_flag.clear() # Asegurarse de que la bandera esté limpia
                serial_read_thread = threading.Thread(target=read_serial_data, daemon=True)
                serial_read_thread.start()
                print("Hilo de lectura serial iniciado.")
            
            # Resetear el estado de envío a Adafruit IO para permitir que se envíen nuevos estados
            last_adafruit_io_status_sent = "" 
            send_adafruit_io_status("Conectado") # Enviar estado general de conexión
            
            # Habilitar o deshabilitar botones según el modo actual
            if root.title() == "Control de Motores ESP32 - Modo Manual":
                for btn_list in motor_buttons_widgets:
                    for btn in btn_list:
                        btn.config(state=tk.NORMAL)
            
    except serial.SerialException as e:
        status_label.config(text=f"Estado: Error de Conexión", foreground="red")
        messagebox.showerror("Error de Conexión", f"No se pudo conectar a {selected_port}:\n{e}")
        print(f"Error de conexión: {e}")
        ser = None

def disconnect_serial():
    """Desconecta el puerto serial globalmente."""
    global ser, serial_read_thread, stop_serial_read_flag, last_adafruit_io_status_sent
    
    # Señal para detener el hilo de lectura
    stop_serial_read_flag.set()
    if serial_read_thread and serial_read_thread.is_alive():
        serial_read_thread.join(timeout=1) # Esperar un poco a que el hilo termine
        if serial_read_thread.is_alive():
            print("Advertencia: El hilo de lectura serial no se detuvo correctamente.")
    
    if ser and ser.is_open:
        try:
            ser.close()
            print("Desconectado del puerto serial.")
            # Actualizar labels de estado en ambos modos (si existen)
            if status_label_manual and status_label_manual.winfo_exists():
                status_label_manual.config(text="Estado: Desconectado", foreground="orange")
                connect_button_manual.config(text="Conectar", command=lambda: connect_serial_common(port_combobox_manual.get(), status_label_manual, connect_button_manual))
                for btn_list in motor_buttons_widgets:
                    for btn in btn_list:
                        btn.config(state=tk.DISABLED)
            if status_label_detection and status_label_detection.winfo_exists():
                status_label_detection.config(text="Estado: Desconectado", foreground="orange")
                connect_button_detection.config(text="Conectar", command=lambda: connect_serial_common(port_combobox_detection.get(), status_label_detection, connect_button_detection))
            
            send_adafruit_io_status("Desconectado") # Enviar estado general de desconexión

        except serial.SerialException as e:
            messagebox.showerror("Error Serial", f"Error al desconectar: {e}")
            print(f"Error al desconectar: {e}")
        finally:
            ser = None
    elif status_label_manual and status_label_manual.winfo_exists(): # Si no estaba conectado pero la GUI manual está visible
        status_label_manual.config(text="Estado: Ya desconectado", foreground="gray")
    elif status_label_detection and status_label_detection.winfo_exists(): # Si no estaba conectado pero la GUI detección está visible
        status_label_detection.config(text="Estado: Ya desconectado", foreground="gray")
    
    # Si no hay conexión y no está en selección de modo, enviar "Esperando datos"
    if not ser and root.title() != "Selecciona un Modo":
            send_adafruit_io_status("Esperando datos")


def send_adafruit_io_status(status_message):
    """Envía un mensaje de estado general a los feeds de Adafruit IO, evitando repeticiones."""
    global adafruit_io_connected, last_adafruit_io_status_sent

    if adafruit_io_connected and last_adafruit_io_status_sent != status_message:
        try:
            # Solo enviamos al FEED_LAST_COMMAND cuando se cambia de estado general de la app
            aio.send_data(FEED_LAST_COMMAND, status_message) 
            last_adafruit_io_status_sent = status_message
            print(f"Enviado '{status_message}' a Adafruit IO feed de comando.")
        except RequestError as e:
            print(f"Error al enviar '{status_message}' a Adafruit IO (Rate Limit/Otro): {e}")
        except Exception as e:
            print(f"Error inesperado al enviar '{status_message}' a Adafruit IO: {e}")

def read_serial_data():
    """Función que se ejecuta en un hilo para leer datos seriales."""
    global ser
    while not stop_serial_read_flag.is_set():
        if ser and ser.is_open:
            try:
                line = ser.readline().decode('utf-8').strip()
                if line:
                    root.after(0, lambda: process_serial_line(line))
            except serial.SerialException as e:
                print(f"Error de lectura serial: {e}")
                root.after(0, lambda: messagebox.showerror("Error de Lectura", f"Error al leer del puerto serial: {e}\nDesconectando..."))
                root.after(0, disconnect_serial) # Desconectar desde el hilo principal, usando la función general
                break # Salir del bucle del hilo
            except UnicodeDecodeError as e:
                print(f"Error de decodificación: {e} - Ignorando línea.")
            time.sleep(0.01) # Pequeño retardo para no consumir CPU excesivamente
        else:
            time.sleep(0.1) # Esperar si el puerto no está abierto


def process_serial_line(line):
    """
    Procesa una línea de datos seriales, actualiza la interfaz y envía a Adafruit IO.
    Se actualizan los conteos si el frame de detección está visible.
    La confirmación de comando ya NO actualiza el FEED_LAST_COMMAND.
    """
    global adafruit_io_connected, last_adafruit_io_publish_time

    parts = line.split(',')
    
    # --- PROCESAR DATA_REPORT (Conteo de eventos) ---
    # Esto ahora se procesa SIEMPRE que se reciba, sin importar el modo.
    if len(parts) >= 3 and parts[0] == "DATA_REPORT":
        try:
            events_sec = float(parts[1])
            events_min = float(parts[2])
            
            # Solo actualizar la GUI si el frame de detección está visible (para evitar errores si no existe)
            if events_sec_label and events_sec_label.winfo_exists():
                events_sec_label.config(text=f"{events_sec:.1f}")
            if events_min_label and events_min_label.winfo_exists():
                events_min_label.config(text=f"{events_min:.1f}")
            
            # --- ENVÍO A ADAFRUIT IO (CON TEMPORIZADOR) ---
            current_time = time.time()
            if adafruit_io_connected and (current_time - last_adafruit_io_publish_time) >= ADA_IO_PUBLISH_INTERVAL_SEC:
                try:
                    aio.send_data(FEED_EVENTS_PER_SECOND, f"{events_sec:.1f}")
                    aio.send_data(FEED_EVENTS_PER_MINUTE, f"{events_min:.1f}")
                    last_adafruit_io_publish_time = current_time
                    print(f"Datos enviados a Adafruit IO: Segundos={events_sec:.1f}, Minutos={events_min:.1f}")
                except RequestError as e:
                    print(f"Error al enviar datos a Adafruit IO (Rate Limit/Otro): {e}")
                except Exception as e:
                    print(f"Error inesperado al enviar datos a Adafruit IO: {e}")
            # --- FIN ENVÍO A ADAFRUIT IO ---

            # --- Procesar estado de las placas (si tu ESP32 las envía) ---
            if len(parts) >= 6:
                plate_states = parts[3:]
                # Solo actualizar la GUI si los labels de placas existen y son visibles
                if plate_status_labels and plate_status_labels[0].winfo_exists():
                    for i, state in enumerate(plate_states):
                        if i < len(plate_status_labels):
                            state_upper = state.strip().upper()
                            if state_upper == "ENABLE":
                                plate_status_labels[i].config(text="ENABLE", foreground="green")
                            elif state_upper == "DISABLE":
                                plate_status_labels[i].config(text="DISABLE", foreground="red")
                            else:
                                plate_status_labels[i].config(text=state.strip(), foreground="gray")
        except ValueError:
            print(f"Error al convertir números de la línea DATA_REPORT: {line}")

    # --- PROCESAR CONFIRMACIÓN DE ÚLTIMO COMANDO ---
    # La confirmación de comando ahora solo se imprime en consola, NO se envía a Adafruit IO.
    if line.startswith("CMD_ACK:") or (line.startswith("Motor") and "Mov_OK:" in line):
        confirmed_command = line.split(':')[-1].strip()
        print(f"Comando '{confirmed_command}' confirmado por el ESP32 (no enviado a Adafruit IO).")


# --- Configuración de la Interfaz Gráfica ---
root = tk.Tk()
root.title("Control y Detección Nuclear")
root.geometry("1200x650") # Aumentado el tamaño para acomodar los nuevos botones
root.resizable(False, False)

# Estilo para los widgets
style = ttk.Style()
style.theme_use("clam")

# Colores y fuentes para una mejor estética
BG_COLOR = "#ECECEC" # Fondo gris claro
FRAME_BG = "#E0E0E0" # Fondo de los marcos
BTN_COLOR_CW = "#4CAF50" # Verde para horario (cuarto de vuelta)
BTN_COLOR_CCW = "#F44336" # Rojo para anti-horario (cuarto de vuelta)
BTN_COLOR_THIRD_CW = "#2196F3" # Azul para tercio de vuelta horario
BTN_COLOR_THIRD_CCW = "#FF9800" # Naranja para tercio de vuelta anti-horario
TEXT_COLOR = "#333333" # Texto oscuro
HEADER_FONT = ('Arial', 12, 'bold')
BUTTON_FONT = ('Arial', 9, 'bold') # Fuente ligeramente más pequeña para que quepan todos los botones

root.config(bg=BG_COLOR)

style.configure("TFrame", background=FRAME_BG)
style.configure("TLabelFrame", background=FRAME_BG, foreground=TEXT_COLOR, font=('Arial', 10, 'bold'))
style.configure("TLabel", background=FRAME_BG, foreground=TEXT_COLOR, font=('Arial', 9))
style.configure("TButton", font=BUTTON_FONT, padding=7, relief="raised") # Padding ligeramente ajustado
style.map("TButton",
          background=[('active', '#D0D0D0'), ('!disabled', '#E0E0E0')],
          foreground=[('disabled', '#A0A0A0')])

style.configure("Green.TButton", background=BTN_COLOR_CW, foreground="white")
style.map("Green.TButton", background=[('active', '#66BB6A'), ('!disabled', BTN_COLOR_CW)])

style.configure("Red.TButton", background=BTN_COLOR_CCW, foreground="white")
style.map("Red.TButton", background=[('active', '#EF5350'), ('!disabled', BTN_COLOR_CCW)])

# Nuevos estilos para los botones de tercio de vuelta
style.configure("Blue.TButton", background=BTN_COLOR_THIRD_CW, foreground="white")
style.map("Blue.TButton", background=[('active', '#64B5F6'), ('!disabled', BTN_COLOR_THIRD_CW)])

style.configure("Orange.TButton", background=BTN_COLOR_THIRD_CCW, foreground="white")
style.map("Orange.TButton", background=[('active', '#FFB74D'), ('!disabled', BTN_COLOR_THIRD_CCW)])


# --- Contenedor principal para cambiar entre modos ---
main_container = ttk.Frame(root)
main_container.pack(fill="both", expand=True)

# --- Variables globales para widgets del modo manual ---
port_combobox_manual = None
connect_button_manual = None
status_label_manual = None
motors_container_frame = None
motor_buttons_widgets = [] # Se llenará cuando se cree la interfaz manual

# --- Variables globales para widgets del modo detección nuclear ---
port_combobox_detection = None
connect_button_detection = None
status_label_detection = None
detection_frame = None
events_sec_label = None
events_min_label = None
plate_status_labels = [] # Lista para almacenar los Labels de estado de las placas

# --- Funciones para cambiar de modo ---
def show_manual_mode():
    """Muestra la interfaz del modo manual de control de motores."""
    global port_combobox_manual, connect_button_manual, status_label_manual, \
             motors_container_frame, motor_buttons_widgets, ser, last_adafruit_io_status_sent

    for widget in main_container.winfo_children():
        widget.destroy()

    root.geometry("1200x650")
    root.title("Control de Motores ESP32 - Modo Manual")

    # --- Marco de Conexión Serial (arriba) ---
    serial_frame = ttk.LabelFrame(main_container, text="Configuración de Conexión Serial", padding=(10,10))
    serial_frame.pack(padx=20, pady=15, fill="x", expand=False)

    ttk.Label(serial_frame, text="Puerto Serial:").pack(side="left", padx=5, pady=5)
    port_combobox_manual = ttk.Combobox(serial_frame, values=list_serial_ports(), state="readonly", width=30)
    port_combobox_manual.pack(side="left", padx=5, pady=5, expand=True, fill="x")
    ports_found = list_serial_ports()
    if ports_found:
        port_combobox_manual.set(ports_found[0])

    connect_button_manual = ttk.Button(serial_frame, text="Conectar", command=lambda: connect_serial_common(port_combobox_manual.get(), status_label_manual, connect_button_manual))
    connect_button_manual.pack(side="left", padx=(10, 5), pady=5)

    status_label_manual = ttk.Label(serial_frame, text="Estado: Desconectado", foreground="orange")
    status_label_manual.pack(side="left", padx=5, pady=5, expand=True)

    # --- Botón para volver al menú principal ---
    back_button = ttk.Button(serial_frame, text="<< Volver", command=show_mode_selection)
    back_button.pack(side="right", padx=5, pady=5)

    # --- Marco Principal para los Motores (horizontal) ---
    motors_container_frame = ttk.Frame(main_container, padding=(10,10))
    motors_container_frame.pack(padx=20, pady=10, fill="both", expand=True)

    motor_buttons_widgets = [] # Reiniciar la lista para este modo

    def create_motor_group_manual(parent_frame, motor_num, cmd_cw, cmd_ccw, cmd_third_cw, cmd_third_ccw):
        """Crea y empaqueta los controles para un motor, incluyendo giros de cuarto y tercio de vuelta."""
        motor_frame = ttk.LabelFrame(parent_frame, text=f"Control Motor {motor_num}", padding=(10,10))
        motor_frame.pack(side="left", padx=10, pady=10, fill="both", expand=True)

        quarter_turn_frame = ttk.Frame(motor_frame)
        quarter_turn_frame.pack(pady=5)
        ttk.Label(quarter_turn_frame, text="Cuarto de Vuelta:").pack(side="top", pady=2)

        btn_cw = ttk.Button(quarter_turn_frame, text="Horario (D)",
                             command=lambda: send_command(cmd_cw), style="Green.TButton")
        btn_cw.pack(side="left", padx=3, pady=2)

        btn_ccw = ttk.Button(quarter_turn_frame, text="Anti-Horario (I)",
                             command=lambda: send_command(cmd_ccw), style="Red.TButton")
        btn_ccw.pack(side="left", padx=3, pady=2)

        third_turn_frame = ttk.Frame(motor_frame)
        third_turn_frame.pack(pady=5)
        ttk.Label(third_turn_frame, text="Tercio de Vuelta:").pack(side="top", pady=2)

        btn_third_cw = ttk.Button(third_turn_frame, text="Horario (H)",
                                     command=lambda: send_command(cmd_third_cw), style="Blue.TButton")
        btn_third_cw.pack(side="left", padx=3, pady=2)

        btn_third_ccw = ttk.Button(third_turn_frame, text="Anti-Horario (T)",
                                     command=lambda: send_command(cmd_third_ccw), style="Orange.TButton")
        btn_third_ccw.pack(side="left", padx=3, pady=2)

        return [btn_cw, btn_ccw, btn_third_cw, btn_third_ccw]

    motor_buttons_widgets.append(create_motor_group_manual(motors_container_frame, 1, 
                                    COMMAND_MOTOR1_CW, COMMAND_MOTOR1_CCW, 
                                    COMMAND_MOTOR1_THIRD_CW, COMMAND_MOTOR1_THIRD_CCW))
    motor_buttons_widgets.append(create_motor_group_manual(motors_container_frame, 2, 
                                    COMMAND_MOTOR2_CW, COMMAND_MOTOR2_CCW, 
                                    COMMAND_MOTOR2_THIRD_CW, COMMAND_MOTOR2_THIRD_CCW))
    motor_buttons_widgets.append(create_motor_group_manual(motors_container_frame, 3, 
                                    COMMAND_MOTOR3_CW, COMMAND_MOTOR3_CCW, 
                                    COMMAND_MOTOR3_THIRD_CW, COMMAND_MOTOR3_THIRD_CCW))

    for btn_list in motor_buttons_widgets:
        for btn in btn_list:
            btn.config(state=tk.DISABLED)

    # Re-evaluar estado de conexión y habilitar/deshabilitar botones
    if ser and ser.is_open:
        status_label_manual.config(text=f"Estado: Conectado a {ser.port}", foreground="green")
        connect_button_manual.config(text="Desconectar", command=disconnect_serial)
        for btn_list in motor_buttons_widgets:
            for btn in btn_list:
                btn.config(state=tk.NORMAL)
    else:
        status_label_manual.config(text="Estado: Desconectado", foreground="orange")
        connect_button_manual.config(text="Conectar", command=lambda: connect_serial_common(port_combobox_manual.get(), status_label_manual, connect_button_manual))

    # Actualizar Adafruit IO al entrar en este modo
    send_adafruit_io_status("Modo Manual Activo")


def show_detection_mode():
    """Muestra la interfaz del modo de detección nuclear."""
    global detection_frame, events_sec_label, events_min_label, plate_status_labels, \
             port_combobox_detection, connect_button_detection, status_label_detection, ser, last_adafruit_io_status_sent

    for widget in main_container.winfo_children():
        widget.destroy()

    root.geometry("600x600")
    root.title("Detección Nuclear")

    detection_frame = ttk.Frame(main_container, padding=(20, 20))
    detection_frame.pack(fill="both", expand=True)

    back_button = ttk.Button(detection_frame, text="<< Volver", command=show_mode_selection)
    back_button.pack(anchor="nw", pady=(0, 15))

    ttk.Label(detection_frame, text="Información de Detección Nuclear", font=HEADER_FONT).pack(pady=(0, 15))

    # --- Marco de Conexión Serial para el modo detección ---
    serial_detection_frame = ttk.LabelFrame(detection_frame, text="Configuración de Conexión Serial", padding=(10,10))
    serial_detection_frame.pack(padx=0, pady=5, fill="x", expand=False)

    ttk.Label(serial_detection_frame, text="Puerto Serial:").pack(side="left", padx=5, pady=5)
    port_combobox_detection = ttk.Combobox(serial_detection_frame, values=list_serial_ports(), state="readonly", width=25)
    port_combobox_detection.pack(side="left", padx=5, pady=5, expand=True, fill="x")
    ports_found = list_serial_ports()
    if ports_found:
        port_combobox_detection.set(ports_found[0])

    connect_button_detection = ttk.Button(serial_detection_frame, text="Conectar", command=lambda: connect_serial_common(port_combobox_detection.get(), status_label_detection, connect_button_detection))
    connect_button_detection.pack(side="left", padx=(10, 5), pady=5)

    status_label_detection = ttk.Label(serial_detection_frame, text="Estado: Desconectado", foreground="orange")
    status_label_detection.pack(side="left", padx=5, pady=5, expand=True)

    # --- Eventos Ionizantes ---
    events_frame = ttk.LabelFrame(detection_frame, text="Eventos Ionizantes", padding=(10,10))
    events_frame.pack(pady=10, fill="x", expand=False)

    ttk.Label(events_frame, text="Eventos Ionizantes por Segundo:").grid(row=0, column=0, sticky="w", padx=5, pady=2)
    events_sec_label = ttk.Label(events_frame, text="0.0", font=('Arial', 14, 'bold'), foreground="blue")
    events_sec_label.grid(row=0, column=1, sticky="e", padx=5, pady=2)

    ttk.Label(events_frame, text="Eventos Ionizantes por Minuto:").grid(row=1, column=0, sticky="w", padx=5, pady=2)
    events_min_label = ttk.Label(events_frame, text="0.0", font=('Arial', 14, 'bold'), foreground="blue")
    events_min_label.grid(row=1, column=1, sticky="e", padx=5, pady=2)
    events_frame.grid_columnconfigure(1, weight=1)

    # --- Estado de las Placas ---
    plates_status_frame = ttk.LabelFrame(detection_frame, text="Estado de las Placas", padding=(10,10))
    plates_status_frame.pack(pady=10, fill="x", expand=False)

    plate_status_labels = [] # Reiniciar la lista

    for i in range(1, 4):
        ttk.Label(plates_status_frame, text=f"PLACA {i}:").grid(row=i-1, column=0, sticky="w", padx=5, pady=2)
        status_label_plate = ttk.Label(plates_status_frame, text="DISABLE", font=('Arial', 12, 'bold'), foreground="red")
        status_label_plate.grid(row=i-1, column=1, sticky="e", padx=5, pady=2)
        plate_status_labels.append(status_label_plate)
    plates_status_frame.grid_columnconfigure(1, weight=1)

    # Re-evaluar estado de conexión
    if ser and ser.is_open:
        status_label_detection.config(text=f"Estado: Conectado a {ser.port}", foreground="green")
        connect_button_detection.config(text="Desconectar", command=disconnect_serial)
    else:
        status_label_detection.config(text="Estado: Desconectado", foreground="orange")
        connect_button_detection.config(text="Conectar", command=lambda: connect_serial_common(port_combobox_detection.get(), status_label_detection, connect_button_detection))
    
    # Actualizar Adafruit IO al entrar en este modo
    send_adafruit_io_status("Modo Detección Activo")


def show_mode_selection():
    """Muestra la pantalla inicial de selección de modo."""
    for widget in main_container.winfo_children():
        widget.destroy()

    global ser, serial_read_thread, stop_serial_read_flag, last_adafruit_io_status_sent
    if ser and ser.is_open:
        try:
            ser.close()
            print("Puerto serial cerrado al volver a la selección de modo.")
        except serial.SerialException as e:
            print(f"Error al cerrar serial al volver a selección de modo: {e}")
        finally:
            ser = None
    
    stop_serial_read_flag.set()
    if serial_read_thread and serial_read_thread.is_alive():
        serial_read_thread.join(timeout=1)
        if serial_read_thread.is_alive():
            print("Advertencia: El hilo de lectura serial no se detuvo correctamente al cambiar de modo.")
    
    if adafruit_io_connected:
        try:
            # Send numerical values of 0 or a placeholder like "0.0" when disconnecting
            aio.send_data(FEED_EVENTS_PER_SECOND, "0.0") 
            aio.send_data(FEED_EVENTS_PER_MINUTE, "0.0")
            aio.send_data(FEED_LAST_COMMAND, "Modo de Selección Activo") # Actualizar el feed aquí
            last_adafruit_io_status_sent = "Modo de Selección Activo"
            print("Adafruit IO actualizado a 'Modo de Selección Activo'.")
        except RequestError as e:
            print(f"Error al actualizar Adafruit IO al cambiar a selección de modo: {e}")
        except Exception as e:
            print(f"Error inesperado al actualizar Adafruit IO al cambiar a selección de modo: {e}")


    root.geometry("600x600")
    root.title("Selecciona un Modo")

    selection_frame = ttk.Frame(main_container, padding=(20, 20))
    selection_frame.pack(expand=True)

    ttk.Label(selection_frame, text="Selecciona el Modo de Operación:", font=HEADER_FONT).pack(pady=20)

    manual_mode_button = ttk.Button(selection_frame, text="Modo Manual (Control de Motores)",
                                     command=show_manual_mode, width=40)
    manual_mode_button.pack(pady=10)

    detection_mode_button = ttk.Button(selection_frame, text="Modo de Detección Nuclear",
                                         command=show_detection_mode, width=40)
    detection_mode_button.pack(pady=10)

# --- Configurar el cierre de la ventana ---
def on_closing():
    global ser, serial_read_thread, stop_serial_read_flag
    
    stop_serial_read_flag.set()
    if serial_read_thread and serial_read_thread.is_alive():
        serial_read_thread.join(timeout=1)
        if serial_read_thread.is_alive():
            print("Advertencia: El hilo de lectura serial no se detuvo correctamente al cerrar la aplicación.")

    if ser and ser.is_open:
        try:
            ser.close()
            print("Puerto serial cerrado al salir.")
        except serial.SerialException as e:
            print(f"Error al cerrar serial al salir: {e}")
    
    if adafruit_io_connected:
        try:
            # Send numerical values of 0 or a placeholder like "0.0" when closing
            aio.send_data(FEED_EVENTS_PER_SECOND, "0.0") 
            aio.send_data(FEED_EVENTS_PER_MINUTE, "0.0")
            aio.send_data(FEED_LAST_COMMAND, "Aplicación Cerrada")
            print("Estado 'Aplicación Cerrada' enviado a Adafruit IO al cerrar.")
        except RequestError as e:
            print(f"Error al enviar 'Aplicación Cerrada' a Adafruit IO al salir: {e}")
        except Exception as e:
            print(f"Error inesperado al enviar estado de desconexión a Adafruit IO: {e}")

    root.destroy()

root.protocol("WM_DELETE_WINDOW", on_closing)

# Mostrar la pantalla de selección de modo al iniciar
show_mode_selection()

# Iniciar el bucle principal de Tkinter
root.mainloop()