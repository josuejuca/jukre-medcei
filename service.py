# service.py
# Serviço Windows que faz ping e update DDNS periodicamente.
# Requer: pywin32, requests
# Instalação:  py service.py install
# Start/Stop:  py service.py start | stop

import win32serviceutil
import win32service
import win32event
import servicemanager
import socket
import time
import json
import os
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime, timezone
import requests

BASE_DIR = r"C:\jukre"
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
LOG_PATH = os.path.join(BASE_DIR, "log.txt")
PING_URL = "https://api.juk.re/ping"
UPDATE_URL_TPL = "https://api.juk.re/v2/ddns/update?token={token}"

SERVICE_NAME = "JukreDDNS"
SERVICE_DISPLAY_NAME = "Juk.RE DDNS"
SERVICE_DESC = "Serviço que verifica conectividade da API Juk.RE e atualiza o DDNS periodicamente."

# Garante a pasta
os.makedirs(BASE_DIR, exist_ok=True)

# --- logging simples + rotativo (1 linha JSON por evento)
logger = logging.getLogger("jukre")
logger.setLevel(logging.INFO)
handler = RotatingFileHandler(LOG_PATH, maxBytes=512_000, backupCount=3, encoding="utf-8")
formatter = logging.Formatter("%(message)s")
handler.setFormatter(formatter)
if not logger.handlers:
    logger.addHandler(handler)

def now_iso():
    return datetime.now(timezone.utc).isoformat()

def read_config():
    # valores padrão
    cfg = {"token-update": "", "interval_seconds": 300}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            user_cfg = json.load(f)
            if isinstance(user_cfg, dict):
                cfg.update(user_cfg)
    except FileNotFoundError:
        # cria arquivo base se não existir
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.info(json.dumps({
            "ts": now_iso(),
            "type": "error",
            "stage": "read_config",
            "error": str(e)
        }, ensure_ascii=False))
    return cfg

def log_json(obj):
    logger.info(json.dumps(obj, ensure_ascii=False))

def safe_get(url, timeout=10):
    try:
        r = requests.get(url, timeout=timeout, headers={"accept": "application/json"})
        return r.status_code, r.text, r
    except Exception as e:
        return None, str(e), None

class JukreService(win32serviceutil.ServiceFramework):
    _svc_name_ = SERVICE_NAME
    _svc_display_name_ = SERVICE_DISPLAY_NAME
    _svc_description_ = SERVICE_DESC

    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)
        socket.setdefaulttimeout(30)
        self.hWaitStop = win32event.CreateEvent(None, 0, 0, None)
        self.stop_requested = False

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        # LOGA parada do serviço (para uptime)
        log_json({"ts": now_iso(), "type": "service_stop"})
        self.stop_requested = True
        win32event.SetEvent(self.hWaitStop)

    def SvcDoRun(self):
        # LOGA início do serviço (para uptime)
        log_json({"ts": now_iso(), "type": "service_start"})
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STARTED,
            (self._svc_name_, "started")
        )
        self.main()

    def main(self):
        while not self.stop_requested:
            cfg = read_config()
            interval = cfg.get("interval_seconds", 300) or 300

            # 1) ping na API
            sc, body, resp = safe_get(PING_URL)
            ping_payload = {
                "ts": now_iso(),
                "type": "ping",
                "ok": None,
                "status_code": sc,
                "raw": None,
                "parsed": None
            }
            if sc:
                ping_payload["raw"] = body
                try:
                    parsed = resp.json()
                except Exception:
                    parsed = None
                ping_payload["parsed"] = parsed
                ping_payload["ok"] = (sc == 200 and bool(parsed and parsed.get("ok")))
            else:
                ping_payload["ok"] = False
                ping_payload["raw"] = body
            log_json(ping_payload)

            # 2) se token definido, tenta update
            token = (cfg.get("token-update") or "").strip()
            if token:
                url = UPDATE_URL_TPL.format(token=token)
                sc2, body2, resp2 = safe_get(url)
                update_payload = {
                    "ts": now_iso(),
                    "type": "update",
                    "status_code": sc2,
                    "raw": body2,
                    "parsed": None,
                    "ok": False
                }
                if sc2:
                    try:
                        parsed2 = resp2.json()
                    except Exception:
                        parsed2 = None
                    update_payload["parsed"] = parsed2
                    # se retornou o objeto esperado sem "detail" de erro, consideramos ok
                    if sc2 == 200 and parsed2 and "detail" not in parsed2:
                        update_payload["ok"] = True
                log_json(update_payload)
            else:
                log_json({
                    "ts": now_iso(),
                    "type": "update",
                    "ok": False,
                    "reason": "token-update ausente no config.json"
                })

            # espera com possibilidade de parada imediata
            rc = win32event.WaitForSingleObject(self.hWaitStop, int(interval * 1000))
            if rc == win32event.WAIT_OBJECT_0:
                break


if __name__ == "__main__":
    win32serviceutil.HandleCommandLine(JukreService)
