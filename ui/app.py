import sys
import os
import streamlit as st

# Add project root to Python path
sys.path.append(
    os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
)

from converter.tableau_to_dax import tableau_to_dax

st.set_page_config(
    page_title="Tableau → DAX Converter",
    layout="wide"
)

st.title("🔁 Tableau Measure → DAX Converter")
# st.write("App loaded successfully ✅")

# import streamlit as st
from converter.tableau_to_dax import tableau_to_dax



st.markdown(
    """
Convert Tableau calculated measures into Power BI DAX.

**Supported :**
- IF / ELSE / ELSEIF  
- CASE → SWITCH  
- FIXED / INCLUDE / EXCLUDE  
- Common functions (IFNULL, ZN, COUNTD, AVG)
"""
)

default_table = st.text_input(
    "Default Table Name",
    value="Table",
    help="Used to prefix fields like [Profit] → Table[Profit]"
)

tableau_expr = st.text_area(
    "Tableau Formula",
    height=220,
    placeholder="IF SUM([Sales]) > 0 THEN [Profit] ELSE 0 END"
)

col1, col2 = st.columns([1, 4])

with col1:
    convert = st.button("Convert")

if convert:
    if not tableau_expr.strip():
        st.warning("Please paste a Tableau formula.")
    else:
        try:
            dax_expr = tableau_to_dax(tableau_expr, default_table)

            st.subheader("DAX Output")
            st.code(dax_expr, language="DAX")

            st.success("Conversion successful ✔")
        except Exception as e:
            st.error("Conversion failed ❌")
            st.exception(e)

