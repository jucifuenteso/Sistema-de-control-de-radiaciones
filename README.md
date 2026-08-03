# Sistema de Control de Radiaciones — Blindaje Automatizado con Barreras Motorizadas

Proyecto desarrollado para la asignatura de **Instrumentación Virtual**. El sistema simula una respuesta automática de contención ante una fuga de radiación: un detector Geiger mide el nivel de radiación y, mediante comunicación inalámbrica, activa de forma remota un conjunto de compuertas motorizadas fabricadas en distintos materiales de blindaje (cobre, plomo y aluminio). Todo el proceso puede monitorearse en tiempo real desde una interfaz de escritorio y desde un panel en línea.

---

## Tabla de contenidos

- [Descripción general](#descripción-general)
- [Arquitectura del sistema](#arquitectura-del-sistema)
- [Componentes del proyecto](#componentes-del-proyecto)
- [Hardware utilizado](#hardware-utilizado)
- [Protocolo de comunicación](#protocolo-de-comunicación)
- [Requisitos](#requisitos)
- [Instalación y configuración](#instalación-y-configuración)
- [Uso del sistema](#uso-del-sistema)
- [Integración con Adafruit IO](#integración-con-adafruit-io)
- [Estructura del repositorio](#estructura-del-repositorio)
- [Seguridad y buenas prácticas](#seguridad-y-buenas-prácticas)
- [Posibles mejoras futuras](#posibles-mejoras-futuras)
- [Autores](#autores)
- [Licencia](#licencia)

---

## Descripción general

El proyecto simula un sistema de contención automática de radiación en tres etapas:

1. **Detección**: un microcontrolador STM32 conectado a un detector Geiger–Müller registra los eventos de ionización (conteos por segundo y por minuto).
2. **Transmisión inalámbrica**: los conteos se envían vía USART a través de un par de antenas XBee hacia un ESP32 receptor.
3. **Actuación y control**: el ESP32 evalúa los conteos recibidos y, al superar un umbral de referencia, activa un motor paso a paso que despliega una compuerta de blindaje (placa 3, posición "enable"). Cuando el nivel de radiación vuelve a la normalidad, la compuerta regresa a su posición inicial.

En paralelo, el ESP32 admite comandos manuales por puerto serie USB para operar de forma independiente los tres motores (uno por cada material de blindaje: cobre, plomo y aluminio), permitiendo pruebas de laboratorio sin necesidad de una fuga real.

Toda la operación —conexión serial, conteos en tiempo real, estado de las placas y control manual de motores— se centraliza en una **interfaz gráfica desarrollada en Python (Tkinter)**, que además publica los datos en la nube mediante **Adafruit IO** para su visualización remota.

---

## Arquitectura del sistema

```
 ┌─────────────────┐        USART (XBee)         ┌──────────────────────┐
 │   STM32 +        │ ───────────────────────────▶│   ESP32               │
 │   Geiger–Müller  │   "COMANDO,conteos/s,        │   (RX2/TX2)           │
 │   (Detección)    │        conteos/min"          │                        │
 └─────────────────┘                              │  - Evalúa umbral       │
                                                    │  - Controla 3 motores │
                                                    │    paso a paso        │
                                                    │  - Reporta por USB    │
                                                    └───────────┬───────────┘
                                                                │ USB Serial
                                                                │ (115200 baud)
                                                                ▼
                                                  ┌───────────────────────────┐
                                                  │  Interfaz Python (Tkinter) │
                                                  │  - Modo Manual             │
                                                  │  - Modo Detección          │
                                                  │  - Envío a Adafruit IO     │
                                                  └───────────┬────────────────┘
                                                              │ HTTPS / Adafruit IO API
                                                              ▼
                                                  ┌───────────────────────────┐
                                                  │   Dashboard Adafruit IO    │
                                                  │   (Monitoreo en línea)     │
                                                  └───────────────────────────┘
```

---

## Componentes del proyecto

### 1. Firmware ESP32 (`esp32_control.ino`)

- Recibe los conteos de radiación desde el STM32 vía `Serial2` (USART2, pines RX2=16 / TX2=17, 19200 baudios).
- Controla **tres motores paso a paso 28BYJ-48** (uno por compuerta/material) mediante manejo de medio paso (*half-step drive*), lo que duplica la resolución y mejora el torque respecto al modo de onda completa.
- Cada motor puede moverse:
  - Un **cuarto de vuelta**, horario o antihorario (control manual).
  - Un **tercio de vuelta**, horario o antihorario (usado automáticamente por la lógica de contención de la placa 3, y disponible también para control manual).
- Movimiento **no bloqueante**: cada motor se gestiona de forma independiente por temporización (`millis()`), permitiendo mover varios motores "simultáneamente" sin detener el bucle principal.
- Mantiene **torque de retención** al finalizar cada giro (no corta la energía de las bobinas), evitando que las compuertas se desplacen por gravedad o vibración.
- Lógica de contención automática: si los conteos por minuto superan `conteoreferencia` (por defecto 100), el motor 3 gira un tercio de vuelta antihorario para llevar la placa a la posición "enable" (barrera desplegada). Al normalizarse el conteo, la placa regresa automáticamente a su posición inicial.
- Acepta comandos manuales por USB Serial con el formato `MOTOR#X`, donde `#` es el número de motor (1–3) y `X` es la acción:

  | Comando   | Acción                                  |
  |-----------|------------------------------------------|
  | `MOTOR1D` | Motor 1 — cuarto de vuelta horario        |
  | `MOTOR1I` | Motor 1 — cuarto de vuelta antihorario    |
  | `MOTOR1H` | Motor 1 — tercio de vuelta horario        |
  | `MOTOR1T` | Motor 1 — tercio de vuelta antihorario    |
  | ...       | (equivalente para `MOTOR2` y `MOTOR3`)    |

### 2. Interfaz de escritorio en Python (`interfaz_control.py`)

Aplicación construida con **Tkinter** que ofrece dos modos de operación:

- **Modo Manual**: permite enviar comandos de giro (cuarto y tercio de vuelta, en ambos sentidos) a cada uno de los tres motores de forma individual, útil para calibración y pruebas.
- **Modo Detección Nuclear**: muestra en tiempo real los eventos ionizantes por segundo y por minuto, así como el estado (`ENABLE` / `DISABLE`) de cada una de las tres placas de blindaje.

Características técnicas:

- Detección automática de puertos seriales disponibles (`pyserial`).
- Lectura serial en un **hilo independiente** (`threading`) para no bloquear la interfaz gráfica.
- Publicación periódica de datos hacia **Adafruit IO** (cada 5 segundos, configurable) para evitar exceder los límites de la API.
- Manejo de reconexión y cierre seguro del puerto serial y del hilo de lectura.
- Cierre controlado de la aplicación (`WM_DELETE_WINDOW`), notificando el estado final a Adafruit IO.

### 3. Plataforma en línea — Adafruit IO

Se utilizan tres feeds para exponer el estado del sistema en un dashboard remoto:

| Feed (Adafruit IO)     | Contenido                                             |
|-------------------------|--------------------------------------------------------|
| `conteos-por-segundo`   | Eventos ionizantes detectados por segundo              |
| `conteos-por-minuto`    | Eventos ionizantes detectados por minuto                |
| `ultimo-comando`        | Último estado/evento relevante de la aplicación (conexión, modo activo, cierre, etc.) |

---

## Hardware utilizado

- **STM32** — microcontrolador para adquisición de datos del detector Geiger–Müller.
- **Detector Geiger–Müller** — sensor de radiación ionizante.
- **Módulos de antena XBee (par transmisor/receptor)** — enlace inalámbrico USART entre el STM32 y el ESP32.
- **ESP32** — microcontrolador central de control, recibe los conteos y acciona los motores.
- **3x motor paso a paso 28BYJ-48** (con su driver ULN2003 o equivalente) — accionamiento de las compuertas de blindaje.
- **3 compuertas/placas de blindaje**, fabricadas en:
  - Cobre
  - Plomo
  - Aluminio
- **PC** con puerto USB — ejecuta la interfaz de Python y publica los datos en Adafruit IO.

### Asignación de pines del ESP32

| Motor    | IN1 | IN2 | IN3 | IN4 |
|----------|-----|-----|-----|-----|
| Motor 1  | 25  | 26  | 27  | 32  |
| Motor 2  | 13  | 12  | 14  | 33  |
| Motor 3  | 2   | 4   | 5   | 18  |

| USART2 (Serial2 — comunicación con XBee) | Pin |
|-------------------------------------------|-----|
| RX2                                        | 16  |
| TX2                                        | 17  |
| Baudios                                    | 19200 |

---

## Protocolo de comunicación

### STM32 → ESP32 (vía XBee / `Serial2`)

Trama de texto separada por comas, terminada en salto de línea:

```
COMANDO,conteos_por_segundo,conteos_por_minuto
```

Ejemplo: `DATA,12,340`

### ESP32 → PC (vía USB Serial, 115200 baudios)

El ESP32 reenvía los conteos recibidos en el siguiente formato, consumido por la interfaz de Python:

```
DATA_REPORT,conteos_por_segundo,conteos_por_minuto[,estado_placa1,estado_placa2,estado_placa3]
```

### PC → ESP32 (comandos manuales, vía USB Serial)

```
MOTOR<1-3><D|I|H|T>
```

- `D` / `I`: giro de un cuarto de vuelta (horario / antihorario).
- `H` / `T`: giro de un tercio de vuelta (horario / antihorario).

---

## Requisitos

### Firmware (ESP32)

- Arduino IDE o PlatformIO con soporte para ESP32.
- Librerías: `WiFi.h`, `HardwareSerial.h` (incluidas en el core de ESP32).

### Interfaz de Python

- Python 3.9 o superior.
- Dependencias:

```bash
pip install pyserial adafruit-io
```

---

## Instalación y configuración

1. **Cargar el firmware** `esp32_control.ino` en el ESP32 usando Arduino IDE, seleccionando la placa correspondiente y el puerto correcto.
2. **Conectar el hardware**: motores paso a paso a los pines indicados, y módulo XBee receptor a los pines RX2/TX2 del ESP32.
3. **Configurar Adafruit IO**:
   - Crear una cuenta en [io.adafruit.com](https://io.adafruit.com).
   - Crear los tres feeds: `conteos-por-segundo`, `conteos-por-minuto` y `ultimo-comando`.
   - Obtener el `AIO_USERNAME` y el `AIO_KEY` desde **My Key** en el panel de Adafruit IO.
4. **Configurar credenciales en la interfaz de Python**: definir `AIO_USERNAME` y `AIO_KEY` como variables de entorno (recomendado) en lugar de escribirlas directamente en el código fuente (ver sección [Seguridad y buenas prácticas](#seguridad-y-buenas-prácticas)).
5. **Instalar dependencias de Python** (ver sección anterior).
6. **Ejecutar la interfaz**:

```bash
python interfaz_control.py
```

---

## Uso del sistema

1. Al iniciar la aplicación, se muestra una pantalla de selección de modo:
   - **Modo Manual (Control de Motores)**: para pruebas y calibración individual de cada compuerta.
   - **Modo de Detección Nuclear**: para monitoreo en tiempo real del sistema completo.
2. Seleccionar el puerto serial correspondiente al ESP32 y pulsar **Conectar**.
3. En **Modo Manual**, usar los botones de cada motor para probar los giros de cuarto y tercio de vuelta.
4. En **Modo de Detección**, observar en tiempo real los conteos por segundo/minuto y el estado (`ENABLE`/`DISABLE`) de cada placa. Cuando el conteo por minuto supere el umbral configurado en el ESP32 (`conteoreferencia`), la placa 3 se desplegará automáticamente.
5. Los datos se publican automáticamente en el dashboard de Adafruit IO cada 5 segundos.

---

## Integración con Adafruit IO

El dashboard en línea permite visualizar de forma remota:

- Gráficas históricas de conteos por segundo y por minuto.
- El último estado/evento relevante del sistema (conexión, modo activo, cierre de la aplicación).

Se recomienda crear un **dashboard** en Adafruit IO con widgets tipo *line chart* para los feeds de conteos, y un widget de texto para `ultimo-comando`.

---

## Estructura del repositorio

```
.
├── firmware/
│   └── esp32_control.ino      # Firmware del ESP32 (control de motores y recepción USART)
├── interfaz/
│   └── interfaz_control.py    # Interfaz gráfica en Python (Tkinter + Adafruit IO)
└── README.md                  # Este archivo
```

---

## Seguridad y buenas prácticas

> ⚠️ **Importante**: el código fuente original incluye la clave de API de Adafruit IO (`AIO_KEY`) escrita directamente en el archivo. **Antes de subir el proyecto a un repositorio público (GitHub, GitLab, etc.), se debe:**
>
> 1. Revocar y regenerar la clave `AIO_KEY` actual desde el panel de Adafruit IO (**My Key**), ya que quedó expuesta en el código compartido.
> 2. Mover las credenciales (`AIO_USERNAME`, `AIO_KEY`) a variables de entorno o a un archivo de configuración excluido del control de versiones (por ejemplo, un `.env` agregado a `.gitignore`), y cargarlas en `interfaz_control.py` con `os.environ.get(...)`.
> 3. Nunca hacer *commit* de credenciales, tokens o claves de API al historial de Git.

Otras recomendaciones:

- Validar siempre que el puerto serial esté disponible antes de intentar reconectar, para evitar bloqueos de la interfaz.
- Considerar agregar un mecanismo de *timeout*/reintento en la comunicación XBee para tolerar pérdidas de paquetes.

---

## Posibles mejoras futuras

- Registro histórico local (CSV/base de datos) de los conteos, además del envío a Adafruit IO.
- Umbral de referencia (`conteoreferencia`) configurable remotamente desde la interfaz de Python en lugar de estar fijo en el firmware.
- Retroalimentación visual (LED o buzzer) en el ESP32 ante niveles críticos de radiación.
- Autenticación y cifrado en el enlace XBee para escenarios de uso real.
- Sensores de posición (fin de carrera o encoder) en los motores para verificar físicamente que las compuertas alcanzaron la posición esperada.

---

## Autores

*(Completar con los nombres de los integrantes del equipo y la institución/asignatura)*

- Nombre — Rol
- Nombre — Rol

**Asignatura:** Instrumentación Virtual

---

## Licencia

*(Especificar la licencia del proyecto, por ejemplo MIT, o indicar que es un proyecto académico de uso interno)*
