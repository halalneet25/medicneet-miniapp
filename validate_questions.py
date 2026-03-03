#!/usr/bin/env python3
"""
validate_questions.py — Structural validator for MedicNEET questions.

Reads questions from the local SQLite database and flags structural problems:
format errors, empty/duplicate options, statement-count mismatches,
assertion-reason format issues, and match-the-following column mismatches.

Usage:
    python validate_questions.py                # validate all questions
    python validate_questions.py --ids 1-50     # validate ID range
    python validate_questions.py --dry-run      # print flags, don't save

Output: flagged_questions.json (same directory as the script)
"""

import os, re, sys, json, sqlite3, argparse, logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# ─── CONFIG ──────────────────────────────────────────────────────────
DB_PATH = os.getenv("DB_PATH", "/home/opc/medicneet-miniapp/medicneet.db")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_PATH = os.path.join(SCRIPT_DIR, "flagged_questions.json")

VALID_ANSWERS = {"A", "B", "C", "D"}


# ─── DB READER ───────────────────────────────────────────────────────

def read_questions(id_range=None):
    """Read questions from SQLite, returning list of dicts."""
    if not os.path.exists(DB_PATH):
        logger.error(f"Database not found: {DB_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    if id_range:
        c.execute(
            "SELECT * FROM questions WHERE id BETWEEN ? AND ? ORDER BY id",
            (id_range[0], id_range[1]),
        )
    else:
        c.execute("SELECT * FROM questions ORDER BY id")

    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


# ─── STRUCTURAL CHECKS ──────────────────────────────────────────────

def check_format(row):
    """Empty/duplicate options, answer validity, short question text."""
    flags = []
    q = (row.get("question") or "").strip()

    if not q:
        flags.append("Question text is empty")
    elif len(q) < 20:
        flags.append(f"Question text too short ({len(q)} chars, minimum 20)")

    options = {
        "A": (row.get("option_a") or "").strip(),
        "B": (row.get("option_b") or "").strip(),
        "C": (row.get("option_c") or "").strip(),
        "D": (row.get("option_d") or "").strip(),
    }

    for label, text in options.items():
        if not text:
            flags.append(f"Option {label} is empty")

    seen = {}
    for label, text in options.items():
        if text:
            normalized = text.lower().strip()
            if normalized in seen:
                flags.append(f"Option {label} duplicates Option {seen[normalized]}")
            else:
                seen[normalized] = label

    answer = (row.get("correct_answer") or "").upper().strip()
    if answer not in VALID_ANSWERS:
        flags.append(f"Correct answer '{answer}' is not in [A, B, C, D]")

    return flags


def _extract_statement_labels(text):
    """Pull statement labels like S1, S2, 1., 2., (i), (ii) from text."""
    labels = set()
    labels.update(re.findall(r"\bS(\d+)\b", text, re.IGNORECASE))
    labels.update(re.findall(r"\bStatement\s+(\d+)\b", text, re.IGNORECASE))
    labels.update(re.findall(r"(?:^|\n)\s*(\d+)\s*[.)\-:]", text))

    roman_map = {
        "i": "1", "ii": "2", "iii": "3", "iv": "4", "v": "5",
        "vi": "6", "vii": "7", "viii": "8", "ix": "9", "x": "10",
    }
    for r in re.findall(r"\(([ivxl]+)\)", text, re.IGNORECASE):
        if r.lower() in roman_map:
            labels.add(roman_map[r.lower()])

    return {int(x) for x in labels if x.isdigit()}


def check_statement_count(row):
    """Flag when question references statements that never appear in options."""
    flags = []
    q = row.get("question") or ""
    opts_text = " ".join(
        (row.get(f"option_{x}") or "") for x in ["a", "b", "c", "d"]
    )

    q_labels = _extract_statement_labels(q)
    if len(q_labels) < 2:
        return flags

    opt_labels = _extract_statement_labels(opts_text)
    if not opt_labels:
        return flags

    missing = q_labels - opt_labels
    if missing:
        flags.append(
            f"Statements {sorted(missing)} in question but never referenced "
            f"in options (question has {sorted(q_labels)}, "
            f"options reference {sorted(opt_labels)})"
        )
    return flags


_AR_PATTERNS = [
    r"both.*true.*explains",
    r"both.*true.*does\s*not\s*explain",
    r"true.*false",
    r"false.*true",
    r"both.*false",
    r"both.*correct.*explanation",
    r"both.*correct.*not.*explanation",
]


def check_assertion_reason(row):
    """If it's an assertion-reason question, verify options follow standard format."""
    flags = []
    q = (row.get("question") or "").lower()

    is_ar = bool(
        re.search(r"\bassertion\b.*\breason\b", q)
        or re.search(r"\bassertion\s*\(a\).*\breason\s*\(r\)", q)
    )
    if not is_ar:
        return flags

    options = [(row.get(f"option_{x}") or "").lower() for x in ["a", "b", "c", "d"]]
    matched = sum(
        1 for opt in options
        if any(re.search(p, opt, re.IGNORECASE) for p in _AR_PATTERNS)
    )

    if matched < 3:
        flags.append(
            f"Assertion-Reason question but only {matched}/4 options follow "
            f"standard A/R format"
        )
    return flags


def _count_column_items(text, col_label):
    """Count items listed under a column label."""
    match = re.search(
        rf"{col_label}\s*[:\-]?\s*(.*?)(?:Column\s|$)",
        text, re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return 0
    section = match.group(1)

    lettered = re.findall(r"(?:\(([a-z])\)|([a-z])\s*[.)\-:])", section, re.IGNORECASE)
    if lettered:
        return len(lettered)
    roman = re.findall(r"\(([ivxl]+)\)", section, re.IGNORECASE)
    if roman:
        return len(roman)
    numbered = re.findall(r"(\d+)\s*[.)\-:]", section)
    if numbered:
        return len(numbered)
    return 0


def check_match_following(row):
    """Match-the-following: column item counts should be equal."""
    flags = []
    q = (row.get("question") or "").lower()

    if not ("match" in q and "following" in q) and not re.search(r"match\s+(the|column)", q):
        return flags

    q_full = row.get("question") or ""
    col1 = _count_column_items(q_full, r"Column\s*I(?!\s*I)")
    col2 = _count_column_items(q_full, r"Column\s*II")

    if col1 > 0 and col2 > 0 and col1 != col2:
        flags.append(
            f"Match-the-following: Column I has {col1} items but "
            f"Column II has {col2} items"
        )
    return flags


# ─── ORCHESTRATOR ────────────────────────────────────────────────────

def validate(rows):
    """Run all checks. Returns list of flagged question dicts."""
    logger.info(f"Validating {len(rows)} questions...")
    flagged = []

    checks = [
        check_format,
        check_statement_count,
        check_assertion_reason,
        check_match_following,
    ]

    for row in rows:
        all_flags = []
        for check in checks:
            all_flags.extend(check(row))

        if all_flags:
            flagged.append({
                "id": row.get("id"),
                "sheet_row": row.get("sheet_row"),
                "question": ((row.get("question") or "")[:120]),
                "correct_answer": (row.get("correct_answer") or "").upper().strip(),
                "chapter": row.get("chapter") or "",
                "flags": all_flags,
            })

    return flagged


def main():
    parser = argparse.ArgumentParser(
        description="Validate MedicNEET questions for structural issues"
    )
    parser.add_argument("--ids", help="ID range to validate, e.g. 1-50", default=None)
    parser.add_argument("--dry-run", action="store_true",
                        help="Print flags but don't save to file")
    parser.add_argument("--db", help="Path to SQLite database", default=None)
    args = parser.parse_args()

    if args.db:
        global DB_PATH
        DB_PATH = args.db

    id_range = None
    if args.ids:
        parts = args.ids.split("-")
        id_range = (int(parts[0]), int(parts[1]))

    rows = read_questions(id_range)
    logger.info(f"Read {len(rows)} questions from {DB_PATH}")

    if not rows:
        print("No questions found in database.")
        return

    results = validate(rows)

    total_flags = sum(len(r["flags"]) for r in results)
    print(f"\n{'='*60}")
    print(f"VALIDATION COMPLETE")
    print(f"  Questions checked : {len(rows)}")
    print(f"  Questions flagged : {len(results)}")
    print(f"  Total flags       : {total_flags}")
    print(f"{'='*60}\n")

    for r in results:
        label = f"ID {r['id']}" if r["id"] else f"sheet_row {r['sheet_row']}"
        print(f"  {label}: {r['question'][:80]}...")
        for f in r["flags"]:
            print(f"    -> {f}")
        print()

    if not args.dry_run and results:
        output = {
            "validated_at": datetime.utcnow().isoformat() + "Z",
            "db_path": DB_PATH,
            "total_checked": len(rows),
            "total_flagged": len(results),
            "total_flags": total_flags,
            "flagged_questions": results,
        }
        with open(OUTPUT_PATH, "w") as fp:
            json.dump(output, fp, indent=2)
        print(f"Saved to {OUTPUT_PATH}")
    elif not results:
        print("No issues found!")


if __name__ == "__main__":
    main()
