# 🏀 SuperManager Basket

La app elige sola dónde guardar los datos:

- **Sin claves de Turso** → usa `supermanager.db` en tu PC, como siempre (`streamlit run app.py`).
- **Con `TURSO_DATABASE_URL` y `TURSO_AUTH_TOKEN`** → usa la base de datos de Turso en la nube.

En el Panel de admin, debajo de la contraseña, verás cuál está usando.

## Archivos

| Archivo | Qué hace |
|---|---|
| `app.py` | La web (clasificación, quinteto, panel de admin) |
| `db.py` | Conexión: Turso o archivo local |
| `crear_db.py` | Tablas, amigos y reglas iniciales (la app lo ejecuta sola si falta algo) |
| `procesar_jornada.py` | Cierre de jornada: precios, sanciones y autotopillo |
| `copias.py` | Descargar / restaurar copias de seguridad |
| `identidad.py` | Códigos personales de los mánagers |
| `requirements.txt` | Lo que Streamlit Cloud tiene que instalar |

## Publicarla gratis (se hace una vez)

### 1. Base de datos en Turso
1. Entra en turso.tech y crea una cuenta (puedes usar tu GitHub).
2. Crea una base de datos llamada `supermanager`. Si te deja elegir ubicación, elige una de **EE. UU.**: Streamlit Cloud está allí y así cada consulta tarda menos.
3. En la página de esa base de datos, copia la **URL** (empieza por `libsql://`) y genera un **token** con permiso de lectura y escritura. Guárdalos: son la llave de los datos.

No hace falta crear tablas: la app las crea en el primer arranque.

### 2. Código en GitHub
1. Crea un repositorio nuevo (puede ser público: ni la contraseña ni el token van en el código).
2. Sube: `app.py`, `db.py`, `crear_db.py`, `procesar_jornada.py`, `copias.py`, `identidad.py`, `requirements.txt`, `.gitignore` y `README.md`.
3. **No subas** `supermanager.db` ni `.streamlit/secrets.toml`. Con `git` el `.gitignore` ya los deja fuera, pero si arrastras archivos en la web de GitHub el `.gitignore` no actúa: no los arrastres.

### 3. App en Streamlit Community Cloud
1. Entra en share.streamlit.io con tu cuenta de GitHub y pulsa **Create app**.
2. Elige el repositorio, la rama (`main`) y el archivo `app.py`.
3. En **Advanced settings**: Python 3.12 o 3.13, y en **Secrets** pega esto con tus datos:

   ```toml
   TURSO_DATABASE_URL = "libsql://supermanager-tuusuario.turso.io"
   TURSO_AUTH_TOKEN = "el-token-de-turso"
   SM_ADMIN_PASSWORD = "la-contraseña-de-admin"
   ```

4. **Deploy**. El primer arranque tarda un par de minutos (instala las librerías).
5. Comparte el enlace con el grupo.

Los secretos se pueden cambiar luego en la app → **Settings → Secrets**.

### 4. Pasar los datos que ya tienes
Si ya jugasteis jornadas con la versión local:
Panel de admin → **4. Copia de seguridad** → sube tu `supermanager.db` → marca la casilla → **Restaurar**.
Sustituye todo lo que haya en Turso por lo del archivo (si falla, no cambia nada).

## Códigos de los mánagers
Para guardar quinteto, cada uno entra con su nombre y su código de 4 cifras. Así nadie puede guardar el quinteto de otro.
1. Panel de admin → **5. Códigos de los mánagers** → **Generar códigos** (vienen marcados los que aún no tienen).
2. Apunta la tabla que aparece y manda a cada uno **su** código por privado. Después pulsa **Ya los he apuntado**: no se vuelven a ver.
3. Si alguien lo pierde, genérale uno nuevo solo a él; el anterior deja de valer.

En la base de datos solo se guarda una huella del código, no el código.

## Empezar de cero
Panel de admin → **6. Empezar la liga de cero** → escribe `BORRAR` → **Empezar de cero**.
Borra jornadas, quintetos, estadísticas, sanciones e historial, y deja todos los precios en el precio base. Los mánagers y sus códigos se mantienen. Hay una casilla para volver también a las reglas del mercado por defecto.

## Copias de seguridad
Panel de admin → **4. Copia de seguridad** → **Preparar copia** → **Descargar**.
Hazlo después de cada jornada: es un archivo pequeño y te cubre ante cualquier susto.
Ese mismo archivo sirve para abrir la app en local o para restaurar.

## Probar en tu PC contra Turso
Copia `.streamlit/secrets.toml.ejemplo` como `.streamlit/secrets.toml`, rellénalo y ejecuta `streamlit run app.py`.
Sin ese archivo, la app vuelve a usar `supermanager.db`.

## Si algo falla
- **"No se pudo conectar con la base de datos (Turso…)"**: revisa la URL y el token en los secretos (sin espacios ni saltos de línea de más).
- **La app dice que está dormida**: pasa tras 12 horas sin visitas. Se pulsa el botón y despierta; los datos están en Turso y no se pierden.
- Los errores completos se ven en Streamlit Cloud → tu app → **Manage app** (abajo a la derecha).
