# Avisador de juegos PS1

Busca anuncios nuevos de juegos y lotes de PlayStation 1 en Vinted y Wallapop y envía avisos por Telegram cada 30 minutos.

## Configuración en GitHub

1. Crea un repositorio **público** nuevo y sube todos estos archivos. No subas nunca el token dentro de un archivo.
2. En el repositorio abre **Settings → Secrets and variables → Actions**.
3. Pulsa **New repository secret** y crea `TELEGRAM_BOT_TOKEN` con el token entregado por BotFather.
4. Abre la pestaña **Actions**, selecciona **Vigilar juegos PS1** y pulsa **Run workflow**.
5. La primera ejecución detectará automáticamente el chat al que enviaste `/start` y recibirás la confirmación en Telegram.

`TELEGRAM_CHAT_ID` es opcional. Solo hace falta configurarlo si el bot se usa en varios chats.

## Comportamiento

- La primera ejecución registra los resultados existentes y no envía decenas de mensajes antiguos.
- Las ejecuciones posteriores notifican únicamente identificadores nuevos.
- El estado se conserva en `state.json` mediante commits automáticos.
- GitHub puede retrasar unos minutos las tareas programadas cuando hay mucha carga.

## Seguridad

El token vive únicamente en GitHub Actions Secrets. Si se filtra, revócalo inmediatamente desde BotFather y crea otro.
