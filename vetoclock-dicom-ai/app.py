import streamlit as st

try:
    import db
    import dicom_processor
    import claude_client
except Exception as _import_error:
    import traceback
    st.error(f"Error de importación: {_import_error}")
    st.code(traceback.format_exc())
    st.stop()

st.set_page_config(
    page_title="VetoClock DICOM AI",
    page_icon="🔬",
    layout="wide"
)

st.title("🔬 VetoClock DICOM AI")
st.caption("Prototipo — TC Torácico · Perro · tac_1")
st.divider()

id_caso = st.number_input("ID del caso", min_value=1, step=1, value=31295)

if st.button("Analizar caso", type="primary"):

    with st.spinner("Cargando datos del caso..."):
        caso = db.get_caso(id_caso)

    if not caso:
        st.error(f"No se encontró el caso {id_caso}")
        st.stop()

    if not caso.get("enlacedicom"):
        st.error("Este caso no tiene DICOM asociado")
        st.stop()

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Datos del paciente")
        st.markdown(f"""
| Campo | Valor |
|---|---|
| **Especie** | {caso.get('especie', '—')} |
| **Raza** | {caso.get('raza', '—')} |
| **Edad** | {caso.get('edad', '—')} años |
| **Peso** | {caso.get('peso', '—')} kg |
| **Tipo TAC** | {caso.get('tipotac', '—')} |
        """)

        st.subheader("Presentación clínica")
        st.write(caso.get("presentacion") or "No disponible")

        if caso.get("antecedentes"):
            st.subheader("Antecedentes")
            st.write(caso["antecedentes"])

    with col2:
        status = st.status("Cargando DICOM...", expanded=True)
        try:
            with status:
                st.write("📦 Comprobando caché local...")
                resultado_dicom = dicom_processor.descargar_y_procesar(
                    caso["enlacedicom"],
                    n_cortes=20,
                    presentacion=caso.get("presentacion", ""),
                    antecedentes=caso.get("antecedentes", ""),
                )
                n = len(resultado_dicom["pulmon"])
                counts = resultado_dicom.get("counts_zona", [7, 7, 6])
                st.write(f"✅ {n} cortes · craneal {counts[0]} / medio {counts[1]} / caudal {counts[2]}")
                if resultado_dicom.get("series_info"):
                    for s in resultado_dicom["series_info"]:
                        st.write(f"  Serie: **{s['desc']}** — {s['n_slices']} slices")
            status.update(label=f"✅ DICOM listo — {n} cortes ({counts[0]}/{counts[1]}/{counts[2]} cr/med/caud)", state="complete", expanded=False)
        except Exception as e:
            status.update(label="❌ Error procesando DICOM", state="error")
            st.error(str(e))
            st.stop()

        if n == 0:
            status.update(label="❌ No se cargaron cortes DICOM", state="error")
            st.error(
                "No se pudieron cargar cortes del DICOM. "
                "Revisa los logs para ver si el ZIP contiene archivos .dcm válidos con pixel_array. "
                "No se generará informe sin imágenes."
            )
            st.stop()

        tab1, tab2, tab3 = st.tabs(["🫁 Pulmón", "🫀 Tejido blando", "🧈 Grasa"])

        for tab, ventana in [(tab1, "pulmon"), (tab2, "tejido_blando"), (tab3, "grasa")]:
            with tab:
                cols = st.columns(4)
                for i, img in enumerate(resultado_dicom[ventana]):
                    cols[i % 4].image(img, use_container_width=True, caption=f"Corte {i+1}")

        if resultado_dicom["hu_stats"]:
            st.subheader("📊 Densidades HU por corte")
            for i, s in enumerate(resultado_dicom["hu_stats"], 1):
                st.caption(
                    f"Corte {i}: media **{s['mean']} HU** | "
                    f"p10 **{s['p10']} HU** | p25 **{s['p25']} HU** — {s['caracterizacion']}"
                )

    st.divider()

    with st.spinner("Buscando casos similares..."):
        region = "torax"
        casos_similares = db.get_casos_similares(
            especie=caso.get("especie", "perro"),
            tipotac=caso.get("tipotac", "tac_1"),
            region=region,
            excluir_id=id_caso,
            limit=3
        )
        st.caption(f"{len(casos_similares)} casos similares encontrados como referencia")

    with st.spinner("Generando informe con IA... (puede tardar 30-60 segundos)"):
        try:
            informe = claude_client.generar_informe(caso, resultado_dicom, casos_similares)
        except Exception as e:
            st.error(f"Error generando informe: {e}")
            st.stop()

    st.subheader("📋 Informe generado por IA")
    st.info("Este informe es un borrador de apoyo. Debe ser revisado y validado por el especialista.")
    st.markdown(informe)

    if st.button("Ver informe real del especialista"):
        informe_real = db.get_informe(id_caso)
        if informe_real:
            st.subheader("📄 Informe del especialista")
            st.markdown(informe_real)
        else:
            st.warning("Este caso no tiene informe activado")
