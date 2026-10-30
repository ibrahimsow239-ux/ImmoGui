FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY index.html style.css app.js auth.js server.py domain.py excel_export.py ./
COPY assets/residence-immogui.jpg assets/maisons-locatives.jpg ./assets/
ENV HOST=0.0.0.0 PORT=8000 APP_ENV=production DATABASE_PATH=/data/immogui.sqlite3 PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["python", "server.py"]
