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
               │ текущие данные + компактная история раз в 2 минуты
               ▼
          SQLite (WAL mode)
               │
               ▼
     FastAPI ── /api/current
             ├─ /api/history
             ├─ /api/analytics
             ├─ /api/analytics/period
             ├─ /api/status
             └─ / (панель с графиками)
```

Полный набор разобранных значений хранится в одной перезаписываемой текущей
записи. История содержит только существенные поля для графиков и расчётов с
шагом две минуты; сырые пакеты устройства не сохраняются. Симулятор использует
ту же схему и API, поэтому фронтенд не нужно переключать вручную.

Пять крупных карточек показывают солнечную генерацию, потребление дома,
аккумулятор, сеть и состояние Raspberry Pi. При выборе карточки под ней
открывается соответствующий подробный график. Постоянный раздел истории
переключается между днём, неделей, месяцем и всем временем; длительные периоды
строятся по компактным суточным итогам в SQLite. В шапке отдельно видны номер
последнего кадра, точное время его записи и текущие часы, поэтому остановка
обновлений сразу заметна. В ответе `/api/current` дополнительно доступны
пофазные токи, частота, DC-шина и мощность резервного выхода.

Отдельный системный монитор раз в минуту сохраняет загрузку CPU, load average,
память, температуру, диск, uptime Raspberry Pi и полный физический размер
SQLite вместе с WAL-файлом. API: `/api/system/current` и
`/api/system/history`.

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

Второй терминал (на Mac часть Linux-метрик может быть недоступна):

```bash
.venv/bin/python system_monitor.py
```

Третий терминал:

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
- `FELICITY_HISTORY_INTERVAL_SECONDS` — шаг компактной истории, по умолчанию `120`.

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
Linux. На **Home Assistant OS** используйте приложение из следующего раздела.

## Home Assistant OS

Репозиторий содержит готовое приложение в каталоге
`felicity_dashboard_addon`. Оно использует Home Assistant Ingress, поэтому
панель защищена вашей учётной записью Home Assistant, а прямой HTTP-порт по
умолчанию отключён. База хранится в постоянном `/data` и включается в резервную
копию приложения.

Добавьте в магазине приложений обычный HTTPS URL репозитория:

```text
https://github.com/okiyashko1337/felicity-dashboard
```

В актуальном английском интерфейсе путь выглядит так: **Settings → Apps → App
store → ⋮ → Repositories**. В версиях, где ещё используется прежнее название:
**Settings → Add-ons → Add-on Store → ⋮ → Repositories**.

После добавления репозитория обновите список, установите **Felicity Energy
Dashboard**, проверьте `inverter_host: 192.168.1.135` на вкладке
**Configuration** и запустите приложение. Затем включите **Show in sidebar** и
откройте **Felicity Energy**.

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
