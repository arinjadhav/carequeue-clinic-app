#!/usr/bin/env bash
# Builds and starts CareQueue, then prints the link and opens it in the browser.
cd "$(dirname "$0")" || exit 1
docker compose up --build -d || { echo "Docker failed to start. Is Docker Desktop running?"; exit 1; }

echo "Waiting for the app to start..."
ready=0
for i in $(seq 1 40); do
  if curl -fs http://localhost:8000/health >/dev/null 2>&1; then ready=1; break; fi
  sleep 1
done

USER_NAME=$(grep '^ADMIN_USERNAME=' .env 2>/dev/null | cut -d= -f2-)
USER_PASS=$(grep '^ADMIN_PASSWORD=' .env 2>/dev/null | cut -d= -f2-)

echo ""
if [ "$ready" = "1" ]; then
  echo "CareQueue is running."
  echo "  Link:     http://localhost:8000/login"
  echo "  Username: ${USER_NAME:-admin}"
  echo "  Password: ${USER_PASS:-see: docker compose logs clinic-queue}"
  command -v open >/dev/null 2>&1 && open http://localhost:8000/login
else
  echo "The app did not respond in time. Check: docker compose logs clinic-queue | tail -20"
fi
