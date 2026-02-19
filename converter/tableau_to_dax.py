import re
from typing import List


# ---------------------------
# Tokenizer
# ---------------------------

TOKEN_REGEX = re.compile(
    r"""
    (?P<KEYWORD>\bIF\b|\bTHEN\b|\bELSEIF\b|\bELSE\b|\bEND\b|\bCASE\b|\bWHEN\b)
    |(?P<FIELD>\[[^\]]+\])
    |(?P<NUMBER>-?\d+(\.\d+)?)
    |(?P<STRING>"[^"]*")
    |(?P<OPERATOR>=|<>|<=|>=|<|>)
    |(?P<LPAREN>\()
    |(?P<RPAREN>\))
    |(?P<COMMA>,)
    |(?P<OTHER>[^\s]+)
    """,
    re.IGNORECASE | re.VERBOSE,
)


def tokenize(expr: str) -> List[str]:
    return [m.group(0) for m in TOKEN_REGEX.finditer(expr)]


# ---------------------------
# Parser
# ---------------------------

class Parser:
    def __init__(self, tokens: List[str]):
        self.tokens = tokens
        self.pos = 0

    def peek(self):
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def consume(self, expected=None):
        tok = self.peek()
        if expected and tok.upper() != expected:
            raise ValueError(f"Expected {expected}, got {tok}")
        self.pos += 1
        return tok

    def parse_expression(self):
        if self.peek() and self.peek().upper() == "IF":
            return self.parse_if()
        if self.peek() and self.peek().upper() == "CASE":
            return self.parse_case()
        return self.parse_simple()

    def parse_simple(self):
        parts = []
        while self.peek() and self.peek().upper() not in {
            "THEN", "ELSE", "ELSEIF", "WHEN", "END"
        }:
            parts.append(self.consume())
        return " ".join(parts)

    # -------- IF --------

    def parse_if(self):
        self.consume("IF")
        cond = self.parse_expression()
        self.consume("THEN")
        then_expr = self.parse_expression()

        conditions = [(cond, then_expr)]

        while self.peek() and self.peek().upper() == "ELSEIF":
            self.consume("ELSEIF")
            cond = self.parse_expression()
            self.consume("THEN")
            val = self.parse_expression()
            conditions.append((cond, val))

        if self.peek() and self.peek().upper() == "ELSE":
            self.consume("ELSE")
            else_expr = self.parse_expression()
        else:
            else_expr = "BLANK()"

        self.consume("END")

        parts = ["TRUE()"]
        for c, v in conditions:
            parts.extend([c, v])
        parts.append(else_expr)

        return f"SWITCH({', '.join(parts)})"

    # -------- CASE --------

    def parse_case(self):
        self.consume("CASE")

        base_expr = None
        if self.peek().upper() != "WHEN":
            base_expr = self.parse_simple()

        whens = []

        while self.peek() and self.peek().upper() == "WHEN":
            self.consume("WHEN")
            when_cond = self.parse_expression()
            self.consume("THEN")
            then_expr = self.parse_expression()
            whens.append((when_cond, then_expr))

        if self.peek() and self.peek().upper() == "ELSE":
            self.consume("ELSE")
            else_expr = self.parse_expression()
        else:
            else_expr = "BLANK()"

        self.consume("END")

        parts = ["TRUE()"]
        for w, t in whens:
            if base_expr:
                parts.append(f"{base_expr} = {w}")
            else:
                parts.append(w)
            parts.append(t)

        parts.append(else_expr)
        return f"SWITCH({', '.join(parts)})"


# ---------------------------
# Conditional aggregation
# ---------------------------

def extract_conditional_aggregation(expr: str):
    expr = expr.strip()

    cond_pattern = re.compile(
        r"""
        (?P<agg>SUM|COUNT|AVG|MIN|MAX|COUNTD)\s*\(
            \s*IF\s+(?P<cond>.*?)\s+
            THEN\s+(?P<val>.*?)\s+
            END\s*
        \)
        """,
        re.IGNORECASE | re.DOTALL | re.VERBOSE,
    )

    m = cond_pattern.search(expr)
    if m:
        agg = m.group("agg").upper()
        cond = m.group("cond")
        val = m.group("val")
        return f"{agg}({val})", [cond]

    simple_pattern = re.compile(
        r"""
        (?P<agg>SUM|COUNT|AVG|MIN|MAX|COUNTD)\s*\(
            (?P<val>.*?)
        \)
        """,
        re.IGNORECASE | re.DOTALL | re.VERBOSE,
    )

    m = simple_pattern.search(expr)
    if m:
        agg = m.group("agg").upper()
        val = m.group("val")
        return f"{agg}({val})", []

    return None, None


# ---------------------------
# LOD preprocessing
# ---------------------------

def preprocess_lod(expr: str, default_table: str) -> str:
    expr = expr.strip()

    lod = re.match(
        r'\{\s*(FIXED|EXCLUDE|INCLUDE)\s+(.*?)\s*:\s*(.*?)\s*\}$',
        expr,
        flags=re.IGNORECASE | re.DOTALL,
    )

    if not lod:
        return expr

    lod_type, dims, inner = lod.groups()
    lod_type = lod_type.upper()
    dims = [d.strip() for d in dims.split(",") if d.strip()]

    agg_expr, filters = extract_conditional_aggregation(inner)
    if not agg_expr:
        raise ValueError("LOD expressions must contain supported aggregation")

    agg_match = re.match(r'(\w+)\((.*)\)', agg_expr, re.IGNORECASE)
    if not agg_match:
        raise ValueError("Unsupported aggregation inside LOD")

    agg_func = agg_match.group(1).upper()
    measure_expr = agg_match.group(2).strip()

    if agg_func == "COUNTD":
        agg_func = "DISTINCTCOUNT"
    if agg_func == "AVG":
        agg_func = "AVERAGE"

    dim_list = ", ".join(dims)
    filter_clause = ", " + ", ".join(filters) if filters else ""

    if lod_type == "FIXED":
        return f"""
CALCULATE(
    {agg_func}({measure_expr})
    {filter_clause},
    ALLEXCEPT({default_table}, {dim_list})
)
""".strip()

    elif lod_type == "EXCLUDE":
        return f"""
CALCULATE(
    {agg_func}({measure_expr})
    {filter_clause},
    REMOVEFILTERS({dim_list})
)
""".strip()

    elif lod_type == "INCLUDE":
        if agg_func == "DISTINCTCOUNT":
            return f"""
CALCULATE(
    DISTINCTCOUNT({measure_expr})
    {filter_clause},
    VALUES({dim_list})
)
""".strip()

        iterator_map = {
            "SUM": "SUMX",
            "AVERAGE": "AVERAGEX",
            "COUNT": "COUNTX",
            "MIN": "MINX",
            "MAX": "MAXX"
        }

        outer_iterator = iterator_map.get(agg_func, "SUMX")

        return f"""
{outer_iterator}(
    SUMMARIZE(
        {default_table},
        {dim_list},
        "InnerValue",
        CALCULATE({agg_func}({default_table}{measure_expr}){filter_clause})
    ),
    [InnerValue]
)
""".strip()

    return expr


# ---------------------------
# Public API
# ---------------------------

def tableau_to_dax(tableau_expr: str, default_table: str = "Table"):
    expr = tableau_expr.replace("'", '"').strip()

    expr = preprocess_lod(expr, default_table)
    if expr.upper().startswith(("SUMX(", "AVERAGEX(", "COUNTX(", "MINX(", "MAXX(")):
        return expr

    tokens = tokenize(expr)
    dax = Parser(tokens).parse_expression()

    dax = re.sub(
        r'\[([^\]]+)\]',
        rf"{default_table}[\1]",
        dax,
    )

    # ---------------------------
    # Function mappings
    # ---------------------------
    dax = re.sub(r'\bISNULL\s*\(', 'ISBLANK(', dax, flags=re.IGNORECASE)
    dax = re.sub(r'\bIFNULL\s*\(', 'COALESCE(', dax, flags=re.IGNORECASE)
    dax = re.sub(r'\bZN\s*\(', 'COALESCE(', dax, flags=re.IGNORECASE)
    dax = re.sub(r'\bCOUNTD\s*\(', 'DISTINCTCOUNT(', dax, flags=re.IGNORECASE)
    dax = re.sub(r'\bAVG\s*\(', 'AVERAGE(', dax, flags=re.IGNORECASE)

    # ---------------------------
    # Logical operator mappings
    # ---------------------------
    dax = re.sub(r'\bAND\b', '&&', dax, flags=re.IGNORECASE)
    dax = re.sub(r'\bOR\b', '||', dax, flags=re.IGNORECASE)

    dax = re.sub(r'\s+', ' ', dax).strip()
    return dax



