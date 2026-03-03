#!/usr/bin/env python3
"""
validate_questions.py — Structural validator for MedicNEET question sheet.

Reads questions from Google Sheet (same credentials as app.py sync) and flags
structural problems: format errors, statement-count mismatches, broken
assertion-reason format, match-the-following column mismatches, and option
coverage gaps (via Claude Haiku).

Usage:
    python validate_questions.py              # validate all rows
    python validate_questions.py --rows 2-50  # validate specific range
    python validate_questions.py --dry-run    # print flags, don't save

Output: /home/opc/medicneet-miniapp/flagged_questions.json
"""

import os, re, sys, json, argparse, logging
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# ─── CONFIG ──────────────────────────────────────────────────────────
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "")
GOOGLE_CREDS_FILE = os.getenv("GOOGLE_CREDS_FILE", "credentials.json")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OUTPUT_PATH = "/home/opc/medicneet-miniapp/flagged_questions.json"


# ─── SHEET READER ────────────────────────────────────────────────────
def read_sheet():
    """Read all rows from Google Sheet, returning list of dicts + row numbers."""
    if not GOOGLE_SHEET_ID:
        logger.error("GOOGLE_SHEET_ID not set")
        sys.exit(1)

    import gspread
    from google.oauth2.service_account import Credentials

    creds = Credentials.from_service_account_file(
        GOOGLE_CREDS_FILE,
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets.readonly",
            "https://www.googleapis.com/auth/drive.readonly",
        ],
    )
    sheet = gspread.authorize(creds).open_by_key(GOOGLE_SHEET_ID).sheet1
    rows = sheet.get_all_records()
    # tag each row with its sheet row number (header is row 1)
    for i, row in enumerate(rows):
        row["_sheet_row"] = i + 2
    return rows


# ─── STRUCTURAL CHECKS (pure Python, no API) ────────────────────────

VALID_ANSWERS = {"A", "B", "C", "D"}


def check_format(row):
    """Check 2: Format issues — empty/duplicate options, answer validity, short question."""
    flags = []
    q = str(row.get("Question", "")).strip()
    if not q:
        flags.append("Question text is empty")
    elif len(q) < 20:
        flags.append(f"Question text too short ({len(q)} chars, minimum 20)")

    options = {
        "A": str(row.get("Option A", "")).strip(),
        "B": str(row.get("Option B", "")).strip(),
        "C": str(row.get("Option C", "")).strip(),
        "D": str(row.get("Option D", "")).strip(),
    }

    # empty options
    for label, text in options.items():
        if not text:
            flags.append(f"Option {label} is empty")

    # duplicate options
    seen = {}
    for label, text in options.items():
        if text:
            lower = text.lower().strip()
            if lower in seen:
                flags.append(f"Option {label} duplicates Option {seen[lower]}")
            else:
                seen[lower] = label

    # correct answer validity
    answer = str(row.get("Correct Answer", "")).upper().strip()
    if answer not in VALID_ANSWERS:
        flags.append(f"Correct Answer '{answer}' not in [A, B, C, D]")

    return flags


def _extract_statement_labels(text):
    """Pull statement labels like S1, S2, 1., 2., (i), (ii) etc. from text."""
    labels = set()

    # S1, S2 ... or Statement 1, Statement 2 ...
    labels.update(re.findall(r'\bS(\d+)\b', text, re.IGNORECASE))
    labels.update(re.findall(r'\bStatement\s+(\d+)\b', text, re.IGNORECASE))

    # Numbered statements: "1." "2." at start of lines or after newlines
    labels.update(re.findall(r'(?:^|\n)\s*(\d+)\s*[.)\-:]', text))

    # Roman numerals in parentheses: (i), (ii), (iii), (iv), (v)
    roman = re.findall(r'\(([ivxl]+)\)', text, re.IGNORECASE)
    roman_map = {"i": "1", "ii": "2", "iii": "3", "iv": "4", "v": "5",
                 "vi": "6", "vii": "7", "viii": "8", "ix": "9", "x": "10"}
    for r in roman:
        if r.lower() in roman_map:
            labels.add(roman_map[r.lower()])

    return {int(x) for x in labels if x.isdigit()}


def check_statement_count(row):
    """Check 3: If question mentions S1-S5 but options only reference S1-S3, flag it."""
    flags = []
    q = str(row.get("Question", ""))
    options_text = " ".join(
        str(row.get(f"Option {x}", "")) for x in "ABCD"
    )

    q_labels = _extract_statement_labels(q)
    if len(q_labels) < 2:
        return flags  # not a multi-statement question

    opt_labels = _extract_statement_labels(options_text)
    if not opt_labels:
        return flags

    # statements referenced in question but never in any option
    missing = q_labels - opt_labels
    if missing:
        sorted_missing = sorted(missing)
        flags.append(
            f"Statements {sorted_missing} appear in question but are never "
            f"referenced in options (question has {sorted(q_labels)}, "
            f"options reference {sorted(opt_labels)})"
        )

    return flags


# Standard assertion-reason option patterns (case-insensitive keywords)
_AR_KEYWORDS = [
    r"both.*true.*explains",
    r"both.*true.*does\s*not\s*explain",
    r"true.*false",
    r"false.*true",
    r"both.*false",
    r"both.*correct.*explanation",
    r"both.*correct.*not.*explanation",
]


def _is_ar_question(q):
    """Detect assertion-reason format questions."""
    q_lower = q.lower()
    return bool(
        re.search(r'\bassertion\b.*\breason\b', q_lower)
        or re.search(r'\b(a)\b\s*[:.].*\b(r)\b\s*[:.]\s', q_lower)
    )


def check_assertion_reason(row):
    """Check 4: If it's an A/R question, verify options follow standard format."""
    flags = []
    q = str(row.get("Question", ""))
    if not _is_ar_question(q):
        return flags

    options = [str(row.get(f"Option {x}", "")).lower().strip() for x in "ABCD"]
    matched = 0
    for opt in options:
        for pattern in _AR_KEYWORDS:
            if re.search(pattern, opt, re.IGNORECASE):
                matched += 1
                break

    if matched < 3:
        flags.append(
            f"Assertion-Reason question but only {matched}/4 options follow "
            f"standard A/R format (expected patterns like 'Both true and R "
            f"explains A', 'A true but R false', etc.)"
        )

    return flags


def _extract_column_items(text, col_label):
    """Count items under a column label like 'Column I' or 'Column II'."""
    # Try to find the section for this column
    pattern = rf'{col_label}\s*[:\-]?\s*(.*?)(?:Column\s|$)'
    match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
    if not match:
        return 0

    section = match.group(1)
    # Count lettered items: (a) (b) (c) or a. b. c. or A) B) C)
    lettered = re.findall(r'(?:\(([a-z])\)|([a-z])\s*[.)\-:])', section, re.IGNORECASE)
    if lettered:
        return len(lettered)

    # Count roman numerals: (i) (ii) or i. ii.
    roman = re.findall(r'\(([ivxl]+)\)', section, re.IGNORECASE)
    if roman:
        return len(roman)

    # Count numbered: 1. 2. 3.
    numbered = re.findall(r'(\d+)\s*[.)\-:]', section)
    if numbered:
        return len(numbered)

    return 0


def check_match_following(row):
    """Check 5: Match-the-following — column item counts should match."""
    flags = []
    q = str(row.get("Question", ""))
    q_lower = q.lower()

    if "match" not in q_lower or "following" not in q_lower:
        # also check for "match the" / "match column"
        if not re.search(r'match\s+(the|column)', q_lower):
            return flags

    col1_count = _extract_column_items(q, r"Column\s*I(?!\s*I)")
    col2_count = _extract_column_items(q, r"Column\s*II")

    if col1_count > 0 and col2_count > 0 and col1_count != col2_count:
        flags.append(
            f"Match-the-following: Column I has {col1_count} items but "
            f"Column II has {col2_count} items"
        )

    return flags


# ─── OPTION COVERAGE CHECK (Claude Haiku) ───────────────────────────

def _is_coverage_question(q):
    """Detect questions about which statements are correct/incorrect."""
    q_lower = q.lower()
    patterns = [
        r'which.*(statement|assertion)s?\s+(is|are)\s+(not\s+)?(correct|true|incorrect|false|wrong)',
        r'(correct|incorrect|true|false)\s+statement',
        r'how\s+many.*statements?\s+(is|are)\s+(correct|true|incorrect|false)',
        r'select\s+the\s+(correct|incorrect)',
        r'which.*(?:of\s+the\s+)?(above|following)\s+(is|are)\s+(correct|true|incorrect|false)',
    ]
    return any(re.search(p, q_lower) for p in patterns)


def check_option_coverage_batch(rows):
    """Check 1: Use Claude Haiku to analyze statement-vs-option logic.

    Batches eligible questions and makes one API call per question.
    Returns dict mapping sheet_row -> list of flags.
    """
    if not ANTHROPIC_API_KEY:
        logger.warning("ANTHROPIC_API_KEY not set — skipping option coverage checks")
        return {}

    try:
        import anthropic
    except ImportError:
        logger.warning("anthropic package not installed — skipping option coverage checks")
        return {}

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    results = {}

    eligible = [(r, r["_sheet_row"]) for r in rows if _is_coverage_question(str(r.get("Question", "")))]

    if not eligible:
        return results

    logger.info(f"Running option coverage check on {len(eligible)} questions via Claude Haiku...")

    for row, sheet_row in eligible:
        q = str(row.get("Question", ""))
        opts = {x: str(row.get(f"Option {x}", "")) for x in "ABCD"}
        correct = str(row.get("Correct Answer", "")).upper().strip()

        prompt = f"""You are a structural question validator. You do NOT need domain knowledge.

Analyze this multiple-choice question ONLY for structural/logical consistency:

QUESTION: {q}

OPTIONS:
A: {opts['A']}
B: {opts['B']}
C: {opts['C']}
D: {opts['D']}

MARKED ANSWER: {correct}

Check ONLY these structural issues (NOT whether the biology/science is correct):
1. If the question asks "which statements are correct/incorrect", do the options cover a reasonable range of combinations? Or are some statement numbers missing from ALL options?
2. Are there obvious logical contradictions in the option structure? (e.g., question asks about 4 statements but options only cover combinations of 3)
3. Does the marked answer option actually exist and make structural sense?

Respond with EXACTLY one line:
- If no structural issues: "OK"
- If issues found: "FLAG: <brief description of the structural issue>"

Do NOT comment on scientific accuracy. Only structural/logical problems."""

        try:
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=150,
                messages=[{"role": "user", "content": prompt}],
            )
            answer = response.content[0].text.strip()
            if answer.upper().startswith("FLAG"):
                reason = answer.split(":", 1)[1].strip() if ":" in answer else answer
                results[sheet_row] = [f"Option coverage: {reason}"]
        except Exception as e:
            logger.error(f"Haiku API error for row {sheet_row}: {e}")

    return results


# ─── MAIN ORCHESTRATOR ───────────────────────────────────────────────

def validate_all(rows, row_range=None):
    """Run all checks on rows. Returns list of flagged question dicts."""
    if row_range:
        start, end = row_range
        rows = [r for r in rows if start <= r["_sheet_row"] <= end]

    logger.info(f"Validating {len(rows)} questions...")

    # Phase 1: pure-Python structural checks (2-5)
    flagged = {}  # sheet_row -> {info + flags list}
    for row in rows:
        sr = row["_sheet_row"]
        all_flags = []
        all_flags.extend(check_format(row))
        all_flags.extend(check_statement_count(row))
        all_flags.extend(check_assertion_reason(row))
        all_flags.extend(check_match_following(row))

        if all_flags:
            flagged[sr] = {
                "sheet_row": sr,
                "question": str(row.get("Question", ""))[:120],
                "correct_answer": str(row.get("Correct Answer", "")).upper().strip(),
                "flags": all_flags,
            }

    # Phase 2: Claude Haiku option-coverage check (1)
    coverage_flags = check_option_coverage_batch(rows)
    for sr, flags in coverage_flags.items():
        if sr in flagged:
            flagged[sr]["flags"].extend(flags)
        else:
            row = next((r for r in rows if r["_sheet_row"] == sr), None)
            if row:
                flagged[sr] = {
                    "sheet_row": sr,
                    "question": str(row.get("Question", ""))[:120],
                    "correct_answer": str(row.get("Correct Answer", "")).upper().strip(),
                    "flags": flags,
                }

    return sorted(flagged.values(), key=lambda x: x["sheet_row"])


def main():
    parser = argparse.ArgumentParser(description="Validate MedicNEET question sheet structure")
    parser.add_argument("--rows", help="Row range to validate, e.g. 2-50", default=None)
    parser.add_argument("--dry-run", action="store_true", help="Print flags but don't save to file")
    args = parser.parse_args()

    row_range = None
    if args.rows:
        parts = args.rows.split("-")
        row_range = (int(parts[0]), int(parts[1]))

    rows = read_sheet()
    logger.info(f"Read {len(rows)} rows from sheet")

    results = validate_all(rows, row_range=row_range)

    # Summary
    total_flags = sum(len(r["flags"]) for r in results)
    print(f"\n{'='*60}")
    print(f"VALIDATION COMPLETE")
    print(f"  Questions checked : {len(rows) if not row_range else row_range[1]-row_range[0]+1}")
    print(f"  Questions flagged : {len(results)}")
    print(f"  Total flags       : {total_flags}")
    print(f"{'='*60}\n")

    for r in results:
        print(f"  Row {r['sheet_row']}: {r['question'][:80]}...")
        for f in r["flags"]:
            print(f"    -> {f}")
        print()

    if not args.dry_run and results:
        output = {
            "validated_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
            "total_checked": len(rows),
            "total_flagged": len(results),
            "total_flags": total_flags,
            "flagged_questions": results,
        }
        os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
        with open(OUTPUT_PATH, "w") as f:
            json.dump(output, f, indent=2)
        print(f"Saved to {OUTPUT_PATH}")
    elif not results:
        print("No issues found!")


if __name__ == "__main__":
    main()
