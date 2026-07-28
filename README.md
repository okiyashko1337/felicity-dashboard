# Felicity Dashboard

Локальный монитор инвертора для Raspberry Pi 5.

## Архитектура

```text
Felicity inverter ──RS-485/Modbus RTU──> collector.py
                                             │
                                      запись каждые 2 с
                                             ▼
                                      SQLite (WAL mode)
                                             │
                                       чтение последней
                                             ▼
Browser <── / и /api/current ── FastAPI (app.py)
```

`collector.py` и `app.py` запускаются как отдельные процессы. Только сборщик
открывает `/dev/ttyUSB0`. Время записывается в UTC в формате ISO 8601.

## Установка на Raspberry Pi

```bash
sudo mkdir -p /opt/felicity-dashboard
sudo cp -R . /opt/felicity-dashboard
sudo chown -R pi:pi /opt/felicity-dashboard
cd /opt/felicity-dashboard
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
sudo usermod -aG dialout pi
```

После добавления пользователя в `dialout` требуется выйти из системы и войти
снова (или перезагрузить Raspberry Pi).

## Тестовый запуск

В первом терминале:

```bash
.venv/bin/python collector.py
```

Во втором терминале:

```bash
.venv/bin/uvicorn app:app --host 0.0.0.0 --port 8000
```

Откройте `http://IP-АДРЕС-RASPBERRY:8000`. Документация API доступна по
`http://IP-АДРЕС-RASPBERRY:8000/docs`.

Пример ответа:

```json
{
  "id": 42,
  "timestamp": "2026-07-28T12:34:56.123456+00:00",
  "start_address": 0,
  "registers": [230, 50, 0, 127, 18, 0, 0, 1, 65535, 24]
}
```

## Автозапуск

Скопируйте оба файла из каталога `systemd` в `/etc/systemd/system/`, затем:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now felicity-collector felicity-web
```

Если имя пользователя не `pi`, измените строку `User=` в обоих service-файлах.

