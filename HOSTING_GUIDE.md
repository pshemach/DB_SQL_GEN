# Hosting Guide on Linux

Host both apps with `systemd` so they keep running after SSH logout and restart on failure or server reboot.

| App | File | Port | URL |
|---|---|---|---|
| Streamlit UI | `app.py` | `8582` | `http://SERVER_IP:8582` |
| FastAPI + web UI | `api.py` | `8588` | `http://SERVER_IP:8588` |

FastAPI also serves:

- API docs: `http://SERVER_IP:8588/docs`
- Web UI: `http://SERVER_IP:8588/app`
- Health: `http://SERVER_IP:8588/health`

Project path:

```bash
/root/Desktop/ML-Projects/DB_SQL_GEN
```

Virtual environment:

```bash
/root/Desktop/ML-Projects/DB_SQL_GEN/.venv
```

---

## 1. Test Both Apps Manually First

```bash
cd /root/Desktop/ML-Projects/DB_SQL_GEN
source .venv/bin/activate
```

Streamlit UI:

```bash
streamlit run app.py --server.port 8582 --server.address 0.0.0.0 --server.headless true
```

FastAPI (in a second SSH session):

```bash
cd /root/Desktop/ML-Projects/DB_SQL_GEN
source .venv/bin/activate
uvicorn src.api:app --host 0.0.0.0 --port 8588
```

If `uvicorn` is missing:

```bash
pip install uvicorn
```

Stop each process with `Ctrl + C` before installing systemd services.

---

## 2. Install systemd Services

From the project folder:

```bash
cd /root/Desktop/ML-Projects/DB_SQL_GEN

sudo cp deploy/textsql-streamlit.service /etc/systemd/system/textsql-streamlit.service
sudo cp deploy/textsql-api.service /etc/systemd/system/textsql-api.service

sudo systemctl daemon-reload
sudo systemctl enable --now textsql-streamlit textsql-api
sudo systemctl status textsql-streamlit textsql-api --no-pager
```

If you previously created the Streamlit unit by hand, copying the file from `deploy/` replaces it with the same port and command.

---

## 3. Open Firewall Ports

If UFW is enabled:

```bash
sudo ufw allow 8582/tcp
sudo ufw allow 8588/tcp
sudo ufw reload
sudo ufw status
```

If UFW is inactive, no firewall change is required at OS level.

---

## 4. Check Ports

```bash
sudo ss -tulpn | grep -E '8582|8588'
```

Expected:

```text
0.0.0.0:8582
0.0.0.0:8588
```

---

## 5. Logs

Live logs:

```bash
journalctl -u textsql-streamlit -u textsql-api -f
```

Recent logs:

```bash
journalctl -u textsql-streamlit -n 100 --no-pager
journalctl -u textsql-api -n 100 --no-pager
```

---

## 6. Common Commands

Restart both after a code update:

```bash
sudo systemctl restart textsql-streamlit textsql-api
```

Restart one app:

```bash
sudo systemctl restart textsql-streamlit
sudo systemctl restart textsql-api
```

Stop / start:

```bash
sudo systemctl stop textsql-streamlit textsql-api
sudo systemctl start textsql-streamlit textsql-api
```

Status:

```bash
sudo systemctl status textsql-streamlit textsql-api --no-pager
```

Disable auto-start:

```bash
sudo systemctl disable textsql-streamlit textsql-api
```

---

## 7. Update Code on the Server

```bash
cd /root/Desktop/ML-Projects/DB_SQL_GEN
git fetch origin
git pull origin dev
sudo systemctl restart textsql-streamlit textsql-api
sudo systemctl status textsql-streamlit textsql-api --no-pager
```

If the server has local edits you want to throw away:

```bash
cd /root/Desktop/ML-Projects/DB_SQL_GEN
git fetch origin
git reset --hard origin/dev
git clean -fd
sudo systemctl restart textsql-streamlit textsql-api
```

---

## 8. If a Service Keeps Restarting

Status will show `activating (auto-restart)` or `status=1/FAILURE`.

```bash
journalctl -u textsql-streamlit -u textsql-api -f
```

Common causes:

1. Wrong virtual environment path
2. Streamlit or uvicorn missing from `.venv`
3. Port already in use
4. Missing Python package
5. `.env` missing from the project directory
6. Database not reachable

Check binaries:

```bash
ls -la /root/Desktop/ML-Projects/DB_SQL_GEN/.venv/bin/streamlit
ls -la /root/Desktop/ML-Projects/DB_SQL_GEN/.venv/bin/uvicorn
```

Install if missing:

```bash
cd /root/Desktop/ML-Projects/DB_SQL_GEN
source .venv/bin/activate
pip install streamlit uvicorn
```

Check ports:

```bash
sudo ss -tulpn | grep -E '8582|8588'
```

---

## 9. Change a Port Later

Edit the unit, then reload:

```bash
sudo nano /etc/systemd/system/textsql-streamlit.service
sudo nano /etc/systemd/system/textsql-api.service
sudo systemctl daemon-reload
sudo systemctl restart textsql-streamlit textsql-api
```

Streamlit port is `--server.port 8582`. API port is `--port 8588`.

---

## 10. Notes

- `Restart=on-failure` restarts a service only if it crashes.
- Both apps keep running after SSH logout.
- Both start on reboot after `systemctl enable`.
- Keep `.env` in `/root/Desktop/ML-Projects/DB_SQL_GEN`. systemd uses that working directory, and settings load `.env` from there.
