import streamlit as st
import requests
import os
from typing import Any


st.set_page_config(
    page_title="DfM Agent",
    layout="wide"
)

BACKEND_URL = os.environ.get("DFM_BACKEND_URL", "http://localhost:8000")


def _mesh_to_pyvista(mesh_payload: dict[str, Any], color_key: str = "draft_rgb") -> Any:
    import numpy as np
    import pyvista as pv

    points = np.asarray(mesh_payload["points"], dtype=float)
    faces = np.asarray(
        [[3, int(a), int(b), int(c)] for a, b, c in mesh_payload["faces"]],
        dtype=int,
    ).ravel()
    poly = pv.PolyData(points, faces)
    if color_key in mesh_payload:
        poly.cell_data[color_key] = np.asarray(mesh_payload[color_key], dtype=float)
    if "face_ids" in mesh_payload:
        poly.cell_data["face_id"] = np.asarray(mesh_payload["face_ids"], dtype=int)
    return poly


def _show_mesh(mesh_payload: dict[str, Any], color_key: str = "draft_rgb") -> bool:
    try:
        import pyvista as pv
        from stpyvista import stpyvista
    except ImportError as exc:
        st.warning(f"PyVista viewer dependencies are unavailable: {exc}")
        return False

    poly = _mesh_to_pyvista(mesh_payload, color_key=color_key)
    plotter = pv.Plotter(window_size=(1100, 720))
    plotter.set_background("#f6f7f9")
    if color_key in poly.cell_data:
        plotter.add_mesh(
            poly,
            scalars=color_key,
            rgb=True,
            show_edges=True,
            edge_color="#30343b",
            line_width=0.4,
        )
    else:
        plotter.add_mesh(
            poly,
            color="#b8c0cc",
            show_edges=True,
            edge_color="#30343b",
            line_width=0.4,
        )
    plotter.add_axes()
    plotter.camera_position = "iso"
    stpyvista(plotter, key=f"viewer-{color_key}")
    return True


st.title("DfM Agent")

st.caption("Bosch RB-CoC Plastics | STEP-native injection molding DfM")


left, center = st.columns([0.28, 0.72])

with left:
    st.subheader("Part")
    try:
        health = requests.get(f"{BACKEND_URL}/health", timeout=5)
        health.raise_for_status()
        st.success("Backend connected")
    except requests.RequestException as exc:
        st.error(f"Backend unavailable: {exc}")
        st.stop()

    try:
        parts_response = requests.get(f"{BACKEND_URL}/parts", timeout=10)
        parts_response.raise_for_status()
        parts = parts_response.json().get("files", [])
    except requests.RequestException as exc:
        st.error(f"Could not list STEP files: {exc}")
        st.stop()

    if not parts:
        st.info("Place a .stp file in data/parts.")
        st.stop()

    selected_part = st.selectbox("STEP file", parts, index=0)
    include_faces = st.checkbox("Include face table", value=False)
    include_mesh = st.checkbox("Build display mesh", value=True)
    mesh_deflection = st.slider("Mesh quality", 0.1, 2.0, 0.5, 0.1)

    st.subheader("Pull Direction")
    dx = st.number_input("X", value=0.0, step=0.1, format="%.3f")
    dy = st.number_input("Y", value=0.0, step=0.1, format="%.3f")
    dz = st.number_input("Z", value=1.0, step=0.1, format="%.3f")

    run_summary = st.button("Load STEP", use_container_width=True)
    run_draft = st.button("Run Draft", type="primary", use_container_width=True)

with center:
    raw_tab, draft_tab = st.tabs(["Raw", "Draft"])

    with raw_tab:
        st.subheader("Raw Geometry")
        if not run_summary:
            st.info("Select a STEP file and load it to inspect exact B-Rep topology.")
        else:
            try:
                response = requests.get(
                    f"{BACKEND_URL}/parts/{selected_part}/summary",
                    params={
                        "include_faces": include_faces,
                        "include_mesh": include_mesh,
                        "mesh_deflection": mesh_deflection,
                    },
                    timeout=120,
                )
                response.raise_for_status()
                summary = response.json()
            except requests.RequestException as exc:
                st.error(f"STEP load failed: {exc}")
                st.stop()

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Solids", summary.get("solid_count", 0))
            c2.metric("Faces", summary.get("face_count", 0))
            c3.metric("Edges", summary.get("edge_count", 0))
            c4.metric("Vertices", summary.get("vertex_count", 0))

            st.json({
                "bounding_box": summary.get("bounding_box"),
                "surface_type_counts": summary.get("surface_type_counts"),
                "edge_type_counts": summary.get("edge_type_counts"),
                "adjacency_stats": summary.get("adjacency_stats"),
                "warnings": summary.get("warnings"),
            })

            if include_mesh and "display_mesh" in summary:
                st.subheader("Display Mesh")
                st.json(summary["display_mesh"])

            if include_faces and "faces" in summary:
                st.subheader("Faces")
                st.dataframe(summary["faces"], use_container_width=True)

    with draft_tab:
        st.subheader("Draft Analysis")
        if not run_draft:
            st.info("Run draft analysis to view classifications.")
        else:
            try:
                response = requests.get(
                    f"{BACKEND_URL}/parts/{selected_part}/draft",
                    params={
                        "dx": dx,
                        "dy": dy,
                        "dz": dz,
                        "include_faces": include_faces,
                        "include_mesh": include_mesh,
                        "mesh_deflection": mesh_deflection,
                    },
                    timeout=180,
                )
                response.raise_for_status()
                result = response.json()
            except requests.RequestException as exc:
                st.error(f"Draft analysis failed: {exc}")
                st.stop()

            draft = result["draft"]
            face_counts = draft["face_counts"]
            percentages = draft["percentages"]

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Good", face_counts["good"], f"{percentages['good_pct']}% area")
            c2.metric("Marginal", face_counts["marginal"], f"{percentages['marginal_pct']}% area")
            c3.metric("Bad", face_counts["bad"], f"{percentages['bad_pct']}% area")
            c4.metric("Severity", draft["severity"].title())

            if include_mesh and "display_mesh" in result:
                shown = _show_mesh(result["display_mesh"], color_key="draft_rgb")
                if not shown:
                    st.json({
                        "display_mesh": {
                            "point_count": result["display_mesh"].get("point_count"),
                            "triangle_count": result["display_mesh"].get("triangle_count"),
                        }
                    })

            if draft["suggestions"]:
                st.subheader("Suggestions")
                for suggestion in draft["suggestions"]:
                    st.write(suggestion["action_text"])

            with st.expander("Draft JSON"):
                st.json(draft)

            if include_faces:
                st.subheader("Faces")
                st.dataframe(result["part"].get("faces", []), use_container_width=True)
