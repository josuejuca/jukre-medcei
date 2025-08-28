# juk.py
# CLI para controlar o serviço e exibir status amigável (com cores e validação de token).
# Requer: pywin32, requests, colorama
#
# Exemplos:
#   juk -c status
#   juk -c start
#   juk -c stop
#   juk -c restart

import argparse
import os
import json
from datetime import datetime, timezone, timedelta
import win32serviceutil
import win32service
import requests
from colorama import init as color_init, Fore, Style

BASE_DIR = r"C:\jukre"
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
LOG_PATH = os.path.join(BASE_DIR, "log.txt")
SERVICE_NAME = "JukreDDNS"
PING_URL = "https://api.juk.re/ping"
UPDATE_URL_TPL = "https://api.juk.re/v2/ddns/update?token={token}"

color_init()

def load_config():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def last_json_lines(types=None, limit=50000):
    """
    Vasculha o final do log e retorna o último registro por tipo desejado.
    types: set/list de tipos (ex.: {"update","ping","service_start"})
    """
    if not os.path.exists(LOG_PATH):
        return {}
    res = {}
    try:
        with open(LOG_PATH, "r", encoding="utf-8") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            take = min(size, limit)
            f.seek(size - take if size > take else 0)
            chunk = f.read().splitlines()
    except Exception:
        return {}

    for line in reversed(chunk):
        try:
            obj = json.loads(line)
        except Exception:
            continue
        t = obj.get("type")
        if types is None or t in types:
            if t not in res:
                res[t] = obj
        if types and all(tt in res for tt in types):
            break
    return res

def human_ts(iso):
    try:
        # converte para UTC-3 (Brasília)
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        br_tz = timezone(timedelta(hours=-3))
        dt_br = dt.astimezone(br_tz)
        return dt_br.strftime("%d/%m/%Y %H:%M:%S")
    except Exception:
        return iso

def get_service_running():
    try:
        st = win32serviceutil.QueryServiceStatus(SERVICE_NAME)
        # índice 1 = currentState
        return st[1] == win32service.SERVICE_RUNNING, st[1]
    except Exception:
        return False, None

def print_status():
    cfg = load_config()
    token = (cfg.get("token-update") or "").strip()

    print("JUK.RE DDNS")
    if not token:
        print('Status: "API Key não definida, edite o arquivo de configuração"')
    else:
        print("Status: Token configurado ✓")

    # PING online/offline
    online = False
    try:
        r = requests.get(PING_URL, timeout=10, headers={"accept": "application/json"})
        data = r.json() if r.status_code == 200 else {}
        online = bool(data.get("ok"))
        ip = data.get("client_ip")
        lat = data.get("latency_ms")
        ver = data.get("version")
        when = data.get("time")
    except Exception:
        data = {}
        ip = lat = ver = when = None

    if online:
        print(f"{Fore.GREEN}Serviço Juk.RE Online{Style.RESET_ALL}")
    else:
        print(f"{Fore.RED}Serviço Juk.RE Offline{Style.RESET_ALL}")

    # extras do ping
    if data:
        if ip:
            print(f"Seu IP público (da API): {ip}")
        if ver:
            print(f"Versão API: {ver}")
        if lat is not None:
            print(f"Latência informada: {lat} ms")
        if when:
            print(f"Relógio API: {when}")

    # Estado do serviço e uptime
    running, raw_state = get_service_running()
    print(f"Serviço Windows: {'Em execução' if running else 'Parado'}")

    latest = last_json_lines(types={"update", "ping", "service_start"})
    if running and "service_start" in latest:
        started_iso = latest["service_start"].get("ts")
        if started_iso:
            try:
                now = datetime.now(timezone.utc)
                started = datetime.fromisoformat(started_iso)
                delta = now - started
                hours, rem = divmod(int(delta.total_seconds()), 3600)
                mins, secs = divmod(rem, 60)
                print(f"Uptime: {hours}h {mins}m {secs}s (desde {human_ts(started_iso)})")
            except Exception:
                pass

    # Validação do token (faz uma chamada de update que não altera IP se já estiver igual)
    if token:
        try:
            url = UPDATE_URL_TPL.format(token=token)
            r2 = requests.get(url, timeout=10, headers={"accept": "application/json"})
            ok = False
            detail = None
            fqdn = ipv4 = None
            if r2.status_code == 200:
                j = r2.json()
                detail = j.get("detail")
                fqdn = j.get("fqdn")
                ipv4 = j.get("ipv4")
                ok = detail is None  # se não veio "detail", token/host estão válidos
            else:
                try:
                    j = r2.json()
                    detail = j.get("detail")
                except Exception:
                    detail = f"HTTP {r2.status_code}"
            if ok:
                print(f"{Fore.GREEN}Token OK{Style.RESET_ALL} — FQDN: {fqdn}  IPv4: {ipv4}")
            else:
                print(f"{Fore.RED}Token inválido{Style.RESET_ALL}" + (f" — {detail}" if detail else ""))
        except Exception as e:
            print(f"{Fore.RED}Falha ao validar token:{Style.RESET_ALL} {e}")

    # Última atualização registrada pelo serviço (do log)
    upd = latest.get("update")
    if upd:
        parsed = upd.get("parsed") or {}
        fqdn = parsed.get("fqdn")
        updated = upd.get("ok")
        ipv4 = parsed.get("ipv4")
        detail = parsed.get("detail") or (upd.get("raw") if isinstance(upd.get("raw"), str) and "Host/token" in upd.get("raw") else None)
        tss = human_ts(upd.get("ts", ""))
        print("\nÚltima atualização DDNS registrada pelo serviço:")
        print(f"  Momento: {tss}")
        if fqdn:
            print(f"  FQDN: {fqdn}")
        if ipv4:
            print(f"  IPv4: {ipv4}")
        if detail:
            print(f"  Erro: {detail}")
        else:
            print(f"  Sucesso: {'sim' if updated else 'não'}")
    else:
        print("\nAinda não há atualização DDNS registrada no log.")

def main():
    parser = argparse.ArgumentParser(prog="juk", description="CLI para o serviço Juk.RE DDNS")
    parser.add_argument("-c", "--command", required=True, choices=["start", "status", "restart", "stop"],
                        help="Comando: start | status | restart | stop")
    args = parser.parse_args()

    cmd = args.command

    if cmd == "status":
        print_status()
        return

    # comandos de serviço (precisa PowerShell/Admin)
    try:
        if cmd == "start":
            win32serviceutil.StartService(SERVICE_NAME)
            print("Iniciando serviço...")
        elif cmd == "stop":
            win32serviceutil.StopService(SERVICE_NAME)
            print("Parando serviço...")
        elif cmd == "restart":
            try:
                win32serviceutil.RestartService(SERVICE_NAME)
            except Exception:
                # fallback: stop+start
                try:
                    win32serviceutil.StopService(SERVICE_NAME)
                except Exception:
                    pass
                win32serviceutil.StartService(SERVICE_NAME)
            print("Reiniciando serviço...")
    except win32service.error as e:
        print(f"Erro ao executar '{cmd}': {e}")
        print("Certifique-se de instalar o serviço e executar como Administrador:")
        print("  python service.py install")
        print("  python service.py start")
    except Exception as e:
        print(f"Erro: {e}")

if __name__ == "__main__":
    main()
