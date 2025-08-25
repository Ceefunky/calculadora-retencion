# app.py — Calculadora de Retención (UF → CLP)
# Requisitos: pip install streamlit requests
# Ejecuta: streamlit run app.py

import requests
import streamlit as st
from datetime import datetime

st.set_page_config(page_title="Calculadora UF→CLP", page_icon="💡", layout="centered")

# ------------------------------
# Utilidades
# ------------------------------

def formato_clp(valor: float) -> str:
    """Formatea CLP con miles con punto y sin decimales."""
    entero = int(round(valor or 0, 0))
    s = f"{entero:,}".replace(",", ".")
    return f"$ {s}"

@st.cache_data(ttl=60*60)
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
    # El primer elemento suele ser el más reciente
    valor = float(serie[0]["valor"])  # CLP por 1 UF
    fecha_iso = serie[0]["fecha"]
    fecha = datetime.fromisoformat(fecha_iso.replace("Z", "+00:00")).date().strftime("%d-%m-%Y")
    return valor, f"mindicador.cl (UF del {fecha})"

# ------------------------------
# Encabezado
# ------------------------------

st.title("Calculadora de Retención UF → CLP")
st.caption(
    "Ingresa precio en UF, cantidad y un **monto de descuento en CLP**. "
    "La app calcula el % equivalente, valida topes por nivel y muestra el total en CLP."
)

# ------------------------------
# Configuración de niveles y topes
# ------------------------------

# Tope base por nivel (puedes ajustarlo si cambian políticas)
TOPES_BASE = {"Nivel 1": 0.25, "Telecierre": 0.40}

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
    )

TOPES_ACTIVOS = TOPES_BASE.copy()
if activar_flash:
    st.info("Ofertas Flash activadas: ajusta los topes permitidos para cada nivel.")
    c1, c2 = st.columns(2)
    with c1:
        top_n1 = st.number_input("Tope Nivel 1 (%)", min_value=0.0, max_value=80.0, value=30.0, step=1.0)
    with c2:
        top_tel = st.number_input("Tope Telecierre (%)", min_value=0.0, max_value=80.0, value=50.0, step=1.0)
    TOPES_ACTIVOS["Nivel 1"] = top_n1 / 100
    TOPES_ACTIVOS["Telecierre"] = top_tel / 100

max_desc = TOPES_ACTIVOS[nivel]

# ------------------------------
# UF: automática (API) o manual
# ------------------------------

col_api, col_manual = st.columns([2, 1])
with col_api:
    uf_ok = False
    uf_valor = None
    fuente = ""
    try:
        uf_valor, fuente = obtener_uf_hoy()
        uf_ok = True
    except Exception:
        uf_ok = False

with col_manual:
    usar_uf_manual = st.toggle(
        "Ingresar UF manualmente",
        value=not uf_ok,
        help="Úsalo si no hay internet o la API no responde",
    )

if usar_uf_manual:
    uf_valor = st.number_input("Valor de 1 UF en CLP", min_value=1.0, value=39000.0, step=100.0)
    fuente = "UF ingresada manualmente"

st.info(f"Valor UF usado: **{formato_clp(uf_valor)}** · Fuente: {fuente}")

# ------------------------------
# Entradas principales (monto en CLP en vez de %)
# ------------------------------

col1, col2 = st.columns(2)
with col1:
    precio_uf = st.number_input("Valor cuota / Precio unitario (UF)", min_value=0.0, value=1.42, step=0.01)
    cantidad = st.number_input("Cantidad", min_value=1, value=1, step=1)
with col2:
    monto_descuento_ing = st.number_input(
        "Monto de descuento solicitado (CLP)",
        min_value=0.0,
        value=8000.0,
        step=100.0,
        help=f"Tope por nivel: {int(max_desc*100)}% del total (cuota×cantidad)",
    )

# ------------------------------
# Cálculo
# ------------------------------

precio_unitario_clp = precio_uf * uf_valor
subtotal = precio_unitario_clp * cantidad

# % solicitado por referencia (antes de aplicar tope)
porcentaje_solicitado = (monto_descuento_ing / subtotal * 100) if subtotal > 0 else 0.0

# Aplicar tope por nivel
monto_tope = subtotal * max_desc
excede_tope = monto_descuento_ing > monto_tope
monto_aplicado = min(monto_descuento_ing, monto_tope)
porcentaje_aplicado = (monto_aplicado / subtotal * 100) if subtotal > 0 else 0.0

if excede_tope:
    st.error(
        f"El monto solicitado {formato_clp(monto_descuento_ing)} excede el tope permitido para {nivel} "
        f"(máx {int(max_desc*100)}% = {formato_clp(monto_tope)}). Se aplicará el tope.",
        icon="⛔",
    )

# Totales
DescuentoCLP = monto_aplicado
TotalCLP = max(subtotal - DescuentoCLP, 0)

# ------------------------------
# Resultados (bonito y claro)
# ------------------------------

m1, m2, m3 = st.columns(3)
with m1:
    st.metric("Subtotal", formato_clp(subtotal))
with m2:
    st.metric("Descuento solicitado", f"{formato_clp(monto_descuento_ing)}", delta=f"{porcentaje_solicitado:.1f}% del total")
with m3:
    st.metric("Descuento aplicado", f"{formato_clp(DescuentoCLP)}", delta=f"{porcentaje_aplicado:.1f}% del total")

st.metric("Total a pagar", formato_clp(TotalCLP))

st.divider()

st.subheader("Detalle")
st.write(
    f"Precio unitario: **{precio_uf:.2f} UF** → **{formato_clp(precio_unitario_clp)}** | Cantidad: **{int(cantidad)}**"
)
st.write(
    f"Nivel: **{nivel}** · Tope permitido: **{int(max_desc*100)}%** {'(Flash activo)' if activar_flash else ''}"
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
            f"Nivel: {nivel}\n"
            f"UF usada: {uf_valor:.2f} CLP\n"
            f"Precio unitario: {precio_uf:.2f} UF ({formato_clp(precio_unitario_clp)})\n"
            f"Cantidad: {int(cantidad)}\n"
            f"Subtotal: {formato_clp(subtotal)}\n"
            f"Descuento solicitado: {formato_clp(monto_descuento_ing)} ({porcentaje_solicitado:.1f}% del total)\n"
            f"Descuento aplicado: {formato_clp(DescuentoCLP)} ({porcentaje_aplicado:.1f}% del total)\n"
            f"Total: {formato_clp(TotalCLP)}\n"
        ),
        height=160,
    )

st.caption(
    "Fuente UF: mindicador.cl · La app ahora usa **monto en CLP** en vez de % y valida topes por nivel (Nivel 1 = 25%, Telecierre = 40%). "
    "Con **Ofertas Flash** puedes ajustar temporalmente esos topes."
)

