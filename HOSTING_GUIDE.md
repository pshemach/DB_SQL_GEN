# Streamlit Hosting Guide on Linux

This guide explains how to host the Text-to-SQL Streamlit app on a Linux server using `systemd`, so the app continues running after SSH logout and restarts automatically on failure/server reboot.

## 1. Project Details

Current project path:

```bash
/root/Desktop/ML-Projects/DB_SQL_GEN
```

Streamlit app file:

```bash
app.py
```

Virtual environment:

```bash
/root/Desktop/ML-Projects/DB_SQL_GEN/.venv
```

Application port:

```bash
8582
```

Access URL:

```text
http://SERVER_IP:8582
```

---

## 2. Test Streamlit Manually First

Go to the project directory:

```bash
cd /root/Desktop/ML-Projects/DB_SQL_GEN
```

Activate the virtual environment:

```bash
source .venv/bin/activate
```

Run Streamlit manually:

```bash
streamlit run app.py --server.port 8582 --server.address 0.0.0.0 --server.headless true
```

Open in browser:

```text
http://SERVER_IP:8582
```

Stop manual execution with:

```bash
Ctrl + C
```

---

## 3. Create systemd Service

Create the service file:

```bash
sudo nano /etc/systemd/system/textsql-streamlit.service
```

Add the following content:

```ini
[Unit]
Description=Text-to-SQL Streamlit App
After=network.target

[Service]
WorkingDirectory=/root/Desktop/ML-Projects/DB_SQL_GEN
ExecStart=/root/Desktop/ML-Projects/DB_SQL_GEN/.venv/bin/streamlit run app.py --server.port 8582 --server.address 0.0.0.0 --server.headless true
Restart=on-failure
RestartSec=10
User=root
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

Save and exit.

---

## 4. Start and Enable the Service

Reload systemd:

```bash
sudo systemctl daemon-reload
```

Start the service:

```bash
sudo systemctl start textsql-streamlit
```

Enable service on server startup:

```bash
sudo systemctl enable textsql-streamlit
```

Check service status:

```bash
sudo systemctl status textsql-streamlit
```

---

## 5. Check Logs

To view live logs:

```bash
journalctl -u textsql-streamlit -f
```

To view recent logs:

```bash
journalctl -u textsql-streamlit -n 100
```

---

## 6. Check Port

Check if Streamlit is listening on port `8582`:

```bash
sudo ss -tulpn | grep 8582
```

Expected result should show a process listening on:

```text
0.0.0.0:8582
```

---

## 7. Open Firewall Port

If firewall is enabled, allow port `8582`.

For Ubuntu with UFW:

```bash
sudo ufw allow 8582/tcp
sudo ufw reload
```

Check UFW status:

```bash
sudo ufw status
```

If UFW is inactive, no firewall change is required at OS level.

---

## 8. Common Commands

Restart the Streamlit app:

```bash
sudo systemctl restart textsql-streamlit
```

Stop the app:

```bash
sudo systemctl stop textsql-streamlit
```

Start the app:

```bash
sudo systemctl start textsql-streamlit
```

Disable auto-start:

```bash
sudo systemctl disable textsql-streamlit
```

View status:

```bash
sudo systemctl status textsql-streamlit
```

---

## 9. If the Service Keeps Restarting

If status shows:

```text
Active: activating (auto-restart)
```

or:

```text
status=1/FAILURE
```

Check logs:

```bash
journalctl -u textsql-streamlit -f
```

Common causes:

1. Wrong virtual environment path
2. Streamlit not installed in `.venv`
3. Wrong app file name
4. Port already in use
5. Missing Python package
6. Environment/config file not found

Check whether Streamlit exists:

```bash
ls -la /root/Desktop/ML-Projects/DB_SQL_GEN/.venv/bin/streamlit
```

If missing, install Streamlit:

```bash
cd /root/Desktop/ML-Projects/DB_SQL_GEN
source .venv/bin/activate
pip install streamlit
```

Check if port is already used:

```bash
sudo ss -tulpn | grep 8582
```

---

## 10. Change Port Later

Edit service file:

```bash
sudo nano /etc/systemd/system/textsql-streamlit.service
```

Change this part:

```ini
--server.port 8582
```

Then reload and restart:

```bash
sudo systemctl daemon-reload
sudo systemctl restart textsql-streamlit
```

---

## 11. Notes

`Restart=on-failure` means the service restarts only if the app crashes or exits with failure.

It will not restart repeatedly if the app is running normally.

The app will continue running after SSH logout.

The app will start automatically after server reboot because this command was used:

```bash
sudo systemctl enable textsql-streamlit
```
