import argparse
import pathlib
import sys

import paramiko

sys.stdout.reconfigure(encoding="utf-8")

HERE = pathlib.Path(__file__).parent
LOG = HERE / "debug-logs" / "deploy.txt"
FILES = ["app.py", "Dockerfile", "docker-compose.yml", "key.txt"]


class Logger:
    def __init__(self):
        LOG.parent.mkdir(exist_ok=True)
        self.f = open(LOG, "w", encoding="utf-8")

    def __call__(self, text=""):
        print(text)
        self.f.write(text + "\n")
        self.f.flush()


log = Logger()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", required=True)
    ap.add_argument("--user", required=True)
    ap.add_argument("--pw", required=True)
    ap.add_argument("mode", choices=["recon", "deploy", "dns", "vv"])
    a = ap.parse_args()

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(a.host, username=a.user, password=a.pw, timeout=15, allow_agent=False, look_for_keys=False)
    except paramiko.ssh_exception.AuthenticationException:
        try:
            transport = ssh.get_transport()
            transport.auth_interactive(a.user, lambda title, instructions, prompts: [a.pw for _ in prompts])
        except Exception as e2:
            log(f"[gagal login] {e2}")
            sys.exit(1)
    except Exception as e:
        log(f"[gagal login] {e}")
        sys.exit(1)
    log(f"[login ok] {a.user}@{a.host}")

    def run(cmd, timeout=600):
        stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
        out = stdout.read().decode("utf-8", "replace")
        err = stderr.read().decode("utf-8", "replace")
        code = stdout.channel.recv_exit_status()
        return code, out, err

    if a.mode == "vv":
        for cmd in [
            "docker inspect voicevox --format '{{json .NetworkSettings.Ports}}'",
            "curl -s -m 5 'http://192.168.101.3:50021/version'",
            "curl -s -m 30 -X POST 'http://192.168.101.3:50021/audio_query?text=hello&speaker=8' | head -c 300",
            "curl -s -m 15 'http://192.168.101.3:50021/speakers' | head -c 300",
        ]:
            code, out, err = run(cmd)
            log(f"--- {cmd[:50]} ---")
            log((out + err).strip() or "(kosong)")
        return

    if a.mode == "dns":
        cfg = "/etc/cloudflared/config.yml"
        tunnel_id = "7daa4019-6cdd-4a52-bc1f-77c12ef5e9a2"
        sudo = f"echo '{a.pw}' | sudo -S"
        code, out, err = run(
            f"{sudo} env TUNNEL_ORIGIN_CERT=/etc/cloudflared/cert.pem cloudflared tunnel route dns {tunnel_id} hana.leticia.my.id",
            timeout=60,
        )
        log(f"[dns route] {(out + err).strip()}")
        code, out, err = run("sleep 2; curl -s -o /dev/null -w '%{http_code}' https://hana.leticia.my.id/")
        log(f"[public check] {out.strip()}")
        return

    if a.mode == "recon":
        for label, cmd in [
            ("os", "uname -a; cat /etc/os-release 2>/dev/null | head -2"),
            ("docker", "docker --version 2>&1; docker compose version 2>&1"),
            ("docker containers", "docker ps --format '{{.Names}}: {{.Image}} ({{.Status}})' 2>&1"),
            ("cloudflared bin", "command -v cloudflared || echo none"),
            ("cloudflared service", "systemctl is-active cloudflared 2>&1; systemctl is-enabled cloudflared 2>&1"),
            ("cloudflared config", "ls /etc/cloudflared 2>&1; cat /etc/cloudflared/config.yml 2>&1"),
            ("cloudflared docker", "docker ps -a --format '{{.Names}}: {{.Image}} {{.Command}}' 2>/dev/null | grep -i cloud || true"),
            ("tunnel token/env", "systemctl cat cloudflared 2>&1 | head -20"),
            ("home", "echo $HOME; ls ~"),
            ("port 8000", "ss -tlnp 2>/dev/null | grep 8000 || echo free"),
        ]:
            code, out, err = run(cmd)
            log(f"--- {label} ---")
            log(out.strip() or "(kosong)")
            if err.strip():
                log(f"[stderr] {err.strip()[:500]}")
        return

    code, out, err = run("docker --version >/dev/null 2>&1 && docker compose version >/dev/null 2>&1 && echo ok")
    if "ok" not in out:
        log("[docker tidak tersedia]")
        log(out + err)
        sys.exit(1)

    sftp = ssh.open_sftp()
    run("mkdir -p ~/kaiwa-renshu")
    for f in FILES:
        sftp.put(str(HERE / f), f"/home/{a.user}/kaiwa-renshu/{f}")
        log(f"[upload] {f}")
    sftp.close()

    log("[build & start]")
    code, out, err = run("cd ~/kaiwa-renshu && docker compose up -d --build 2>&1", timeout=900)
    log(out.strip())
    if code != 0:
        log(f"[gagal, exit {code}]")
        sys.exit(1)

    code, out, err = run("sleep 3; docker ps --format '{{.Names}}: {{.Status}}' | grep kaiwa; curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/")
    log(f"[cek lokal mini-pc] {out.strip()}")

    log("[cloudflared: subdomain hana]")
    cfg = "/etc/cloudflared/config.yml"
    tunnel_id = "7daa4019-6cdd-4a52-bc1f-77c12ef5e9a2"
    sudo = f"echo '{a.pw}' | sudo -S"
    code, out, err = run(f"grep -q 'hana.leticia.my.id' {cfg} && echo ada || echo belum")
    if "belum" in out:
        run(f"{sudo} cp {cfg} {cfg}.bak-hana")
        code, out, err = run(
            f"{sudo} sed -i '/^- service: http_status:404/i - hostname: hana.leticia.my.id\\n  service: http://localhost:8000' {cfg}",
            timeout=60,
        )
        if code != 0:
            log(f"[gagal edit config] {out}{err}")
            sys.exit(1)
        log("[config diedit + backup .bak-hana]")
        code, out, err = run(f"{sudo} systemctl restart cloudflared && sleep 4 && {sudo} systemctl is-active cloudflared", timeout=60)
        log(f"[restart cloudflared] {(out + err).strip()}")
        code, out, err = run(
            f"{sudo} env TUNNEL_ORIGIN_CERT=/etc/cloudflared/cert.pem cloudflared tunnel route dns {tunnel_id} hana.leticia.my.id",
            timeout=60,
        )
        log(f"[dns route] {(out + err).strip()}")
    else:
        log("[hana sudah ada di config, lewati]")

    code, out, err = run("sleep 2; curl -s -o /dev/null -w '%{http_code}' https://hana.leticia.my.id/")
    log(f"[public check] {out.strip()}")


if __name__ == "__main__":
    main()
