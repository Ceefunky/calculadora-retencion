# app.py — Calculadora de Retención (UF → CLP)
# Requisitos: pip install streamlit requests
# Ejecuta: streamlit run app.py

import requests
import streamlit as st
from datetime import datetime
import time, hmac, hashlib, base64, json

# Colocar SIEMPRE antes de cualquier componente de UI
st.set_page_config(page_title="Calculadora UF→CLP", page_icon="💡", layout="centered")

# ==============================
# Utils
# ==============================
def formato_clp(valor: float) -> str:
    """Formatea CLP con miles con punto y sin decimales."""
    entero = int(round(valor or 0, 0))
    s = f"{entero:,}".replace(",", ".")
    return f"$ {s}"

def parse_num(s, default=0.0) -> float:
    """
    Convierte strings con ',' o '.' a float.
    Acepta miles con punto (p.ej. '1.234,56').
    """
    try:
        if isinstance(s, (int, float)):
            return float(s)
        s = str(s).strip()
        # elimina separador de miles '.' y usa '.' como decimal
        s = s.replace(".", "").replace(",", ".")
        return float(s)
    except Exception:
        return float(default)

@st.cache_data(ttl=60 * 60)
def obtener_uf_hoy() -> tuple[float, str]:
    """
    Intenta obtener la UF de hoy desde mindicador.cl.
    Retorna (valor_uf_en_clp, fuente_texto) o lanza excepción si falla.
    """
    url = "https://mindicador.cl/api/uf"
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    data = r.json()
    serie = data.get("serie", [])
    if not serie:
        raise RuntimeError("Respuesta sin datos de UF")
    valor = float(serie[0]["valor"])  # CLP por 1 UF
    fecha_iso = serie[0]["fecha"]
    fecha = datetime.fromisoformat(fecha_iso.replace("Z", "+00:00")).date().strftime("%d-%m-%Y")
    return valor, f"mindicador.cl (UF del {fecha})"

# ==============================
# Roles / Autorización
# ==============================
ADMINS = set(st.secrets.get("auth", {}).get("admins", []))
ADMIN_PASSCODE = st.secrets.get("auth", {}).get("admin_passcode", None)

def get_user_email():
    """Compatibilidad st.user (nuevo) y experimental_user (viejo)."""
    try:
        if getattr(st, "user", None) and getattr(st.user, "email", None):
            return st.user.email
        if hasattr(st, "experimental_user") and st.experimental_user is not None:
            return getattr(st.experimental_user, "email", None)
    except Exception:
        pass
    return None

user_email = get_user_email()
if "is_manager" not in st.session_state:
    st.session_state.is_manager = (user_email in ADMINS) if user_email else False

# Desbloqueo por passcode en la barra lateral (opcional)
if not st.session_state.is_manager and ADMIN_PASSCODE:
    with st.sidebar:
        st.caption("🔒 Solo jefes")
        code = st.text_input("Código de jefe", type="password", placeholder="••••••")
        if code and code == ADMIN_PASSCODE:
            st.session_state.is_manager = True
            st.success("Modo jefe activado")

is_manager = st.session_state.is_manager

# ==============================
# Tokens temporales para agentes (?flash=TOKEN)
# ==============================
TOKEN_KEY = st.secrets.get("auth", {}).get("token_key", "dev-secret-change-me")

def make_flash_token(hours: int, n1_pct: float, tel_pct: float) -> str:
    """Crea un token firmado con expiración y topes flash."""
    payload = {
        "exp": int(time.time()) + hours * 3600,
        "n1": float(n1_pct),   # % Nivel 1
        "tel": float(tel_pct), # % Telecierre
        "v": 1,
    }
    msg = json.dumps(payload, separators=(",", ":")).encode()
    sig = hmac.new(TOKEN_KEY.encode(), msg, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(msg + b"." + sig).decode()

def verify_flash_token(token: str):
    try:
        data = base64.urlsafe_b64decode(token.encode())
        msg, sig = data.rsplit(b".", 1)
        expected = hmac.new(TOKEN_KEY.encode(), msg, hashlib.sha256).digest()
        if not hmac.compare_digest(sig, expected):
            return False, "Firma inválida"
        payload = json.loads(msg.decode())
        if payload.get("exp", 0) < time.time():
            return False, "Token vencido"
        return True, payload
    except Exception as e:
        return False, str(e)

def get_query_param(name: str):
    try:
        return st.query_params.get(name, None)
    except Exception:
        q = st.experimental_get_query_params()
        if name in q:
            v = q[name]
            return v[0] if isinstance(v, list) else v
        return None

# Lee ?flash=TOKEN y guarda en sesión
token_param = get_query_param("flash")
if token_param:
    ok, payload = verify_flash_token(token_param)
    if ok:
        st.session_state.flash_until = payload["exp"]
        st.session_state.flash_topes = {
            "Nivel 1": payload["n1"] / 100.0,
            "Telecierre": payload["tel"] / 100.0,
        }
        st.success(
            f"✅ Ofertas Flash habilitadas hasta "
            f"{datetime.fromtimestamp(payload['exp']).strftime('%d-%m-%Y %H:%M')}"
        )
    else:
        st.warning(f"Token Flash inválido: {payload}")

def flash_active() -> bool:
    return st.session_state.get("flash_until", 0) > time.time()

# ==============================
# UI principal
# ==============================
st.title("Calculadora de Retención UF → CLP")
st.caption(
    "Ingresa precio en UF, cantidad y un **monto de descuento en CLP**. "
    "La app calcula el % equivalente, valida topes por nivel y muestra el total en CLP."
)
st.caption(f"👤 Sesión: {user_email or 'Usuario público'} · Rol: {'Jefe' if is_manager else 'Agente'}")

# --- Config de niveles y topes ---
IVA_RATE = 0.19  # 19% Chile
TOPES_BASE = {"Nivel 1": 0.25, "Telecierre": 0.40}
TOPES_ACTIVOS = TOPES_BASE.copy()

col_nivel, col_flash = st.columns([2, 1])
with col_nivel:
    nivel = st.radio(
        "Nivel de retención",
        options=["Nivel 1", "Telecierre"],
        index=0,
        horizontal=True,
    )
with col_flash:
    activar_flash = st.toggle(
        "Ofertas Flash",
        value=False,
        help="Activa para ampliar topes por nivel en días especiales",
        disabled=not is_manager,  # solo jefes pueden activarlo manualmente
    )

# 1) Si JEFE activó y editó Ofertas Flash desde la UI:
if activar_flash and is_manager:
    st.info("Ofertas Flash activadas (modo jefe): ajusta los topes permitidos.")
    c1, c2 = st.columns(2)
    with c1:
        top_n1 = st.number_input("Tope Nivel 1 (%)", min_value=0.0, max_value=80.0, value=30.0, step=1.0)
    with c2:
        top_tel = st.number_input("Tope Telecierre (%)", min_value=0.0, max_value=80.0, value=50.0, step=1.0)
    TOPES_ACTIVOS["Nivel 1"] = top_n1 / 100.0
    TOPES_ACTIVOS["Telecierre"] = top_tel / 100.0

# 2) Si AGENTE tiene enlace temporal válido:
elif flash_active():
    TOPES_ACTIVOS.update(st.session_state.get("flash_topes", {}))
    mins = int((st.session_state.flash_until - time.time()) // 60)
    st.caption(f"⏳ Ofertas Flash activas por ~{mins} min.")

# Panel para generar enlace temporal (solo jefes)
if is_manager:
    with st.expander("🔑 Enlace temporal de Ofertas Flash para agentes"):
        horas = st.number_input("Duración (horas)", 1, 24, 4)
        n1 = st.number_input("Tope Nivel 1 (Flash %)", 0.0, 80.0, 30.0, 1.0)
        tel = st.number_input("Tope Telecierre (Flash %)", 0.0, 80.0, 50.0, 1.0)
        if st.button("Generar enlace"):
            tok = make_flash_token(int(horas), n1, tel)
            st.code(f"?flash={tok}", language="text")
            st.caption(
                "Copia la URL pública de tu app y agrega ese parámetro. "
                "Ej: https://tuapp.streamlit.app ?flash=...  "
                "Si ya tienes parámetros, añade &flash=..."
            )

max_desc = TOPES_ACTIVOS[nivel]

# ------------------------------
# UF SIEMPRE editable (se precarga desde API)
# ------------------------------
try:
    uf_api, fuente = obtener_uf_hoy()
except Exception:
    uf_api, fuente = 39315.0, "UF manual (API no disponible)"

col_api, _ = st.columns([2, 1])
with col_api:
    uf_valor_txt = st.text_input(
        "Valor de 1 UF en CLP (editable)",
        value=f"{int(round(uf_api)):n}".replace(",", "."),
        help=f"Fuente sugerida: {fuente}. Puedes modificarla libremente."
    )

uf_valor = parse_num(uf_valor_txt, uf_api)
st.info(f"Valor UF usado: **{formato_clp(uf_valor)}** · Fuente: {fuente}")

# ------------------------------
# Entradas principales (abiertas)
# ------------------------------
col1, col2 = st.columns(2)

with col1:
    precio_uf_txt = st.text_input("Valor cuota / Precio unitario (UF)", value="1,40")
with col2:
    monto_descuento_txt = st.text_input(
        "Monto de descuento solicitado (CLP)",
        value="8000",
        help=f"Tope por nivel: {int(max_desc*100)}% del subtotal (incl. IVA)"
    )

cant_txt = st.text_input("Cantidad", value="1")

# Parseo seguro
precio_uf = parse_num(precio_uf_txt, 0.0)
monto_descuento_ing = parse_num(monto_descuento_txt, 0.0)
try:
    cantidad = max(int(parse_num(cant_txt, 1)), 1)
except Exception:
    cantidad = 1

# ------------------------------
# Cálculo (Subtotal incluye IVA; descuento SIN IVA)
# ------------------------------
precio_unitario_clp_neto = precio_uf * uf_valor      # valor cuota en CLP (sin IVA)
neto = precio_unitario_clp_neto * cantidad           # total neto sin IVA
iva_incluido = neto * IVA_RATE                        # IVA 19% sobre neto
subtotal = neto + iva_incluido                        # 🔹 Subtotal YA incluye IVA

# % solicitado por referencia (antes de aplicar tope) – respecto del subtotal con IVA
porcentaje_solicitado = (monto_descuento_ing / subtotal * 100) if subtotal > 0 else 0.0

# Aplicar tope por nivel (porcentaje del subtotal con IVA)
monto_tope = subtotal * max_desc
excede_tope = monto_descuento_ing > monto_tope
monto_aplicado = min(monto_descuento_ing, monto_tope)
porcentaje_aplicado = (monto_aplicado / subtotal * 100) if subtotal > 0 else 0.0

if excede_tope:
    st.error(
        f"El monto solicitado {formato_clp(monto_descuento_ing)} excede el tope permitido para {nivel} "
        f"(máx {int(max_desc*100)}% = {formato_clp(monto_tope)} del subtotal con IVA). Se aplicará el tope.",
        icon="⛔",
    )

# Totales (Total con IVA porque el subtotal ya lo incluye)
DescuentoCLP = monto_aplicado                      # descuento sin IVA
TotalCLP = max(subtotal - DescuentoCLP, 0)

# ------------------------------
# Resultados
# ------------------------------
r1c1, r1c2, r1c3 = st.columns(3)
with r1c1:
    st.metric("Subtotal (incl. IVA 19%)", formato_clp(subtotal))
with r1c2:
    st.metric("IVA incluido (19%)", formato_clp(iva_incluido))
with r1c3:
    st.metric("Descuento solicitado", formato_clp(monto_descuento_ing), delta=f"{porcentaje_solicitado:.1f}% del subtotal")

r2c1, r2c2, r2c3 = st.columns(3)
with r2c1:
    st.metric("Descuento aplicado", formato_clp(DescuentoCLP), delta=f"{porcentaje_aplicado:.1f}% del subtotal")
with r2c2:
    st.empty()
with r2c3:
    st.metric("Total a pagar (incl. IVA)", formato_clp(TotalCLP))

st.divider()
st.subheader("Detalle")
st.write(
    f"Precio unitario: **{precio_uf:.2f} UF** → **{formato_clp(precio_unitario_clp_neto)}** (neto) | "
    f"Cantidad: **{int(cantidad)}** | IVA incluido: **{formato_clp(iva_incluido)}**"
)
st.write(
    f"Nivel: **{nivel}** · Tope permitido sobre subtotal (incl. IVA): **{int(max_desc*100)}%** "
    f"{'(Flash activo)' if (activar_flash and is_manager) or flash_active() else ''}"
)

# ------------------------------
# Opcional: redondeo y exportación
# ------------------------------
with st.expander("Opciones avanzadas"):
    redondear_mil = st.toggle("Redondear total al millar más cercano", value=False)
    if redondear_mil:
        TotalCLP = round(TotalCLP / 1000) * 1000
        st.write(f"Total redondeado: **{formato_clp(TotalCLP)}**")

    st.text_area(
        "Resumen",
        value=(
            f"UF usada (editable): {uf_valor:.2f} CLP\n"
            f"Precio unitario: {precio_uf:.2f} UF ({formato_clp(precio_unitario_clp_neto)} neto)\n"
            f"Cantidad: {int(cantidad)}\n"
            f"IVA incluido (19%): {formato_clp(iva_incluido)}\n"
            f"Subtotal (incl. IVA): {formato_clp(subtotal)}\n"
            f"Descuento solicitado: {formato_clp(monto_descuento_ing)} ({porcentaje_solicitado:.1f}% del subtotal)\n"
            f"Descuento aplicado: {formato_clp(DescuentoCLP)} ({porcentaje_aplicado:.1f}% del subtotal)\n"
            f"Total a pagar (incl. IVA): {formato_clp(TotalCLP)}\n"
        ),
        height=200,
    )

st.caption(
    "Los topes de descuento se calculan sobre el **subtotal con IVA**. "
    "Las entradas son abiertas: puedes escribir con coma/punto y miles. "
    "La UF se precarga desde la API pero puedes modificarla."
)









