# app.py — Calculadora de Retención (UF → CLP)
# Requisitos: pip install streamlit requests
# Ejecuta: streamlit run app.py

import requests
import streamlit as st
from datetime import datetime

st.set_page_config(page_title="Calculadora de Retención UF→CLP", page_icon="💡", layout="centered")

# ------------------------------
# Utilidades
# ------------------------------

def formato_clp(valor: float) -> str:
    # Formato chileno: separador de miles con punto y sin decimales por defecto
    entero = int(round(valor, 0))
    s = f"{entero:,}".replace(",", ".")
    return f"$ {s}"

@st.cache_data(ttl=60*60)
def obtener_uf_hoy() -> tuple[float, str]:
    """Intenta obtener la UF de hoy desde mindicador.cl.
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
st.caption("Elige el nivel, ingresa el precio en UF, la cantidad y el % de descuento. La app calcula el total en CLP y respeta los máximos por nivel.")

# ------------------------------
# Entrada del nivel (controla tope de descuento)
# ------------------------------

nivel = st.segmented_control(
    "Nivel de retención",
    options=["Nivel 1", "Telecierre"],
    selection_mode="single",
    default="Nivel 1",
)

TOPE_DESCUENTO = {"Nivel 1": 0.25, "Telecierre": 0.40}
max_desc = TOPE_DESCUENTO[nivel]

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
    usar_uf_manual = st.toggle("Ingresar UF manualmente", value=not uf_ok, help="Úsalo si no hay internet o la API no responde")

if usar_uf_manual:
    uf_valor = st.number_input("Valor de 1 UF en CLP", min_value=1.0, value=39000.0, step=100.0)
    fuente = "UF ingresada manualmente"

st.info(f"Valor UF usado: **{formato_clp(uf_valor)}** · Fuente: {fuente}")

# ------------------------------
# Entradas principales
# ------------------------------

col1, col2 = st.columns(2)
with col1:
    precio_uf = st.number_input("Precio unitario (UF)", min_value=0.0, value=10.0, step=0.5)
    cantidad = st.number_input("Cantidad", min_value=1, value=1, step=1)
with col2:
    solicitado_pct = st.number_input(
        "% descuento solicitado",
        min_value=0.0,
        max_value=100.0,
        value=15.0,
        step=0.5,
        help=f"Tope por nivel: {int(max_desc*100)}%",
    )

# ------------------------------
# Cálculo
# ------------------------------

precio_unitario_clp = precio_uf * uf_valor
subtotal = precio_unitario_clp * cantidad

solicitado = solicitado_pct / 100
aplicado = min(solicitado, max_desc)

descuento_clp = subtotal * aplicado
total_clp = subtotal - descuento_clp

# Advertencias visuales
if solicitado > max_desc:
    st.warning(
        f"El descuento solicitado ({solicitado_pct:.1f}%) excede el tope para {nivel} (máx {int(max_desc*100)}%). Se aplicará {int(max_desc*100)}%.",
        icon="⚠️",
    )

# ------------------------------
# Resultados (bonito y claro)
# ------------------------------

m1, m2, m3 = st.columns(3)
with m1:
    st.metric("Subtotal", formato_clp(subtotal))
with m2:
    st.metric("Descuento aplicado", f"{aplicado*100:.1f}%", delta=f"-{formato_clp(descuento_clp)}")
with m3:
    st.metric("Total a pagar", formato_clp(total_clp))

st.divider()

st.subheader("Detalle")
st.write(
    f"Precio unitario: **{precio_uf:.2f} UF** → **{formato_clp(precio_unitario_clp)}** | Cantidad: **{int(cantidad)}**"
)
st.write(
    f"Nivel: **{nivel}** · Tope permitido: **{int(max_desc*100)}%** · Solicitado: **{solicitado_pct:.1f}%** · Aplicado: **{aplicado*100:.1f}%**"
)

# ------------------------------
# Opcional: redondeo y exportación
# ------------------------------

with st.expander("Opciones avanzadas"):
    redondear_mil = st.toggle("Redondear total al millar más cercano", value=False)
    if redondear_mil:
        total_clp = round(total_clp / 1000) * 1000
        st.write(f"Total redondeado: **{formato_clp(total_clp)}**")

    if st.button("Copiar resumen (portapapeles)"):
        st.toast("Selecciona y copia desde el cuadro siguiente.")

    st.text_area(
        "Resumen",
        value=(
            f"Nivel: {nivel}\n"
            f"UF usada: {uf_valor:.2f} CLP\n"
            f"Precio unitario: {precio_uf:.2f} UF ({formato_clp(precio_unitario_clp)})\n"
            f"Cantidad: {int(cantidad)}\n"
            f"Subtotal: {formato_clp(subtotal)}\n"
            f"Descuento aplicado: {aplicado*100:.1f}% ({formato_clp(descuento_clp)})\n"
            f"Total: {formato_clp(total_clp)}\n"
        ),
        height=150,
    )

st.caption("Fuente UF: mindicador.cl · La app aplica validaciones de tope: Nivel 1 = 25%, Telecierre = 40%.")

