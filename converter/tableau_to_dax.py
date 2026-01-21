import re


def tableau_to_dax(tableau_expr: str, default_table: str = "Table"):
    """
    Converts a Tableau custom measure formula to a DAX measure expression.

    Parameters:
        tableau_expr (str): Tableau formula (e.g. IF/CASE/etc).
        default_table (str): Table name to prefix unqualified columns.

    Returns:
        str: DAX formula as a string.

    Raises:
        ValueError: If an unsupported Tableau construct is detected.
    """

    expr = tableau_expr

    # Normalize quotes and whitespace
    expr = expr.replace("'", "\"").strip()

    # Prefix unqualified fields [Field] with table name
    expr = re.sub(r'\[([^\]]+)\]', rf"{default_table}[\1]", expr)

    # Convert ELSEIF to ELSE IF
    expr = re.sub(r'\bELSEIF\b', 'ELSE IF', expr, flags=re.IGNORECASE)

    # Handle IF / ELSEIF
    if re.search(r'\bIF\b.*\bELSE IF\b', expr, flags=re.IGNORECASE):
        pattern = re.compile(
            r'IF\s+(.*?)\s+THEN\s+(.*?)\s+ELSE\s+IF\s+'
            r'(.*?)\s+THEN\s+(.*?)\s+ELSE\s+(.*?)\s+END',
            flags=re.IGNORECASE
        )
        match = pattern.search(expr)
        if match:
            cond1, val1, cond2, val2, val_else = match.groups()
            expr = f"IF({cond1}, {val1}, IF({cond2}, {val2}, {val_else}))"
    else:
        pattern = re.compile(
            r'IF\s+(.*?)\s+THEN\s+(.*?)\s+ELSE\s+(.*?)\s+END',
            flags=re.IGNORECASE
        )
        match = pattern.search(expr)
        if match:
            cond, val_true, val_false = match.groups()
            expr = f"IF({cond}, {val_true}, {val_false})"

    # Handle CASE → SWITCH
    if re.search(r'\bCASE\b', expr, flags=re.IGNORECASE):
        base_match = re.match(r'\s*CASE\s+(.*?)\s+WHEN', expr, flags=re.IGNORECASE)
        base = base_match.group(1) if base_match else None

        whens = re.findall(
            r'WHEN\s+(.*?)\s+THEN\s+(.*?)(?=\s+WHEN|\s+ELSE|\s+END)',
            expr, flags=re.IGNORECASE
        )

        else_match = re.search(r'ELSE\s+(.*?)\s+END', expr, flags=re.IGNORECASE)
        else_val = else_match.group(1) if else_match else None

        cases = [f"{val}, {res}" for val, res in whens]

        if base:
            expr = "SWITCH(" + base + ", " + ", ".join(cases)
        else:
            expr = "SWITCH(TRUE(), " + ", ".join(cases)

        if else_val:
            expr += f", {else_val}"
        expr += ")"

    # Function mappings
    expr = re.sub(r'\bIFNULL\s*\(\s*(.*?)\s*,\s*(.*?)\)', r'COALESCE(\1, \2)', expr, flags=re.IGNORECASE)
    expr = re.sub(r'\bISNULL\s*\(\s*(.*?)\s*\)', r'ISBLANK(\1)', expr, flags=re.IGNORECASE)
    expr = re.sub(r'\bZN\s*\(\s*(.*?)\s*\)', r'COALESCE(\1, 0)', expr, flags=re.IGNORECASE)
    expr = re.sub(r'\bCOUNTD\s*\(\s*(.*?)\s*\)', r'DISTINCTCOUNT(\1)', expr, flags=re.IGNORECASE)
    expr = re.sub(r'\bAVG\s*\(', 'AVERAGE(', expr, flags=re.IGNORECASE)

    # WINDOW_SUM (basic)
    win = re.search(
        r'WINDOW_SUM\s*\(\s*(SUM\(.*?\))\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*\)',
        expr, flags=re.IGNORECASE
    )
    if win:
        inner_sum, start_offset, _ = win.groups()
        months = abs(int(start_offset)) + 1
        expr = (
            f"CALCULATE({inner_sum}, "
            f"DATESINPERIOD('Date'[Date], LASTDATE('Date'[Date]), {-months}, MONTH))"
        )

    # LOD expressions
    fixed = re.search(
        r'\{FIXED\s+' + re.escape(default_table) + r'\[([^\]]+)\]\s*:\s*(.*?)\}',
        expr, flags=re.IGNORECASE
    )
    if fixed:
        dim, inner = fixed.groups()
        expr = f"CALCULATE({inner}, ALLEXCEPT({default_table}, {default_table}[{dim}]))"

    include = re.search(
        r'\{INCLUDE\s+' + re.escape(default_table) + r'\[([^\]]+)\]\s*:\s*(.*?)\}',
        expr, flags=re.IGNORECASE
    )
    if include:
        dim, inner = include.groups()
        expr = f"CALCULATE({inner}, ALLSELECTED({default_table}[{dim}]))"

    exclude = re.search(
        r'\{EXCLUDE\s+' + re.escape(default_table) + r'\[([^\]]+)\]\s*:\s*(.*?)\}',
        expr, flags=re.IGNORECASE
    )
    if exclude:
        dim, inner = exclude.groups()
        expr = f"CALCULATE({inner}, ALL({default_table}[{dim}]))"

    # Cleanup
    expr = re.sub(r'\s+', ' ', expr).strip()

    if '{' in expr or 'WINDOW_' in expr:
        raise ValueError(f"Unsupported Tableau construct in '{tableau_expr}'")

    return expr



