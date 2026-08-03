#include <WiFi.h> // Se mantiene por si hay dependencias internas del ESP32, aunque no se use activamente.
#include <HardwareSerial.h> // Para usar Serial2 (USART2)

// --- Variable de referencia para conteos por minuto ---
const int conteoreferencia = 100;

// --- Configuración de USART2 y Serial (USB) ---
#define RX2_PIN 16
#define TX2_PIN 17
const int BAUD_RATE_USART2 = 19200;
const int BAUD_RATE_USB_SERIAL = 115200; // Ligeramente ajustado para compatibilidad en algunos terminales, aunque 115200 es común.

// --- Variables para los conteos y comandos recibidos por USART2 ---
volatile int num1 = 0;
volatile int intnum2 = 0;
String receivedCommand = "CMD aun no recibido";

// --- Buffer para la recepción de datos de USART2 ---
String usart2RxBuffer = "";
const char NEWLINE_CHAR = '\n';
const int MAX_BUFFER_SIZE = 100;

// --- Definiciones para los motores 28BYJ-48 ---
const int IN1_MOTOR1 = 25;
const int IN2_MOTOR1 = 26;
const int IN3_MOTOR1 = 27;
const int IN4_MOTOR1 = 32;

const int IN1_MOTOR2 = 13;
const int IN2_MOTOR2 = 12;
const int IN3_MOTOR2 = 14;
const int IN4_MOTOR2 = 33;

const int IN1_MOTOR3 = 2;
const int IN2_MOTOR3 = 4;
const int IN3_MOTOR3 = 5;
const int IN4_MOTOR3 = 18;

// --- Secuencia de pasos para HALF STEP DRIVE - Mayor Torque y Mayor Precisión ---
// Esta secuencia energiza 1 bobina, luego 2 bobinas, alternando.
// Resulta en mayor torque que Wave Drive y el doble de resolución.
// ¡ATENCIÓN! Esto DUPLICA el número efectivo de pasos por revolución.
byte waveDriveSequence[8][4] = { // ¡Ahora 8 pasos en lugar de 4!
  {HIGH, LOW, LOW, LOW},      // Paso 1: Bobina 1 activa (similar a Wave Drive)
  {HIGH, HIGH, LOW, LOW},     // Paso 2: Bobinas 1 y 2 activas (doble fase)
  {LOW, HIGH, LOW, LOW},      // Paso 3: Bobina 2 activa
  {LOW, HIGH, HIGH, LOW},     // Paso 4: Bobinas 2 y 3 activas
  {LOW, LOW, HIGH, LOW},      // Paso 5: Bobina 3 activa
  {LOW, LOW, HIGH, HIGH},     // Paso 6: Bobinas 3 y 4 activas
  {LOW, LOW, LOW, HIGH},      // Paso 7: Bobina 4 activa
  {HIGH, LOW, LOW, HIGH}      // Paso 8: Bobinas 4 y 1 activas
};

// --- Ajuste para un paso más rápido (ajusta si es necesario para tu aplicación) ---
const int stepDelayMicros = 2000; // 2ms de retardo entre cada paso. Ajusta esto para velocidad.
const long stepDelayMillis = stepDelayMicros / 1000;

// Dado que Half Step tiene el doble de pasos que Wave Drive, el stepsPerRevolution se duplica.
// 4096 pasos era para Wave Drive. Para Half Step, se convierte en 8192 pasos por revolución.
const int stepsPerRevolutionHalfStep = 4096 * 2; // O sea, 8192
const int stepsPerQuarterTurn = stepsPerRevolutionHalfStep / 4;
const int stepsPerThirdTurn = stepsPerRevolutionHalfStep / 3;

// Estructura para agrupar los pines de cada motor y su estado
struct StepperMotor {
  int in1, in2, in3, in4;
  int currentSequenceIndex; // Ahora de 0 a 7 para la secuencia de 8 pasos
};

// Crear instancias de la estructura para cada motor
StepperMotor motor1 = {IN1_MOTOR1, IN2_MOTOR1, IN3_MOTOR1, IN4_MOTOR1, 0};
StepperMotor motor2 = {IN1_MOTOR2, IN2_MOTOR2, IN3_MOTOR2, IN4_MOTOR2, 0};
StepperMotor motor3 = {IN1_MOTOR3, IN2_MOTOR3, IN3_MOTOR3, IN4_MOTOR3, 0};

// --- Variables de estado para el control NO BLOQUEANTE de cada motor ---
bool motor1Moving = false;
int motor1StepsRemaining = 0;
unsigned long motor1LastStepTime = 0;
int motor1Direction = 0;

bool motor2Moving = false;
int motor2StepsRemaining = 0;
unsigned long motor2LastStepTime = 0;
int motor2Direction = 0;

bool motor3Moving = false;
int motor3StepsRemaining = 0;
unsigned long motor3LastStepTime = 0;
int motor3Direction = 0;
// Variable para rastrear si el motor 3 se movió por conteo alto (posición "enable")
bool motor3MovedByHighCount = false;
// Nueva variable para indicar si la placa está en la posición "enable"
bool motor3InEnablePosition = false; // Inicialmente en posición "inicial"

// --- PROTOTIPOS DE FUNCIONES ---
void moveStep(StepperMotor &motor, int direction);
void startMotorTurn(StepperMotor &motor, int motorNum, int steps, int direction);
void startMotorQuarterTurnClockwise(StepperMotor &motor, int motorNum);
void startMotorQuarterTurnCounterClockwise(StepperMotor &motor, int motorNum);
// Nuevos prototipos para los giros de un tercio de vuelta
void startMotorThirdTurnClockwise(StepperMotor &motor, int motorNum);
void startMotorThirdTurnCounterClockwise(StepperMotor &motor, int motorNum);
// Fin nuevos prototipos
void handleSingleMotorMovement(StepperMotor &motor, bool &movingFlag, int &stepsLeft, unsigned long &lastStepT, int &dir, int motorNumber);
void handleSerial2Data();
void handleUsbSerialCommands();


// --- IMPLEMENTACIÓN DE FUNCIONES ---

void moveStep(StepperMotor &motor, int direction) {
  // La secuencia tiene 8 pasos (índices 0 a 7)
  motor.currentSequenceIndex += direction;

  if (motor.currentSequenceIndex >= 8) {
    motor.currentSequenceIndex = 0;
  } else if (motor.currentSequenceIndex < 0) {
    motor.currentSequenceIndex = 7;
  }

  digitalWrite(motor.in1, waveDriveSequence[motor.currentSequenceIndex][0]);
  digitalWrite(motor.in2, waveDriveSequence[motor.currentSequenceIndex][1]);
  digitalWrite(motor.in3, waveDriveSequence[motor.currentSequenceIndex][2]);
  digitalWrite(motor.in4, waveDriveSequence[motor.currentSequenceIndex][3]);
}

void startMotorTurn(StepperMotor &motor, int motorNum, int steps, int direction) {
  Serial.print("Comando: Iniciando giro para Motor "); Serial.print(motorNum);
  Serial.print(" Pasos: "); Serial.print(steps);
  Serial.print(" Dirección: "); Serial.println(direction == 1 ? "Horario" : "Anti-Horario");

  if (motorNum == 1) {
    motor1Moving = true;
    motor1StepsRemaining = steps;
    motor1Direction = direction;
    motor1LastStepTime = millis();
  } else if (motorNum == 2) {
    motor2Moving = true;
    motor2StepsRemaining = steps;
    motor2Direction = direction;
    motor2LastStepTime = millis();
  } else if (motorNum == 3) {
    motor3Moving = true;
    motor3StepsRemaining = steps;
    motor3Direction = direction;
    motor3LastStepTime = millis();
  }
}

void startMotorQuarterTurnClockwise(StepperMotor &motor, int motorNum) {
  startMotorTurn(motor, motorNum, stepsPerQuarterTurn, 1);
}

void startMotorQuarterTurnCounterClockwise(StepperMotor &motor, int motorNum) {
  startMotorTurn(motor, motorNum, stepsPerQuarterTurn, -1);
}

// --- NUEVAS FUNCIONES DE GIRO DE UN TERCIO DE VUELTA ---
void startMotorThirdTurnClockwise(StepperMotor &motor, int motorNum) {
  startMotorTurn(motor, motorNum, stepsPerThirdTurn, 1);
}

void startMotorThirdTurnCounterClockwise(StepperMotor &motor, int motorNum) {
  startMotorTurn(motor, motorNum, stepsPerThirdTurn, -1);
}
// --- FIN NUEVAS FUNCIONES ---

void handleSingleMotorMovement(StepperMotor &motor, bool &movingFlag, int &stepsLeft, unsigned long &lastStepT, int &dir, int motorNumber) {
  if (movingFlag) {
    if (millis() - lastStepT >= stepDelayMillis) {
      moveStep(motor, dir);
      stepsLeft--;
      lastStepT = millis();

      if (stepsLeft <= 0) {
        movingFlag = false;
        // ¡IMPORTANTE! Se eliminaron las líneas que ponían los pines a LOW.
        // Esto permite que el motor mantenga el "torque de retención" en su última posición.
        Serial.print("Motor "); Serial.print(motorNumber); Serial.println(" giro completado.");
      }
    }
  }
}

void handleSerial2Data() {
  if (Serial2.available()) {
    char incomingByte = Serial2.read();

    if (incomingByte == '\n' || incomingByte == '\r') {
      usart2RxBuffer.trim();

      if (usart2RxBuffer.length() > 0) {
        int firstCommaIndex = usart2RxBuffer.indexOf(',');
        int secondCommaIndex = usart2RxBuffer.indexOf(',', firstCommaIndex + 1);

        if (firstCommaIndex != -1 && secondCommaIndex != -1) {
          receivedCommand = usart2RxBuffer.substring(0, firstCommaIndex);
          String num1Str = usart2RxBuffer.substring(firstCommaIndex + 1, secondCommaIndex);
          String num2Str = usart2RxBuffer.substring(secondCommaIndex + 1);

          num1 = num1Str.toInt();
          intnum2 = num2Str.toInt();

          Serial.print("Comando identificado (Serial2): "); Serial.println(receivedCommand);
          Serial.print("Conteos por segundo (Serial2): "); Serial.println(num1);
          Serial.print("Conteos por minuto (Serial2): "); Serial.println(intnum2);

          Serial.println(receivedCommand + "," + String(num1) + "," + String(intnum2));

          // Lógica para mover a la posición "enable"
          if (intnum2 > conteoreferencia) {
            // Solo mover si el motor no está en movimiento y no está ya en la posición "enable"
            if (!motor3Moving && !motor3InEnablePosition) {
              Serial.println("Conteos por minuto (intnum2) es mayor que conteoreferencia. Moviendo motor 3 en sentido ANTI-HORARIO un tercio de vuelta (a posición 'enable').");
              startMotorThirdTurnCounterClockwise(motor3, 3);
              motor3MovedByHighCount = true; // Se mantiene para la lógica de regreso
              motor3InEnablePosition = true; // Establece que la placa está en la posición "enable"
            } else if (motor3InEnablePosition) {
              Serial.println("Motor 3 ya está en la posición 'enable'. No se requiere movimiento.");
            } else {
              Serial.println("Motor 3 ya está en movimiento. Comando de giro por conteo alto ignorado.");
            }
          }
          // Lógica para volver a la posición "inicial"
          else if (intnum2 <= conteoreferencia && motor3MovedByHighCount) {
            // Solo mover si el motor no está en movimiento y está en la posición "enable"
            if (!motor3Moving && motor3InEnablePosition) {
              Serial.println("Conteos por minuto (intnum2) es menor o igual que conteoreferencia. Devolviendo motor 3 en sentido HORARIO un tercio de vuelta (a posición 'inicial').");
              startMotorThirdTurnClockwise(motor3, 3);
              motor3MovedByHighCount = false; // Restablecer para la próxima vez que se supere el conteo
              motor3InEnablePosition = false; // Establece que la placa está de vuelta en la posición "inicial"
            } else if (!motor3InEnablePosition) {
              Serial.println("Motor 3 ya está en la posición 'inicial'. No se requiere movimiento de regreso.");
            } else {
              Serial.println("Motor 3 ya está en movimiento. Comando de devolución por conteo bajo ignorado.");
            }
          }

        } else {
          Serial.println("Formato de comando inválido (Serial2). Se esperaba 'COMANDO,NUM1,NUM2'");
        }
      }
      usart2RxBuffer = "";
    } else {
      if (usart2RxBuffer.length() < MAX_BUFFER_SIZE - 1) {
        usart2RxBuffer += incomingByte;
      } else {
        Serial.println("Buffer USART2 desbordado. Limpiando.");
        usart2RxBuffer = "";
      }
    }
  }
}

void handleUsbSerialCommands() {
  if (Serial.available()) {
    String command = Serial.readStringUntil('\n');
    command.trim();
    command.toUpperCase();

    Serial.print("Comando USB Serial recibido: ");
    Serial.println(command);

    if (command.startsWith("MOTOR")) {
      char motorNumChar = command.charAt(5); // Carácter que indica el número de motor (1, 2, 3)
      char actionChar = command.charAt(6);   // Carácter que indica la acción (I, D, H, T)

      int motorNumber = motorNumChar - '0'; // Convierte el carácter a entero

      // Verifica si es un comando para cuarto de vuelta (I o D)
      if ((motorNumber >= 1 && motorNumber <= 3) && (actionChar == 'I' || actionChar == 'D')) {
        if ((motorNumber == 1 && motor1Moving) ||
            (motorNumber == 2 && motor2Moving) ||
            (motorNumber == 3 && motor3Moving)) {
            Serial.print("Error: Motor "); Serial.print(motorNumber); Serial.println(" ya está en movimiento. Comando ignorado.");
            return;
        }

        StepperMotor *targetMotor;
        switch (motorNumber) {
          case 1: targetMotor = &motor1; break;
          case 2: targetMotor = &motor2; break;
          case 3: targetMotor = &motor3; break;
          default: targetMotor = nullptr; break;
        }

        if (targetMotor != nullptr) {
          if (actionChar == 'D') { // Giro de un cuarto de vuelta horario
            startMotorQuarterTurnClockwise(*targetMotor, motorNumber);
          } else { // actionChar == 'I' (Giro de un cuarto de vuelta anti-horario)
            startMotorQuarterTurnCounterClockwise(*targetMotor, motorNumber);
          }
          receivedCommand = command; // Actualiza receivedCommand para comandos USB
        }
      }
      // *** INICIO: NUEVAS LÍNEAS DE CÓDIGO PARA TERCIO DE VUELTA ***
      // Verifica si es un comando para tercio de vuelta (H o T)
      else if ((motorNumber >= 1 && motorNumber <= 3) && (actionChar == 'H' || actionChar == 'T')) {
        if ((motorNumber == 1 && motor1Moving) ||
            (motorNumber == 2 && motor2Moving) ||
            (motorNumber == 3 && motor3Moving)) {
            Serial.print("Error: Motor "); Serial.print(motorNumber); Serial.println(" ya está en movimiento. Comando ignorado.");
            return;
        }

        StepperMotor *targetMotor;
        switch (motorNumber) {
          case 1: targetMotor = &motor1; break;
          case 2: targetMotor = &motor2; break;
          case 3: targetMotor = &motor3; break;
          default: targetMotor = nullptr; break;
        }

        if (targetMotor != nullptr) {
          if (actionChar == 'H') { // Giro de un tercio de vuelta horario
            startMotorThirdTurnClockwise(*targetMotor, motorNumber);
          } else { // actionChar == 'T' (Giro de un tercio de vuelta anti-horario)
            startMotorThirdTurnCounterClockwise(*targetMotor, motorNumber);
          }
          receivedCommand = command; // Actualiza receivedCommand para comandos USB
        }
      }
      // *** FIN: NUEVAS LÍNEAS DE CÓDIGO PARA TERCIO DE VUELTA ***
      else {
        Serial.println("Comando de motor inválido (USB). Formato esperado: MOTOR#I/D (cuarto de vuelta) o MOTOR#H/T (tercio de vuelta)");
      }
    } else {
      Serial.println("Comando USB Serial no reconocido o no es un comando de motor. Ignorado.");
    }
  }
}


// --- SETUP Y LOOP PRINCIPALES ---

void setup() {
  Serial.begin(BAUD_RATE_USB_SERIAL);
  Serial.println("\n--- ESP32 Iniciando ---");

  Serial2.begin(BAUD_RATE_USART2, SERIAL_8N1, RX2_PIN, TX2_PIN);
  Serial.print("USART2 iniciado en RX:"); Serial.print(RX2_PIN); Serial.print(" TX:"); Serial.print(TX2_PIN); Serial.print(" a "); Serial.print(BAUD_RATE_USART2); Serial.println(" baudios.");
  Serial.println("Esperando datos de 'COMANDO,NUM1,NUM2' en Serial2...");

  pinMode(motor1.in1, OUTPUT); pinMode(motor1.in2, OUTPUT); pinMode(motor1.in3, OUTPUT); pinMode(motor1.in4, OUTPUT);
  // No es estrictamente necesario ponerlos en LOW aquí si el motor va a moverse inmediatamente,
  // pero ayuda a asegurar un estado conocido al inicio.
  digitalWrite(motor1.in1, LOW); digitalWrite(motor1.in2, LOW); digitalWrite(motor1.in3, LOW); digitalWrite(motor1.in4, LOW);

  pinMode(motor2.in1, OUTPUT); pinMode(motor2.in2, OUTPUT); pinMode(motor2.in3, OUTPUT); pinMode(motor2.in4, OUTPUT);
  digitalWrite(motor2.in1, LOW); digitalWrite(motor2.in2, LOW); digitalWrite(motor2.in3, LOW); digitalWrite(motor2.in4, LOW);

  pinMode(motor3.in1, OUTPUT); pinMode(motor3.in2, OUTPUT); pinMode(motor3.in3, OUTPUT); pinMode(motor3.in4, OUTPUT);
  digitalWrite(motor3.in1, LOW); digitalWrite(motor3.in2, LOW); digitalWrite(motor3.in3, LOW); digitalWrite(motor3.in4, LOW);

  Serial.println("--- Control de 3 Motores 28BYJ-48 (Half Step Drive - Mayor Torque y Precisión) ---");
  Serial.println("Comandos para motores (USB):");
  Serial.println("    Cuarto de vuelta:");
  Serial.println("        MOTOR#D    -> Horario (e.g., MOTOR1D)");
  Serial.println("        MOTOR#I    -> Anti-horario (e.g., MOTOR2I)");
  Serial.println("    Tercio de vuelta:");
  Serial.println("        MOTOR#H    -> Horario (e.g., MOTOR3H)");
  Serial.println("        MOTOR#T    -> Anti-horario (e.g., MOTOR1T)");
  Serial.println("------------------------------------------------------------------");
}

void loop() {
  handleSerial2Data();
  handleUsbSerialCommands();

  // Las funciones handleSingleMotorMovement ahora mantienen el torque de retención
  // al no apagar los pines después de cada movimiento.
  handleSingleMotorMovement(motor1, motor1Moving, motor1StepsRemaining, motor1LastStepTime, motor1Direction, 1);
  handleSingleMotorMovement(motor2, motor2Moving, motor2StepsRemaining, motor2LastStepTime, motor2Direction, 2);
  handleSingleMotorMovement(motor3, motor3Moving, motor3StepsRemaining, motor3LastStepTime, motor3Direction, 3);

  delay(1);
}