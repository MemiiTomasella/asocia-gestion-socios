# Sistema de Gestión de Socios — Sociedad Italiana de Goya (TFI)

Backend Django + MySQL, frontend con plantillas HTML5, Bootstrap 5 (CDN) y JavaScript básico.

## Puesta en marcha

1. **Entorno virtual e instalación de dependencias**

   ```bash
   python -m venv venv
   source venv/bin/activate        # En Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

   > `mysqlclient` necesita las librerías de desarrollo de MySQL en Linux
   > (`sudo apt install default-libmysqlclient-dev build-essential pkg-config`).
   > En Windows y macOS suele instalarse directamente con pip.

2. **Crear la base de datos en MySQL**

   ```sql
   CREATE DATABASE sociedad_italiana CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
   ```

3. **Variables de entorno**: copiá `.env.example` como `.env` y completá `SECRET_KEY`,
   `DB_USER` y `DB_PASSWORD`.

4. **Migraciones y usuario administrador**

   ```bash
   python manage.py makemigrations socios   # genera socios/migrations/0001_initial.py
   python manage.py migrate
   python manage.py createsuperuser
   ```

   > `makemigrations` hay que correrlo una sola vez, antes del primer `migrate`.

5. **Ejecutar**

   ```bash
   python manage.py runserver
   ```

   - Sistema: http://127.0.0.1:8000/ (pide iniciar sesión)
   - Panel de administración: http://127.0.0.1:8000/admin/

6. **Primeros pasos**: en el Admin cargá al menos una *Categoría* (ej.: Activo, $5000);
   después podés dar de alta socios desde el sistema, generar las cuotas del mes
   (Cuotas → Generar cuotas del mes) y cobrarlas.

## Pruebas automáticas

```bash
python manage.py test
```

(Para correrlas sin MySQL podés poner `DB_ENGINE=sqlite` en el `.env`.)

## Estructura

```
config/            settings.py, urls.py, wsgi.py, asgi.py
socios/            models.py, admin.py, forms.py, views.py, urls.py, tests.py, migrations/
templates/         base.html, includes/, registration/login.html, socios/*.html
```
