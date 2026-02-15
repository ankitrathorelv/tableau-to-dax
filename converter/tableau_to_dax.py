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

     # Normalize ELSEIF
    expr = re.sub(r'\bELSEIF\b', 'ELSE IF', expr, flags=re.IGNORECASE)

    # -------------------------
    # IF / ELSE IF / ELSE → SWITCH(TRUE())
    # -------------------------
    if re.search(r'\bIF\b', expr, flags=re.IGNORECASE):

        header = re.match(
            r'IF\s+(.*?)\s+THEN\s+(.*)',
            expr,
            flags=re.IGNORECASE | re.DOTALL
        )

        if header:
            conditions = []
            remainder = header.group(2)

            # First IF
            then_match = re.match(
                r'(.*?)\s+ELSE\s+(.*)',
                remainder,
                flags=re.IGNORECASE | re.DOTALL
            )
            if not then_match:
                raise ValueError("Invalid IF syntax")

            conditions.append((header.group(1), then_match.group(1)))
            remainder = then_match.group(2)

            # ELSE IF blocks
            while re.match(r'IF\s+', remainder, flags=re.IGNORECASE):
                elseif = re.match(
                    r'IF\s+(.*?)\s+THEN\s+(.*?)\s+ELSE\s+(.*)',
                    remainder,
                    flags=re.IGNORECASE | re.DOTALL
                )
                if not elseif:
                    break
                conditions.append((elseif.group(1), elseif.group(2)))
                remainder = elseif.group(3)

            # ELSE
            else_match = re.match(
                r'(.*?)\s*END\s*$',
                remainder,
                flags=re.IGNORECASE | re.DOTALL
            )
            if not else_match:
                raise ValueError("Missing END in IF")

            else_value = else_match.group(1)

            # Build SWITCH(TRUE())
            parts = ["TRUE()"]
            for cond, val in conditions:
                parts.append(cond)
                parts.append(val)

            parts.append(else_value)

            expr = f"SWITCH({', '.join(parts)})"


    # CASE → SWITCH(TRUE())
    # Correctly detects:
    #   CASE WHEN ...   (boolean)
    #   CASE <expr> WHEN ... (value)
    # -------------------------
    if re.search(r'\bCASE\b', expr, flags=re.IGNORECASE):
    
        # Boolean CASE: CASE WHEN ...
        boolean_case = re.match(
            r'\s*CASE\s+WHEN\b',
            expr,
            flags=re.IGNORECASE | re.DOTALL
        )
    
        # Value CASE: CASE <expr> WHEN ...
        value_case = re.match(
            r'\s*CASE\s+(.*?)\s+WHEN\b',
            expr,
            flags=re.IGNORECASE | re.DOTALL
        ) if not boolean_case else None
    
        base_expr = value_case.group(1) if value_case else None
    
        whens = re.findall(
            r'WHEN\s+(.*?)\s+THEN\s+(.*?)(?=\s+WHEN|\s+ELSE|\s+END)',
            expr,
            flags=re.IGNORECASE | re.DOTALL
        )
    
        else_match = re.search(
            r'ELSE\s+(.*?)\s+END',
            expr,
            flags=re.IGNORECASE | re.DOTALL
        )
    
        else_val = else_match.group(1) if else_match else None
    
        parts = ["TRUE()"]
    
        for when_part, then_part in whens:
            if base_expr:
                # CASE <expr> WHEN <value>
                parts.append(f"{base_expr} = {when_part}")
            else:
                # CASE WHEN <condition>
                parts.append(when_part)
    
            parts.append(then_part)
    
        if else_val:
            parts.append(else_val)
    
        expr = f"SWITCH({', '.join(parts)})"


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

    # # LOD expressions
    # fixed = re.search(
    #     r'\{FIXED\s+' + re.escape(default_table) + r'\[([^\]]+)\]\s*:\s*(.*?)\}',
    #     expr, flags=re.IGNORECASE
    # )
    # if fixed:
    #     dim, inner = fixed.groups()
    #     expr = f"CALCULATE({inner}, ALLEXCEPT({default_table}, {default_table}[{dim}]))"

    # include = re.search(
    #     r'\{INCLUDE\s+' + re.escape(default_table) + r'\[([^\]]+)\]\s*:\s*(.*?)\}',
    #     expr, flags=re.IGNORECASE
    # )
    # if include:
    #     dim, inner = include.groups()
    #     expr = f"CALCULATE({inner}, ALLSELECTED({default_table}[{dim}]))"

    # exclude = re.search(
    #     r'\{EXCLUDE\s+' + re.escape(default_table) + r'\[([^\]]+)\]\s*:\s*(.*?)\}',
    #     expr, flags=re.IGNORECASE
    # )
    # if exclude:
    #     dim, inner = exclude.groups()
    #     expr = f"CALCULATE({inner}, ALL({default_table}[{dim}]))"

    # # Cleanup
    # expr = re.sub(r'\s+', ' ', expr).strip()

    # if '{' in expr or 'WINDOW_' in expr:
    #     raise ValueError(f"Unsupported Tableau construct in '{tableau_expr}'")

    # return expr

    # First handle LODs before prefixing
    fixed = re.search(r'\bFIXED\s+(.*?)\s*:\s*(.*?)\}', expr, flags=re.IGNORECASE | re.DOTALL)
    include = re.search(r'\bINCLUDE\s+(.*?)\s*:\s*(.*?)\}', expr, flags=re.IGNORECASE | re.DOTALL)
    exclude = re.search(r'\bEXCLUDE\s+(.*?)\s*:\s*(.*?)\}', expr, flags=re.IGNORECASE | re.DOTALL)
    # exclude = re.search(r'\bEXCLUDE\b', expr, flags=re.IGNORECASE)
    

    if fixed:
        dims, inner = fixed.groups()
        dims = [f"{default_table}[{d.strip().strip('[]')}]" for d in dims.split(',')]
        inner = re.sub(r'\[([^\]]+)\]', rf"{default_table}[\1]", inner)
        expr = f"CALCULATE({inner}, ALLEXCEPT({default_table}, {', '.join(dims)}))"

    elif include:
        dims, inner = include.groups()
        dims = [f"{default_table}[{d.strip().strip('[]')}]" for d in dims.split(',')]
        inner = re.sub(r'\[([^\]]+)\]', rf"{default_table}[\1]", inner)
        if len(dims) == 1:
            expr = f"AVERAGEX(VALUES({dims[0]}), CALCULATE({inner}))"
        else:
            expr = f"AVERAGEX(CROSSJOIN({', '.join([f'VALUES({d})' for d in dims])}), CALCULATE({inner}))"

    elif exclude:
        dims, inner = exclude.groups()
        dims = [f"{default_table}[{d.strip().strip('[]')}]" for d in dims.split(',')]
        inner = re.sub(r'\[([^\]]+)\]', rf"{default_table}[\1]", inner)
        expr = f"CALCULATE({inner}, REMOVEFILTERS({', '.join(dims)}))"
        
    return expr


    