# Felicity Dashboard

Локальная панель для гибридного инвертора Felicity IVGM. Текущая версия
получает данные от штатного Wi-Fi-модуля по локальному TCP-протоколу, потому
что RS-485-порт конкретной установки не отвечает на Modbus-запросы.

## Как это устроено

```text
Felicity Wi-Fi module (TCP 53970)
               │ read-only запрос каждые 2 секунды
               ▼
        collector.py + parser
               │ сырые и нормализованные данные
               ▼
          SQLite (WAL mode)
               │
               ▼
     FastAPI ── /api/current
             ├─ /api/history
             ├─ /api/status
             └─ / (панель с графиками)
```

В одной записи хранятся и исходные пакеты устройства, и разобранные значения.
Симулятор пишет в ту же таблицу и использует тот же API, поэтому фронтенд не
нужно переключать вручную.

Панель строит историю общей мощности, PV1/PV2, напряжений MPPT, SOC и
напряжения аккумулятора, трёх фаз сети, нагрузки по фазам, температур, токов
обоих BMS и разброса напряжения ячеек. В ответе `/api/current` дополнительно
доступны пофазные токи, частота, DC-шина, мощность резервного выхода и полный
сырой пакет устройства в поле `raw`.

## Первый запуск на Mac

В каталоге проекта:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Проверка одного живого чтения и записи в базу:

```bash
.venv/bin/python collector.py --host 192.168.1.135 --once
```

Затем запустите два процесса. Первый терминал:

```bash
FELICITY_HOST=192.168.1.135 .venv/bin/python collector.py
```

Второй терминал:

```bash
.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
```

Откройте [http://127.0.0.1:8000](http://127.0.0.1:8000). API доступен по
адресам `/api/current`, `/api/history?limit=180` и `/api/status`.

Настройки можно задать переменными окружения:

- `FELICITY_HOST` — IP Wi-Fi-модуля, по умолчанию `192.168.1.135`;
- `FELICITY_PORT` — локальный порт, по умолчанию `53970`;
- `FELICITY_POLL_INTERVAL_SECONDS` — период опроса, по умолчанию `2`;
- `FELICITY_DB_PATH` — путь к SQLite, по умолчанию `data/felicity.db`.

## Режим симуляции

Симулятор не подключается к инвертору:

```bash
.venv/bin/python simulator.py
```

Для единственного тестового снимка:

```bash
.venv/bin/python simulator.py --once
```

После этого веб-сервер запускается той же командой `uvicorn main:app`.

## Raspberry Pi OS / обычный Linux

Пример установки в `/opt`:

```bash
sudo mkdir -p /opt/felicity-dashboard
sudo cp -R . /opt/felicity-dashboard
sudo chown -R pi:pi /opt/felicity-dashboard
cd /opt/felicity-dashboard
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp felicity.env.example felicity.env
```

Укажите правильный IP в `felicity.env`, затем скопируйте service-файлы из
`systemd/` в `/etc/systemd/system/` и включите их:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now felicity-collector felicity-web
```

Важно: эти unit-файлы предназначены для Raspberry Pi OS и другого обычного
Linux. На **Home Assistant OS** нет обычной установки systemd/venv; проект
нужно упаковать как локальный Home Assistant add-on. Это следующий отдельный
этап.

## Старый Modbus-вариант

Экспериментальный RS-485-сборщик сохранён в `modbus_collector.py`, а сканер
регистров — в `scan_registers.py`. Они не используются веб-панелью по
умолчанию.

## Безопасность

TCP-порт `53970` не имеет прикладной авторизации. Не пробрасывайте его на
роутере и не публикуйте в интернет. Для будущего доступа из iOS безопаснее
использовать VPN или авторизованный HTTPS-шлюз, не прямой доступ к модулю.

## Проверки

```bash
.venv/bin/python -m unittest discover -s tests -v
```
